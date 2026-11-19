# 实验性脚本

这些是一次性验证或诊断工具，不保证随主流程演进保持可用。

| 脚本 | 用途 |
|---|---|
| `smoke_api.py` | 测试 API 通不通 |
| `diag.py` | 定位结构 diff 的第一个位置 |
| `risk_report.py` | 验证"风险分级"假设（结论：无效，已弃用） |
| `ab_memory.py` | 三层记忆 A/B（结论：单段收益很小） |
| `ab_polish.py` | 润色前后评分对照 |
| `timeline_check.py` | 时间线矛盾检测（结论：不够可靠） |
| `backfill_hashes.py` | 为旧译文补写原文哈希（迁移用） |

运行方式与主工具相同，从仓库根目录执行：

```bash
python tools/experiments/smoke_api.py
```
