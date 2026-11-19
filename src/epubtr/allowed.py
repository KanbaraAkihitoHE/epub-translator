"""记录"允许保留日文"的段落（字谜、原名），避免反复报未译。"""

from __future__ import annotations

import json
from pathlib import Path

from .store import save_json

NAME = "allow_kana.json"


def path_of(work: Path) -> Path:
    return Path(work) / NAME


def load(work: Path) -> set[str]:
    p = path_of(work)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return set()


def add(work: Path, doc: str, uid: str) -> None:
    items = load(work)
    items.add(f"{doc}:{uid}")
    save_json(path_of(work), sorted(items))


def contains(work: Path, doc: str, uid: str) -> bool:
    return f"{doc}:{uid}" in load(work)
