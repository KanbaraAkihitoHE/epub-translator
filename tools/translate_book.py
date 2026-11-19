"""整本翻译，按 doc 落盘，可断点续跑。

用法：python tools/translate_book.py <epub> [max_docs]
产物：work/<slug>/<doc_index>.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.store import save_json  # noqa: E402
from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.glossary import check as gl_check, load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.llm import load_config                # noqa: E402
from epubtr.translate import src_hash, translate_doc  # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, z = open_book(Path(argv[1]))
    max_docs = int(argv[2]) if len(argv) > 2 else 0
    work = Path("work") / slug(book.title or Path(argv[1]).stem)
    work.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    gl = gl_load(Path("kb") / slug(book.title or Path(argv[1]).stem))
    notes = to_prompt(gl)
    style_path = Path("kb") / slug(book.title or Path(argv[1]).stem) / "style.md"
    if style_path.exists():
        notes += "\n\n【风格指南】\n" + style_path.read_text(encoding="utf-8")[:1500]

    # 三层记忆：书级设定 + 前情摘要
    bible = None
    bible_path = Path("kb") / slug(book.title or Path(argv[1]).stem) / "auto_bible.json"
    if bible_path.exists():
        from epubtr.bible import Bible
        bible = Bible(**json.loads(bible_path.read_text(encoding="utf-8")))
        notes += "\n\n" + bible.digest()
        print(f"预读设定：{len(bible.characters)} 人物 / {len(bible.terms)} 术语", flush=True)
    if notes:
        print(f"术语表：{len(gl.get('characters', []))} 人物 / "
              f"{len(gl.get('terms', []))} 术语", flush=True)
    docs = book.docs[:max_docs] if max_docs else book.docs

    total_blocks = 0
    for idx, item in enumerate(docs):
        dest = work / f"{idx:03d}.json"
        if dest.exists():
            print(f"[skip] {item.full}")
            continue
        raw = read_doc(z, item)
        doc = extract_doc(item.full, raw)
        if not doc.blocks:
            save_json(dest, {"href": item.full, "units": {}})
            continue
        t0 = time.time()
        print(f"[doc {idx + 1}/{len(docs)}] {item.full} blocks={len(doc.blocks)}", flush=True)
        doc_notes = notes
        if bible is not None:
            title = next((b.source for b in doc.blocks if b.kind == "heading"), "")
            ch = next((c for c in bible.chapters if c["title"][:20] == title[:20]), None)
            prev = bible.chapters[max(0, idx - 3):idx]
            if prev:
                doc_notes += "\n\n【前情】\n" + "\n".join(
                    f"- {p['title']}：{p['summary'][:120]}" for p in prev)
            if ch:
                doc_notes += f"\n\n【本章梗概】{ch['summary'][:200]}"
        try:
            out, stats = translate_doc(cfg, book.title, book.creator, doc.blocks,
                                       notes=doc_notes)
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {type(e).__name__}: {e}")
            continue
        viol = sum(len(gl_check(gl, b.source, out.get(b.uid, ""))) for b in doc.blocks)
        save_json(dest, {
            "href": item.full, "units": out,
            "src_hash": {b.uid: src_hash(b) for b in doc.blocks},
            "stats": {"prompt_tokens": stats.prompt_tokens,
                      "completion_tokens": stats.completion_tokens,
                      "calls": stats.calls, "cache_hits": stats.cache_hits,
                      "failures": stats.failures,
                      "glossary_violations": viol}})
        total_blocks += len(doc.blocks)
        print(f"  ok {time.time() - t0:.1f}s tokens={stats.prompt_tokens}/"
              f"{stats.completion_tokens} fail={len(stats.failures)} gl={viol}", flush=True)

    print(f"done: {total_blocks} blocks -> {work}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
