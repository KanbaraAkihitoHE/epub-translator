"""单独翻译章节标题：意译优先、全书一致。

用法：python tools/translate_titles.py <epub>
产物：work/<slug>/titles.json  {"日文标题": "中文标题"}
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.store import save_json  # noqa: E402
from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.llm import chat, load_config          # noqa: E402
from epubtr.package import plain                  # noqa: E402

SYSTEM = """你在为一部日本推理小说拟定中文章节标题。
要求：
1. 习语、双关按**含义**译，不要逐字直译。宁可朴素，不要造出「先给眉毛抹上唾沫星子」这种字面句。
2. 编号保留：第一話 → 第一章，１ → 1，Ⅰ → Ⅰ。
3. 同一人物/地点/关键词，全书译法一致。
4. 确实无法传达的双关，可在标题后加「（译注：……）」，但正文标题尽量不超过 12 字。
5. 序章、尾声、解説之类的固定词按中文出版习惯处理（解说/后记）。
只输出 JSON：{"titles":[{"ja":"原文","zh":"译文"}]}
"""


def collect(path: Path) -> tuple[object, list[str]]:
    book, z = open_book(path)
    seen: dict[str, None] = {}
    # 目录标签
    for n in z.namelist():
        if n.endswith("nav.xhtml") or n.endswith(".ncx"):
            raw = z.read(n).decode("utf-8", "ignore")
            if n.endswith(".ncx"):
                labels = re.findall(r"<text>(.*?)</text>", raw, re.S)
            else:
                labels = re.findall(r"<a[^>]*>(.*?)</a>", raw, re.S)
            for lab in labels:
                t = plain(re.sub(r"<[^>]+>", "", lab))
                if t:
                    seen.setdefault(t, None)
    # 正文标题
    for it in book.docs:
        doc = extract_doc(it.full, read_doc(z, it))
        for b in doc.blocks:
            if b.kind == "heading":
                t = plain(b.source)
                if t:
                    seen.setdefault(t, None)
    z.close()
    return book, list(seen)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, titles = collect(src)
    print(f"{len(titles)} 个标题")
    cfg = load_config()
    prompt = (f"书名：{book.title}\n作者：{book.creator}\n\n"
              + json.dumps({"titles": titles}, ensure_ascii=False, indent=1))
    r = chat(cfg, SYSTEM, prompt, temperature=0.4, max_tokens=4096, json_mode=True)
    data = json.loads(r.text)
    mapping = {}
    for it in data.get("titles", []):
        ja, zh = it.get("ja", ""), it.get("zh", "")
        if ja and zh:
            mapping[ja] = zh
    # 标题也必须走术语表，不能自己造名
    from epubtr.names import load_for
    res = load_for(book.title or src.stem)
    mapping = {ja: res.normalize(zh) for ja, zh in mapping.items()}
    work = Path("work") / "".join(
        c if c.isalnum() or c in "-_" else "_" for c in (book.title or src.stem))[:40]
    work.mkdir(parents=True, exist_ok=True)
    save_json(work / "titles.json", mapping)
    for ja, zh in mapping.items():
        print(f"  {ja}  ->  {zh}")
    print(f"写入 {work / 'titles.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
