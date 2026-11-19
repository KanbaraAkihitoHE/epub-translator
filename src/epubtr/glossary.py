"""术语表：加载、注入提示词、译后校验。"""

from __future__ import annotations

import json
import re
from pathlib import Path

MARK = re.compile(r"⟦[^⟧]*⟧")
KATA = re.compile(r"[\u30a0-\u30ff]")


def _occurs(ja: str, text: str) -> bool:
    """日文没有空格，纯片假名术语要排除"长词的一部分"这种假命中。

    例：リサ 出现在 ウリサバイテイル 里，前后都是片假名 → 不算。
    """
    if not ja:
        return False
    if not all("\u30a0" <= c <= "\u30ff" for c in ja):
        return ja in text
    start = 0
    while True:
        i = text.find(ja, start)
        if i < 0:
            return False
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(ja)] if i + len(ja) < len(text) else ""
        if not (KATA.match(before) and KATA.match(after)):
            return True
        start = i + 1


def load(work_dir: Path) -> dict:
    p = work_dir / "glossary.json"
    if not p.exists():
        return {"characters": [], "terms": []}
    return json.loads(p.read_text(encoding="utf-8"))


def to_prompt(gl: dict) -> str:
    lines = []
    chars = gl.get("characters", [])
    terms = gl.get("terms", [])
    if chars:
        lines.append("【人物译名（全书记住，必须一致）】")
        for c in chars:
            lines.append(f"- {c['ja']} → {c['zh']}")
    if terms:
        lines.append("【术语与作品名（必须使用给定译法）】")
        for t in terms:
            note = f"（{t['note']}）" if t.get("note") else ""
            lines.append(f"- {t['ja']} → {t['zh']}{note}")
    return "\n".join(lines)


def check(gl: dict, source: str, target: str) -> list[str]:
    """返回疑似违规：原文出现了术语，译文却没有给定译法。

    只对**人名**与标了 level=exact 的术语做硬校验；
    普通术语允许同义改写，否则误报会淹没报告。
    """
    t = MARK.sub("", target).replace("《", "").replace("》", "")
    chars = gl.get("characters", [])
    jas = [c["ja"] for c in chars]
    bad = []
    for item in chars:
        ja = item["ja"]
        # 简称（キリコ）是全名（可能キリコ）的子串：正文用简称是正常的，跳过
        if any(other != ja and ja in other for other in jas):
            continue
        # 绰号/常见词（スーパー＝超市、キミ＝你）不做硬校验
        if "绰号" in (item.get("note") or "") or item.get("weak"):
            continue
        zh = item["zh"].strip("《》")
        # 全名常被简称替代（田辺進一郎→田边进）：姓氏出现即认可
        if _occurs(ja, source) and not (zh in t or (len(zh) >= 3 and zh[:2] in t)):
            bad.append(f"{ja}→{zh}")
    for item in gl.get("terms", []):
        if item.get("level") != "exact":
            continue
        ja = item["ja"]
        zh = item["zh"].strip("《》")
        if _occurs(ja, source) and zh not in t:
            bad.append(f"{ja}→{zh}")
    return bad
