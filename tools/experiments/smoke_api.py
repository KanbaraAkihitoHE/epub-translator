"""API 通路冒烟测试：不打印 key。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from epubtr.llm import LLMError, chat, load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    print(f"endpoint = {cfg.base_url}")
    print(f"model    = {cfg.model}")
    print(f"key      = {cfg.api_key[:6]}…{cfg.api_key[-4:]}（已脱敏）")
    t0 = time.time()
    try:
        r = chat(
            cfg,
            system="你是精通日语的翻译，只输出译文，不要解释。",
            user="把这句话译成简体中文：雨が降っていた。",
            max_tokens=100,
        )
    except LLMError as e:
        print(f"[FAIL] {e}")
        return 1
    print(f"[OK] {time.time() - t0:.1f}s  tokens in/out = "
          f"{r.prompt_tokens}/{r.completion_tokens}")
    print(f"译文：{r.text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
