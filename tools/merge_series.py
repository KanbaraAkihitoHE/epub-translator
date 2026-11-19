"""系列记忆：把前作的术语表合并到新书。

用法：
    python tools/merge_series.py <新书.epub> [--from <前作.epub> ...]

不带 --from 时，自动找同作者的其它书。
冲突时**前作优先**，并写进报告供人工复核。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book                      # noqa: E402
from epubtr.paths import report as report_path, slug    # noqa: E402
from epubtr.glossary import load as gl_load            # noqa: E402
from epubtr.store import save_json                     # noqa: E402


def merge(target: dict, source: dict, src_name: str) -> tuple[int, list[str]]:
    added, conflicts = 0, []
    for group in ("characters", "terms"):
        by_ja = {x["ja"]: x for x in target.get(group, [])}
        for item in source.get(group, []):
            ja, zh = item.get("ja"), item.get("zh")
            if not ja or not zh:
                continue
            if ja in by_ja:
                old = by_ja[ja].get("zh")
                if old != zh:
                    conflicts.append(f"{ja}: 本书「{old}」→ 前作「{zh}」（已采用前作）")
                    by_ja[ja]["zh"] = zh
                    for k in ("variants", "note"):
                        if item.get(k):
                            by_ja[ja][k] = item[k]
            else:
                target.setdefault(group, []).append(dict(item))
                added += 1
    return added, conflicts


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    target_epub = Path(argv[1])
    book, _ = open_book(target_epub)
    name = slug(book.title or target_epub.stem)
    target_kb = Path("kb") / name
    if not (target_kb / "glossary.json").exists():
        print(f"新书还没有术语表：{target_kb}（先跑 preread）")
        return 1

    sources: list[Path] = []
    if "--from" in argv:
        i = argv.index("--from")
        sources = [Path(p) for p in argv[i + 1:]]
    else:
        for epub in sorted(Path("assets/samples").glob("*.epub")):
            if epub.resolve() == target_epub.resolve():
                continue
            other, _ = open_book(epub)
            if book.creator and other.creator == book.creator:
                sources.append(epub)

    if not sources:
        print("没有找到同作者的其它书，请用 --from 指定")
        return 1

    gl = gl_load(target_kb)
    lines = [f"# 系列合并：{book.title}", ""]
    total_added, total_conf = 0, []
    for src in sources:
        sbook, _ = open_book(src)
        sname = slug(sbook.title or src.stem)
        sgl = gl_load(Path("kb") / sname)
        if not sgl.get("characters"):
            print(f"跳过（无术语表）：{sbook.title}")
            continue
        added, conflicts = merge(gl, sgl, sbook.title)
        total_added += added
        total_conf += conflicts
        print(f"{sbook.title[:30]}: 新增 {added}，冲突 {len(conflicts)}")
        lines += [f"## 来源：{sbook.title}",
                  f"- 新增 {added} 条", f"- 冲突 {len(conflicts)} 条", ""]
        lines += [f"- {c}" for c in conflicts]

    save_json(target_kb / "glossary.json", gl)
    rp = report_path(name, "series-merge.md")
    rp.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n合计新增 {total_added} 条，冲突 {len(total_conf)} 条")
    print("报告:", rp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
