"""IR / 扫描器 / 回写的核心测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.render import MarkerError, rewrite, tokenize  # noqa: E402
from epubtr.scan import canonical_tags, scan, tag_stream  # noqa: E402

PAGE = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>t</title><style>p{}</style></head>
<body>
<h1>第一章</h1>
<p class="indent">彼は窓の外を見ていた。<em>雨</em>が降っていた。</p>
<p><ruby>漢字<rt>かんじ</rt></ruby>と<ruby>雨<rt>あめ</rt></ruby>。</p>
<p>脚注<a epub:type="noteref" href="#n1">1</a>あり。</p>
<p>画像<img src="a.png" alt="a>b"/>と改行<br/>。</p>
<aside epub:type="footnote" id="n1"><p>脚注の本文</p></aside>
<div><p>入れ子</p></div>
<pre>コード　は　そのまま</pre>
</body></html>
"""


class TestScan(unittest.TestCase):
    def test_tags_and_spans(self):
        sc = scan(PAGE)
        tags = [e.tag for e in sc.elements]
        self.assertIn("p", tags)
        self.assertIn("ruby", tags)
        # 属性里带 > 不截断
        img = next(e for e in sc.elements if e.tag == "img")
        self.assertIn('alt="a>b"', img.attrs_raw)
        self.assertTrue(img.self_closing)

    def test_text_ranges_match_raw(self):
        sc = scan(PAGE)
        for t in sc.texts:
            self.assertEqual(sc.raw[t.start:t.end], t.raw)

    def test_void_without_slash(self):
        sc = scan("<p>a<br>b</p>")
        br = next(e for e in sc.elements if e.tag == "br")
        self.assertTrue(br.self_closing)

    def test_doctype_internal_subset(self):
        raw = '<!DOCTYPE html [ <!ENTITY x "y"> ]><p>a</p>'
        sc = scan(raw)
        self.assertEqual([e.tag for e in sc.elements], ["p"])

    def test_unclosed_tag_tolerated(self):
        sc = scan("<div><p>a")
        self.assertEqual(len(sc.elements), 2)


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.doc = extract_doc("t.xhtml", PAGE)
        self.by_src = {b.source: b for b in self.doc.blocks}

    def test_blocks_found(self):
        self.assertGreaterEqual(len(self.doc.blocks), 6)

    def test_footnote_is_opaque(self):
        # aside 内的 p 不应成为 block
        self.assertFalse(any("脚注の本文" in b.source for b in self.doc.blocks))

    def test_pre_is_opaque(self):
        self.assertFalse(any("コード" in b.source for b in self.doc.blocks))

    def test_noteref_verbatim(self):
        b = next(b for b in self.doc.blocks if "脚注" in b.source)
        self.assertIn("⟦i0⟧⟦/i0⟧", b.source)
        self.assertTrue(b.spans[0].verbatim)

    def test_ruby_dropped_but_base_kept(self):
        # D15：注音对中文读者无价值，只保留 base 文本，不产生标记
        b = next(b for b in self.doc.blocks if "漢字" in b.source)
        self.assertEqual(b.source, "漢字と雨。")
        self.assertFalse(b.spans)
        self.assertNotIn("かんじ", b.source)
        self.assertNotIn("あめ", b.source)

    def test_nested_block_not_double_counted(self):
        self.assertEqual(len([b for b in self.doc.blocks if "入れ子" in b.source]), 1)


class TestRewrite(unittest.TestCase):
    def setUp(self):
        self.doc = extract_doc("t.xhtml", PAGE)

    def test_identity_is_byte_identical(self):
        out = rewrite(self.doc, {b.uid: b.source for b in self.doc.blocks})
        self.assertEqual(out, PAGE)

    def test_synthetic_keeps_structure(self):
        # 把每个非空白字符换成"译"，保留全部标记
        def simple(s: str) -> str:
            out = []
            for k, v in tokenize(s):
                if k == "text":
                    t = str(v)
                    out.append("".join("译" if c.strip() else c for c in t))
                else:
                    m = {"open": "i", "close": "/i", "void": "v"}[k]
                    out.append(f"⟦{m}{v}⟧")
            return "".join(out)

        out = rewrite(self.doc, {b.uid: simple(b.source) for b in self.doc.blocks})
        self.assertEqual(canonical_tags(out), canonical_tags(PAGE))
        self.assertNotEqual(out, PAGE)

    def test_missing_marker_rejected(self):
        b = next(b for b in self.doc.blocks if b.spans)
        with self.assertRaises(MarkerError):
            from epubtr.render import render_block
            render_block(b, b.source.replace("⟦i0⟧", "").replace("⟦/i0⟧", ""))

    def test_bad_nesting_rejected(self):
        b = next(b for b in self.doc.blocks if len(b.spans) >= 2)
        bad = b.source.replace("⟦/i0⟧", "", 1).replace("⟦i0⟧", "", 1)
        bad += "⟦i0⟧⟦/i1⟧"  # 故意错配
        from epubtr.render import render_block
        with self.assertRaises(MarkerError):
            render_block(b, bad)

    def test_rewrite_never_writes_broken(self):
        # 全部标记删掉 -> 拒绝写入 -> 输出等于原文
        out = rewrite(self.doc, {b.uid: "没有标记的译文" for b in self.doc.blocks
                                 if b.spans})
        self.assertEqual(out, PAGE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
