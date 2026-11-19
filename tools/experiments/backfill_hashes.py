"""为已有译文补写原文哈希（一次性迁移）。

用法：python tools/backfill_hashes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.epub import open_book, read_doc        # noqa: E402
from epubtr.ir import extract_doc                   # noqa: E402
from epubtr.translate import src_hash               # noqa: E402


def main() -> int:
    total = 0
    for epub in sorted(Path("assets/samples").glob("*.epub")):
        book, z = open_book(epub)
        slug = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in (book.title or epub.stem))[:40]
        work = Path("work") / slug
        if not work.exists():
            continue
        for d in (work, work / "rev"):
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json")):
                if f.name == "titles.json":
                    continue
                data = json.loads(f.read_text(encoding="utf-8"))
                item = next((i for i in book.docs if i.full == data["href"]), None)
                if item is None:
                    continue
                doc = extract_doc(item.full, read_doc(z, item))
                data["src_hash"] = {b.uid: src_hash(b) for b in doc.blocks}
                f.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")
                total += 1
        print(f"{book.title[:24]}: 已补", flush=True)
    print(f"共 {total} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
