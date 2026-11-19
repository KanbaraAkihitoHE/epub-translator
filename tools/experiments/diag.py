"""诊断：定位结构 diff 的第一个位置。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.render import tokenize, rewrite       # noqa: E402
from epubtr.scan import tag_stream                # noqa: E402
from epubtr.text import CJK_RE                    # noqa: E402


def simple(s: str) -> str:
    out = []
    for k, v in tokenize(s):
        if k == "text":
            t = str(v)
            out.append("".join("译" if c.strip() else c for c in t))
        else:
            m = {"open": "i", "close": "/i", "void": "v"}[k]
            out.append(f"⟦{m}{v}⟧")
    return "".join(out)


def main() -> int:
    book, z = open_book(Path(sys.argv[1]))
    href = sys.argv[2]
    item = next(i for i in book.docs if i.full.endswith(href.split("/")[-1]))
    raw = read_doc(z, item)
    doc = extract_doc(item.full, raw)
    out = rewrite(doc, {b.uid: simple(b.source) for b in doc.blocks})
    a, b = tag_stream(raw), tag_stream(out)
    print(f"{item.full}: tags raw={len(a)} out={len(b)}")
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print("first diff at", i)
            for j in range(max(0, i - 4), min(len(a), i + 4)):
                print(f"  raw[{j}]={a[j]}")
            print("  ---")
            for j in range(max(0, i - 4), min(len(b), i + 4)):
                print(f"  out[{j}]={b[j]}")
            break
    else:
        if len(a) != len(b):
            print("长度不同但前缀一致；尾部：")
            print(" raw tail:", a[-6:])
            print(" out tail:", b[-6:])
    # 统计 block 内是否有注脚/孤立闭标签
    for blk in doc.blocks:
        inner = raw[blk.content_start:blk.content_end]
        if "</br>" in inner or "</img>" in inner or "<!--" in inner:
            print("suspect block:", blk.uid, blk.tag, inner[:120].replace("\n", " "))
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
