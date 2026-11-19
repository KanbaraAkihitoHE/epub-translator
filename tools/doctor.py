"""环境自检：依赖、配置、目录、密钥是否就位。

用法：python tools/doctor.py
"""

from __future__ import annotations

import importlib
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OK, BAD, WARN = "[OK]  ", "[FAIL]", "[WARN]"


def main() -> int:
    problems = 0
    print(f"Python {sys.version.split()[0]}")

    for mod in ("lxml", "fontTools"):
        try:
            importlib.import_module(mod)
            print(OK, f"依赖 {mod}")
        except ImportError:
            print(BAD, f"缺少依赖 {mod}（pip install {mod}）")
            problems += 1

    cfg = ROOT / "config" / "local.json"
    if not cfg.exists():
        print(BAD, "缺少 config/local.json（可从 local.example.json 复制）")
        problems += 1
    else:
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            p = data.get("provider", {})
            key = p.get("api_key", "")
            if not key or key.startswith("sk-xxx"):
                print(BAD, "config/local.json 里没有可用的 api_key")
                problems += 1
            else:
                print(OK, f"配置：{p.get('base_url')} / {p.get('model')} / "
                          f"key {key[:5]}…{key[-4:]}")
            font = Path(data.get("font", {}).get("path", ""))
            print(OK if font.exists() else WARN,
                  f"字体：{font}" + ("" if font.exists() else "（不存在，将不内嵌）"))
        except json.JSONDecodeError as e:
            print(BAD, f"config/local.json 不是合法 JSON：{e}")
            problems += 1

    for d in ("assets/samples", "work", "out", "reports", "kb", "cache"):
        p = ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            print(WARN, f"目录 {d} 不存在，已创建")
        else:
            print(OK, f"目录 {d}")

    books = list((ROOT / "assets" / "samples").glob("*.epub"))
    print(OK if books else WARN, f"样书 {len(books)} 本")

    with socket.socket() as s:
        free = s.connect_ex(("127.0.0.1", 8765)) != 0
    print(OK if free else WARN,
          "端口 8765 " + ("可用" if free else "已被占用（审校服务可能已在运行）"))

    print()
    print("自检通过" if problems == 0 else f"有 {problems} 个问题需要处理")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
