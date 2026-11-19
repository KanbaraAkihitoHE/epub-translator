"""核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanText:
    """物理文本节点，区间左闭右开，指向 doc.raw。"""

    start: int
    end: int
    raw: str
    parent: "ScanElem | None" = None


@dataclass
class ScanElem:
    tag: str
    attrs_raw: str
    open_start: int
    open_end: int
    parent: "ScanElem | None" = None
    children: list[object] = field(default_factory=list)
    close_start: int = -1
    close_end: int = -1
    self_closing: bool = False
    index: int = -1

    @property
    def is_void(self) -> bool:
        return self.self_closing


@dataclass
class ScanResult:
    raw: str
    root: ScanElem
    elements: list[ScanElem]
    texts: list[ScanText]
    declarations: list[tuple[int, int]]

    def slice(self, start: int, end: int) -> str:
        return self.raw[start:end]


@dataclass
class Span:
    sid: int
    tag: str
    open_raw: str
    close_raw: str
    open_start: int
    open_end: int
    close_start: int
    close_end: int
    self_closing: bool = False
    verbatim: bool = False
    ruby_rt: str | None = None
    ruby_policy: str | None = None


@dataclass
class Block:
    uid: str
    index: int
    tag: str
    kind: str
    open_raw: str
    close_raw: str
    content_start: int
    content_end: int
    spans: tuple[Span, ...]
    source: str
    opaque_inside: tuple[tuple[int, int], ...] = ()
    parent_attrs: str = ""


@dataclass
class Doc:
    href: str
    raw: str
    blocks: list[Block]
    scan: ScanResult
    warnings: list[str] = field(default_factory=list)
