"""一条命令跑完整流水线，每步都可断点续跑。

用法：
    python tools/pipeline.py <epub> [--until build]

步骤：预读 → 标题 → 翻译 → 修订 → 润色 → 自动修复 → 打包 → 校验
任一步失败即停止；修复后重新执行会跳过已完成的部分。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def run(desc: str, argv: list[str]) -> bool:
    print(f"\n=== {desc} ===", flush=True)
    r = subprocess.run([sys.executable, *argv], cwd=ROOT)
    if r.returncode != 0:
        print(f"!! {desc} 失败（退出码 {r.returncode}）", flush=True)
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    epub = argv[1]
    until = "verify"
    if "--until" in argv:
        until = argv[argv.index("--until") + 1]

    base = Path(epub)
    sys.path.insert(0, str(ROOT / "src"))
    from epubtr.epub import open_book
    book, _ = open_book(base)
    name = slug(book.title or base.stem)
    root = ROOT
    steps = [
        ("预读", ["tools/preread.py", epub],
         lambda: (root / "kb" / name / "auto_bible.json").exists()),
        ("标题", ["tools/translate_titles.py", epub],
         lambda: (root / "work" / name / "titles.json").exists()),
        ("翻译", ["tools/translate_book.py", epub], None),
        ("修订", ["tools/revise_book.py", epub], None),
        ("润色", ["tools/polish.py", epub], None),
        ("自动修复", ["tools/autofix.py", epub], None),
        ("打包", ["tools/build_epub.py", epub], None),
        ("校验", ["tools/verify_epub.py",
                  f"out/{base.stem.split(' (')[0]}.zh.epub", epub], None),
    ]
    for desc, cmd, skip_if in steps:
        if skip_if is not None and skip_if():
            print(f"\n=== {desc} === 已完成，跳过", flush=True)
        elif not run(desc, cmd):
            return 1
        if desc == until:
            break
    print("\n流水线结束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
