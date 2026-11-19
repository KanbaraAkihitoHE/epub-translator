"""A/B 验证润色效果：同一批段落，润色前后各评一次分。

用法：python tools/ab_polish.py <epub> [样本数]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.epub import open_book, read_doc        # noqa: E402
from epubtr.ir import extract_doc                  # noqa: E402
from epubtr.llm import chat, load_config          # noqa: E402
from epubtr.paths import report as report_path, slug  # noqa: E402
from epubtr.render import MarkerError, tokenize, validate  # noqa: E402

JUDGE = """你在给日本小说译成中文的译文打分。四个维度各 1–5 分：
fidelity（保真：无漏译误译增译）、fluency（中文通顺）、register（语体口吻）、ambiguity（含糊处保留）。
只输出 JSON：{"fidelity":n,"fluency":n,"register":n,"ambiguity":n}
"""

POLISH = """你是中文编辑，润色日本小说的译文。
只改表达（语序、用词、冗余、翻译腔），不改事实、不增删信息、不解释；
保留全部内联标记，数量与顺序不变；人名术语数字不动；原文含糊处保持含糊。
输出 JSON：{"units":[{"id":"...","text":"..."}]}
"""


def judge(cfg, ja: str, zh: str) -> dict | None:
    try:
        r = chat(cfg, JUDGE, f"【原文】\n{ja}\n\n【译文】\n{zh}",
                 temperature=0.0, max_tokens=200, json_mode=True)
        d = json.loads(r.text)
        return {k: int(d.get(k, 0)) for k in
                ("fidelity", "fluency", "register", "ambiguity")}
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    limit = int(argv[2]) if len(argv) > 2 else 30
    book, z = open_book(Path(argv[1]))
    name = slug(book.title or Path(argv[1]).stem)
    work = Path("work") / name
    rev = work / "rev"
    cfg = load_config()

    picked = []
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        style_ids = {i["id"] for i in data.get("issues", [])
                     if i.get("type") in ("style", "fluency")}
        for b in doc.blocks:
            if b.uid in style_ids and data["units"].get(b.uid):
                picked.append({"doc": item.full, "uid": b.uid, "ja": b.source,
                               "zh": data["units"][b.uid], "spans": b.spans})
            if len(picked) >= limit:
                break
        if len(picked) >= limit:
            break

    print(f"样本 {len(picked)} 段（审校判为风格问题的段落）")
    for i, p in enumerate(picked):
        p["before"] = judge(cfg, p["ja"], p["zh"])
        print(f"  评分 {i + 1}/{len(picked)}", end="\r", flush=True)
    print()

    for i in range(0, len(picked), 6):
        group = picked[i:i + 6]
        payload = json.dumps({"units": [{"id": p["uid"], "ja": p["ja"],
                                         "zh": p["zh"]} for p in group]},
                             ensure_ascii=False, indent=1)
        try:
            r = chat(cfg, POLISH, payload, temperature=0.3, max_tokens=4096,
                     json_mode=True)
            out = json.loads(r.text).get("units", [])
        except Exception:  # noqa: BLE001
            continue
        for it in out:
            p = next((x for x in group if x["uid"] == it.get("id")), None)
            if p is None or not isinstance(it.get("text"), str):
                continue
            try:
                validate(tokenize(it["text"]), p["spans"])
            except MarkerError:
                continue
            p["after_text"] = it["text"]
    for p in picked:
        p["after"] = judge(cfg, p["ja"], p.get("after_text", p["zh"]))

    def avg(rows, k, which):
        vals = [r[which][k] for r in rows if r.get(which)]
        return round(statistics.mean(vals), 2) if vals else 0

    dims = ("fidelity", "fluency", "register", "ambiguity")
    before = {k: avg(picked, k, "before") for k in dims}
    after = {k: avg(picked, k, "after") for k in dims}
    changed = [p for p in picked if p.get("after_text") and p["after_text"] != p["zh"]]

    lines = [f"# 润色 A/B：{book.title}", "",
             f"- 样本 {len(picked)} 段，实际改写 {len(changed)} 段", "",
             "| 维度 | 润色前 | 润色后 | 变化 |", "|---|---:|---:|---:|"]
    for k in dims:
        lines.append(f"| {k} | {before[k]} | {after[k]} | {after[k] - before[k]:+.2f} |")
    lines += ["", "## 改写示例", ""]
    for p in changed[:8]:
        lines += [f"**{p['doc'].split('/')[-1]} · {p['uid']}**",
                  f"- 前：{p['zh'][:110]}",
                  f"- 后：{p['after_text'][:110]}", ""]
    p = report_path(name, "ab-polish.md")
    p.write_text("\n".join(lines), encoding="utf-8")
    print("前:", before)
    print("后:", after)
    print("改写", len(changed), "段，报告", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
