"""翻译一章，输出中日对照，方便人工判断质量。

用法：python tools/translate_chapter.py <epub> <doc文件名> [段数上限]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.llm import load_config                # noqa: E402
from epubtr.translate import translate_doc        # noqa: E402

IN_RATE = 2.0   # 元/百万 token（估）
OUT_RATE = 8.0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    book, z = open_book(Path(argv[1]))
    target = argv[2]
    limit = int(argv[3]) if len(argv) > 3 else 0
    item = next(i for i in book.docs if i.full.endswith(target))
    raw = read_doc(z, item)
    doc = extract_doc(item.full, raw)
    blocks = doc.blocks[:limit] if limit else doc.blocks
    print(f"{book.title} / {item.full} / {len(blocks)} 段")

    cfg = load_config()
    out, stats = translate_doc(
        cfg, book.title, book.creator, blocks,
        progress=lambda d, t: print(f"  {d}/{t}", end="\r", flush=True),
    )
    print()
    cost = stats.prompt_tokens / 1e6 * IN_RATE + stats.completion_tokens / 1e6 * OUT_RATE
    print(f"调用 {stats.calls} 次 | tokens {stats.prompt_tokens}/{stats.completion_tokens} "
          f"| 约 ¥{cost:.3f} | 失败 {len(stats.failures)}")

    lines = [f"# 试译：{book.title}", "", f"- 章节：`{item.full}`",
             f"- 段数：{len(blocks)}", f"- tokens：{stats.prompt_tokens}/{stats.completion_tokens}",
             f"- 失败：{len(stats.failures)}", ""]
    for b in blocks:
        lines += [f"**{b.uid}**  ", f"> {b.source}", "", out[b.uid], ""]
    from epubtr.paths import report as report_path
    out_path = report_path("".join(c if c.isalnum() or c in "-_" else "_" for c in (book.title or ""))[:40],
                           f"sample-{target.replace('/', '_')}.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"写入 {out_path}")

    for b in blocks[:3]:
        print(f"\n--- {b.uid} ---")
        print("日:", b.source[:160])
        print("中:", out[b.uid][:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
