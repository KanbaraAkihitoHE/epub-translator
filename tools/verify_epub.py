"""产物验收：结构、可解析性、译文覆盖率、与原文的结构同构。

用法：python tools/verify_epub.py out/xxx.zh.epub [原书.epub]
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lxml import etree                          # noqa: E402

from epubtr.scan import canonical_tags          # noqa: E402

CJK = lambda s: sum(1 for c in s if "\u4e00" <= c <= "\u9fff")  # noqa: E731
KANA = re.compile(r"[\u3040-\u30ff]")


def strip_injected(html: str) -> str:
    html = re.sub(r"<link[^>]*epubtr-font[^>]*>", "", html)
    html = re.sub(r"<style[^>]*>[^<]*writing-mode[^<]*</style>", "", html, flags=re.S)
    return html


def xhtml_names(z: zipfile.ZipFile) -> list[str]:
    return [n for n in z.namelist()
            if n.lower().endswith((".xhtml", ".html", ".htm"))]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    ok = True
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            print("[FAIL] mimetype 不是第一个/未存储")
            ok = False
        names = xhtml_names(z)
        bad = []
        total_cjk = 0
        kana_docs = []
        for n in names:
            data = z.read(n)
            text = data.decode("utf-8", "ignore")
            try:
                etree.fromstring(data)
            except etree.XMLSyntaxError as e:
                bad.append(f"{n}: {e}")
            body = re.sub(r"<rt[^>]*>.*?</rt>", "", text, flags=re.S)
            body = re.sub(r"<[^>]+>", "", body)
            body = re.sub(r"（[^）]{0,30}[\u3040-\u30ff][^）]{0,30}）", "", body)  # 人名注记
            kana = len(KANA.findall(body))
            if kana > 50:
                kana_docs.append((n, kana))
            total_cjk += CJK(body)
        print(f"[{'PASS' if not bad else 'FAIL'}] XML 可解析 {len(names)} 篇，"
              f"中文汉字 {total_cjk:,}")
        if kana_docs:
            print(f"[WARN] 疑似未译（假名残留 >50）：{len(kana_docs)} 篇")
            for n, k in kana_docs[:5]:
                print(f"    {n}: {k} 个假名")
        else:
            print("[PASS] 无假名残留")
        for b in bad[:5]:
            print("   ", b)
        ok = ok and not bad

        if len(argv) > 2:
            with zipfile.ZipFile(argv[2]) as src:
                diffs = 0
                for n in xhtml_names(z):
                    if n not in src.namelist():
                        continue
                    a = canonical_tags(src.read(n).decode("utf-8"))
                    b = canonical_tags(strip_injected(z.read(n).decode("utf-8")))
                    if a != b:
                        diffs += 1
                        if diffs <= 3:
                            print(f"   结构差异: {n} ({len(a)} vs {len(b)} tags)")
                print(f"[{'PASS' if diffs == 0 else 'FAIL'}] 结构同构："
                      f"{diffs} 篇有差异")
                ok = ok and diffs == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
