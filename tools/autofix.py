"""自动修复：机械性标点 + 对术语/假名异常的段落自动重译。

用法：python tools/autofix.py <epub> [--dry]
产物：原地更新 work/<slug>/rev/*.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.store import save_json  # noqa: E402
from epubtr.epub import open_book, read_doc        # noqa: E402
from epubtr.glossary import check as gl_check      # noqa: E402
from epubtr.glossary import load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                   # noqa: E402
from epubtr.llm import load_config                  # noqa: E402
from epubtr.punct import check_text                 # noqa: E402
from epubtr.textnorm import looks_japanese           # noqa: E402
from epubtr.render import MarkerError, tokenize, validate  # noqa: E402
from epubtr.translate import translate_batch        # noqa: E402

KANA = re.compile(r"[\u3040-\u30ff]")


def fix_punct(text: str) -> tuple[str, int]:
    errs = check_text(text)
    fixes = []
    for pos, msg in errs:
        if msg.startswith("多余的"):
            fixes.append((pos, ""))
        elif "被" in msg and msg.endswith("关闭"):
            want = msg[1:msg.index("」")]
            closer = {"「": "」", "『": "』", "“": "”", "‘": "’",
                      "（": "）", "《": "》"}.get(want, "")
            if closer:
                fixes.append((pos, closer))
    for pos, rep in sorted(fixes, reverse=True):
        text = text[:pos] + rep + text[pos + 1:]
    return text, len(fixes)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    dry = "--dry" in argv
    book, z = open_book(Path(argv[1]))
    name = "".join(c if c.isalnum() or c in "-_" else "_"
                   for c in (book.title or Path(argv[1]).stem))[:40]
    kb = Path("kb") / name
    gl = gl_load(kb)
    notes = to_prompt(gl)
    style = kb / "style.md"
    if style.exists():
        notes += "\n\n【风格指南】\n" + style.read_text(encoding="utf-8")[:1200]
    cfg = load_config()
    rev = Path("work") / name / "rev"
    docs = {it.full: it for it in book.docs}

    punct_n = retrans = fixed_ok = 0
    for f in sorted(rev.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        href = data["href"]
        item = docs.get(href)
        if item is None:
            continue
        doc = extract_doc(href, read_doc(z, item))
        units = data["units"]
        for b in doc.blocks:
            text = units.get(b.uid)
            if not text:
                continue
            new, n = fix_punct(text)
            if n:
                punct_n += n
                text = new
            bad = gl_check(gl, b.source, text)
            kana = len(KANA.findall(text))
            if bad or kana > 3 or looks_japanese(text):
                retrans += 1
                try:
                    got = translate_batch(cfg, book.title, book.creator, [b],
                                          notes=notes, allow_fallback=False)
                    cand = got.get(b.uid)
                except Exception:  # noqa: BLE001
                    cand = None
                if cand and not gl_check(gl, b.source, cand) \
                        and len(KANA.findall(cand)) <= kana \
                        and not looks_japanese(cand):
                    text = cand
                    fixed_ok += 1
            units[b.uid] = text
        if not dry:
            save_json(f, data)
    print(f"{book.title[:24]}: 标点修正 {punct_n} 处 · 重译 {retrans} 段 · "
          f"改善 {fixed_ok} 段" + ("（dry-run）" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
