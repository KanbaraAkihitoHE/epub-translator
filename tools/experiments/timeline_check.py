"""时间线矛盾检测：规则抽取 + 一次模型审阅。

用法：python tools/timeline_check.py <epub>
产物：docs/timeline-report.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.llm import chat, load_config          # noqa: E402
from epubtr.package import plain                  # noqa: E402

TIME_RE = re.compile(
    r"(午前|午後|深夜|未明|明け方|朝|昼|夕方|夜)"
    r"|([0-9０-９一二三四五六七八九十百]+)\s*(時|時半|分|秒|月|日|年|週間|日前|時間)"
    r"|(前日|翌日|翌朝|当日|同日|昨日|今日|明日|一昨年|去年|今年)")


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def times_in(text: str) -> list[str]:
    out = []
    for m in TIME_RE.finditer(text):
        out.append(m.group(0))
    return out


SYSTEM = """你在核对一部日本推理小说的时间线。

下面按**阅读顺序**列出书中出现的时间信息（位置、日文原文片段、中文译文）。
请找出可能的时间线矛盾，例如：
- 同一事件在不同章节被说成不同时间；
- 时间顺序颠倒（后发生的事被说成先发生）；
- 时长对不上（说"三天前"，但前文只过了一天）；
- 同一个人/物在同一时刻出现在两地（若明显是叙述诡计则不算）。

要求：
1. 只报**有把握**的矛盾；没有就返回空数组。
2. 每条给出位置 id、矛盾点、理由（一句话）。
3. 注意：叙述性诡计、倒叙、作中作可能故意制造时间错位，遇到时标注"疑似有意"。

输出 JSON：{"issues":[{"id":"位置","point":"矛盾点","reason":"理由","intentional":true|false}]}
"""


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

    entries = []
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
            ja = plain(b.source)
            ts = times_in(ja)
            if not ts:
                continue
            entries.append({"id": f"{item.full.split('/')[-1]}:{b.uid}",
                            "times": ts,
                            "ja": ja[:120],
                            "zh": data["units"].get(b.uid, "")[:120]})
        if len(entries) > 400:
            break

    print(f"时间信息 {len(entries)} 条，模型审阅中…")
    payload = json.dumps({"timeline": entries[:260]}, ensure_ascii=False)
    try:
        r = chat(cfg, SYSTEM, payload, temperature=0.1, max_tokens=4000,
                 json_mode=True)
        issues = json.loads(r.text).get("issues", [])
    except Exception as e:  # noqa: BLE001
        print("调用失败:", e)
        issues = []

    lines = [f"# 时间线检查：{book.title}", "",
             f"- 抽取时间信息 {len(entries)} 条，送检 {min(len(entries), 260)} 条",
             f"- 疑似矛盾 {len(issues)} 条", ""]
    for it in issues:
        flag = "（疑似有意）" if it.get("intentional") else ""
        lines += [f"### {it.get('id','')} {flag}",
                  f"- 矛盾点：{it.get('point','')}",
                  f"- 理由：{it.get('reason','')}", ""]
    if not issues:
        lines.append("未发现矛盾。")

    from epubtr.paths import report as report_path
    report_path(name, "timeline.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"疑似矛盾 {len(issues)} 条，写入 docs/timeline-report.md")
    for it in issues[:5]:
        print(" -", it.get("point", "")[:60], "|", it.get("reason", "")[:50])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
