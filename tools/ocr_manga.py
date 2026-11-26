"""用 manga-ocr 识别日文竖排书页。

用法：
    python tools/ocr_manga.py <图片目录> --out work/_ocr/manga.json

图片按文件名排序（建议先重命名成 001.jpg、002.jpg…）。
已识别的页会跳过，可断点续跑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder = Path(argv[1])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/manga.json")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS
                   and not p.name.startswith("000_"))
    if not files:
        print("没有图片")
        return 1

    done: dict[str, str] = {}
    if out.exists():
        done = json.loads(out.read_text(encoding="utf-8"))

    from manga_ocr import MangaOcr
    print("加载模型…", flush=True)
    mocr = MangaOcr()

    for i, p in enumerate(files, 1):
        if p.name in done:
            continue
        try:
            text = mocr(str(p))
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(files)}] {p.name} 失败：{e}")
            continue
        done[p.name] = text.strip()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
        preview = done[p.name].replace("\n", " ")[:36]
        print(f"[{i}/{len(files)}] {p.name} | {preview}", flush=True)

    print(f"\n完成 {len(done)} 页 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
