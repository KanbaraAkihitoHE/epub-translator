"""风险模型验证：高分段的修订问题率是否真的更高。

用法：python tools/risk_report.py <epub>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.risk import score                     # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, z = open_book(Path(argv[1]))
    work = Path("work") / slug(book.title or Path(argv[1]).stem)
    rev = work / "rev"
    buckets: dict[str, list[int]] = defaultdict(list)
    threshold_stats = {0.3: [0, 0], 0.5: [0, 0], 0.7: [0, 0]}
    total = 0

    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        rp = rev / f.name
        if not rp.exists():
            continue
        data = json.loads(rp.read_text(encoding="utf-8"))
        issue_ids = {i["id"] for i in data.get("issues", [])}
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        for b in doc.blocks:
            total += 1
            s = score(b).score
            key = f"{int(s * 10) / 10:.1f}"
            buckets[key].append(1 if b.uid in issue_ids else 0)
            for t in threshold_stats:
                if s >= t:
                    threshold_stats[t][0] += 1
                    threshold_stats[t][1] += 1 if b.uid in issue_ids else 0

    print(f"总段数 {total}\n")
    print("| 风险分 | 段数 | 有问题 | 问题率 |")
    print("|---|---:|---:|---:|")
    for k in sorted(buckets, key=float):
        rows = buckets[k]
        n = len(rows)
        hit = sum(rows)
        print(f"| {k} | {n} | {hit} | {hit / n:.0%} |")

    print("\n若按阈值只对高分段落做修订：")
    print("| 阈值 | 覆盖段数 | 覆盖率 | 捕获问题 | 问题召回 | 省下的修订量 |")
    print("|---:|---:|---:|---:|---:|---:|")
    all_hits = sum(sum(v) for v in buckets.values())
    for t, (n, hit) in threshold_stats.items():
        print(f"| {t} | {n} | {n / total:.0%} | {hit}/{all_hits} | "
              f"{hit / max(1, all_hits):.0%} | {1 - n / total:.0%} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
