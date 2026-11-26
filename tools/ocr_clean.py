"""把 OCR 结果整理成可读文本：修错字、合并断行成段落。

用法：
    python tools/ocr_clean.py work/_ocr/manga.json --title "赤いスイムキャップ" --out work/_ocr/clean.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epubtr.llm import chat, load_config      # noqa: E402
from epubtr.parallel import run as parallel_run  # noqa: E402

SYSTEM = """你是日文校对。下面是竖排书页的 OCR 结果，可能有错字、漏字、断行错误。

请：
1. 修正明显的 OCR 错误（同音字、近形字、被误识的假名）；
2. 把断行合并成自然的段落，段落之间用空行分隔；
3. 保留原文全部内容、「」『』引号与标点风格，不得增删情节，不得改写措辞；
4. 只输出整理后的正文，不要解释。

如果某处实在无法辨认，用 ＊ 代替那一个字符，不要编造。"""


def clean_page(cfg, name: str, text: str) -> str:
    r = chat(cfg, SYSTEM, f"【{name}】\n{text}", temperature=0.0, max_tokens=2000)
    return r.text.strip()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/clean.txt")
    title = argv[argv.index("--title") + 1] if "--title" in argv else ""

    pages: dict[str, str] = json.loads(src.read_text(encoding="utf-8"))
    names = sorted(pages)
    if not names:
        print("没有 OCR 结果")
        return 1
    cfg = load_config()

    def work(name: str) -> str:
        try:
            return clean_page(cfg, name, pages[name])
        except Exception as e:  # noqa: BLE001
            print(f"  {name} 失败：{e}")
            return pages[name]

    cleaned = parallel_run(work, names)
    body = "\n\n".join(t for t in cleaned if t)
    if title:
        body = f"# {title}\n\n" + body
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"写入 {out}（{len(body)} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
