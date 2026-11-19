"""把预读得到的别名/绰号写进术语表。

用法：python tools/alias_glossary.py <epub>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book                   # noqa: E402
from epubtr.llm import chat, load_config           # noqa: E402

SYSTEM = """你在为日本小说的人物绰号定中文译名。

给你人物（日文全名、中文全名、日文绰号）。要求：
- 绰号译名要与中文全名同源，读者能看出是同一个人；
- 音译或意译都可以，但要自然、好记；
- 不要和全名完全相同（绰号要有区分度）。

输出 JSON：{"aliases":[{"ja":"绰号","zh":"中文绰号"}]}
"""


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    book, _ = open_book(Path(argv[1]))
    name = slug(book.title or Path(argv[1]).stem)
    kb = Path("kb") / name
    bible = json.loads((kb / "auto_bible.json").read_text(encoding="utf-8"))
    gl = json.loads((kb / "glossary.json").read_text(encoding="utf-8"))
    have = {c["ja"] for c in gl["characters"]}

    chars = []
    for c in bible.get("characters", []):
        aliases = [a for a in c.get("aliases", [])
                   if len(a) >= 2 and a != c.get("name_ja") and a not in have]
        if aliases:
            chars.append({"ja": c.get("name_ja"), "zh": c.get("name_ja"),
                          "aliases": aliases})
    if not chars:
        print("没有待处理的绰号")
        return 0

    zh_of = {c["ja"]: c["zh"] for c in gl["characters"]}
    for c in chars:
        c["zh"] = zh_of.get(c["ja"], c["ja"])

    payload = json.dumps({"characters": chars}, ensure_ascii=False, indent=1)
    r = chat(load_config(), SYSTEM, payload, temperature=0.3, max_tokens=2000,
             json_mode=True)
    data = json.loads(r.text)
    added = 0
    for it in data.get("aliases", []):
        ja, zh = it.get("ja", ""), it.get("zh", "")
        if ja and zh and ja not in have:
            gl["characters"].append({"ja": ja, "zh": zh, "note": "绰号"})
            have.add(ja)
            added += 1
            print(f"  {ja} -> {zh}")
    (kb / "glossary.json").write_text(
        json.dumps(gl, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"加入 {added} 个绰号，术语表现有 {len(gl['characters'])} 人物")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
