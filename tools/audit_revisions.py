"""复核已有修订：用 LLM 判断每处改写是否可信，不可信的回退为初稿。

用法：
    python tools/audit_revisions.py <epub> [--apply]

不加 --apply 只报告，不修改。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc          # noqa: E402
from epubtr.glossary import load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                     # noqa: E402
from epubtr.llm import load_config                     # noqa: E402
from epubtr.parallel import run as parallel_run        # noqa: E402
from epubtr.revise import verify_change                # noqa: E402
from epubtr.store import save_json                     # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    apply_ = "--apply" in argv
    book, z = open_book(src)
    name = slug(book.title or src.stem)
    work = Path("work") / name
    rev_dir = work / "rev"
    if not rev_dir.exists():
        print("还没有修订版")
        return 1
    cfg = load_config()

    docs = {it.full: it for it in book.docs}
    tasks = []
    for rf in sorted(rev_dir.glob("*.json")):
        rev = json.loads(rf.read_text(encoding="utf-8"))
        draft = json.loads((work / rf.name).read_text(encoding="utf-8"))
        item = docs.get(rev["href"])
        if item is None:
            continue
        doc = extract_doc(rev["href"], read_doc(z, item))
        sources = {b.uid: b.source for b in doc.blocks}
        for uid, text in rev.get("units", {}).items():
            old = draft.get("units", {}).get(uid, "")
            if old and text != old and uid in sources:
                tasks.append((rf, uid, old, text, sources[uid]))

    print(f"待复核改写 {len(tasks)} 处")

    def work_one(task):
        rf, uid, old, new, source = task
        keep, why = verify_change(cfg, source, old, new)
        return rf, uid, keep, why, old

    results = parallel_run(work_one, tasks)
    bad = [r for r in results if not r[2]]
    print(f"判定需回退 {len(bad)} 处 / 共 {len(results)}")
    for rf, uid, keep, why, old in bad[:12]:
        print(f"  {rf.name} {uid}: {why}")

    if apply_ and bad:
        by_file: dict[Path, list[str]] = {}
        for rf, uid, keep, why, old in bad:
            by_file.setdefault(rf, []).append(uid)
        for rf, uids in by_file.items():
            data = json.loads(rf.read_text(encoding="utf-8"))
            draft = json.loads((work / rf.name).read_text(encoding="utf-8"))
            for uid in uids:
                data["units"][uid] = draft["units"][uid]
            save_json(rf, data)
        print(f"已回退 {len(bad)} 处，改回初稿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
