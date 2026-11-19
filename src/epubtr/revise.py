"""P2 自评 + P3 修订：只改问题段，改坏了就退回。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .glossary import check as gl_check
from .llm import LLMConfig, chat
from .model import Block
from .render import MarkerError, tokenize, validate

CRITIQUE_SYSTEM = """你是日译中的审校。给你日文原文和中文初稿，找出**必须修改**的问题。

按 MQM 分类：
- accuracy：误译、漏译、增译（最高优先级）
- terminology：术语/人名前后不一致
- style：语体不符、翻译腔过重
- fluency：中文不通顺、指代混乱

要求：
1. 只报有把握的问题，宁可少报；没有就返回空数组。
2. 不要因为"可以更好"就报，只报**错误或明显别扭**。
3. 注意：正文里保留的日文（字谜、谐音、专名）是有意为之，不算问题。
4. 输出 JSON：{"issues":[{"id":"段落id","type":"accuracy","severity":"major|minor","note":"一句话中文说明"}]}
"""

REVISE_SYSTEM = """你是日译中的译者，正在根据审校意见修改译文。

要求：
1. 只改被指出的问题；没提到的部分尽量保持原样。
2. 修订后的译文必须覆盖原文的**全部信息**，不得因为改写而丢掉细节、语气或歧义。
3. 不增译、不解释、不补充原文没有的信息。
4. 保留全部内联标记（⟦i3⟧、⟦/i3⟧、⟦v3⟧），数量、顺序、嵌套都不变。
5. 如果某个意见会导致译文变差或丢信息，宁可不改，保持原样。
6. 输出 JSON：{"units":[{"id":"...","text":"..."}]}
"""


def should_revise(issues: list[Issue]) -> list[Issue]:
    """只自动修硬错误；风格/流畅度问题留给人工。"""
    return [i for i in issues if i.type == "accuracy" and i.severity == "major"]


@dataclass
class Issue:
    uid: str
    type: str
    severity: str
    note: str


@dataclass
class ReviseStats:
    critique_calls: int = 0
    revise_calls: int = 0
    issues: int = 0
    revised: int = 0
    rejected: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    notes: list[str] = field(default_factory=list)


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


def critique(cfg: LLMConfig, blocks: list[Block], drafts: dict[str, str],
             stats: ReviseStats, notes: str = "") -> list[Issue]:
    payload = json.dumps({"units": [{"id": b.uid, "ja": b.source,
                                     "zh": drafts.get(b.uid, "")} for b in blocks]},
                         ensure_ascii=False, indent=1)
    prompt = (f"【术语】\n{notes}\n\n" if notes else "") + "【待审】\n" + payload
    r = chat(cfg, CRITIQUE_SYSTEM, prompt, temperature=0.1, max_tokens=2048,
             json_mode=True)
    stats.critique_calls += 1
    stats.prompt_tokens += r.prompt_tokens
    stats.completion_tokens += r.completion_tokens
    try:
        data = _json(r.text)
    except Exception:
        stats.notes.append(f"critique JSON 解析失败 @{blocks[0].uid}")
        return []
    ids = {b.uid for b in blocks}
    out = []
    for it in data.get("issues", []):
        uid = it.get("id", "")
        if uid in ids:
            out.append(Issue(uid=uid, type=str(it.get("type", "")),
                             severity=str(it.get("severity", "minor")),
                             note=str(it.get("note", ""))[:120]))
    stats.issues += len(out)
    return out


def revise(cfg: LLMConfig, blocks: list[Block], drafts: dict[str, str],
           issues: list[Issue], stats: ReviseStats, notes: str = "") -> dict[str, str]:
    by_id = {b.uid: b for b in blocks}
    payload = json.dumps({
        "issues": [{"id": i.uid, "type": i.type, "severity": i.severity, "note": i.note}
                   for i in issues],
        "units": [{"id": i.uid, "ja": by_id[i.uid].source,
                   "zh": drafts.get(i.uid, "")} for i in issues],
    }, ensure_ascii=False, indent=1)
    prompt = (f"【术语】\n{notes}\n\n" if notes else "") + "【审校意见】\n" + payload
    r = chat(cfg, REVISE_SYSTEM, prompt, temperature=0.2, max_tokens=4096,
             json_mode=True)
    stats.revise_calls += 1
    stats.prompt_tokens += r.prompt_tokens
    stats.completion_tokens += r.completion_tokens
    data = _json(r.text)
    out: dict[str, str] = {}
    for it in data.get("units", []):
        uid, text = it.get("id"), it.get("text")
        if uid not in by_id or not isinstance(text, str):
            continue
        b = by_id[uid]
        try:
            validate(tokenize(text), b.spans)
        except MarkerError:
            stats.rejected += 1
            continue
        out[uid] = text
    stats.revised += len(out)
    return out


VERIFY_SYSTEM = """你是日译中校对。给你日文原文、初稿译文、修订译文，判断这次修订是否可信。

只有同时满足以下条件才判 keep：
1. 修订确实修正了初稿的问题；
2. 没有引入新错误：误译、错字、生造词、把正确的地方改错、把含糊处说死。

只输出 JSON：{"decision":"keep" 或 "revert","reason":"一句话"}"""


def verify_change(cfg, source: str, draft: str, revised: str) -> tuple[bool, str]:
    """LLM 复核一次修订是否可信。"""
    prompt = f"【原文】\n{source}\n\n【初稿】\n{draft}\n\n【修订】\n{revised}"
    try:
        r = chat(cfg, VERIFY_SYSTEM, prompt, temperature=0.0,
                 max_tokens=200, json_mode=True)
        d = json.loads(r.text)
        return d.get("decision") == "keep", str(d.get("reason", ""))[:80]
    except Exception:  # noqa: BLE001
        return True, "复核失败，保留修订"
