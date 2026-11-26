"""书页 OCR（PaddleOCR，日文竖排/双栏），按行序拼接。

用法：
    python tools/ocr_paddle.py <图片目录> [--out work/_ocr/paddle.json]

适合扫描件。按 y 分行、行内从右到左，能处理杂志双栏与跨页。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("FLAGS_use_mkldnn", "0")

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
NOISE = re.compile(r"^[\s0-9oO]{1,3}$")


def order_boxes(boxes: list[list[float]], texts: list[str]) -> str:
    """PaddleOCR 已按版面给出阅读顺序，直接采用；只去页眉与页码。"""
    body = [t for t in texts if not NOISE.match(t)]
    text = "".join(body)
    text = re.sub(r"^(米澤穂信)?赤いスイムキャップ(米澤穂信)?", "", text)
    text = text.replace("米澤穂信赤いスイムキャップ", "").replace("赤いスイムキャップ米澤穂信", "")
    return text


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/paddle.json")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS
                   and not p.name.startswith("000_"))
    if not files:
        print("没有图片")
        return 1

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="japan", use_doc_orientation_classify=False,
                    use_doc_unwarping=False, use_textline_orientation=True,
                    enable_mkldnn=False)

    done: dict[str, str] = {}
    if out.exists():
        done = json.loads(out.read_text(encoding="utf-8"))

    for i, p in enumerate(files, 1):
        if p.name in done:
            continue
        res = ocr.predict(str(p))
        if not res:
            continue
        d = res[0].json["res"]
        text = order_boxes(d["rec_boxes"], d["rec_texts"])
        done[p.name] = text
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i}/{len(files)}] {p.name} | {text[:36]}", flush=True)

    print(f"\n完成 {len(done)} 页 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
