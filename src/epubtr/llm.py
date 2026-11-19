"""OpenAI 兼容的 LLM 客户端（只依赖标准库）。

设计要点：
- key 只从配置文件读，绝不打印、绝不写进日志；
- 429/5xx 退避重试，其余错误直接抛出；
- 返回 token 用量，便于成本核算。
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .paths import ROOT

CACHE_DIR = ROOT / "cache"
CACHE_ENABLED = os.environ.get("EPUBTR_NO_CACHE") != "1"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    timeout: int = 120
    max_retries: int = 3


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False


def _cache_key(cfg: LLMConfig, system: str, user: str,
               temperature: float, max_tokens: int, json_mode: bool) -> str:
    h = hashlib.sha256()
    for part in (cfg.base_url, cfg.model, system, user,
                 str(temperature), str(max_tokens), str(json_mode)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _cache_get(key: str) -> dict | None:
    if not CACHE_ENABLED:
        return None
    p = CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _cache_put(key: str, data: dict) -> None:
    if not CACHE_ENABLED:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_config(path: str | Path = "config/local.json") -> LLMConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    p = data["provider"]
    return LLMConfig(
        base_url=p["base_url"].rstrip("/"),
        model=p["model"],
        api_key=p["api_key"],
        timeout=p.get("timeout", 120),
        max_retries=p.get("max_retries", 3),
    )


def _post(url: str, payload: bytes, cfg: LLMConfig) -> dict:
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_watchdog(url: str, payload: bytes, cfg: LLMConfig) -> dict:
    """urllib 的 timeout 只管单次 socket 操作，死连接会永久阻塞，这里加硬超时。"""
    box: dict = {}

    def run() -> None:
        try:
            box["data"] = _post(url, payload, cfg)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=cfg.timeout + 20)
    if t.is_alive():
        raise LLMError(f"调用看门狗超时（>{cfg.timeout + 20}s）")
    if "err" in box:
        raise box["err"]
    return box["data"]


def chat(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> LLMResponse:
    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = f"{cfg.base_url}/chat/completions"
    last_err: Exception | None = None

    key = _cache_key(cfg, system, user, temperature, max_tokens, json_mode)
    hit = _cache_get(key)
    if hit:
        return LLMResponse(text=hit["text"], cached=True)

    for attempt in range(cfg.max_retries):
        t0 = time.time()
        try:
            data = _post_watchdog(url, payload, cfg)
            latency = int((time.time() - t0) * 1000)
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            usage = data.get("usage") or {}
            text = text.strip()
            _cache_put(key, {"text": text,
                             "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                             "completion_tokens": int(usage.get("completion_tokens", 0))})
            return LLMResponse(
                text=text,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=latency,
            )
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last_err = LLMError(f"HTTP {e.code}: {detail}")
            if e.code in (429, 500, 502, 503, 504) and attempt < cfg.max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise last_err from e
        except (urllib.error.URLError, socket.timeout, TimeoutError, LLMError,
                http.client.HTTPException, ConnectionError, OSError) as e:
            last_err = LLMError(f"网络错误: {e}")
            if attempt < cfg.max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise last_err from e
    raise last_err or LLMError("未知错误")
