"""构建黄金集：固定抽样，覆盖对话/叙述/长句/字谜风险。

用法：python tools/build_golden.py <epub> [更多 epub ...]
产物：eval/golden.jsonl（多本合并，带 book 字段）
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402

RISK = re.compile(r"[＊\*]{2,}|「[^」]{0,6}」")
QUOTA = {"dialogue": 18, "narration": 14, "long": 12, "risk": 8, "short": 8}


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def category(b) -> str:
    s = b.source
    if "「" in s and len(s) < 120:
        return "dialogue"
    if RISK.search(s):
        return "risk"
    if len(s) > 130:
        return "long"
    if len(s) < 25:
        return "short"
    return "narration"


def collect(src: Path) -> list[dict]:
    book, z = open_book(src)
    name = slug(book.title or src.stem)
    work = Path("work") / name
    rev = work / "rev"
    if not work.exists():
        print(f"跳过（没有译文）：{book.title}")
        return []
    pool: dict[str, list[dict]] = {}
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        for b in doc.blocks:
            zh = data["units"].get(b.uid, "")
            if not zh or len(zh) < 6:
                continue
            pool.setdefault(category(b), []).append({
                "book": name,
                "id": f"{name}:{item.full}:{b.uid}",
                "doc": item.full, "uid": b.uid,
                "category": category(b), "source": b.source, "current": zh,
            })
    rng = random.Random(20261118)
    picked = []
    for cat, n in QUOTA.items():
        items = pool.get(cat, [])
        rng.shuffle(items)
        picked += items[:n]
    picked.sort(key=lambda x: x["id"])
    print(f"  {book.title[:26]}: {len(picked)} 条")
    return picked


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    picked: list[dict] = []
    for p in argv[1:]:
        picked += collect(Path(p))
    Path("eval").mkdir(exist_ok=True)
    with Path("eval/golden.jsonl").open("w", encoding="utf-8") as f:
        for it in picked:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"黄金集 {len(picked)} 条 -> eval/golden.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
