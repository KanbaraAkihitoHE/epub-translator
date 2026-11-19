"""把 work/ 里的译文打包成 EPUB。

用法：python tools/build_epub.py <epub>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book                  # noqa: E402
from epubtr.package import build_epub              # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, _ = open_book(src)
    work = Path("work") / slug(book.title or src.stem)
    if not work.exists():
        print(f"没有译文目录 {work}")
        return 1
    translations: dict[str, dict[str, str]] = {}
    drafts: dict[str, dict[str, str]] = {}
    hashes: dict[str, dict[str, str]] = {}
    rev = work / "rev"
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        draft = json.loads(f.read_text(encoding="utf-8"))
        drafts[draft["href"]] = draft.get("units", {})
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        translations[data["href"]] = data["units"]
        if data.get("src_hash"):
            hashes[data["href"]] = data["src_hash"]

    # 构建前清理：回退可疑修订、统一引号、修正敬称写法
    from epubtr.cleanup import clean, corpus_counts
    counts = corpus_counts([t for u in translations.values() for t in u.values()])
    clean_stats = {"rolled_back": 0, "quotes": 0, "honorific": 0, "readings": 0}
    for href, units in list(translations.items()):
        cleaned, st = clean(drafts.get(href, {}), units, {}, counts)
        translations[href] = cleaned
        for k in clean_stats:
            clean_stats[k] += st[k]
    titles: dict[str, str] = {}
    tpath = work / "titles.json"
    if tpath.exists():
        titles = json.loads(tpath.read_text(encoding="utf-8"))
    gl_path = Path("kb") / work.name / "glossary.json"
    names = 0
    if gl_path.exists():
        names = len(json.loads(gl_path.read_text(encoding="utf-8"))
                    .get("characters", []))
    cfg = json.loads(Path("config/local.json").read_text(encoding="utf-8"))

    # 字体解析顺序：配置 → assets/fonts/ → 系统楷体 → 不内嵌
    def resolve_font() -> Path | None:
        cand = [Path(cfg.get("font", {}).get("path", ""))]
        cand += sorted(Path("assets/fonts").glob("*.tt[fc]")) \
            + sorted(Path("assets/fonts").glob("*.otf"))
        cand.append(Path(r"C:\Windows\Fonts\simkai.ttf"))
        for p in cand:
            if p and p.exists():
                return p
        return None

    font_path = resolve_font()
    if font_path is None:
        print("[warn] 没找到可用字体，改为不内嵌（可用 assets/fonts/ 放一个开源楷体）")
    out = Path("out") / (src.stem.split(" (")[0] + ".zh.epub")
    stats = build_epub(src, translations, out, font_path=font_path, titles=titles,
                       normalize_size=cfg.get("font", {}).get("normalize_size", True),
                       hashes=hashes)
    print(f"写入 {out}")
    print(f"  已翻 {stats['docs']} 篇 / {stats['blocks']} 段")
    print(f"  字体子集 {stats['font_bytes'] / 1024:.0f} KB")
    print(f"  标题替换 {len(titles)} 条 · 人物页注记 {stats['names_annotated']} 条")
    print(f"  清理：回退可疑修订 {clean_stats['rolled_back']} 段 · "
          f"引号统一 {clean_stats['quotes']} 段 · 敬称修正 {clean_stats['honorific']} 段 · "
          f"读音清理 {clean_stats['readings']} 段")
    stale = stats.get("stale", [])
    print(f"  原文变更（待重译）{len(stale)} 段")
    if stale:
        from epubtr.paths import report as report_path
        report_path(work.name, "stale.json").write_text(
            json.dumps(stale, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main(sys.argv))
