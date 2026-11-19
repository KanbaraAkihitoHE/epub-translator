"""从扫描结果提取 Block 与可译 source（见 docs/ir.md §6）。"""

from __future__ import annotations

import re

from .model import Block, Doc, ScanElem, ScanResult, ScanText, Span
from .scan import BLOCK_TAGS, OPAQUE_TAGS, scan
from .text import MARK_CLOSE, MARK_OPEN, normalize_space, unescape

ATTR_RE = re.compile(
    r"""([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?"""
)

KIND = {
    "h1": "heading", "h2": "heading", "h3": "heading",
    "h4": "heading", "h5": "heading", "h6": "heading",
    "li": "list_item", "dd": "list_item", "dt": "list_item",
    "td": "cell", "th": "cell", "caption": "caption",
    "figcaption": "caption", "blockquote": "blockquote",
}


def parse_attrs(attrs_raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(attrs_raw):
        name = m.group(1)
        val = m.group(2) if m.group(2) is not None else (
            m.group(3) if m.group(3) is not None else (m.group(4) or ""))
        out[name.lower()] = val
    return out


def is_opaque(el: ScanElem) -> bool:
    if el.tag in OPAQUE_TAGS:
        return True
    attrs = parse_attrs(el.attrs_raw)
    et = attrs.get("epub:type", "") + " " + attrs.get("role", "")
    return any(k in et for k in ("footnote", "endnote", "doc-footnote"))


def is_verbatim(el: ScanElem) -> bool:
    attrs = parse_attrs(el.attrs_raw)
    et = attrs.get("epub:type", "") + " " + attrs.get("role", "")
    return "noteref" in et or "doc-noteref" in et


def _has_block_descendant(el: ScanElem) -> bool:
    for ch in el.children:
        if isinstance(ch, ScanElem):
            if ch.tag in BLOCK_TAGS:
                return True
            if _has_block_descendant(ch):
                return True
    return False


def _has_text(el: ScanElem) -> bool:
    for ch in el.children:
        if isinstance(ch, ScanText):
            if ch.raw.strip():
                return True
        elif isinstance(ch, ScanElem) and not is_opaque(ch):
            if _has_text(ch):
                return True
    return False


def _has_opaque_ancestor(el: ScanElem) -> bool:
    p = el.parent
    while p is not None and p.tag != "#document":
        if is_opaque(p):
            return True
        p = p.parent
    return False


def _ruby_parts(raw: str, el: ScanElem) -> tuple[str, str, str, str] | None:
    """返回 (开标记原文, base 原文, 闭标记原文, 读音)。

    - 单个 rb：原样保留 rb/rt 结构，只替换 base 文本；
    - 多个 rb（一字一注）：归一为 `<ruby>译文<rt>合并读音</rt></ruby>`。
    """
    children = el.children
    ruby_open = raw[el.open_start:el.open_end]
    ruby_close = raw[el.close_start:el.close_end]
    has_rb = any(isinstance(c, ScanElem) and c.tag == "rb" for c in children)

    if has_rb:
        bases: list[str] = []
        rts: list[str] = []
        for ch in children:
            if isinstance(ch, ScanText):
                if ch.raw.strip():
                    return None           # rb 之间混入实文本：不支持
            elif ch.tag == "rb":
                bases.append(raw[ch.open_end:ch.close_start])
            elif ch.tag == "rt":
                rts.append(raw[ch.open_end:ch.close_start])
            elif ch.tag == "rp":
                continue
            else:
                return None
        if not bases or not any(t.strip() for t in bases):
            return None
        rt = "".join(t.strip() for t in rts)
        if len(bases) == 1:
            rb = next(c for c in children if isinstance(c, ScanElem) and c.tag == "rb")
            prefix = raw[el.open_end:rb.open_start]
            suffix = raw[rb.close_start:el.close_start]
            return (ruby_open + prefix + raw[rb.open_start:rb.open_end],
                    raw[rb.open_end:rb.close_start],
                    suffix + ruby_close, rt)
        base = "".join(b.strip() for b in bases)
        return ruby_open, base, f"<rt>{rt}</rt>{ruby_close}", rt

    # 无 rb：前导文本作为 base
    rest = children
    base = ""
    base_end = el.open_end
    idx = 0
    while idx < len(rest) and isinstance(rest[idx], ScanText):
        base += rest[idx].raw
        base_end = rest[idx].end
        idx += 1
    rest = rest[idx:]
    if not base.strip():
        return None
    rts = []
    for ch in rest:
        if isinstance(ch, ScanText):
            if ch.raw.strip():
                return None
        elif ch.tag == "rt":
            rts.append(raw[ch.open_end:ch.close_start])
        elif ch.tag != "rp":
            return None
    rt = "".join(t.strip() for t in rts)
    return ruby_open, base, raw[base_end:el.close_start] + ruby_close, rt


class _BlockBuilder:
    def __init__(self, raw: str):
        self.raw = raw
        self.spans: list[Span] = []
        self.out: list[str] = []

    def _span(self, el: ScanElem, *, verbatim: bool = False,
              close_extra: str = "", open_raw: str | None = None,
              close_raw: str | None = None,
              ruby_rt: str | None = None) -> Span:
        sid = len(self.spans)
        span = Span(
            sid=sid,
            tag=el.tag,
            open_raw=open_raw if open_raw is not None else self.raw[el.open_start:el.open_end],
            close_raw=(close_raw if close_raw is not None
                       else close_extra + self.raw[el.close_start:el.close_end]),
            open_start=el.open_start,
            open_end=el.open_end,
            close_start=el.close_start,
            close_end=el.close_end,
            self_closing=el.self_closing,
            verbatim=verbatim,
            ruby_rt=ruby_rt,
        )
        self.spans.append(span)
        return span

    def walk(self, el: ScanElem) -> None:
        for ch in el.children:
            self._child(ch)

    def _child(self, ch) -> None:
        if isinstance(ch, ScanText):
            self.out.append(unescape(ch.raw))
            return
        if ch.tag == "span":
            # 转换工具留下的排版 span（常包着标点），解包不留标记
            self.walk(ch)
            return
        if ch.self_closing:
            sp = self._span(ch)
            self.out.append(f"{MARK_OPEN}v{sp.sid}{MARK_CLOSE}")
            return
        if ch.tag == "ruby":
            # 注音对中文读者无信息价值，只保留 base 文本（见 ADR D15）
            parts = _ruby_parts(self.raw, ch)
            if parts is not None and "<" not in parts[1]:
                self.out.append(unescape(parts[1]))
                return
            # 复杂 ruby（base 里含图片/标签）：解包，跳过读音
            for sub in ch.children:
                if isinstance(sub, ScanElem) and sub.tag in ("rt", "rp"):
                    continue
                if isinstance(sub, ScanElem) and sub.tag == "rb":
                    self.walk(sub)
                    continue
                self._child(sub)
            return
        if is_opaque(ch) or is_verbatim(ch):
            sp = self._span(ch, verbatim=True,
                            close_extra=self.raw[ch.open_end:ch.close_start])
            self.out.append(f"{MARK_OPEN}i{sp.sid}{MARK_CLOSE}"
                            f"{MARK_OPEN}/i{sp.sid}{MARK_CLOSE}")
            return
        sp = self._span(ch)
        self.out.append(f"{MARK_OPEN}i{sp.sid}{MARK_CLOSE}")
        self.walk(ch)
        self.out.append(f"{MARK_OPEN}/i{sp.sid}{MARK_CLOSE}")


def extract_doc(href: str, raw: str) -> Doc:
    sc = scan(raw)
    blocks: list[Block] = []
    for el in sc.elements:
        if el.tag not in BLOCK_TAGS:
            continue
        if is_opaque(el):
            continue
        if _has_opaque_ancestor(el):
            continue
        if el.self_closing or el.close_start < 0:
            continue
        if _has_block_descendant(el):
            continue
        if not _has_text(el):
            continue
        b = _BlockBuilder(raw)
        b.walk(el)
        source = normalize_space("".join(b.out))
        if not source.strip():
            continue
        blocks.append(Block(
            uid=f"d{len(blocks):03d}",
            index=len(blocks),
            tag=el.tag,
            kind=KIND.get(el.tag, "para"),
            open_raw=raw[el.open_start:el.open_end],
            close_raw=raw[el.close_start:el.close_end],
            content_start=el.open_end,
            content_end=el.close_start,
            spans=tuple(b.spans),
            source=source,
            parent_attrs=el.parent.attrs_raw if el.parent is not None else "",
        ))
    return Doc(href=href, raw=raw, blocks=blocks, scan=sc)


def overlaps(blocks: list[Block]) -> list[tuple[int, int]]:
    bad = []
    for a, b in zip(blocks, blocks[1:]):
        if b.content_start < a.content_end:
            bad.append((a.index, b.index))
    return bad
