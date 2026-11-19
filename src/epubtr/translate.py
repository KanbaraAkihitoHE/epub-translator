"""翻译层 v1：块级批译 + 结构化输出 + 标记校验 + 降级。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha1

from .llm import LLMConfig, LLMError, chat
from .model import Block
from .render import MarkerError, tokenize, validate


def src_hash(block: Block) -> str:
    """译文块对应的原文指纹，用于重建时发现 IR 变更。"""
    return sha1(block.source.encode("utf-8")).hexdigest()[:16]

SYSTEM = """你是一位资深的日文小说译者，正在把一本日本推理小说译成简体中文。

【铁律】
1. 忠实优先：不增译、不解释、不补充原文没有的信息。原文故意含糊的地方保持含糊。
2. 只输出译文，不写译者注（除非原文本身有注）。
3. 保留全部内联标记：形如 ⟦i3⟧ 与 ⟦/i3⟧ 的成对标记、⟦v3⟧ 的单标记。
   标记的数量、顺序、嵌套关系必须与原文完全一致；标记之间的文字要翻译。
   绝对不要翻译、删除、复制或改写标记本身。
4. 一个 id 对应一段译文；不要合并或拆分 id。
5. 输出必须是 JSON：{"units":[{"id":"...","text":"..."}]}，不要输出任何其他内容。

【语体】
- 简体中文，大众出版物语体，通顺克制，避免翻译腔。
- 叙述与对话分开处理：对话要像中文里的人在说话。
- **保留叙述者的口癖与语气**：`だぜ`、`ね`、`です`、`さ` 这类口吻用中文语气词与句式体现，
  但不要每句都加，整体自然即可。
- 标点：日文「」保留；「、」在句中作逗号时改为「，」；「！？」归一为「？」或「！」。
- 人名用日文汉字对应的简体字（御手洗潔 → 御手洗洁）。

【专名与译注】
- 真实存在的作品、作者、地名，**优先使用中文通行译名**：アクロイド殺害事件 → 《罗杰疑案》，
  クリスティ → 阿加莎·克里斯蒂。不确定时保留原文，不要生造译名。
- 双关、谐音、文字游戏无法在中文里复现时，在句末加简短译注：
  「（译注：原文谐音，兼有……之意）」，一条不超过 25 字。
