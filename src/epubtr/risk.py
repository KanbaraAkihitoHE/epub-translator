"""段落风险打分：决定哪些段落值得多跑一遍。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Block

KEIGO = re.compile(r"(です|ます|ございます|いただ|申し上げ|伺|存じ|おっしゃ|なさい|ください)")
HONORIFIC = re.compile(r"(さん|君|ちゃん|様|先生|先輩|部長|課長|警部)")
WORDPLAY = re.compile(r"([＊\*]{2,}|／|・{2,}|[ァ-ヶ]{4,})")
LONG = 150


@dataclass
class RiskScore:
    score: float
    tags: tuple[str, ...]


def score(block: Block, glossary_ja: tuple[str, ...] = ()) -> RiskScore:
    s = block.source
    tags: list[str] = []
    v = 0.0
    if "「" in s:
        v += 0.20
        tags.append("dialogue")
    if KEIGO.search(s):
        v += 0.15
        tags.append("keigo")
    if len(s) > LONG:
        v += 0.15
        tags.append("long")
    if WORDPLAY.search(s):
        v += 0.25
        tags.append("wordplay")
    if any(sp.ruby_rt for sp in block.spans):
        v += 0.10
        tags.append("ruby")
    if HONORIFIC.search(s):
        v += 0.05
        tags.append("honorific")
    if any(g in s for g in glossary_ja):
        v += 0.10
        tags.append("term")
    if "……" in s or "——" in s:
        v += 0.05
        tags.append("pause")
    return RiskScore(score=min(v, 1.0), tags=tuple(tags))


def route(block: Block, threshold: float = 0.5,
          glossary_ja: tuple[str, ...] = ()) -> str:
    """high = 走自评+修订；low = 只出草稿。"""
    return "high" if score(block, glossary_ja).score >= threshold else "low"
