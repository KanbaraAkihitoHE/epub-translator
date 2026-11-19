"""文本处理：实体、空白、标记。"""

from __future__ import annotations

import html
import re

MARK_OPEN = "⟦"
MARK_CLOSE = "⟧"
MARK_RE = re.compile(r"⟦(/?)([iv])(\d+)⟧")

CJK_RE = re.compile(
    r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)
WS_RE = re.compile(r"[ \t\r\n\f\v]+")


def unescape(s: str) -> str:
    return html.unescape(s)


def escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def normalize_space(s: str) -> str:
    """日语原文里的换行/缩进不应变成中文空格。"""
    s = WS_RE.sub(" ", s)
    # 空格两侧都是 CJK 时删掉
    out = []
    for idx, ch in enumerate(s):
        if ch == " ":
            prev = s[idx - 1] if idx else ""
            nxt = s[idx + 1] if idx + 1 < len(s) else ""
            if (prev and CJK_RE.match(prev)) and (nxt and CJK_RE.match(nxt)):
                continue
        out.append(ch)
    return "".join(out).strip()


def has_cjk(s: str) -> bool:
    return bool(CJK_RE.search(s))
