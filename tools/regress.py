"""回归测试：用当前 prompt 重译黄金集，评分并与基线对比。

用法：
    python tools/regress.py baseline     # 建立基线
    python tools/regress.py v2           # 与基线对比

产物：
    eval/fresh-<tag>.jsonl      本次重译结果
    reports/_shared/regress-<tag>.md
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.llm import chat, load_config           # noqa: E402
from epubtr.model import Block                     # noqa: E402
from epubtr.paths import report as report_path     # noqa: E402
from epubtr.translate import translate_batch       # noqa: E402

MARK = re.compile(r"⟦[^⟧]*⟧")
JUDGE = """你在给日本小说译成中文的译文打分。四个维度各 1–5 分：
fidelity（保真）、fluency（流畅）、register（语体口吻）、ambiguity（含糊处保留）。
只输出 JSON：{"fidelity":n,"fluency":n,"register":n,"ambiguity":n}
"""


def to_block(i: int, item: dict) -> Block:
    src = MARK.sub("", item["source"])
    return Block(uid=f"g{i}", index=i, tag="p", kind="para",
                 open_raw="", close_raw="", content_start=0, content_end=0,
                 spans=(), source=src)


def main(argv: list[str]) -> int:
    tag = argv[1] if len(argv) > 1 else "baseline"
    cfg = load_config()
    items = [json.loads(l) for l in
             Path("eval/golden.jsonl").read_text(encoding="utf-8").splitlines() if l]
    print(f"黄金集 {len(items)} 条，重译中…")

    out = []
    for i in range(0, len(items), 8):
        group = items[i:i + 8]
        blocks = [to_block(i + j, it) for j, it in enumerate(group)]
        try:
            trans = translate_batch(cfg, "回归测试", "未知", blocks, notes="")
        except Exception as e:  # noqa: BLE001
            print("  翻译失败:", e)
            continue
        for j, it in enumerate(group):
            out.append({**it, "fresh": trans.get(f"g{i + j}", "")})
        print(f"  {i + len(group)}/{len(items)}", end="\r", flush=True)
    print()

    for it in out:
        if not it.get("fresh"):
            continue
        s = 0
        try:
            r = chat(cfg, JUDGE,
                     f"【原文】\n{it['source']}\n\n【译文】\n{it['fresh']}",
                     temperature=0.0, max_tokens=200, json_mode=True)
            d = json.loads(r.text)
            it["scores"] = {k: int(d.get(k, 0)) for k in
                            ("fidelity", "fluency", "register", "ambiguity")}
        except Exception:  # noqa: BLE001
            it["scores"] = {"fidelity": 0, "fluency": 0, "register": 0, "ambiguity": 0}

    Path("eval").mkdir(exist_ok=True)
    Path(f"eval/fresh-{tag}.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in out), encoding="utf-8")

    def avg(rows, k):
        vals = [r["scores"][k] for r in rows if r.get("scores")]
        return round(statistics.mean(vals), 2) if vals else 0

    overall = {k: avg(out, k) for k in
               ("fidelity", "fluency", "register", "ambiguity")}

    base_path = Path("eval/baseline-fresh.json")
    lines = [f"# 回归报告（{tag}）", "", f"- 样本 {len(out)} 条", "",
             "| 维度 | 本次 | 基线 | 变化 |", "|---|---:|---:|---:|"]
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else None
    for k, v in overall.items():
        b = base["overall"][k] if base else "—"
        delta = f"{v - b:+.2f}" if base else "—"
        lines.append(f"| {k} | {v} | {b} | {delta} |")
    if not base:
        base_path.write_text(json.dumps({"tag": tag, "overall": overall},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        lines += ["", "已建立基线（eval/baseline-fresh.json）。"]

    worst = sorted([r for r in out if r.get("scores")],
                   key=lambda r: sum(r["scores"].values()))[:8]
    lines += ["", "## 最低分段落", ""]
    for r in worst:
        lines.append(f"- `{r['id']}` {r['scores']} · {r['fresh'][:60]}")

    p = report_path(None, f"regress-{tag}.md")
    p.write_text("\n".join(lines), encoding="utf-8")
    print("总体:", overall)
    print("写入", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
