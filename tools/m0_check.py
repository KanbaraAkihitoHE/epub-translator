"""M0 验收：身份往返 + 结构同构 + IR 统计。

用法：python tools/m0_check.py assets/samples/*.epub
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc          # noqa: E402
from epubtr.ir import extract_doc, overlaps          # noqa: E402
from epubtr.render import tokenize, rewrite          # noqa: E402
from epubtr.scan import canonical_tags           # noqa: E402
from epubtr.text import CJK_RE                       # noqa: E402


def synth(source: str) -> str:
    """保留全部标记，把含 CJK 的文本换成占位译文。"""
    out = []
    for kind, val in tokenize(source):
        if kind == "text":
            s = str(val)
            out.append("译" * max(1, len(s) // 2) if CJK_RE.search(s) else s)
        else:
            mark = {"open": "i", "close": "/i", "void": "v"}[kind]
            out.append(f"⟦{mark}{val}⟧")
    return "".join(out)


def check(path: Path) -> dict:
    book, z = open_book(path)
    res = {
        "file": path.name, "title": book.title, "drm": book.drm,
        "vertical": book.vertical, "docs": 0, "blocks": 0, "spans": 0,
        "ruby": 0, "verbatim": 0, "chars": 0,
        "identity_fail": [], "structure_fail": [], "overlap": [],
        "scan_warn": 0, "marker_fail": 0,
    }
    for item in book.docs:
        raw = read_doc(z, item)
        doc = extract_doc(item.full, raw)
        res["docs"] += 1
        res["blocks"] += len(doc.blocks)
        res["spans"] += sum(len(b.spans) for b in doc.blocks)
        res["ruby"] += sum(1 for b in doc.blocks for s in b.spans if s.ruby_rt or s.tag == "ruby")
        res["verbatim"] += sum(1 for b in doc.blocks for s in b.spans if s.verbatim)
        res["chars"] += sum(len(b.source) for b in doc.blocks)
        res["scan_warn"] += len(doc.scan.declarations) and 0 or 0
        res["overlap"] += [(item.full, a, b) for a, b in overlaps(doc.blocks)]

        identity = rewrite(doc, {b.uid: b.source for b in doc.blocks})
        if identity != raw:
            res["identity_fail"].append(item.full)
        try:
            out = rewrite(doc, {b.uid: synth(b.source) for b in doc.blocks})
        except Exception as e:  # noqa: BLE001
            res["marker_fail"] += 1
            res["structure_fail"].append(f"{item.full}: {e}")
            continue
        if canonical_tags(out) != canonical_tags(raw):
            res["structure_fail"].append(item.full)
    return res


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rows = [check(Path(p)) for p in argv[1:]]
    for r in rows:
        ok = (not r["identity_fail"] and not r["structure_fail"]
              and not r["overlap"] and not r["marker_fail"])
        print(f"[{'PASS' if ok else 'FAIL'}] {r['title'] or r['file'][:40]}")
        print(f"       docs={r['docs']} blocks={r['blocks']} spans={r['spans']} "
              f"ruby={r['ruby']} verbatim={r['verbatim']} chars={r['chars']:,}")
        if r["identity_fail"]:
            print(f"       identity 失败: {r['identity_fail'][:3]}")
        if r["structure_fail"]:
            print(f"       结构失败: {r['structure_fail'][:3]}")
        if r["overlap"]:
            print(f"       block 重叠: {r['overlap'][:3]}")
    from epubtr.paths import report as report_path
    report_path(None, "m0-report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    all_ok = all(not r["identity_fail"] and not r["structure_fail"]
                 and not r["overlap"] and not r["marker_fail"] for r in rows)
    print("\n" + ("全部通过" if all_ok else "存在失败项"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
