"""译文审计：逐段比对日文原文与中文译文，区分 OCR 问题与翻译问题。

用法：
    python tools/audit_mismatch.py <epub> [--apply] [--sample 20]

--apply：对"译文问题"的段落自动重译，并用同一审计复核，通过才替换。
报告写入 reports/<书名>/mismatch.md。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc          # noqa: E402
from epubtr.glossary import load as gl_load, to_prompt  # noqa: E402
from epubtr.ir import extract_doc                     # noqa: E402
from epubtr.llm import chat, load_config               # noqa: E402
from epubtr.parallel import run as parallel_run        # noqa: E402
from epubtr.paths import report as report_path         # noqa: E402
from epubtr.store import save_json                     # noqa: E402
from epubtr.translate import translate_batch           # noqa: E402

JUDGE = """判断中文译文是否准确传达日文原文的意思（看事实、指代、语气，不必逐字）。
若不一致，判断原因：
- "ocr"：日文原文有明显 OCR 错误（错字、缺字、不成词），导致无法准确翻译；
- "translation"：日文可读，但译文误译、漏译或添加。
只输出 JSON：{"match": true/false, "cause": "ocr"|"translation"|"", "reason": "一句话"}"""


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def judge(cfg, ja: str, zh: str) -> dict:
    r = chat(cfg, JUDGE, f"【日文】\n{ja}\n\n【中文】\n{zh}",
             temperature=0.0, max_tokens=200, json_mode=True)
    try:
        return json.loads(r.text)
    except json.JSONDecodeError:
        return {"match": True, "cause": "", "reason": "解析失败"}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src_path = Path(argv[1])
    apply_ = "--apply" in argv
    sample = int(argv[argv.index("--sample") + 1]) if "--sample" in argv else 0
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else []

    book, z = open_book(src_path)
    name = slug(book.title or src_path.stem)
    work = Path("work") / name
    rev = work / "rev"
    cfg = load_config()
    kb = Path("kb") / name
    notes = to_prompt(gl_load(kb)) if (kb / "glossary.json").exists() else ""

    docs = {it.full: it for it in book.docs}
    blocks = {}
    units = {}
    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        item = docs.get(data["href"])
        if item is None:
            continue
        doc = extract_doc(data["href"], read_doc(z, item))
        for b in doc.blocks:
            blocks[b.uid] = (f, b, data["href"])
        use = rev / f.name if (rev / f.name).exists() else f
        units.update(json.loads(use.read_text(encoding="utf-8")).get("units", {}))

    uids = [u for u in blocks if units.get(u)]
    if only:
        uids = [u for u in uids if u in only]
    if sample:
        uids = uids[:sample]
    print(f"待审计 {len(uids)} 段")

    def audit(uid: str) -> dict:
        return {"uid": uid, **judge(cfg, blocks[uid][1].source, units[uid])}

    results = parallel_run(audit, uids)
    bad = [r for r in results if not r.get("match")]
    ocr = [r for r in bad if r.get("cause") == "ocr"]
    tr = [r for r in bad if r.get("cause") != "ocr"]
    print(f"不一致 {len(bad)}：OCR {len(ocr)}，译文 {len(tr)}")

    fixed = 0
    if apply_ and tr:
        def repair(r: dict) -> dict:
            uid = r["uid"]
            f, b, href = blocks[uid]
            try:
                out = translate_batch(cfg, book.title, book.creator, [b],
                                      notes=notes + f"\n\n【特别注意】{r['reason']}",
                                      allow_fallback=False)
            except Exception:  # noqa: BLE001
                return r
            text = out.get(uid, "").strip()
            if not text or text == units[uid]:
                return r
            recheck = judge(cfg, b.source, text)
            if recheck.get("match"):
                units[uid] = text
                path = rev / f.name if (rev / f.name).exists() else f
                data = json.loads(path.read_text(encoding="utf-8"))
                data.setdefault("units", {})[uid] = text
                save_json(path, data)
                return {**r, "fixed": True, "new": text[:40]}
            return r

        repaired = parallel_run(repair, tr)
        fixed = sum(1 for r in repaired if r.get("fixed"))
        print(f"自动重译并复核通过 {fixed}/{len(tr)}")
        tr = [r for r in repaired if not r.get("fixed")]

    lines = [f"# 译文审计：{book.title}", "",
             f"- 审计 {len(uids)} 段，不一致 {len(bad)} 段",
             f"- OCR 导致 {len(ocr)} 段，译文导致 {len(tr)} 段（本次自动修复 {fixed}）", ""]
    for r in ocr:
        lines.append(f"- [OCR] `{r['uid']}` {r.get('reason', '')}")
    for r in tr:
        lines.append(f"- [译文] `{r['uid']}` {r.get('reason', '')}")
    report_path(name, "mismatch.md").write_text("\n".join(lines), encoding="utf-8")
    print("报告：reports/%s/mismatch.md" % name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
