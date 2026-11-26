"""把整理好的日文文本做成竖排 EPUB。

用法：
    python tools/make_vertical_epub.py work/_ocr/clean.txt --title "赤いスイムキャップ" --author "米澤穂信" --out out/xxx.ja.epub
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epubtr.txtbook import build_txt_epub  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    def opt(name: str, default: str = "") -> str:
        return argv[argv.index(name) + 1] if name in argv else default

    src = Path(argv[1])
    title = opt("--title", "无名片段")
    author = opt("--author", "")
    out = Path(opt("--out", f"out/{title}.ja.epub"))
    raw = src.read_text(encoding="utf-8")
    if not raw.lstrip().startswith("# "):
        raw = f"# {title}\n\n{raw}"
    path, real_title = build_txt_epub(raw, out, title=title, author=author,
                                      lang="ja", vertical=True)
    print(f"写入 {path}（{real_title}，竖排）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
