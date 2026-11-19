"""物理扫描器：在原始 XHTML 字符串上算出标签与文本节点的精确区间。

设计要点（见 docs/ir.md §3）：
- 不重新序列化，只记录位置；
- 尊重引号，`alt="a>b"` 不会截断；
- 坏 HTML 容忍：闭标签不匹配时向上找，找不到就忽略并留 warning。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import ScanElem, ScanResult, ScanText

VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)

BLOCK_TAGS = frozenset(
    "p div h1 h2 h3 h4 h5 h6 li dd dt td th blockquote figcaption "
    "aside section article header footer caption pre".split()
)

OPAQUE_TAGS = frozenset("script style pre code svg math template".split())


@dataclass
class TagEvent:
    kind: str  # open | close | self | decl
    name: str
    attrs_raw: str
    start: int
    end: int


@dataclass
class ScanStats:
    elements: int = 0
    text_nodes: int = 0
    declarations: int = 0
    warnings: list[str] = field(default_factory=list)


def _skip_comment(raw: str, i: int) -> int:
    e = raw.find("-->", i + 4)
    return len(raw) if e < 0 else e + 3


def _skip_cdata(raw: str, i: int) -> int:
    e = raw.find("]]>", i + 9)
    return len(raw) if e < 0 else e + 3


def _skip_pi(raw: str, i: int) -> int:
    e = raw.find("?>", i + 2)
    return len(raw) if e < 0 else e + 2


def _skip_decl(raw: str, i: int) -> int:
    """<!DOCTYPE ... [ ... ]> 里可能含 '>'，需要按括号深度跳过。"""
    depth = 0
    j = i + 2
    n = len(raw)
    while j < n:
        c = raw[j]
        if c == "[":
            depth += 1
        elif c == "]" and depth:
            depth -= 1
        elif c == ">" and depth == 0:
            return j + 1
        j += 1
    return n


def _tag_end(raw: str, i: int) -> int:
    """从 '<' 起找到匹配的 '>'，跳过引号内的 '>'。"""
    quote = ""
    j = i + 1
    n = len(raw)
    while j < n:
        c = raw[j]
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == ">":
            return j + 1
        j += 1
    return n


def _split_open(chunk: str) -> tuple[str, str, bool]:
    """'<p class="x" />' -> ('p', 'class="x"', True)"""
    body = chunk[1:-1] if chunk.endswith(">") else chunk[1:]
    self_closing = False
    stripped = body.rstrip()
    if stripped.endswith("/"):
        self_closing = True
        body = stripped[:-1]
    body = body.lstrip()
    k = 0
    while k < len(body) and body[k] not in " \t\r\n/>":
        k += 1
    name = body[:k]
    attrs = body[k:].strip()
    return name, attrs, self_closing


def scan(raw: str) -> ScanResult:
    n = len(raw)
    i = 0
    root = ScanElem("#document", "", 0, 0, None)
    stack: list[ScanElem] = [root]
    elements: list[ScanElem] = []
    texts: list[ScanText] = []
    decls: list[tuple[int, int]] = []
    warnings: list[str] = []

    def add_text(start: int, end: int) -> None:
        if end <= start:
            return
        t = ScanText(start, end, raw[start:end], stack[-1])
        stack[-1].children.append(t)
        texts.append(t)

    while i < n:
        lt = raw.find("<", i)
        if lt < 0:
            add_text(i, n)
            break
        add_text(i, lt)

        if raw.startswith("<!--", lt):
            e = _skip_comment(raw, lt)
        elif raw.startswith("<![CDATA[", lt):
            e = _skip_cdata(raw, lt)
            decls.append((lt, e))  # CDATA 原样保留，不进文本节点
        elif raw.startswith("<?", lt):
            e = _skip_pi(raw, lt)
            decls.append((lt, e))
        elif raw.startswith("<!", lt):
            e = _skip_decl(raw, lt)
            decls.append((lt, e))
        else:
            e = _tag_end(raw, lt)
            chunk = raw[lt:e]
            if chunk.startswith("</"):
                name = chunk[2:-1].strip().split(" ")[0].rstrip(">").strip()
                if not _close(stack, name, lt, e):
                    warnings.append(f"孤立闭标签 </{name}> @{lt}")
            else:
                name, attrs, self_c = _split_open(chunk)
                if not name:
                    warnings.append(f"无法解析的标签 @{lt}: {chunk[:30]!r}")
                    i = e
                    continue
                el = ScanElem(
                    tag=name,
                    attrs_raw=attrs,
                    open_start=lt,
                    open_end=e,
                    parent=stack[-1],
                    self_closing=self_c or name.lower() in VOID_TAGS,
                )
                el.index = len(elements)
                elements.append(el)
                stack[-1].children.append(el)
                if not el.self_closing:
                    stack.append(el)
        i = e

    for el in stack[1:]:
        el.close_start = el.close_end = n
        warnings.append(f"未闭合标签 <{el.tag}> @{el.open_start}")

    return ScanResult(raw=raw, root=root, elements=elements, texts=texts,
                      declarations=decls)


def _close(stack: list[ScanElem], name: str, start: int, end: int) -> bool:
    for k in range(len(stack) - 1, 0, -1):
        if stack[k].tag == name:
            for m in range(len(stack) - 1, k - 1, -1):
                el = stack[m]
                if m == k:
                    el.close_start, el.close_end = start, end
                else:
                    el.close_start = el.close_end = start
            del stack[k:]
            return True
    return False


IGNORED_TAGS = frozenset({"ruby", "rb", "rt", "rp", "span"})


def canonical_tags(raw: str) -> list[tuple[str, str, str]]:
    """结构比对用：忽略注音与排版 span（见 ADR D15）。

    中文版会解包 ruby/span，因此比对时两边都把它们当作不存在；
    其余标签（段落、标题、图片、链接等）仍要求逐项一致。
    """
    return [(kind, name, attrs) for kind, name, attrs in tag_stream(raw)
            if name not in IGNORED_TAGS]



def tag_stream(raw: str) -> list[tuple[str, str, str]]:
    """结构比对用：只看标签序列（名、属性原文、是否自闭合）。"""
    out: list[tuple[str, str, str]] = []
    n = len(raw)
    i = 0
    while i < n:
        lt = raw.find("<", i)
        if lt < 0:
            break
        if raw.startswith("<!--", lt):
            i = _skip_comment(raw, lt)
            continue
        if raw.startswith("<![CDATA[", lt):
            i = _skip_cdata(raw, lt)
            continue
        if raw.startswith("<?", lt):
            i = _skip_pi(raw, lt)
            continue
        if raw.startswith("<!", lt):
            i = _skip_decl(raw, lt)
            continue
        e = _tag_end(raw, lt)
        chunk = raw[lt:e]
        if chunk.startswith("</"):
            name = chunk[2:-1].strip().split(" ")[0].rstrip(">").strip()
            out.append(("close", name, ""))
        else:
            name, attrs, self_c = _split_open(chunk)
            out.append(("self" if (self_c or name.lower() in VOID_TAGS) else "open",
                        name, attrs))
        i = e
    return out
