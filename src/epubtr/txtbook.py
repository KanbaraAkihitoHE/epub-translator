"""把纯文本包装成最小 EPUB，好让现有流水线直接处理。

支持：空行分段、`# 标题`、`---` 场景分隔。
"""

from __future__ import annotations

import html
import zipfile
from pathlib import Path

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def parse_text(raw: str) -> tuple[str, list[tuple[str, str]]]:
    """返回 (书名, [(kind, text)])，kind 为 h1 / para。"""
    title = ""
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        if buf:
            blocks.append(("para", "".join(buf).strip()))
            buf.clear()

    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s:
            flush()
            continue
        if s == "---":
            flush()
            blocks.append(("hr", ""))
            continue
        if s.startswith("# "):
            flush()
            if not title:
                title = s[2:].strip()
                blocks.append(("h1", title))
            else:
                blocks.append(("h2", s[2:].strip()))
            continue
        buf.append(s)
    flush()
    return title, blocks


def build_txt_epub(raw: str, out: Path, *, title: str = "",
                   author: str = "", lang: str = "ja") -> tuple[Path, str]:
    """生成最小 EPUB。返回 (路径, 书名)。"""
    parsed_title, blocks = parse_text(raw)
    title = title or parsed_title or "未命名片段"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    body: list[str] = []
    for kind, text in blocks:
        if kind == "h1":
            body.append(f"<h1>{html.escape(text)}</h1>")
        elif kind == "h2":
            body.append(f"<h2>{html.escape(text)}</h2>")
        elif kind == "hr":
            body.append("<hr/>")
        else:
            body.append(f"<p>{html.escape(text)}</p>")
    chapter = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<html xmlns="http://www.w3.org/1999/xhtml" '
               'xmlns:epub="http://www.idpf.org/2007/ops" lang="ja">'
               f"<head><title>{html.escape(title)}</title></head><body>\n"
               + "\n".join(body) + "\n</body></html>")

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:txt-{abs(hash(title)) % 10**12}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:creator>{html.escape(author or "佚名")}</dc:creator>
    <dc:language>{lang}</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch"/>
  </spine>
</package>
"""

    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head><body>
<nav epub:type="toc"><ol><li><a href="chapter.xhtml">{html.escape(title)}</a></li></ol></nav>
</body></html>
"""

    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/chapter.xhtml", chapter)
    return out, title
