"""全书预读（P0）：分章摘要 → 汇总成设定集（人物/术语/风险）。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .llm import LLMConfig, chat

MAP_SYSTEM = """你在读一本日本推理小说的一章，为后续翻译做准备。
请提炼：
1. summary：本章发生了什么（120 字以内，中文）
2. characters：本章出场的**日文原名**（只列人名，不要称谓）
3. terms：本章出现的专有名词（地名、组织、作品名、专业词），日文原文
4. notes：值得注意的文字游戏、方言、叙述手法、伏笔（没有就空数组）

只输出 JSON：{"summary":"...","characters":["..."],"terms":["..."],"notes":["..."]}
"""

REDUCE_SYSTEM = """你在整理一本日本推理小说的设定集，供翻译时保持全书一致。

根据各章摘要，输出：
{
 "synopsis": "全书梗概，200字以内",
 "characters": [
   {"name_ja":"日文原名","aliases":["别名/简称"],"gender":"male|female|hidden|unknown",
    "role":"身份/职业","register":"说话风格（如：丁宁、粗鲁、敬语多）","first":"首次出现的章节标题"}
 ],
 "terms": [{"ja":"日文","type":"person|place|org|work|term","zh_hint":"若有通行中文译名则填，否则留空"}],
 "risks": [{"type":"wordplay|dialect|narrative_trick|keigo_shift|name_reading","where":"章节","note":"一句话"}]
}

要求：
- 人物只收有名字的，最多 30 个；术语最多 40 个。
- 性别不明确就写 hidden（叙述性诡计常见）。
- 不要编造没出现过的名字；输出要紧凑，避免超长被截断。
- 只输出 JSON。
"""


@dataclass
class Bible:
    synopsis: str = ""
    characters: list[dict] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def digest(self, max_chars: int = 1200) -> str:
        """给翻译提示词用的压缩版。"""
        parts = [f"【梗概】{self.synopsis}"]
        if self.characters:
            names = "、".join(
                f"{c.get('name_ja','')}({c.get('role','')})" for c in self.characters[:20])
            parts.append(f"【人物】{names}")
        if self.risks:
            parts.append("【注意】" + "；".join(
                f"{r.get('type')}@{r.get('where','')}" for r in self.risks[:6]))
        return "\n".join(parts)[:max_chars]


def _chunks(text: str, size: int = 6000) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def _json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def build(cfg: LLMConfig, chapters: list[dict], progress=None) -> Bible:
    """chapters: [{"title": str, "text": str}]"""
    summaries = []
    for i, ch in enumerate(chapters, 1):
        pieces = _chunks(ch["text"])
        partials = []
        for piece in pieces:
            r = chat(cfg, MAP_SYSTEM,
                     f"章节标题：{ch['title']}\n\n正文：\n{piece}",
                     temperature=0.2, max_tokens=800, json_mode=True)
            try:
                partials.append(_json(r.text))
            except json.JSONDecodeError:
                continue
        if not partials:
            continue
        merged = {
            "title": ch["title"],
            "summary": " ".join(p.get("summary", "") for p in partials)[:300],
            "characters": sorted({c for p in partials for c in p.get("characters", [])}),
            "terms": sorted({t for p in partials for t in p.get("terms", [])}),
            "notes": sorted({n for p in partials for n in p.get("notes", [])}),
        }
        summaries.append(merged)
        if progress:
            progress(i, len(chapters))

    payload = json.dumps({"chapters": summaries}, ensure_ascii=False)
    data: dict = {}
    for attempt in range(2):
        prompt = payload[:60000]
        if attempt:
            prompt += "\n\n【注意】上一次输出不是合法 JSON（可能被截断）。" \
                      "请输出更紧凑的合法 JSON，人物不超过 30 个。"
        r = chat(cfg, REDUCE_SYSTEM, prompt, temperature=0.2,
                 max_tokens=8000, json_mode=True)
        try:
            data = _json(r.text)
            break
        except json.JSONDecodeError:
            if attempt == 1:
                raise
    return Bible(
        synopsis=data.get("synopsis", ""),
        characters=data.get("characters", []),
        terms=data.get("terms", []),
        risks=data.get("risks", []),
        chapters=summaries,
    )
