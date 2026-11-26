"""把照片里的日文（竖排）OCR 成文本，按页输出 JSON。

依赖 Windows 自带 OCR（winrt），无需联网。

用法：
    python tools/ocr_pages.py <图片目录> [--out work/_ocr/pages.json]
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".webp"}
KANA = re.compile(r"[\u3040-\u30ff]")

try:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile
except ImportError:  # pragma: no cover
    print("需要安装：pip install winrt-runtime winrt-Windows.Media.Ocr "
          "winrt-Windows.Graphics.Imaging winrt-Windows.Storage winrt-Windows.Globalization")
    raise SystemExit(1)


async def ocr_file(path: Path) -> list[dict]:
    f = await StorageFile.get_file_from_path_async(str(path))
    stream = await f.open_async(FileAccessMode.READ)
    dec = await BitmapDecoder.create_async(stream)
    bmp = await dec.get_software_bitmap_async()
    eng = OcrEngine.try_create_from_language(Language("ja"))
    res = await eng.recognize_async(bmp)
    out = []
    for ln in res.lines:
        if not ln.words:
            continue
        r = ln.words[0].bounding_rect
        out.append({"x": round(r.x), "y": round(r.y),
                    "w": round(r.width), "h": round(r.height),
                    "text": ln.text})
    return out


def column_text(lines: list[dict]) -> str:
    """竖排：按列从右到左读；同一列按 y 从上到下。"""
    if not lines:
        return ""
    cols: list[list[dict]] = []
    for ln in sorted(lines, key=lambda d: -d["x"]):
        if cols and abs(cols[-1][-1]["x"] - ln["x"]) <= 24:
            cols[-1].append(ln)
        else:
            cols.append([ln])
    parts = []
    for col in cols:
        col.sort(key=lambda d: d["y"])
        parts.append("".join(l["text"] for l in col))
    text = "".join(parts)
    text = re.sub(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])", "", text)
    return text.strip()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/pages.json")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS)
    pages = []
    for p in files:
        lines = asyncio.run(ocr_file(p))
        text = column_text(lines)
        kana = len(KANA.findall(text))
        pages.append({"file": p.name, "lines": lines, "text": text, "kana": kana})
        print(f"{p.name[:14]}… 行 {len(lines):>3} 假名 {kana:>4} | {text[:40]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写入 {out}（{len(pages)} 页）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
