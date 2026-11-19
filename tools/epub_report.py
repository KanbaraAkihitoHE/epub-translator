"""EPUB 体检工具（L0 ingest 的最小版本）。

用法：
    python tools/inspect.py assets/samples/*.epub

输出：每本书的结构报告（JSON），并汇总到 docs/samples-report.md。
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lxml import etree

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}

DRM_ALGOS = {
    "http://www.idpf.org/2008/embedding",  # 字体混淆（不是 DRM）
    "http://ns.adobe.com/pdf/enc#RC",      # 字体混淆
}
DRM_HINTS = ("lcp", "adept", "license.lcpl")


def localname(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def text_of(el) -> str:
    return "".join(el.itertext())


@dataclass
class DocStat:
    href: str
    chars: int = 0
    text_nodes: int = 0
    ruby: int = 0
    rt: int = 0
    footnotes: int = 0
    noterefs: int = 0
    images: int = 0
    svg: int = 0
    headings: list[str] = field(default_factory=list)
    blocks: int = 0


@dataclass
class BookStat:
    path: str
    ok: bool = True
    error: str = ""
    title: str = ""
    language: str = ""
    creator: str = ""
    epub_version: str = ""
    spine_count: int = 0
    page_progression: str = ""
    has_nav: bool = False
    has_ncx: bool = False
    drm: str = "none"
    encrypted_entries: list[str] = field(default_factory=list)
    vertical_css: bool = False
    fonts: int = 0
    images: int = 0
    docs: list[DocStat] = field(default_factory=list)
    total_chars: int = 0
    total_ruby: int = 0
    total_notes: int = 0
    guess: str = ""


def check_container(z: zipfile.ZipFile) -> tuple[bool, str]:
    infos = z.infolist()
    if not infos:
        return False, "空压缩包"
    first = infos[0]
    if first.filename != "mimetype":
        return False, f"mimetype 不是第一个条目（实际是 {first.filename}）"
    if first.compress_type != zipfile.ZIP_STORED:
        return False, "mimetype 被压缩"
    if z.read("mimetype").decode("ascii", "replace").strip() != "application/epub+zip":
        return False, "mimetype 内容不对"
    if "META-INF/container.xml" not in z.namelist():
        return False, "缺 META-INF/container.xml"
    return True, ""


def find_opf(z: zipfile.ZipFile) -> str:
    root = etree.fromstring(z.read("META-INF/container.xml"))
    for rf in root.iter():
        if localname(rf) == "rootfile":
            return rf.get("full-path", "")
    raise ValueError("container.xml 里没有 rootfile")


def inspect_drm(z: zipfile.ZipFile) -> tuple[str, list[str]]:
    names = set(z.namelist())
    if "META-INF/license.lcpl" in names:
        return "LCP", []
    if "META-INF/rights.xml" in names:
        return "ADEPT?", []
    if "META-INF/encryption.xml" not in names:
        return "none", []
    root = etree.fromstring(z.read("META-INF/encryption.xml"))
    encrypted, drm = [], False
    for el in root.iter():
        if localname(el) != "EncryptedData":
            continue
        alg = ""
        uri = ""
        for sub in el.iter():
            ln = localname(sub)
            if ln == "EncryptionMethod":
                alg = sub.get("Algorithm", "")
            elif ln == "CipherReference":
                uri = sub.get("URI", "")
        encrypted.append(uri)
        low = (alg + " " + uri).lower()
        if not any(a in alg for a in DRM_ALGOS) and any(h in low for h in DRM_HINTS):
            drm = True
    return ("DRM" if drm else "font-obfuscation" if encrypted else "none"), encrypted


def scan_css(z: zipfile.ZipFile, names: list[str]) -> tuple[bool, int]:
    vertical, fonts = False, 0
    for n in names:
        low = n.lower()
        if low.endswith(".css"):
            try:
                css = z.read(n).decode("utf-8", "ignore")
            except Exception:
                continue
            if re.search(r"(?:-epub-)?writing-mode\s*:\s*vertical", css):
                vertical = True
        elif low.endswith((".otf", ".ttf", ".woff", ".woff2")):
            fonts += 1
    return vertical, fonts


def stat_doc(z: zipfile.ZipFile, href: str) -> DocStat:
    st = DocStat(href=href)
    root = etree.fromstring(z.read(href), etree.XMLParser(recover=True))
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ln = localname(el)
        et = el.get("{http://www.idpf.org/2007/ops}type", "")
        if ln == "ruby":
            st.ruby += 1
        elif ln == "rt":
            st.rt += 1
        elif ln == "img":
            st.images += 1
        elif ln == "svg":
            st.svg += 1
        elif ln in ("h1", "h2", "h3"):
            t = text_of(el).strip()
            if t:
                st.headings.append(f"{ln}:{t[:40]}")
        if "footnote" in et or "endnote" in et:
            st.footnotes += 1
        if "noteref" in et:
            st.noterefs += 1
        if ln in ("p", "div", "li"):
            if not any(isinstance(c.tag, str) and localname(c) in ("p", "div", "li") for c in el):
                st.blocks += 1
    body = root.find(".//xhtml:body", NS)
    texts = [t for t in (body.itertext() if body is not None else []) if t.strip()]
    st.chars = sum(len(t) for t in texts)
    st.text_nodes = len(texts)
    return st


def inspect(path: Path) -> BookStat:
    bs = BookStat(path=str(path))
    try:
        with zipfile.ZipFile(path) as z:
            ok, err = check_container(z)
            if not ok:
                bs.ok, bs.error = False, err
                return bs
            opf_path = find_opf(z)
            opf = etree.fromstring(z.read(opf_path))
            base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

            bs.title = "".join(opf.xpath("//dc:title/text()", namespaces=NS))
            bs.language = "".join(opf.xpath("//dc:language/text()", namespaces=NS))
            bs.creator = "".join(opf.xpath("//dc:creator/text()", namespaces=NS))
            bs.epub_version = opf.get("version", "")

            spine = opf.find("opf:spine", NS)
            if spine is not None:
                bs.page_progression = spine.get("page-progression-direction", "")
                ids = [it.get("idref") for it in spine.findall("opf:itemref", NS)]
            else:
                ids = []

            manifest = {}
            for it in opf.findall("opf:manifest/opf:item", NS):
                manifest[it.get("id")] = it

            for iid in ids:
                it = manifest.get(iid)
                if it is None:
                    continue
                href = it.get("href", "")
                mt = it.get("media-type", "")
                full = base + href
                if mt == "application/xhtml+xml":
                    try:
                        bs.docs.append(stat_doc(z, full))
                    except Exception as e:  # 坏文档不阻塞
                        bs.docs.append(DocStat(href=full))
                        bs.error += f"[{href}: {e}] "
                bs.spine_count += 1

            bs.has_nav = "nav" in [it.get("properties", "") for it in manifest.values()]
            bs.has_ncx = any(it.get("media-type") == "application/x-dtbncx+xml"
                             for it in manifest.values())
            bs.drm, bs.encrypted_entries = inspect_drm(z)
            bs.vertical_css, bs.fonts = scan_css(z, z.namelist())
            bs.images = sum(1 for n in z.namelist()
                            if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")))
    except Exception as e:
        bs.ok, bs.error = False, f"{type(e).__name__}: {e}"
        return bs

    bs.total_chars = sum(d.chars for d in bs.docs)
    bs.total_ruby = sum(d.ruby for d in bs.docs)
    bs.total_notes = sum(d.footnotes for d in bs.docs)
    heads = sum(len(d.headings) for d in bs.docs)
    if bs.spine_count >= 3 and heads >= 8 and bs.total_chars < 120000:
        bs.guess = "短篇集/多章作品（标题多、篇幅分散）"
    elif bs.spine_count <= 3:
        bs.guess = "单文件长篇（spine 少，需按标题切章）"
    else:
        bs.guess = "常规长篇（spine 即章节）"
    return bs


def to_markdown(reports: list[BookStat]) -> str:
    lines = ["# 样书体检报告", "", f"共 {len(reports)} 本。", ""]
    for r in reports:
        lines += [f"## {Path(r.path).name}", ""]
        if not r.ok:
            lines += [f"**读取失败**：{r.error}", ""]
            continue
        lines += [
            f"- 书名：{r.title}",
            f"- 作者：{r.creator}",
            f"- 语言：`{r.language}` · EPUB `{r.epub_version}` · spine {r.spine_count} 篇",
            f"- DRM：**{r.drm}**" + (f"（{', '.join(r.encrypted_entries)}）" if r.encrypted_entries else ""),
            f"- 竖排 CSS：{'是' if r.vertical_css else '否'} · 内嵌字体 {r.fonts} · 图片 {r.images}",
            f"- 正文：{r.total_chars:,} 字 · ruby {r.total_ruby} · 脚注 {r.total_notes}",
            f"- 判断：{r.guess}",
            "",
            "| doc | 字数 | 块 | ruby | 脚注 | 标题 |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for d in r.docs:
            if d.chars == 0 and not d.headings:
                continue
            lines.append(
                f"| {d.href.split('/')[-1]} | {d.chars:,} | {d.blocks} | {d.ruby} | {d.footnotes} | "
                f"{'; '.join(d.headings[:3])[:60]} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    reports = []
    for p in argv[1:]:
        r = inspect(Path(p))
        reports.append(r)
        flag = "OK " if r.ok else "ERR"
        print(f"[{flag}] {Path(p).name}: {r.title} | {r.total_chars:,}字 | "
              f"ruby={r.total_ruby} notes={r.total_notes} drm={r.drm} "
              f"vertical={r.vertical_css} spine={r.spine_count}")
        if not r.ok:
            print("      ", r.error)
    from epubtr.paths import report as report_path, slug as make_slug
    for r in reports:
        d = Path(r.path)
        s = make_slug(r.title or d.stem)
        report_path(s, "inspect.md").write_text(to_markdown([r]), encoding="utf-8")
        report_path(s, "inspect.json").write_text(
            json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding="utf-8")
    report_path(None, "samples-report.md").write_text(to_markdown(reports), encoding="utf-8")
    report_path(None, "samples-report.json").write_text(
        json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\n写入 reports/<书名>/inspect.md 与 reports/_shared/samples-report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
