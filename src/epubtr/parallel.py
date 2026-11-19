"""并行执行工具：批次独立，结果按原顺序归位。"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

LOCK = threading.Lock()


def workers(default: int = 3) -> int:
    try:
        return max(1, int(os.environ.get("EPUBTR_WORKERS", default)))
    except ValueError:
        return default


def run(fn: Callable[[T], R], items: Iterable[T],
        max_workers: int | None = None) -> list[R]:
    items = list(items)
    n = max_workers or workers()
    if n <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(fn, items))
