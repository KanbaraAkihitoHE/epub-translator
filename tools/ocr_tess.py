"""书页扫描件 OCR（Tesseract jpn_vert），带预处理。

用法：
    python tools/ocr_tess.py <图片目录> [--out work/_ocr/tess.json]

适合平板扫描或平整拍摄的竖排日文书页；手机斜拍效果差。
需要：tesseract.exe + work/_ocr/tessdata/jpn_vert.traineddata
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
TESS_CANDIDATES = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", "tesseract"]
ROOT = Path(__file__).resolve().parents[1]
TESSDATA = ROOT / "work" / "_ocr" / "tessdata"


def tesseract() -> str:
    for c in TESS_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return c
    raise SystemExit("找不到 tesseract，请先安装（winget install UB-Mannheim.TesseractOCR）")


def otsu(a: np.ndarray) -> int:
    hist, _ = np.histogram(a, bins=256, range=(0, 256))
    total, sum_all = a.size, float(np.dot(np.arange(256), hist))
    sum_b = w_b = 0.0
    best_t, best_v = 128, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        v = w_b * w_f * (sum_b / w_b - (sum_all - sum_b) / w_f) ** 2
        if v > best_v:
            best_t, best_v = t, v
    return best_t


def prepare(img: Image.Image) -> Image.Image:
    """灰度化 + 裁到文字区域 + 增强对比。扫描件无需复杂纠偏。"""
    g = img.convert("L")
    a = np.array(g)
    th = otsu(a)
    ink = a < th
    h, w = a.shape
    mh, mw = int(h * 0.02), int(w * 0.02)
    sub = ink[mh:h - mh, mw:w - mw]
    ys, xs = np.where(sub)
    if len(ys) == 0:
        return g
    x0, x1 = xs.min() + mw, xs.max() + mw
    y0, y1 = ys.min() + mh, ys.max() + mh
    pad = 12
    crop = g.crop((max(0, x0 - pad), max(0, y0 - pad),
                   min(w, x1 + pad), min(h, y1 + pad)))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    crop = crop.filter(ImageFilter.MedianFilter(3))
    return ImageOps.autocontrast(crop)


def clean(text: str) -> str:
    text = re.sub(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/tess.json")
    psm = argv[argv.index("--psm") + 1] if "--psm" in argv else "3"
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS
                   and not p.name.startswith("000_"))
    if not files:
        print("没有图片")
        return 1
    if not (TESSDATA / "jpn_vert.traineddata").exists():
        print(f"缺少 {TESSDATA / 'jpn_vert.traineddata'}")
        return 1

    tess = tesseract()
    done: dict[str, str] = {}
    if out.exists():
        done = json.loads(out.read_text(encoding="utf-8"))

    tmp = ROOT / "work" / "_ocr" / "_page.png"
    for i, p in enumerate(files, 1):
        if p.name in done:
            continue
        prepare(Image.open(p)).save(tmp)
        base = ROOT / "work" / "_ocr" / "_out"
        subprocess.run([tess, str(tmp), str(base), "--tessdata-dir", str(TESSDATA),
                        "-l", "jpn_vert", "--psm", psm],
                       capture_output=True)
        text = clean(base.with_suffix(".txt").read_text(encoding="utf-8"))
        if re.search(r"[「『]\s*[」』]", text):
            print(f"  [warn] {p.name} 出现空引号，可能有数字/字符未识别")
        done[p.name] = text
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i}/{len(files)}] {p.name} | {text[:36]}", flush=True)

    print(f"\n完成 {len(done)} 页 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
