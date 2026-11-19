"""对黄金集打分：四维 rubric + 确定性断言，保存基线便于回归对比。

用法：python tools/eval_run.py <tag>
产物：eval/results-<tag>.json、docs/eval-<tag>.md
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.llm import chat, load_config       # noqa: E402

SYSTEM = """你在给日本小说译成中文的译文打分。给你日文原文和中文译文。

四个维度各 1–5 分（5 最好）：
- fidelity：保真。无漏译、无误译、无增译。
- fluency：中文通顺度。像中文母语者写的，不拗口。
- register：语体与口吻。叙述/对话区分、人物语气、敬称处理得当。
- ambiguity：原文故意含糊处（性别、身份、时间、谁说的）是否保留。

注意：正文中保留的日文（字谜、谐音、专有名词）可能是刻意为之，不要因此扣分。

只输出 JSON：
{"fidelity":n,"fluency":n,"register":n,"ambiguity":n,"errors":["最多两条具体问题"]}
"""


def main(argv: list[str]) -> int:
    tag = argv[1] if len(argv) > 1 else "baseline"
    cfg = load_config()
    items = [json.loads(l) for l in
             Path("eval/golden.jsonl").read_text(encoding="utf-8").splitlines() if l]
    results = []
    for i, it in enumerate(items, 1):
        prompt = (f"【原文】\n{it['source']}\n\n【译文】\n{it['current']}")
        try:
            r = chat(cfg, SYSTEM, prompt, temperature=0.0, max_tokens=300,
                     json_mode=True)
            s = json.loads(r.text)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}] fail {e}")
            continue
        rec = {"id": it["id"], "category": it["category"],
               "scores": {k: int(s.get(k, 0)) for k in
                          ("fidelity", "fluency", "register", "ambiguity")},
               "errors": s.get("errors", [])}
        results.append(rec)
        print(f"  [{i}/{len(items)}] {it['category']:9s} {rec['scores']}", flush=True)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["scores"])

    def avg(rows, k):
        return round(statistics.mean(x[k] for x in rows), 2) if rows else 0

    summary = {
        "tag": tag,
        "n": len(results),
        "overall": {k: avg([r["scores"] for r in results], k)
                    for k in ("fidelity", "fluency", "register", "ambiguity")},
        "by_category": {c: {k: avg(rows, k) for k in
                            ("fidelity", "fluency", "register", "ambiguity")}
                        for c, rows in by_cat.items()},
        "worst": sorted(results, key=lambda r: sum(r["scores"].values()))[:10],
    }
    Path("eval").mkdir(exist_ok=True)
    Path(f"eval/results-{tag}.json").write_text(
        json.dumps({"summary": summary, "results": results},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# 评测报告（{tag}）", "",
             f"样本 {summary['n']} 条", "",
             "| 维度 | 均分 |", "|---|---:|"]
    for k, v in summary["overall"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 分类", "", "| 类别 | n | fidelity | fluency | register | ambiguity |",
              "|---|---:|---:|---:|---:|---:|"]
    for c, v in summary["by_category"].items():
        n = len(by_cat[c])
        lines.append(f"| {c} | {n} | {v['fidelity']} | {v['fluency']} | "
                     f"{v['register']} | {v['ambiguity']} |")
    lines += ["", "## 最差的 10 条", ""]
    for r in summary["worst"]:
        lines.append(f"- `{r['id']}` {r['scores']} · {'；'.join(r['errors'])[:80]}")
    from epubtr.paths import report as report_path
    report_path(None, f"eval-{tag}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n总体: {summary['overall']}")
    print(f"写入 eval/results-{tag}.json 与 docs/eval-{tag}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
