"""自动质检：不需要读日文，也能找出最可能出问题的段落。

用法：python tools/qa_report.py <epub>
产出：docs/qa-report.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.glossary import check as gl_check    # noqa: E402
from epubtr.glossary import load as gl_load      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.package import plain                  # noqa: E402

KANA = re.compile(r"[\u3040-\u30ff]")
CJK = re.compile(r"[\u4e00-\u9fff]")


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def zh_len(s: str) -> int:
    return len(re.sub(r"⟦[^⟧]*⟧", "", s))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, z = open_book(src)
    work = Path("work") / slug(book.title or src.stem)
    gl = gl_load(Path("kb") / slug(book.title or src.stem))

    rows = []
    seen: dict[str, list[str]] = {}
    all_units = {}
    rev = work / "rev"

    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        units = data["units"]
        all_units[item.full] = units
        for b in doc.blocks:
            ja = plain(b.source)
            zh = units.get(b.uid, "")
            if not ja:
                continue
            ratio = zh_len(zh) / max(1, len(ja))
            kana = len(KANA.findall(zh))
            viol = gl_check(gl, b.source, zh)
            flags = []
            if not zh:
                flags.append("空译文")
            elif zh.strip() == ja.strip():
                flags.append("未译")
            if kana > 2:
                flags.append(f"假名{kana}")
            if ratio < 0.45:
                flags.append(f"过短{ratio:.2f}")
            if ratio > 1.35:
                flags.append(f"过长{ratio:.2f}")
            if viol:
                flags.append("术语:" + ",".join(viol[:2]))
            if len(zh) > 8:
                seen.setdefault(zh, []).append(f"{item.full}:{b.uid}")
            rows.append({"doc": item.full, "uid": b.uid, "ja": b.source,
                         "zh": zh, "ratio": ratio, "flags": flags})

    for zh, locs in seen.items():
        if len(locs) > 2 and len(zh) > 10:
            for loc in locs:
                for r in rows:
                    if f"{r['doc']}:{r['uid']}" == loc:
                        r["flags"].append(f"重复×{len(locs)}")

    bad = [r for r in rows if r["flags"]]
    by_doc = Counter(r["doc"] for r in bad)
    total_zh = sum(zh_len(r["zh"]) for r in rows)
    total_kana = sum(len(KANA.findall(r["zh"])) for r in rows)
    total_docs = len(all_units)

    lines = [f"# 质检报告：{book.title}", "",
             f"- 篇数 {total_docs} · 段数 {len(rows)} · 中文 {total_zh:,} 字",
             f"- 可疑段 {len(bad)}（{len(bad) / max(1, len(rows)):.1%}）",
             f"- 译文中的假名总数 {total_kana}", "",
             "## 按篇统计", "", "| 篇 | 可疑段 |", "|---|---:|"]
    for doc, n in by_doc.most_common():
        lines.append(f"| {doc} | {n} |")

    lines += ["", "## 可疑段落（按优先级）", ""]
    for r in bad[:120]:
        lines += [f"### {r['doc']} · {r['uid']} — {'、'.join(r['flags'])}",
                  f"- 日：{r['ja'][:120]}",
                  f"- 中：{r['zh'][:120]}", ""]

    from epubtr.paths import report as report_path
    rp = report_path(slug(book.title or src.stem), "qa.md")
    rp.write_text("\n".join(lines), encoding="utf-8")
    print(f"段数 {len(rows)}，可疑 {len(bad)}（{len(bad) / max(1, len(rows)):.1%}），"
          f"假名残留 {total_kana}")
    for doc, n in by_doc.most_common(5):
        print(f"  {doc}: {n}")
    print("写入 docs/qa-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
