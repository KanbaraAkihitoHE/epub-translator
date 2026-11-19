"""EPUB 重打包 v2：字体内嵌 + 标题替换 + 横排覆盖。"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path

from .epub import open_book, read_doc
from .font import subset_font
from .ir import extract_doc
from .render import rewrite
from .translate import src_hash

FONT_DIR = "fonts"
FONT_FILE = "epubtr-kai.ttf"
CSS_FILE = "epubtr-font.css"
MARK_RE = re.compile(r"⟦[^⟧]*⟧")

CSS_BODY = """@font-face {{
  font-family: "epubtr-kai";
  src: url("{font}") format("truetype");
  font-weight: normal;
  font-style: normal;
}}
html, body {{
  font-family: "epubtr-kai", "KaiTi", "STKaiti", serif !important;
  writing-mode: horizontal-tb !important;
  -webkit-writing-mode: horizontal-tb !important;
  -epub-writing-mode: horizontal-tb !important;
}}
* {{
  font-family: "epubtr-kai", "KaiTi", "STKaiti", serif !important;
}}
.gfont, .calibre3, .p-caution, [class*="font-"] {{
  font-weight: normal !important;
}}
/* 人物介绍页：人名加粗，介绍保持正文 */
.gfont {{
  font-weight: bold !important;
}}
.start-1em, .start-2em, .start-3em, .start-3em1, .start-3em2,
.h-indent-1em, .h-indent-6em, .gfont, .font-080per,
.align-center, .align-end {{
  margin: 0 !important;
  padding: 0 !important;
}}
{size_rule}
"""

SIZE_RULE = """p, div, span, li, td, th, blockquote {
  font-size: 1em !important;
}
body {
  line-height: 1.75 !important;
}
p {
  text-indent: 2em !important;
  margin: 0 !important;
}
h1, h2, h3, h4, h5, h6 {
  text-indent: 0 !important;
  text-align: center !important;
  font-weight: normal !important;
  margin: 1.2em 0 0.8em !important;
}
h1 { font-size: 1.5em !important; }
h2 { font-size: 1.25em !important; }
h3 { font-size: 1.1em !important; }
.align-center, .align-end, .gfont,
.start-1em, .start-2em, .start-3em, .start-3em1, .start-3em2,
.font-080per, .h-indent-1em, .h-indent-6em,
.align-center p, .align-end p, .gfont p,
.start-1em p, .start-2em p, .start-3em p, .start-3em1 p, .start-3em2 p,
.font-080per p, .h-indent-1em p, .h-indent-6em p {
  text-indent: 0 !important;
}
"""


def plain(text: str) -> str:
    return MARK_RE.sub("", text).strip()


def _inject_head(html: str, link: str) -> str:
    if link in html:
        return html
    if "</head>" in html:
        return html.replace("</head>", f"{link}</head>", 1)
    return html


def _fix_opf(data: bytes, manifest_items: list[str]) -> bytes:
    text = data.decode("utf-8")
    text = text.replace('page-progression-direction="rtl"',
                        'page-progression-direction="ltr"')
    text = re.sub(r"(<dc:language[^>]*>)\s*[a-zA-Z-]+\s*(</dc:language>)",
                  r"\1zh-CN\2", text)
    if manifest_items and "</manifest>" in text:
        text = text.replace("</manifest>",
                            "".join(manifest_items) + "</manifest>", 1)
    return text.encode("utf-8")


def _replace_labels(data: bytes, titles: dict[str, str]) -> bytes:
    text = data.decode("utf-8")
    for ja, zh in titles.items():
        if not ja or not zh:
            continue
        text = re.sub(r">(\s*)" + re.escape(ja) + r"(\s*)<",
                      lambda m: f">{m.group(1)}{zh}{m.group(2)}<", text)
    return text.encode("utf-8")


CHAR_HEADING = "登場人物"


def _annotate_character_page(z, book,
                             translations: dict[str, dict[str, str]]) -> tuple[
                                 dict[str, dict[str, str]], int]:
    """只在「登場人物」页给每个人名后面加日文原名；正文不加。

    人物介绍页是读者用来对名字的，所以这一页**每个**名字都注，不管译名
    是否与原名相同；其余页面一概不注。
    """
    total = 0
    for item in book.docs:
        href = item.full
        if href not in translations:
            continue
        try:
            raw = read_doc(z, item)
        except KeyError:
            continue
        doc = extract_doc(href, raw)
        blocks = doc.blocks
        if not any(plain(b.source) == CHAR_HEADING for b in blocks):
            continue
        units = dict(translations[href])
        for b in blocks:
            if "gfont" not in b.parent_attrs:
                continue
            ja = plain(b.source)
            zh = units.get(b.uid)
            if not ja or not zh or ja == CHAR_HEADING or zh.endswith("）"):
                continue
            units[b.uid] = f"{zh}（{ja}）"
            total += 1
        translations[href] = units
    return translations, total


def build_epub(
    book_path: Path,
    translations: dict[str, dict[str, str]],
    out_path: Path,
    *,
    layout_horizontal: bool = True,
    font_path: Path | None = None,
    titles: dict[str, str] | None = None,
    normalize_size: bool = True,
    subset: bool = True,
    hashes: dict[str, dict[str, str]] | None = None,
) -> dict:
    book, z = open_book(book_path)
    doc_by_path = {it.full: it for it in book.docs}
    opf_dir = posixpath.dirname(book.opf_path)
    titles = titles or {}
    stats = {"docs": 0, "blocks": 0, "font_bytes": 0, "skipped": [],
             "names_annotated": 0}

    # 术语唯一权威：所有译文先过一遍 NameResolver，再进入渲染
    from .names import NameResolver
    from .paths import ROOT, slug as make_slug
    resolver = NameResolver.load(ROOT / "kb" / make_slug(book.title))
    if resolver._variants:
        fixed = 0
        for href, units in translations.items():
            for uid, text in list(units.items()):
                new = resolver.normalize(text)
                if new != text:
                    units[uid] = new
                    fixed += 1
        stats["name_fixes"] = fixed

    translations, n_ann = _annotate_character_page(z, book, translations)
    stats["names_annotated"] = n_ann

    # 1) 先渲染所有文档（标题优先用 titles 映射覆盖）
    new_docs: dict[str, str] = {}
    for href, trans in translations.items():
        if href not in doc_by_path:
            continue
        raw = read_doc(z, doc_by_path[href])
        doc = extract_doc(href, raw)
        fixed = dict(trans)
        if hashes:
            hmap = hashes.get(href, {})
            for b in doc.blocks:
                old = hmap.get(b.uid)
                if old and old != src_hash(b):
                    fixed.pop(b.uid, None)      # 原文变了，旧译文不可信
                    stats.setdefault("stale", []).append(f"{href}:{b.uid}")
        for b in doc.blocks:
            key = plain(b.source)
            if key in titles:
                # 保留原位的内联标记，只把文字换掉（目录页的链接项也走这里）
                fixed[b.uid] = b.source.replace(key, titles[key])
        new_docs[href] = rewrite(doc, fixed)
        stats["docs"] += 1
        stats["blocks"] += sum(1 for b in doc.blocks if b.uid in fixed)

    # 2) 字体子集
    font_bytes = b""
    if font_path and font_path.exists():
        chars = set()
        for html in new_docs.values():
            body = re.sub(r"<rt[^>]*>.*?</rt>", "", html, flags=re.S)
            body = re.sub(r"<[^>]+>", "", body)
            chars.update(body)
        chars.update(chr(c) for c in range(32, 127))
        chars.update("　，。、！？：；「」『』（）《》〈〉—…·“”‘’")
        if subset:
            tmp = out_path.parent / f".{out_path.stem}.font.ttf"
            stats["font_bytes"] = subset_font(font_path, "".join(sorted(chars)), tmp)
            font_bytes = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
        else:
            font_bytes = font_path.read_bytes()
            stats["font_bytes"] = len(font_bytes)

    css = CSS_BODY.format(font=FONT_FILE, size_rule=SIZE_RULE if normalize_size else "")
    manifest: list[str] = []
    if font_bytes:
        manifest.append(f'<item href="{FONT_DIR}/{FONT_FILE}" id="epubtr-font" '
                        f'media-type="font/ttf"/>')
        manifest.append(f'<item href="{FONT_DIR}/{CSS_FILE}" id="epubtr-font-css" '
                        f'media-type="text/css"/>')
    layout_css = ""
    if layout_horizontal and not font_bytes:
        layout_css = ("<style type=\"text/css\">html,body{writing-mode:horizontal-tb "
                      "!important;-webkit-writing-mode:horizontal-tb !important;"
                      "-epub-writing-mode:horizontal-tb !important;}</style>")

    # 3) 写包
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as out:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        out.writestr(info, "application/epub+zip")
        if font_bytes:
            out.writestr(f"{opf_dir}/{FONT_DIR}/{FONT_FILE}".lstrip("/"), font_bytes)
            out.writestr(f"{opf_dir}/{FONT_DIR}/{CSS_FILE}".lstrip("/"),
                         css.encode("utf-8"))

        for entry in z.infolist():
            name = entry.filename
            if name == "mimetype":
                continue
            if name == book.opf_path:
                out.writestr(entry, _fix_opf(z.read(name), manifest))
                continue
            if name in new_docs:
                html = new_docs[name]
                if font_bytes:
                    css_href = posixpath.relpath(
                        f"{FONT_DIR}/{CSS_FILE}",
                        posixpath.dirname(name) or ".")
                    html = _inject_head(
                        html, f'<link rel="stylesheet" type="text/css" href="{css_href}"/>')
                elif layout_css:
                    html = _inject_head(html, layout_css)
                out.writestr(entry, html.encode("utf-8"))
                continue
            if name.endswith(".ncx") or name.endswith("nav.xhtml"):
                out.writestr(entry, _replace_labels(z.read(name), titles))
                continue
            out.writestr(entry, z.read(name))

    z.close()
    return stats
