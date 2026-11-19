"""术语的唯一权威：所有产出文字的链路都走这里。

设计（见 roadmap P0-5）：
- 术语表里一条记录：ja（原文）、zh（定名）、variants（已知错误写法）；
- 翻译提示词、标题翻译、人物页注记、术语统一，全部调用同一个 resolve/normalize；
- 任何链路都不允许自己发明译名。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MARK = re.compile(r"⟦[^⟧]*⟧")


class NameResolver:
    def __init__(self, glossary: dict):
        self.characters = glossary.get("characters", [])
        self.terms = glossary.get("terms", [])
        self._canon: dict[str, str] = {}
        self._variants: list[tuple[str, str]] = []
        for group in ("characters", "terms"):
            for it in glossary.get(group, []):
                ja, zh = it.get("ja", ""), it.get("zh", "")
                if ja and zh:
                    self._canon[ja] = zh
                for v in it.get("variants", []) or []:
                    if v and zh and v != zh:
                        self._variants.append((v, zh))
        # 长变体优先，避免「阿边新」被「阿边」先替换
        self._variants.sort(key=lambda x: len(x[0]), reverse=True)

    @classmethod
    def load(cls, kb_dir: Path) -> "NameResolver":
        p = kb_dir / "glossary.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return cls(data)

    # ---- 查询 ----
    def canonical(self, ja: str) -> str | None:
        return self._canon.get(ja)

    def normalize(self, text: str) -> str:
        """把已知错误写法替换成定名（不碰内联标记）。"""
        if not text or not self._variants:
            return text
        # 标记内部只有数字/字母，正常不会命中；保险起见先分离
        parts = re.split(r"(⟦[^⟧]*⟧)", text)
        for i, p in enumerate(parts):
            if p.startswith("⟦"):
                continue
            for bad, good in self._variants:
                if bad in p:
                    p = p.replace(bad, good)
            parts[i] = p
        return "".join(parts)

    def hits(self, text: str) -> list[str]:
        return [bad for bad, _ in self._variants if bad in MARK.sub("", text)]

    def prompt(self) -> str:
        """给翻译提示词用的术语段。"""
        lines = []
        if self.characters:
            lines.append("【人物译名（全书统一）】")
            lines += [f"- {c['ja']} → {c['zh']}" for c in self.characters]
        if self.terms:
            lines.append("【术语与作品名（必须使用给定译法）】")
            for t in self.terms:
                note = f"（{t['note']}）" if t.get("note") else ""
                lines.append(f"- {t['ja']} → {t['zh']}{note}")
        return "\n".join(lines)


def load_for(book_title: str) -> NameResolver:
    from .paths import ROOT, slug
    return NameResolver.load(ROOT / "kb" / slug(book_title))
