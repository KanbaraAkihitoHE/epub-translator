"""文本规范化与可疑改动检测。

- unify_quotes：把中英文引号统一成日式「」/『』
- looks_japanese：判断一段文字是否仍是日文（未译残留）
- homophone_only：判断两段文字是否只差同音字（修订把「犯人」改成「半人」这类）
"""

from __future__ import annotations

import re
import unicodedata

KANA = re.compile(r"[\u3040-\u30ff]")
DIGITS = re.compile(r"\d+")
CJK = re.compile(r"[\u4e00-\u9fff]")

# 修订若引入这些"旧字/日文特有字"，基本可以判定是往原文回退
JP_ONLY = set("當譯擊鬪鬭證歲點兒團圓國學說醫藥藝術頭髮鬍鬚")


def unify_quotes(text: str, style: str = "jp") -> str:
    """把中英文引号与日式引号统一成「」/『』，按嵌套层数自动降级。"""
    if style != "jp":
        return text
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch in ("“", "‘", "「", "『"):
            out.append("『" if depth >= 1 else "「")
            depth += 1
        elif ch in ("”", "’", "」", "』"):
            depth = max(0, depth - 1)
            out.append("』" if depth >= 1 else "」")
        else:
            out.append(ch)
    return "".join(out)


HONORIFIC = re.compile(r"([\u4e00-\u9fff]{2,4})[，,]\s*(小|同学|酱|君|先生|小姐|大人)\s*([。！？]?)")


def fix_honorific(text: str) -> str:
    """「富士子，小。」这类把敬称单独拆出来的写法，还原成「小富士子。」。"""
    def repl(m: re.Match) -> str:
        name, hon, end = m.group(1), m.group(2), m.group(3)
        if hon in ("小", "同学", "酱"):
            return f"小{name}{end}"
        return f"{name}{end}"
    return HONORIFIC.sub(repl, text)


def kana_count(text: str) -> int:
    return len(KANA.findall(text))


def looks_japanese(text: str) -> bool:
    """整段仍是日文的判断：中文译文里出现两个以上假名即视为未译残留。"""
    kana = kana_count(text)
    if kana >= 2:
        return True
    return any(ch in JP_ONLY for ch in text)


def _pinyin(text: str) -> list[str]:
    try:
        from pypinyin import lazy_pinyin
    except ImportError:  # 没装就不做同音检测
        return []
    clean = "".join(c for c in text if CJK.match(c))
    return lazy_pinyin(clean)


def homophone_only(a: str, b: str) -> bool:
    """a、b 字数相同、读音相同、但用字不同 → 疑似同音替换错误。"""
    if a == b:
        return False
    ca = "".join(c for c in a if CJK.match(c))
    cb = "".join(c for c in b if CJK.match(c))
    if len(ca) != len(cb) or len(ca) < 2:
        return False
    pa, pb = _pinyin(ca), _pinyin(cb)
    if not pa or pa != pb:
        return False
    diff = sum(1 for x, y in zip(ca, cb) if x != y)
    return 1 <= diff <= 3


def digits_of(text: str) -> list[str]:
    return DIGITS.findall(unicodedata.normalize("NFKC", text))


def suspicious_change(draft: str, revised: str, source: str) -> str:
    """修订结果可疑时返回原因，否则返回空串。"""
    if not revised or revised == draft:
        return ""
    if kana_count(revised) > kana_count(draft) + 2 and kana_count(source) < 3:
        return "改出了日文假名"
    if digits_of(draft) != digits_of(revised):
        return "数字被改动"
    if homophone_only(draft, revised):
        return "只替换了同音字"
    if len(revised) < len(draft) * 0.5 and len(draft) > 20:
        return "长度骤减"
    return ""


# 常见「日文/繁体字形」→ 简体，防止单字残留
VARIANT = {
    "學": "学", "國": "国", "說": "说", "譯": "译", "擊": "击", "鬥": "斗",
    "當": "当", "證": "证", "歲": "岁", "點": "点", "兒": "儿", "團": "团",
    "圓": "圆", "醫": "医", "藥": "药", "藝": "艺", "術": "术", "頭": "头",
    "髮": "发", "鬍": "胡", "鬚": "须", "戰": "战", "爭": "争", "戀": "恋",
    "愛": "爱", "時": "时", "間": "间", "覺": "觉", "齒": "齿", "龍": "龙",
    "傳": "传", "劇": "剧", "場": "场", "誰": "谁", "讀": "读", "書": "书",
}


def simplify_variants(text: str) -> str:
    return "".join(VARIANT.get(c, c) for c in text)


def kana_outside_quotes(text: str) -> int:
    """引号内（字谜、原名）的假名不算未译。"""
    depth, n = 0, 0
    for ch in text:
        if ch in ("「", "『"):
            depth += 1
        elif ch in ("」", "』"):
            depth = max(0, depth - 1)
        elif depth == 0 and "\u3040" <= ch <= "\u30ff":
            n += 1
    return n
