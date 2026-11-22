"""图形界面：整本翻译 / 片段翻译 / 审校。

用法：
    python tools/gui.py
    pythonw tools/gui.py        # 不显示控制台窗口
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue[str] = queue.Queue()
        root.title("epub-translator")
        root.geometry("940x680")
        root.minsize(760, 520)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill=BOTH, expand=False, padx=10, pady=(10, 0))
        self.nb.add(self._tab_book(), text="  整本 EPUB  ")
        self.nb.add(self._tab_text(), text="  片段文本  ")
        self.nb.add(self._tab_review(), text="  审校  ")

        bar = ttk.Frame(root)
        bar.pack(fill=X, padx=10, pady=(8, 0))
        self.status = StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status).pack(side=LEFT)
        ttk.Button(bar, text="打开输出目录", command=self.open_out).pack(side=RIGHT)
        ttk.Button(bar, text="停止", command=self.stop).pack(side=RIGHT, padx=6)

        self.log = ttk.Frame(root)
        self.log.pack(fill=BOTH, expand=True, padx=10, pady=10)
        self.txt = __import__("tkinter").Text(
            self.log, wrap="word", height=18, font=("Consolas", 9))
        sb = ttk.Scrollbar(self.log, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)
        self.write("提示：首次使用先在 config/local.json 填好 API key（见 config/local.example.json）。")

        self.root.after(100, self.drain)
        if os.environ.get("GUI_SMOKE"):
            root.after(900, root.destroy)

    # ---------- 三个页签 ----------
    def _tab_book(self) -> ttk.Frame:
        f = ttk.Frame(self.nb)
        row = ttk.Frame(f)
        row.pack(fill=X, padx=12, pady=12)
        ttk.Label(row, text="EPUB：").pack(side=LEFT)
        self.book_path = StringVar()
        ttk.Entry(row, textvariable=self.book_path).pack(side=LEFT, fill=X, expand=True, padx=6)
        ttk.Button(row, text="选择…", command=self.pick_book).pack(side=LEFT)
        row2 = ttk.Frame(f)
        row2.pack(fill=X, padx=12)
        ttk.Button(row2, text="开始翻译", command=self.start_book).pack(side=LEFT)
        ttk.Label(row2, text="  全流程：预读 → 翻译 → 修订 → 复核 → 润色 → 打包").pack(side=LEFT)
        return f

    def _tab_text(self) -> ttk.Frame:
        f = ttk.Frame(self.nb)
        row = ttk.Frame(f)
        row.pack(fill=X, padx=12, pady=(12, 6))
        ttk.Label(row, text="标题：").pack(side=LEFT)
        self.section_title = StringVar(value="片段")
        ttk.Entry(row, textvariable=self.section_title, width=28).pack(side=LEFT, padx=6)
        ttk.Label(row, text="术语表：").pack(side=LEFT, padx=(12, 0))
        self.gloss = StringVar(value="（不使用）")
        self.gloss_box = ttk.Combobox(row, textvariable=self.gloss, width=32,
                                      values=self._gloss_choices())
        self.gloss_box.pack(side=LEFT, padx=6)
        ttk.Button(row, text="载入 txt…", command=self.load_txt).pack(side=LEFT)
        self.want_epub = BooleanVar(value=False)
        ttk.Checkbutton(row, text="同时输出 EPUB", variable=self.want_epub).pack(side=LEFT, padx=8)

        self.section_text = __import__("tkinter").Text(f, wrap="word", height=10)
        self.section_text.pack(fill=BOTH, expand=True, padx=12, pady=6)
        self.section_text.insert("1.0", "把日文原文粘贴到这里。空行分段，# 标题，--- 分隔。")

        row3 = ttk.Frame(f)
        row3.pack(fill=X, padx=12, pady=(0, 10))
        ttk.Button(row3, text="开始翻译片段", command=self.start_text).pack(side=LEFT)
        self.drop_cn = BooleanVar(value=True)
        ttk.Checkbutton(row3, text="自动跳过纯中文行", variable=self.drop_cn).pack(side=LEFT, padx=10)
        return f

    def _tab_review(self) -> ttk.Frame:
        f = ttk.Frame(self.nb)
        box = ttk.Frame(f)
        box.pack(fill=X, padx=12, pady=16)
        ttk.Button(box, text="启动并打开审校界面", command=self.open_review).pack(side=LEFT)
        ttk.Button(box, text="停止审校服务", command=self.stop_review).pack(side=LEFT, padx=8)
        ttk.Label(f, text="地址：http://127.0.0.1:8765（只在本机）").pack(anchor="w", padx=12)
        return f

    # ---------- 动作 ----------
    def _gloss_choices(self) -> list[str]:
        kb = ROOT / "kb"
        if not kb.exists():
            return ["（不使用）"]
        names = [d.name for d in kb.iterdir() if (d / "glossary.json").exists()]
        return ["（不使用）"] + sorted(names)

    def pick_book(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("EPUB", "*.epub"), ("全部", "*.*")])
        if p:
            self.book_path.set(p)

    def load_txt(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("文本", "*.txt"), ("全部", "*.*")])
        if p:
            self.section_text.delete("1.0", END)
            self.section_text.insert("1.0", Path(p).read_text(encoding="utf-8", errors="replace"))

    def start_book(self) -> None:
        p = self.book_path.get().strip()
        if not p or not Path(p).exists():
            messagebox.showwarning("提示", "先选择一个 EPUB 文件")
            return
        self.run_cmd(["tools/pipeline.py", p], "整本翻译")

    def start_text(self) -> None:
        raw = self.section_text.get("1.0", END).strip()
        if not raw:
            messagebox.showwarning("提示", "先粘贴或载入日文文本")
            return
        tmp = ROOT / "work" / "_txt" / "gui_input.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(raw, encoding="utf-8")
        argv = ["tools/translate_text.py", str(tmp),
                "--title", self.section_title.get().strip() or "片段"]
        if self.gloss.get() not in ("", "（不使用）"):
            argv += ["--glossary", self.gloss.get()]
        if self.want_epub.get():
            argv.append("--epub")
        if self.drop_cn.get():
            argv.append("--drop-chinese")
        self.run_cmd(argv, "片段翻译")

    def open_review(self) -> None:
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:8765/api/books", timeout=1)
        except Exception:  # noqa: BLE001
            subprocess.Popen([PY, "tools/review_server.py", "8765"], cwd=ROOT,
                             env=ENV, creationflags=CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.root.after(2500, self._open_browser)
            self.write("正在启动审校服务…")
            return
        self._open_browser()

    def _open_browser(self) -> None:
        webbrowser.open("http://127.0.0.1:8765")
        self.write("审校界面已打开：http://127.0.0.1:8765")

    def stop_review(self) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/FI", "WINDOWTITLE eq review_server*"],
                           capture_output=True)
        self.write("已尝试停止审校服务（也可直接关闭浏览器标签）")

    def open_out(self) -> None:
        out = ROOT / "out"
        out.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(out)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(out)])

    # ---------- 子进程与日志 ----------
    def run_cmd(self, argv: list[str], label: str) -> None:
        if self.proc is not None:
            messagebox.showinfo("提示", "已有任务在运行")
            return
        self.txt.delete("1.0", END)
        self.status.set(f"{label} 运行中…")
        self.write(f"$ {' '.join(argv)}")

        def worker():
            self.proc = subprocess.Popen([PY, *argv], cwd=ROOT, env=ENV,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8",
                                         errors="replace",
                                         creationflags=CREATE_NO_WINDOW)
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.q.put(line.rstrip())
            code = self.proc.wait()
            self.q.put(f"__DONE__{code}")
            self.proc = None

        threading.Thread(target=worker, daemon=True).start()

    def drain(self) -> None:
        while True:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break
            if line.startswith("__DONE__"):
                code = line.replace("__DONE__", "")
                self.status.set(f"完成（退出码 {code}）" if code == "0" else f"失败（退出码 {code}）")
                continue
            self.write(line)
        self.root.after(120, self.drain)

    def write(self, text: str) -> None:
        self.txt.insert(END, text + "\n")
        self.txt.see(END)

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.status.set("已停止")
            self.write("已请求停止当前任务")


def main() -> int:
    root = Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