- **译注不得透露后文情节**；拿不准就不加注。
"""


@dataclass
class BatchStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cache_hits: int = 0
    failures: list[str] = field(default_factory=list)


def _book_header(title: str, author: str) -> str:
    return f"【作品】{title}\n【作者】{author}\n【类型】日本推理小说\n"


def _render_units(blocks: list[Block]) -> str:
    return json.dumps(
        {"units": [{"id": b.uid, "source": b.source} for b in blocks]},
        ensure_ascii=False, indent=1)


def build_user_prompt(
    title: str,
    author: str,
    blocks: list[Block],
    *,
    before: str = "",
    after: str = "",
    notes: str = "",
) -> str:
    parts = [_book_header(title, author)]
    if notes:
        parts.append(f"【术语与人物】\n{notes}\n")
    if before:
        parts.append(f"【上文（仅供理解，不要翻译）】\n{before}\n")
    parts.append("【待译段落】\n" + _render_units(blocks))
    if after:
        parts.append(f"\n【下文（仅供理解，不要翻译）】\n{after}")
    return "\n".join(parts)


def _parse_json(text: str) -> dict:
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


def _check_partial(blocks: list[Block], data: dict) -> tuple[dict[str, str], dict[str, str]]:
    """逐段校验，返回（通过, {uid: 错误}）。缺段也算失败。"""
    units = data.get("units")
    if not isinstance(units, list):
        raise ValueError("缺少 units")
    raw: dict[str, str] = {}
    for u in units:
        uid, text = u.get("id"), u.get("text")
        if isinstance(uid, str) and isinstance(text, str):
            raw[uid] = text
    good: dict[str, str] = {}
    bad: dict[str, str] = {}
    for b in blocks:
        t = raw.get(b.uid)
        if t is None:
            bad[b.uid] = "缺段"
            continue
        try:
            validate(tokenize(t), b.spans)
        except MarkerError as e:
            bad[b.uid] = str(e)
            continue
        good[b.uid] = t
    return good, bad


def translate_batch(
    cfg: LLMConfig,
    title: str,
    author: str,
    blocks: list[Block],
    *,
    before: str = "",
    after: str = "",
    notes: str = "",
    stats: BatchStats | None = None,
    temperature: float = 0.3,
    allow_fallback: bool = True,
) -> dict[str, str]:
    stats = stats or BatchStats()
    result: dict[str, str] = {}
    pending = blocks
    error_hint = ""

    for attempt in range(2):
        if not pending:
            break
        prompt = build_user_prompt(title, author, pending, before=before,
                                   after=after, notes=notes) + error_hint
        r = chat(cfg, SYSTEM, prompt, temperature=temperature, json_mode=True,
                 max_tokens=8192)
        stats.calls += 1
        stats.prompt_tokens += r.prompt_tokens
        stats.completion_tokens += r.completion_tokens
        if r.cached:
            stats.cache_hits += 1
        try:
            good, bad = _check_partial(pending, _parse_json(r.text))
        except (ValueError, json.JSONDecodeError) as e:
            error_hint = f"\n\n【上一次输出无法解析】{e}。请只输出合法 JSON。"
            continue
        result.update(good)
        if not bad:
            return result
        pending = [b for b in pending if b.uid in bad]
        detail = "；".join(f"{u}: {m}" for u, m in list(bad.items())[:4])
        error_hint = (f"\n\n【上一次这些段有问题】{detail}。"
                      "请重新输出这些段：内联标记必须逐字保留，数量与顺序不变。")

    if pending and allow_fallback:
        for b in pending:
            stats.failures.append(f"{b.uid}: 标记/格式失败")
            try:
                got = translate_batch(cfg, title, author, [b], before=before,
                                      after=after, notes=notes, stats=stats,
                                      allow_fallback=False)
            except Exception:  # noqa: BLE001
                got = {}
            result.update(got or {b.uid: b.source})
    return result


def translate_doc(
    cfg: LLMConfig,
    title: str,
    author: str,
    blocks: list[Block],
    *,
    batch_size: int = 6,
    window: int = 2,
    notes: str = "",
    progress=None,
    max_workers: int | None = None,
) -> tuple[dict[str, str], BatchStats]:
    from .parallel import LOCK, run as parallel_run, workers as worker_count

    stats = BatchStats()
    jobs = []
    for i in range(0, len(blocks), batch_size):
        group = blocks[i:i + batch_size]
        before = "\n".join(b.source for b in blocks[max(0, i - window):i])
        after = "\n".join(b.source for b in blocks[i + batch_size:i + batch_size + window])
        jobs.append((group, before, after))

    def work(job) -> tuple[list[Block], dict[str, str], BatchStats]:
        group, before, after = job
        local = BatchStats()
        out = translate_batch(cfg, title, author, group, before=before,
                              after=after, notes=notes, stats=local)
        return group, out, local

    n = max_workers or worker_count()
    print(f"  并发 {n} 路，{len(jobs)} 个批次", flush=True)
    result: dict[str, str] = {}
    done = 0
    for group, out, local in parallel_run(work, jobs, n):
        result.update(out)
        with LOCK:
            stats.prompt_tokens += local.prompt_tokens
            stats.completion_tokens += local.completion_tokens
            stats.calls += local.calls
            stats.cache_hits += local.cache_hits
            stats.failures.extend(local.failures)
            done += len(group)
            if progress:
                progress(min(done, len(blocks)), len(blocks))
    return result, stats
