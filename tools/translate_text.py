"""翻译一段纯文本（新书试读、单章节选）。

用法：
    python tools/translate_text.py section.txt --title "第三章" [--glossary 失恋]
    python tools/translate_text.py --text "……" --title "片段"

产物：
    out/<标题>.zh.txt      默认输出
    out/<标题>.zh.epub     加 --epub 时保留

流程：txt 包成最小 EPUB → 现有流水线（预读/翻译/修订/复核/润色/打包）→ 导出 txt。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epubtr.txtbook import build_txt_epub  # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def run(argv: list[str]) -> bool:
    print(f"\n$ {' '.join(argv[1:])}", flush=True)
    r = subprocess.run([sys.executable, *argv], cwd=ROOT)
    return r.returncode == 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2

    def opt(name: str, default: str = "") -> str:
        return args[args.index(name) + 1] if name in args else default

    title = opt("--title")
    author = opt("--author")
    glossary = opt("--glossary")
    out_arg = opt("--out")
    keep_epub = "--epub" in args
    no_revise = "--no-revise" in args
    drop_chinese = "--drop-chinese" in args

    if "--text" in args:
        raw = opt("--text")
    else:
        src = next((a for a in args if not a.startswith("--")
                    and a not in (title, author, glossary, out_arg)), "")
        if not src:
            print("请给出 txt 路径或 --text")
            return 2
        raw = Path(src).read_text(encoding="utf-8")

    if drop_chinese:
        kept = []
        for line in raw.splitlines():
            has_kana = any("\u3040" <= c <= "\u30ff" for c in line)
            has_cjk = any("\u4e00" <= c <= "\u9fff" for c in line)
            if has_cjk and not has_kana and len(line.strip()) > 4:
                continue
            kept.append(line)
        raw = "\n".join(kept)

    name = slug(title or "片段")
    tmp = ROOT / "work" / "_txt" / f"{name}.epub"
    epub, real_title = build_txt_epub(raw, tmp, title=title, author=author)
    print(f"已包装：{epub}（{real_title}）")

    kb = ROOT / "kb" / name
    if glossary:
        src_kb = ROOT / "kb" / glossary
        if not src_kb.exists():
            hits = [d for d in (ROOT / "kb").iterdir()
                    if d.is_dir() and glossary in d.name]
            if len(hits) == 1:
                src_kb = hits[0]
            elif len(hits) > 1:
                hits = [d for d in hits if (d / "glossary.json").exists()] or hits
                hits.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                src_kb = hits[0]
                print(f"匹配到多本，使用最新的一份：{src_kb.name}")
        if not (src_kb / "glossary.json").exists():
            print(f"找不到术语表：{src_kb}")
            return 1
        kb.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_kb / "glossary.json", kb / "glossary.json")
        if (src_kb / "style.md").exists():
            shutil.copy(src_kb / "style.md", kb / "style.md")
        print(f"复用术语表：{glossary}")

    busy = False
    if not (kb / "auto_bible.json").exists() and not glossary:
        busy = not run(["tools/preread.py", str(epub)]) or busy

    ok = run(["tools/translate_book.py", str(epub)]) and not busy
    if ok and not no_revise:
        ok = run(["tools/revise_book.py", str(epub)])
        if ok:
            run(["tools/audit_revisions.py", str(epub), "--apply"])
    if ok:
        run(["tools/polish.py", str(epub)])
    if not ok:
        print("翻译失败，保留中间产物供排查")
        return 1

    run(["tools/build_epub.py", str(epub)])

    # 导出 txt：按篇顺序拼接修订后的译文
    work = ROOT / "work" / name
    lines: list[str] = []
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = work / "rev" / f.name if (work / "rev" / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        for uid in sorted(data.get("units", {})):
            text = data["units"][uid].strip()
            if text:
                lines.append(text)
    out_txt = Path(out_arg) if out_arg else ROOT / "out" / f"{name}.zh.txt"
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n\n".join(lines), encoding="utf-8")

    epub_out = ROOT / "out" / f"{name}.zh.epub"
    print(f"\n完成：{out_txt}（{len(lines)} 段）")
    if keep_epub and epub_out.exists():
        print(f"EPUB：{epub_out}")
    elif epub_out.exists():
        epub_out.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
