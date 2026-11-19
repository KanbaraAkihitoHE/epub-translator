"""跨章一致性检查 v2：按"称呼形式 + 敬称"分组，只提取名字，比较交给代码。

用法：python tools/consistency.py <epub>
产物：docs/consistency-report.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.bible import Bible                     # noqa: E402
from epubtr.epub import open_book, read_doc        # noqa: E402
from epubtr.glossary import check as gl_check, load as gl_load  # noqa: E402
from epubtr.ir import extract_doc                  # noqa: E402
from epubtr.llm import chat, load_config           # noqa: E402
from epubtr.package import plain                   # noqa: E402

EXTRACT_SYSTEM = """给你若干条日文原文和中文译文，都提到了同一个人物。

请从**中文译文**里提取这个人物的中文名字/称呼，每条输出一个：
- 只输出名字本身，不要带「同学、君、小姐、先生、女士、大人」这些敬称；
- 如果译文用的是代词（他/她/那家伙）或没出现名字，输出空字符串；
- 不要脑补，只抄译文里实际写的字。

只输出 JSON：{"items":[{"id":"...","name":"..."}]}
"""

HONORIFIC_JA = ("さん", "君", "くん", "ちゃん", "様", "先生", "先輩", "殿")
HONORIFIC_ZH = ("同学", "君", "小姐", "先生", "女士", "大人", "桑", "老师", "前辈")
# 军衔/职务常常黏在名字后面，比较前先剥掉
RANKS = ("一等海曹", "二等海曹", "三等海曹", "海曹长", "海曹", "曹长", "军曹",
         "警视总监", "警视监", "警视长", "警视正", "警视", "警部补", "警部",
         "巡查部长", "巡查", "社长", "部长", "课长", "主任", "店长", "经理")
RESIDUE = re.compile(r"[さん様ちゃん]|(?<![一-龥])君(?![主])")


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def strip_zh(name: str) -> str:
    n = name.strip()
    for r in RANKS:
        if r in n:
            n = n.replace(r, "")
    for h in HONORIFIC_ZH:
        if n.endswith(h):
            n = n[: -len(h)]
    return n.strip()


def compatible(variants: list[str]) -> bool:
    """简称与全名（互为子串）视为一致，不算漂移。"""
    if len(variants) <= 1:
        return True
    longest = max(variants, key=len)
    return all(v in longest or longest in v for v in variants)


def suffix_of(source: str, alias: str) -> str:
    i = source.find(alias)
    if i < 0:
        return ""
    tail = source[i + len(alias):i + len(alias) + 2]
    for h in HONORIFIC_JA:
        if tail.startswith(h):
            return h
    return ""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, z = open_book(src)
    name = slug(book.title or src.stem)
    work = Path("work") / name
    rev = work / "rev"
    bible = Bible(**json.loads((Path("kb") / name / "auto_bible.json")
                               .read_text(encoding="utf-8")))
    gl = gl_load(Path("kb") / name)
    cfg = load_config()

    rows = []
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
            rows.append({"doc": item.full, "uid": b.uid, "ja": b.source,
                         "zh": data["units"].get(b.uid, "")})

    gl_bad = [(r["doc"], r["uid"], gl_check(gl, r["ja"], r["zh"]))
              for r in rows if gl_check(gl, r["ja"], r["zh"])]
    hon_bad = [(r["doc"], r["uid"]) for r in rows if RESIDUE.search(r["zh"])]

    findings = []
    nicknames = {c["ja"] for c in gl.get("characters", [])
                 if "绰号" in (c.get("note") or "")}
    mains = [c for c in bible.characters if c.get("name_ja")][:10]
    for c in mains:
        aliases = sorted({c["name_ja"], *[a for a in c.get("aliases", []) if len(a) >= 2]},
                         key=len, reverse=True)
        # 绰号与全名的混用是正常的，不作为不一致
        aliases = [a for a in aliases if a not in nicknames]
        hits = []
        for r in rows:
            for a in aliases:
                if a in r["ja"]:
                    hits.append({**r, "form": a, "suffix": suffix_of(r["ja"], a)})
                    break
        if len(hits) < 3:
            continue
        sample = hits[:24]
        payload = json.dumps({"character": c["name_ja"],
                              "occurrences": [{"id": h["uid"], "ja": h["ja"][:140],
                                               "zh": h["zh"][:140]} for h in sample]},
                             ensure_ascii=False, indent=1)
        try:
            resp = chat(cfg, EXTRACT_SYSTEM, payload, temperature=0.0,
                        max_tokens=1200, json_mode=True)
            names = {it["id"]: it.get("name", "")
                     for it in json.loads(resp.text).get("items", [])}
        except Exception as e:  # noqa: BLE001
            print(f"  [skip] {c['name_ja']}: {e}")
            continue

        groups: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list))
        for h in sample:
            zh = strip_zh(names.get(h["uid"], ""))
            if not zh:
                continue
            groups[(h["form"], h["suffix"])][zh].append(h["uid"])
        bad = {k: v for k, v in groups.items()
               if len(v) > 1 and not compatible(list(v.keys()))}
        if bad:
            findings.append({"character": c["name_ja"], "bad": bad,
                             "total": len(hits)})
            print(f"  {c['name_ja']}: 不一致 {len(bad)} 组 / {len(hits)} 处",
                  flush=True)
        else:
            print(f"  {c['name_ja']}: 一致（{len(hits)} 处）", flush=True)

    lines = [f"# 跨章一致性报告：{book.title}", "",
             f"- 全书 {len(rows)} 段", "",
             "## 人名一致性（按称呼形式分组）", ""]
    if findings:
        for f in findings:
            lines.append(f"### {f['character']}（{f['total']} 处提及）")
            for (form, suf), variants in f["bad"].items():
                lines.append(f"- 原文写法 `{form}{suf}` 出现多种译名：")
                for zh, uids in variants.items():
                    lines.append(f"  - `{zh}` ×{len(uids)}（{uids[0]} 等）")
            lines.append("")
    else:
        lines += ["未发现同一称呼形式下的译名漂移。", ""]

    lines += ["## 术语违规", ""]
    lines += [f"- {d} · {u}：{'、'.join(b)}" for d, u, b in gl_bad[:20]] or ["无。"]
    lines += ["", "## 敬称残留", ""]
    lines += [f"- {d} · {u}" for d, u in hon_bad[:20]] or ["无。"]

    from epubtr.paths import report as report_path
    rp = report_path(name, "consistency.md")
    rp.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n人名不一致 {len(findings)} 人 · 术语违规 {len(gl_bad)} · "
          f"敬称残留 {len(hon_bad)}")
    print("写入 reports/<书名>/consistency.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
