"""P4 润色：只改中文表达，不动事实。

用法：
    python tools/polish.py <epub> [doc_index]     # 指定篇，或全部
产物：原地更新 work/<slug>/rev/*.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.store import save_json  # noqa: E402
from epubtr.epub import open_book, read_doc       # noqa: E402
from epubtr.ir import extract_doc                  # noqa: E402
from epubtr.llm import chat, load_config          # noqa: E402
from epubtr.render import MarkerError, tokenize, validate  # noqa: E402

SYSTEM = """你是中文编辑，负责润色日本小说的译文。

铁律：
1. 只改**表达**：语序、用词、冗余、翻译腔。不改事实、不增删信息、不加解释。
2. 保留全部内联标记（⟦i3⟧ ⟦/i3⟧ ⟦v3⟧），数量与顺序不变。
3. 人名、术语、数字、时间一律不动。
4. 原文含糊处（没说清是谁、是什么）保持含糊，不要"顺"明白。
5. 输出 JSON：{"units":[{"id":"...","text":"..."}]}
"""


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, z = open_book(Path(argv[1]))
    name = slug(book.title or Path(argv[1]).stem)
    work = Path("work") / name
    rev = work / "rev"
    cfg = load_config()
    only = int(argv[2]) if len(argv) > 2 else None

    total, changed = 0, 0
    for idx, item in enumerate(book.docs):
        if only is not None and idx != only:
            continue
        f = rev / f"{idx:03d}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        units = data["units"]
        issues = data.get("issues", [])
        targets = {i["id"] for i in issues if i.get("type") in ("style", "fluency")}
        targets &= set(units)
        if not targets:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        blocks = [b for b in doc.blocks if b.uid in targets]
        print(f"{item.full}: 待润色 {len(blocks)} 段", flush=True)
        for i in range(0, len(blocks), 6):
            group = blocks[i:i + 6]
            payload = json.dumps({"units": [
                {"id": b.uid, "ja": b.source, "zh": units[b.uid]} for b in group]},
                ensure_ascii=False, indent=1)
            try:
                r = chat(cfg, SYSTEM, payload, temperature=0.3, max_tokens=4096,
                         json_mode=True)
                out = json.loads(r.text).get("units", [])
            except Exception as e:  # noqa: BLE001
                print("  跳过:", e)
                continue
            for it in out:
                uid, text = it.get("id"), it.get("text")
                b = next((x for x in group if x.uid == uid), None)
                if b is None or not isinstance(text, str):
                    continue
                try:
                    validate(tokenize(text), b.spans)
                except MarkerError:
                    continue
                total += 1
                if text != units[uid]:
                    units[uid] = text
                    changed += 1
        save_json(f, data)
        print(f"  完成，累计改写 {changed}/{total}", flush=True)

    print(f"润色完成：处理 {total} 段，改写 {changed} 段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
