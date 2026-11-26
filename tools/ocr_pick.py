"""两版 OCR 取优：同一页比较 Tesseract 与 PaddleOCR，选更通顺的一份。

用法：
    python tools/ocr_pick.py work/_ocr/pdf_ocr.json work/_ocr/paddle.json --out work/_ocr/best.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.llm import chat, load_config      # noqa: E402
from epubtr.parallel import run as parallel_run  # noqa: E402

HEADER = re.compile(r"(赤いスイムキャップ|米澤穂信){2,}")
SYS = """下面是一页日文竖排书的两个 OCR 结果（A、B）。请判断哪一份更接近通顺的日文原文：
错字更少、句子衔接更自然、没有重复或乱序。
只输出 JSON：{"pick": "A" 或 "B", "reason": "一句话"}。如果两份都差，也选相对好的那份。"""


def clean_head(text: str) -> str:
    text = HEADER.sub("", text)
    text = text.replace("赤いスイムキャップ米澤穂信", "").replace("米澤穂信赤いスイムキャップ", "")
    return text.strip()


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    a = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    b = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("work/_ocr/best.json")
    cfg = load_config()
    pages = sorted(set(a) & set(b))

    def pick(name: str) -> tuple[str, str]:
        ta, tb = clean_head(a[name]), clean_head(b[name])
        try:
            r = chat(cfg, SYS, f"【A】\n{ta[:1500]}\n\n【B】\n{tb[:1500]}",
                     temperature=0.0, max_tokens=120, json_mode=True)
            d = json.loads(r.text)
            chosen = ta if d.get("pick") == "A" else tb
            return name, chosen
        except Exception:  # noqa: BLE001
            return name, ta if len(ta) >= len(tb) else tb

    results = parallel_run(pick, pages)
    best = {n: t for n, t in results}
    out.write_text(json.dumps(best, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"取优完成 {len(best)} 页 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
