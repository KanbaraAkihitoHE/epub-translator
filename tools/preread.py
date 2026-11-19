"""全书预读 + 与书内人物页对照验证。

用法：python tools/preread.py <epub>
产物：kb/<slug>/auto_bible.json / auto_bible.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.bible import build                      # noqa: E402
from epubtr.epub import open_book, read_doc        # noqa: E402
from epubtr.ir import extract_doc                   # noqa: E402
from epubtr.llm import load_config                 # noqa: E402
from epubtr.package import plain                   # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, z = open_book(src)
    chapters = []
    truth: list[str] = []
    for item in book.docs:
        doc = extract_doc(item.full, read_doc(z, item))
        if not doc.blocks:
            continue
        title = next((plain(b.source) for b in doc.blocks if b.kind == "heading"), item.href)
        text = "\n".join(plain(b.source) for b in doc.blocks)
        if len(text) < 40:
            continue
        chapters.append({"title": title[:40], "text": text})
        if any(plain(b.source) == "登場人物" for b in doc.blocks):
            truth = [plain(b.source) for b in doc.blocks if "gfont" in b.parent_attrs]

    print(f"{len(chapters)} 个章节，人物页标准答案 {len(truth)} 人")
    bible = build(load_config(), chapters,
                  progress=lambda i, n: print(f"  摘要 {i}/{n}", end="\r", flush=True))
    print()

    name = slug(book.title or src.stem)
    kb = Path("kb") / name
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "auto_bible.json").write_text(
        json.dumps(bible.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    # 自动生成术语表（已有则不覆盖）
    gl_path = kb / "glossary.json"
    if not gl_path.exists() and bible.characters:
        from epubtr.llm import chat
        sys_p = ("给这部日本小说的中文版定译名。规则：日文汉字转简体；片假名人名按常见音译；"
                 "作品名若是真实存在的用通行译名。\n"
                 "输出 JSON：{\"characters\":[{\"ja\":\"...\",\"zh\":\"...\"}],"
                 "\"terms\":[{\"ja\":\"...\",\"zh\":\"...\",\"note\":\"\"}]}")
        payload = json.dumps({
            "characters": [{"ja": c.get("name_ja"), "role": c.get("role"),
                            "aliases": c.get("aliases", [])}
                           for c in bible.characters],
            "terms": [{"ja": t.get("ja"), "type": t.get("type"),
                       "hint": t.get("zh_hint", "")} for t in bible.terms[:40]],
        }, ensure_ascii=False, indent=1)
        r = chat(load_config(), sys_p, payload, temperature=0.3, max_tokens=4000,
                 json_mode=True)
        gl = json.loads(r.text)
        gl.setdefault("characters", [])
        gl.setdefault("terms", [])
        gl_path.write_text(json.dumps(gl, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        print(f"自动术语表：{len(gl['characters'])} 人物 / {len(gl['terms'])} 术语")

    # 验证
    found = [c.get("name_ja", "") for c in bible.characters]
    hit = [t for t in truth if any(t == f or t in f or f in t for f in found)]
    recall = len(hit) / max(1, len(truth))
    extra = [f for f in found if not any(t == f or t in f or f in t for t in truth)]

    lines = [f"# 自动设定集：{book.title}", "",
             f"- 章节 {len(chapters)} · 人物 {len(found)} · 术语 {len(bible.terms)} "
             f"· 风险 {len(bible.risks)}", "",
             "## 人物页对照", "",
             f"- 标准答案 {len(truth)} 人，自动找到 **{len(hit)}** 人（召回 {recall:.0%}）",
             f"- 未找到：{'、'.join(t for t in truth if t not in hit) or '无'}",
             f"- 额外识别（可能正确或噪声）：{'、'.join(extra[:15]) or '无'}", "",
             "## 梗概", "", bible.synopsis, "",
             "## 人物", ""]
    for c in bible.characters:
        lines.append(f"- **{c.get('name_ja','')}** {c.get('aliases','')} · "
                     f"{c.get('role','')} · {c.get('gender','')} · {c.get('register','')}")
    lines += ["", "## 术语", ""]
    for t in bible.terms[:40]:
        lines.append(f"- {t.get('ja','')} ({t.get('type','')}) {t.get('zh_hint','')}")
    lines += ["", "## 风险", ""]
    for r in bible.risks:
        lines.append(f"- {r.get('type','')} @ {r.get('where','')}：{r.get('note','')}")
    from epubtr.paths import report as report_path
    report_path(name, "preread.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"人物 {len(found)}，召回 {recall:.0%}（{len(hit)}/{len(truth)}）")
    print(f"术语 {len(bible.terms)}，风险 {len(bible.risks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
