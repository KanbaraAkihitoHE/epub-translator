"""标点配对校验（可复用逻辑）。"""

from __future__ import annotations

PAIRS = {
    "「": "」", "『": "』", "（": "）", "(": ")",
    "《": "》", "〈": "〉", "【": "】", "〔": "〕",
    "“": "”", "‘": "’",
}
OPENERS = set(PAIRS)
CLOSERS = {v: k for k, v in PAIRS.items()}


def check_text(text: str) -> list[tuple[int, str]]:
    errs: list[tuple[int, str]] = []
    stack: list[tuple[str, int]] = []
    for i, ch in enumerate(text):
        if ch in OPENERS:
            stack.append((ch, i))
        elif ch in CLOSERS:
            want = CLOSERS[ch]
            if not stack:
                errs.append((i, f"多余的「{ch}」"))
            elif stack[-1][0] != want:
                errs.append((i, f"「{stack[-1][0]}」被「{ch}」关闭"))
                stack.pop()
            else:
                stack.pop()
    for ch, pos in stack:
        errs.append((pos, f"未闭合「{ch}」"))
    return errs
