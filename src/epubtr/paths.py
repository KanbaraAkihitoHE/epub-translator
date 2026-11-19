"""统一路径：报告按书分目录，避免互相覆盖。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def report_dir(book_slug: str | None) -> Path:
    """book_slug 为 None 时写 _shared（跨书/全局报告）。"""
    d = REPORTS / (book_slug or "_shared")
    d.mkdir(parents=True, exist_ok=True)
    return d


def report(book_slug: str | None, name: str) -> Path:
    return report_dir(book_slug) / name
