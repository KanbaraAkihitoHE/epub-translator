"""EPUB 读取（L0 的最小实现）。"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
}


@dataclass
class Item:
    id: str
    href: str
    full: str
    media_type: str
    properties: str = ""


@dataclass
class Book:
    path: Path
    opf_path: str
    items: dict[str, Item] = field(default_factory=dict)
    spine: list[Item] = field(default_factory=list)
    title: str = ""
    language: str = ""
    creator: str = ""
    version: str = ""
    drm: str = "none"
    vertical: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def docs(self) -> list[Item]:
        return [it for it in self.spine if it.media_type == "application/xhtml+xml"]


def _local(el) -> str:
    return etree.QName(el).localname


def open_book(path: Path) -> tuple[Book, zipfile.ZipFile]:
    z = zipfile.ZipFile(path)
    root = etree.fromstring(z.read("META-INF/container.xml"))
    opf_path = ""
    for el in root.iter():
        if _local(el) == "rootfile":
            opf_path = el.get("full-path", "")
            break
    if not opf_path:
        raise ValueError("container.xml 没有 rootfile")
    base = posixpath.dirname(opf_path)

    opf = etree.fromstring(z.read(opf_path))
    book = Book(path=path, opf_path=opf_path, version=opf.get("version", ""))
    book.title = "".join(opf.xpath("//dc:title/text()", namespaces=NS)).strip()
    book.language = "".join(opf.xpath("//dc:language/text()", namespaces=NS)).strip()
    book.creator = "".join(opf.xpath("//dc:creator/text()", namespaces=NS)).strip()

    for it in opf.findall("opf:manifest/opf:item", NS):
        href = it.get("href", "")
        full = posixpath.normpath(posixpath.join(base, href)) if base else href
        item = Item(id=it.get("id", ""), href=href, full=full,
                    media_type=it.get("media-type", ""),
                    properties=it.get("properties", ""))
        book.items[item.id] = item

    spine_el = opf.find("opf:spine", NS)
    if spine_el is not None:
        for ref in spine_el.findall("opf:itemref", NS):
            it = book.items.get(ref.get("idref", ""))
            if it is not None:
                book.spine.append(it)

    names = set(z.namelist())
    if "META-INF/license.lcpl" in names:
        book.drm = "LCP"
    elif "META-INF/encryption.xml" in names:
        enc = z.read("META-INF/encryption.xml").decode("utf-8", "ignore").lower()
        book.drm = "DRM" if ("lcp" in enc or "adept" in enc) else "font-obfuscation"
    for n in names:
        if n.lower().endswith(".css"):
            try:
                if "writing-mode: vertical" in z.read(n).decode("utf-8", "ignore"):
                    book.vertical = True
                    break
            except Exception:
                pass
    return book, z


def read_doc(z: zipfile.ZipFile, item: Item) -> str:
    data = z.read(item.full)
    return data.decode("utf-8")
