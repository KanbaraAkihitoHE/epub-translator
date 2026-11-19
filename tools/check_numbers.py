"""数字/日期一致性检查：抓漏译的数字、增译的数字、前后矛盾的数值。

用法：python tools/check_numbers.py <epub>
产物：docs/numbers-report.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubtr.epub import open_book, read_doc      # noqa: E402
from epubtr.ir import extract_doc                 # noqa: E402
from epubtr.package import plain                  # noqa: E402

KANJI = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
         "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
         "十": 10, "百": 100, "千": 1000, "万": 10000}
DIGITS = {chr(0xFF10 + i): str(i) for i in range(10)}

# 单位 → 语义类别（跨语言对齐）
UNITS = {
    "年": "year", "月": "month", "日": "day", "号": "day",
    "時": "hour", "时": "hour", "点": "hour", "點": "hour",
    "分": "minute", "秒": "second",
    "歳": "age", "岁": "age", "才": "age",
    "人": "people", "名": "people", "位": "people",
    "階": "floor", "层": "floor", "樓": "floor", "楼": "floor",
    "回": "times", "度": "times", "次": "times",
    "円": "money", "元": "money", "日元": "money",
    "ページ": "page", "页": "page", "頁": "page",
    "本": "count", "枚": "count", "個": "count", "个": "count",
    "台": "count", "匹": "count", "件": "count",
}
NUM_RE = re.compile(r"[0-9０-９]+|[一二三四五六七八九十百千万〇零两兩]+")


def parse_num(s: str) -> int | None:
    s = "".join(DIGITS.get(c, c) for c in s)
    if s.isdigit():
        return int(s)
    total, section, last = 0, 0, 0
    for c in s:
        v = KANJI.get(c)
        if v is None:
            return None
        if v < 10:
            last = v
        elif v == 10000:
            section = (section + last) * v
            total += section
            section, last = 0, 0
        else:
            section += (last or 1) * v
            last = 0
    return total + section + last


def facts(text: str) -> Counter:
    """抽出带单位/序数的数字（只比较数值，避免中日量词错配）。"""
    out: Counter = Counter()
    for m in NUM_RE.finditer(text):
        val = parse_num(m.group(0))
        if val is None or val <= 1 or val > 100000:
            continue
        tail = text[m.end():m.end() + 3]
        head = text[max(0, m.start() - 1):m.start()]
        ordinal = head.endswith("第") or tail.startswith(
            ("章", "話", "话", "節", "节", "学期"))
        if ordinal or any(tail.startswith(u) for u in UNITS) or tail.startswith("時間"):
            out[val] += 1
    # 假名数词（ひとり/ふたり）在中译里常变成数字
    for w, v in {"ふたり": 2, "みっつ": 3, "よっつ": 4, "いつつ": 5,
                 "むっつ": 6, "ななつ": 7, "やっつ": 8, "ここのつ": 9,
                 "とお": 10}.items():
        if w in text:
            out[v] += 1
    return out


def slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:40]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    book, z = open_book(src)
    name = slug(book.title or src.stem)
    work = Path("work") / name
    rev = work / "rev"
    issues, timeline = [], []

    for f in sorted(work.glob("*.json")):
        if f.name == "titles.json":
            continue
        use = rev / f.name if (rev / f.name).exists() else f
        data = json.loads(use.read_text(encoding="utf-8"))
        item = next((i for i in book.docs if i.full == data["href"]), None)
        if item is None:
            continue
        doc = extract_doc(item.full, read_doc(z, item))
        for b in doc.blocks:
            ja = facts(plain(b.source))
            zh = facts(data["units"].get(b.uid, ""))
            if not ja and not zh:
                continue
            missing = ja - zh
            extra = zh - ja
            if missing or extra:
                issues.append({"doc": item.full, "uid": b.uid,
                               "ja": plain(b.source)[:90],
                               "zh": data["units"].get(b.uid, "")[:90],
                               "missing": missing, "extra": extra})
            for val, _ in ja.items():
                timeline.append((item.full, b.uid, "value", val))

    lines = [f"# 数字/日期检查：{book.title}", "",
             f"- 全书 {len(timeline)} 处时间类数值", "",
             "## 数值不一致", ""]
    if issues:
        for it in issues[:60]:
            miss = "、".join(str(v) for v in it["missing"].elements())
            extra = "、".join(str(v) for v in it["extra"].elements())
            lines += [f"### {it['doc']} · {it['uid']}",
                      f"- 日：{it['ja']}", f"- 中：{it['zh']}",
                      f"- 缺：{miss or '—'}　多：{extra or '—'}", ""]
    else:
        lines += ["未发现数值不一致。", ""]

    lines += ["## 时间线（按出现顺序）", ""]
    cls_zh = {"year": "年", "month": "月", "day": "日", "hour": "时", "minute": "分"}
    for doc, uid, cls, val in timeline[:80]:
        lines.append(f"- {doc.split('/')[-1]} · {uid}：{val}{cls_zh.get(cls, cls)}")

    from epubtr.paths import report as report_path
    report_path(name, "numbers.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"数值不一致 {len(issues)} 段 · 时间线 {len(timeline)} 处")
    print("写入 docs/numbers-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
