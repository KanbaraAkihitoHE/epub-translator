"""回写：把译文渲染回原文串，绝不重排结构（见 docs/ir.md §7）。"""

from __future__ import annotations

import re

from .model import Block, Doc, Span
from .text import MARK_CLOSE, MARK_OPEN, escape

MARK_RE = re.compile(r"⟦[^⟧]*⟧")

Token = tuple[str, object]  # ("text", str) | ("open"/"close"/"void", sid)


class MarkerError(ValueError):
    pass


def tokenize(s: str) -> list[Token]:
    toks: list[Token] = []
    pos = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == MARK_OPEN:
            j = s.find(MARK_CLOSE, i + 1)
            if j < 0:
                raise MarkerError("未闭合的标记括号")
            body = s[i + 1:j]
            if body.startswith("/i"):
                kind, sid = "close", body[2:]
            elif body.startswith("v"):
                kind, sid = "void", body[1:]
            elif body.startswith("i"):
                kind, sid = "open", body[1:]
            else:
                raise MarkerError(f"未知标记 {body!r}")
            if not sid.isdigit():
                raise MarkerError(f"非法 sid {sid!r}")
            if i > pos:
                toks.append(("text", s[pos:i]))
            toks.append((kind, int(sid)))
            pos = j + 1
            i = j + 1
            continue
        i += 1
    if pos < n:
        toks.append(("text", s[pos:]))
    return toks


def validate(toks: list[Token], spans: tuple[Span, ...]) -> None:
    ids = {sp.sid for sp in spans}
    opened: set[int] = set()
    closed: set[int] = set()
    stack: list[int] = []
    for kind, val in toks:
        if kind == "open":
            sid = int(val)  # type: ignore[arg-type]
            if sid not in ids:
                raise MarkerError(f"未知 sid {sid}")
            if sid in opened:
                raise MarkerError(f"重复开标记 {sid}")
            opened.add(sid)
            stack.append(sid)
        elif kind == "close":
            sid = int(val)  # type: ignore[arg-type]
            if not stack or stack[-1] != sid:
                raise MarkerError(f"标记嵌套错误 @{sid}")
            stack.pop()
            closed.add(sid)
        elif kind == "void":
            sid = int(val)  # type: ignore[arg-type]
            if sid not in ids:
                raise MarkerError(f"未知 void sid {val}")
            opened.add(sid)
            closed.add(sid)
    if stack:
        raise MarkerError(f"未闭合标记 {stack[-1]}")
    missing = ids - opened
    if missing:
        raise MarkerError(f"丢失标记 {sorted(missing)}")
    if opened != closed:
        raise MarkerError(f"闭标记缺失 {sorted(opened - closed)}")


def _emit(tok: Token, by_id: dict[int, Span]) -> str:
    kind, val = tok
    if kind == "text":
        return escape(str(val))
    sp = by_id[int(val)]  # type: ignore[arg-type]
    if kind in ("open", "void"):
        return sp.open_raw
    return sp.close_raw


def render_block(block: Block, target: str) -> str:
    target = target.lstrip("　 \t")  # 竖排原文的行首全角空格，改由 CSS 缩进
    toks = tokenize(target)
    validate(toks, block.spans)
    by_id = {sp.sid: sp for sp in block.spans}
    # 只允许在"空行"处分段，且每段标记自平衡；否则不切
    pieces = _split_paragraphs(toks)
    rendered = []
    for piece in pieces:
        rendered.append("".join(_emit(t, by_id) for t in piece))
    return "\n".join(rendered)


def _split_paragraphs(toks: list[Token]) -> list[list[Token]]:
    """按文本里的空行切段；若某段标记不平衡，则退回不切。"""
    pieces: list[list[Token]] = [[]]
    for tok in toks:
        if tok[0] == "text" and "\n\n" in str(tok[1]):
            chunks = str(tok[1]).split("\n\n")
            pieces[-1].append(("text", chunks[0]))
            for c in chunks[1:]:
                pieces.append([("text", c)])
        else:
            pieces[-1].append(tok)
    pieces = [p for p in pieces if any(
        not (t[0] == "text" and not str(t[1]).strip()) for t in p)]
    if len(pieces) > 1:
        for p in pieces:
            depth = 0
            for k, v in p:
                if k == "open":
                    depth += 1
                elif k == "close":
                    depth -= 1
                if depth < 0:
                    return [toks]  # 不平衡，放弃切分
            if depth != 0:
                return [toks]
    return pieces or [[]]


def rewrite(doc: Doc, translations: dict[str, str]) -> str:
    edits: list[tuple[int, int, str]] = []
    for b in doc.blocks:
        target = translations.get(b.uid)
        if target is None or target == b.source:
            continue  # 没译或译文与原文一致：不写，保证未变部分逐字节相同
        try:
            inner = render_block(b, target)
        except MarkerError:
            # 旧译文里的标记可能对应已被解包的注音/span：剥掉标记再试一次
            stripped = MARK_RE.sub("", target)
            try:
                inner = render_block(b, stripped)
            except MarkerError:
                continue  # 仍不合格：保留原文（I8）
        edits.append((b.content_start, b.content_end, inner))
    out = doc.raw
    for start, end, inner in sorted(edits, reverse=True):
        out = out[:start] + inner + out[end:]
    return out
