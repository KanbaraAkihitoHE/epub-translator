"""按修复表统一错译名（如 加贺见→加贺美）。

用法：python tools/normalize.py <epub>
修复表：kb/<slug>/fixes.json  {"错误写法": "正确写法"}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book                  # noqa: E402


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, _ = open_book(Path(argv[1]))
    name = slug(book.title or Path(argv[1]).stem)
    fix_path = Path("kb") / name / "fixes.json"
    if not fix_path.exists():
        print(f"没有修复表 {fix_path}")
        return 1
    fixes = json.loads(fix_path.read_text(encoding="utf-8")) if fix_path.exists() else {}
    from epubtr.names import NameResolver
    res = NameResolver.load(Path("kb") / name)
    work = Path("work") / name
    total = 0
    for d in (work, work / "rev"):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            if f.name == "titles.json":
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            n = 0
            for uid, text in list(data["units"].items()):
                new = res.normalize(text)
                for bad, good in fixes.items():
                    if bad in new:
                        new = new.replace(bad, good)
                if new != text:
                    data["units"][uid] = new
                    n += 1
            if n:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")
                print(f"  {d.name}/{f.name}: {n} 段")
                total += n
    print(f"共修改 {total} 段，替换 {len(fixes)} 条规则")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
