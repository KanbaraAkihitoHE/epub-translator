"""整本修订：P2 自评 → P3 局部重写。

用法：python tools/revise_book.py <epub> [max_docs]
产物：work/<slug>/rev/<idx>.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.store import save_json  # noqa: E402
from epubtr.epub import open_book, read_doc       # noqa: E402
from epubtr.glossary import check as gl_check, load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                  # noqa: E402
from epubtr.llm import load_config                # noqa: E402
from epubtr.revise import ReviseStats, critique, revise, should_revise  # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, z = open_book(Path(argv[1]))
    name = slug(book.title or Path(argv[1]).stem)
    work = Path("work") / name
    rev = work / "rev"
    rev.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    gl = gl_load(Path("kb") / name)
    notes = to_prompt(gl)
    max_docs = int(argv[2]) if len(argv) > 2 else 0
    docs = book.docs[:max_docs] if max_docs else book.docs

    total = ReviseStats()
    for idx, item in enumerate(docs):
        src = work / f"{idx:03d}.json"
        dest = rev / f"{idx:03d}.json"
        if not src.exists() or dest.exists():
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        units = dict(data["units"])
        src_hashes = data.get("src_hash", {})
        doc = extract_doc(item.full, read_doc(z, item))
        t0 = time.time()
        blocks = doc.blocks
        doc_issues: list[dict] = []
        p0, c0 = total.prompt_tokens, total.completion_tokens

        from epubtr.parallel import LOCK, run as parallel_run, workers as worker_count
        groups = [blocks[i:i + 12] for i in range(0, len(blocks), 12)]

        def work(group):
            local = ReviseStats()
            try:
                issues = critique(cfg, group, units, local, notes)
            except Exception as e:  # noqa: BLE001
                return group, [], {}, local, f"{group[0].uid}: {e}"
            todo = should_revise(issues)
            fixed = {}
            if todo:
                try:
                    fixed = revise(cfg, group, units, todo, local, notes)
                except Exception as e:  # noqa: BLE001
                    fixed = {}
                    issues = issues  # 保留问题记录
            return group, issues, fixed, local, None

        n = worker_count()
        print(f"  并发 {n} 路，{len(groups)} 个批次", flush=True)
        for group, issues, fixed, local, err in parallel_run(work, groups, n):
            with LOCK:
                total.critique_calls += local.critique_calls
                total.revise_calls += local.revise_calls
                total.revised += local.revised
                total.rejected += local.rejected
                total.prompt_tokens += local.prompt_tokens
                total.completion_tokens += local.completion_tokens
            if err:
                print(f"  [skip batch] {err}")
                continue
            doc_issues += [{"id": x.uid, "type": x.type, "severity": x.severity,
                            "note": x.note} for x in issues]
            for uid, text in fixed.items():
                b = next(x for x in group if x.uid == uid)
                if len(gl_check(gl, b.source, text)) > len(gl_check(gl, b.source, units.get(uid, ""))):
                    continue
                units[uid] = text
        save_json(dest, {
            "href": item.full, "units": units, "issues": doc_issues,
            "src_hash": src_hashes,
            "stats": {"critique_calls": total.critique_calls,
                      "revise_calls": total.revise_calls,
                      "issues": len(doc_issues), "revised": total.revised,
                      "rejected": total.rejected,
                      "prompt_tokens": total.prompt_tokens - p0,
                      "completion_tokens": total.completion_tokens - c0}})
        print(f"[{idx + 1}/{len(docs)}] {item.full} {time.time() - t0:.0f}s "
              f"issues={total.issues} revised={total.revised} "
              f"rejected={total.rejected}", flush=True)

    print(f"done: issues={total.issues} revised={total.revised} "
          f"rejected={total.rejected} tokens={total.prompt_tokens}/"
          f"{total.completion_tokens}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
