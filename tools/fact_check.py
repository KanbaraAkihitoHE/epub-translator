"""事实清单：从原文提炼信息点，检查译文是否覆盖（不懂日文也能验保真）。

用法：python tools/fact_check.py <epub>
产出：docs/fact-checklist.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc       # noqa: E402
from epubtr.ir import extract_doc                  # noqa: E402
from epubtr.llm import chat, load_config          # noqa: E402

SYSTEM = """你在核对日译中的**信息完整性**，不评价文采。

对每个段落：
1. 从日文原文提取 1–3 条关键事实（人物、动作、时间地点、数量、关键线索、态度），用简短中文表述。
2. 判断中文译文是否表达了这条事实：yes / partial / no。
   - yes：意思在译文中能找到
   - partial：部分丢失或走样
   - no：译文里没有

只输出 JSON：{"items":[{"id":"段落id","facts":[{"fact":"...","covered":"yes|partial|no"}]}]}
"""


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, z = open_book(src)
    name = slug(book.title or src.stem)
    work = Path("work") / name
    rev = work / "rev"
    cfg = load_config()
    findings = []
    calls = 0

    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if (rev / f.name).exists():
            data = json.loads((rev / f.name).read_text(encoding="utf-8"))
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        units = data["units"]
        blocks = doc.blocks
        for i in range(0, len(blocks), 10):
            group = blocks[i:i + 10]
            payload = json.dumps({"units": [
                {"id": b.uid, "ja": b.source, "zh": units.get(b.uid, "")}
                for b in group]}, ensure_ascii=False, indent=1)
            try:
                r = chat(cfg, SYSTEM, payload, temperature=0.1, max_tokens=2048,
                         json_mode=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [fail] {item.full}@{i}: {e}")
                continue
            calls += 1
            try:
                got = json.loads(r.text)
            except json.JSONDecodeError:
                continue
            for it in got.get("items", []):
                bad = [f for f in it.get("facts", [])
                       if f.get("covered") in ("partial", "no")]
                if bad:
                    findings.append({"doc": item.full, "id": it.get("id"),
                                     "facts": bad})
        print(f"{item.full}: 累计 {len(findings)} 处可疑", flush=True)

    lines = [f"# 事实清单：{book.title}", "",
             f"- 抽查段数：全书 · 调用 {calls} 次",
             f"- 信息缺失/走样：{len(findings)} 处", ""]
    for f in findings:
        lines += [f"### {f['doc']} · {f['id']}", ""]
        for fact in f["facts"]:
            lines.append(f"- [{fact.get('covered')}] {fact.get('fact')}")
        lines.append("")
    from epubtr.paths import report as report_path
    report_path(name, "fact-checklist.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n共 {len(findings)} 处可疑，写入 docs/fact-checklist.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
