"""A/B：同一章"无记忆" vs "三层记忆"各译一遍，比较审校问题数。

用法：python tools/ab_memory.py <epub> <doc_index>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.bible import Bible                      # noqa: E402
from epubtr.epub import open_book, read_doc         # noqa: E402
from epubtr.glossary import load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                    # noqa: E402
from epubtr.llm import load_config                  # noqa: E402
from epubtr.revise import ReviseStats, critique      # noqa: E402
from epubtr.translate import translate_doc           # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    book, z = open_book(Path(argv[1]))
    idx = int(argv[2])
    name = slug(book.title or Path(argv[1]).stem)
    work = Path("work") / name
    cfg = load_config()
    gl = gl_load(Path("kb") / name)
    base = to_prompt(gl)
    style = Path("kb") / name / "style.md"
    if style.exists():
        base += "\n\n【风格指南】\n" + style.read_text(encoding="utf-8")[:1200]

    bpath = Path("kb") / name / "auto_bible.json"
    bible = Bible(**json.loads(bpath.read_text(encoding="utf-8")))

    item = book.docs[idx]
    doc = extract_doc(item.full, read_doc(z, item))
    title = next((b.source for b in doc.blocks if b.kind == "heading"), "")
    ch = next((c for c in bible.chapters if c["title"][:20] == title[:20]), None)
    prev = bible.chapters[max(0, idx - 3):idx]

    mem = base + "\n\n" + bible.digest()
    if prev:
        mem += "\n\n【前情】\n" + "\n".join(
            f"- {p['title']}：{p['summary'][:120]}" for p in prev)
    if ch:
        mem += f"\n\n【本章梗概】{ch['summary'][:200]}"

    results = {}
    for tag, notes in (("A_无记忆", base), ("B_有记忆", mem)):
        t0 = time.time()
        out, st = translate_doc(cfg, book.title, book.creator, doc.blocks, notes=notes)
        path = work / f"ab_{tag[0]}.json"
        path.write_text(json.dumps({"href": item.full, "units": out},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        results[tag] = {"units": out, "time": time.time() - t0,
                        "tokens": (st.prompt_tokens, st.completion_tokens)}
        print(f"{tag}: {time.time() - t0:.0f}s tokens={st.prompt_tokens}/"
              f"{st.completion_tokens}", flush=True)

    for tag in results:
        total = ReviseStats()
        issues = []
        blocks = doc.blocks
        for i in range(0, len(blocks), 12):
            issues += critique(cfg, blocks[i:i + 12], results[tag]["units"], total)
        hard = [x for x in issues if x.type == "accuracy" and x.severity == "major"]
        results[tag]["issues"] = len(issues)
        results[tag]["hard"] = len(hard)
        print(f"{tag}: 问题 {len(issues)}（硬错误 {len(hard)}）")

    a, b = results["A_无记忆"], results["B_有记忆"]
    print(f"\n{name} · {item.full}: 问题 {a['issues']} -> {b['issues']}，"
          f"硬错误 {a['hard']} -> {b['hard']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
