"""构建前的清理：回退可疑修订、统一引号、修正敬称写法。"""

from __future__ import annotations

import re
from collections import Counter

from .textnorm import (CJK, fix_honorific, kana_count, looks_japanese,
                       suspicious_change, unify_quotes)

READING = re.compile(r"[（(][ぁ-んァ-ヶ・ー\s]{1,24}[）)]")


def strip_reading(text: str) -> str:
    """删掉纯假名的读音标注，例如「浅仓秋成（あさくら・あきなり）」。"""
    if not CJK.search(text) or not READING.search(text):
        return text
    rest = READING.sub("", text)
    return rest if rest != text else text


def bigrams(text: str) -> set[str]:
    s = "".join(c for c in text if "\u4e00" <= c <= "\u9fff")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def corpus_counts(texts: list[str]) -> Counter:
    c: Counter = Counter()
    for t in texts:
        st = "".join(ch for ch in t if "\u4e00" <= ch <= "\u9fff")
        for i in range(len(st) - 1):
            c[st[i:i + 2]] += 1
    return c


def rare_introduced(draft: str, revised: str, counts: Counter) -> str:
    """修订引入了全书只出现一次的二字词 → 疑似生造/同音替换。"""
    new = bigrams(revised) - bigrams(draft)
    for bg in new:
        if counts.get(bg, 0) <= 1:
            return bg
    return ""


def clean(drafts: dict[str, str], revs: dict[str, str], sources: dict[str, str],
          counts: Counter) -> tuple[dict[str, str], dict]:
    out: dict[str, str] = {}
    stats = {"rolled_back": 0, "quotes": 0, "honorific": 0, "readings": 0}
    for uid, text in revs.items():
        draft = drafts.get(uid, "")
        src = sources.get(uid, "")
        reason = suspicious_change(draft, text, src) if draft else ""
        if reason:
            text = draft or text
            stats["rolled_back"] += 1
        fixed = unify_quotes(text)
        if fixed != text:
            stats["quotes"] += 1
        text = fixed
        fixed = fix_honorific(text)
        if fixed != text:
            stats["honorific"] += 1
        text = fixed
        fixed = strip_reading(text)
        if fixed != text:
            stats["readings"] += 1
        out[uid] = fixed
    return out, stats
