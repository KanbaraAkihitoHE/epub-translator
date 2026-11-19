# 贡献指南

## 开发环境

```bash
pip install -r requirements.txt
cp config/local.example.json config/local.json   # 填入自己的 key
python tools/doctor.py
```

## 不要提交的东西

`.gitignore` 已经覆盖，但仍请注意：

- `config/local.json`（API key）
- `assets/samples/*.epub`（书籍版权）
- `kb/`、`work/`、`out/`、`reports/`、`eval/*.jsonl`（书籍衍生内容）

提交前自查：

```bash
git status --short
```

## 改动原则

1. **结构保真优先**：任何改动都要保证 `verify_epub.py` 结构同构为 0 差异；
2. **术语只有一个权威**：新增产出文字的链路必须经过 `NameResolver`；
3. **失败可恢复**：写文件用 `store.save_json`，长任务要能断点续跑；
4. **有测试**：`python -m unittest discover -s tests` 必须通过。

## 提交信息

用一句话说清"改了什么、为什么"，中英文均可。
