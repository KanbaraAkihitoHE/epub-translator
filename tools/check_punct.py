"""标点配对校验：引号、括号、书名号是否成对、嵌套是否正确。

用法：python tools/check_punct.py <epub>
产物：reports/<书名>/punctuation.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book                  # noqa: E402
from epubtr.paths import report as report_path, slug  # noqa: E402
from epubtr.punct import check_text                 # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, _ = open_book(Path(argv[1]))
    s = slug(book.title or Path(argv[1]).stem)
    work = Path("work") / s
    rev = work / "rev"

    issues = []
    stats: Counter = Counter()
    total_units = 0
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        units = data["units"]
        total_units += len(units)
        # 整篇连起来检查：日文对话常跨段，逐段检查会把"合法未闭合"误判成错误
        text = "\n".join(units.values())
        spans = []
        pos = 0
        for uid, val in units.items():
            spans.append((pos, pos + len(val), uid))
            pos += len(val) + 1
        errs = check_text(text)
        if errs:
            def uid_at(offset: int) -> str:
                for a, b, uid in spans:
                    if a <= offset <= b:
                        return uid
                return "?"
            issues.append({"doc": data["href"],
                           "errors": [f"{uid_at(p)}：{m}" for p, m in errs[:5]],
                           "sample": text[:100]})
            for _, m in errs:
                stats[m.split("「")[0]] += 1

    lines = [f"# 标点校验：{book.title}", "",
             f"- 段落 {total_units} · 篇数 {len(list(work.glob('*.json'))) - 1}",
             f"- 有问题的篇 {len(issues)}", ""]
    if stats:
        lines += ["## 问题类型", ""]
        lines += [f"- {k}：{n}" for k, n in stats.most_common()]
        lines.append("")
    for it in issues[:40]:
        lines += [f"### {it['doc']}",
                  f"- {'；'.join(it['errors'])}",
                  f"- 片段：{it['sample']}", ""]
    if not issues:
        lines.append("未发现问题。")

    p = report_path(s, "punctuation.md")
    p.write_text("\n".join(lines), encoding="utf-8")
    print(f"标点问题 {len(issues)} 段，写入 {p}")
    for k, n in stats.most_common(5):
        print(f"  {k}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
