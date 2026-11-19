# epub-translator · 日文 EPUB 翻译工坊

把日文小说 EPUB 转成高质量中文 EPUB 的流水线。

不是"整章丢给模型"的翻译器，而是一条**译文生产线**：

- **结构零破坏**——原文串区间替换，除文本外逐字节不变（4 本书验证，0 篇差异）
- **术语一致**——人名/专名只有一个权威，正文、标题、目录、注记统一
- **诡计保护**——字谜、谐音、叙述性诡计不"本地化"，该含糊的地方保持含糊
- **可人工审校**——本地网页界面，问题清单点进去就能改，改完一键重新打包

## 它解决什么问题

直接让 LLM 翻整本书，结果通常是"每句都对、整本书是垃圾"：

| 症状 | 原因 | 本项目的做法 |
|---|---|---|
| 前后人名不一致 | 没有跨章记忆 | 预读生成人物表 + 术语表，全链路注入 |
| 注释/插图/目录全坏 | 粗暴切块再重建 | 中间表示 + 原文串替换，只换文字 |
| 该含糊的地方被说死 | 模型"帮读者理解" | 风险标注 + 禁止增译的硬约束 |
| 改一句 prompt 全部重翻 | 没有缓存 | 内容哈希缓存，命中率极高 |
| 不知道哪里译错了 | 没有质检 | 结构/术语/标点/假名/一致性五类检查 |

## 快速开始

```bash
# 1. 依赖（Python 3.11+）
pip install -r requirements.txt

# 2. 配置：复制模板，填入你自己的 API key
cp config/local.example.json config/local.json

# 3. 自检
python tools/doctor.py

# 4. 放书（只支持无 DRM 的 EPUB）
#    assets/samples/你的书.epub

# 5. 一条命令跑完
python tools/pipeline.py "assets/samples/你的书.epub"
```

产物在 `out/*.zh.epub`，可以直接用阅读器打开。

任一步中断，重新执行同一条命令即可续跑；已完成的篇会跳过。

## 常用命令

| 命令 | 作用 |
|---|---|
| `python tools/doctor.py` | 环境自检 |
| `python tools/pipeline.py <epub>` | 全流程（预读→翻译→修订→润色→打包→校验） |
| `python tools/epub_report.py <epub>` | 体检：DRM、字数、注音、图片、章节 |
| `python tools/preread.py <epub>` | 预读：生成人物表/术语表/风险清单 |
| `python tools/translate_book.py <epub>` | 整本翻译（可断点续跑） |
| `python tools/revise_book.py <epub>` | 自评 + 局部重写 |
| `python tools/polish.py <epub>` | 中文润色（只改表达） |
| `python tools/build_epub.py <epub>` | 重新打包 |
| `python tools/verify_epub.py <out> <src>` | 结构同构校验 |
| `python tools/review_server.py` | 审校界面（http://127.0.0.1:8765） |

## 审校界面

```
问题清单（标点 / 术语 / 假名 / 待重译） → 点开段落
  ├─ 日文原文
  ├─ 修订差异（红删绿增）
  ├─ 译文编辑
  └─ 保存 / 用初稿 / 标记已看
术语表（可搜索）· 待确认绰号 · 一键重新打包
```

设计原则：**不需要判断的自动修，需要判断的才让人看**。

## 结构

```
assets/samples/   放原书
kb/<书名>/        知识资产：术语、风格、预读设定
work/<书名>/      中间产物：译文、修订版
out/              成品 EPUB
reports/<书名>/   质检报告
src/epubtr/       核心库
tools/            命令行工具
docs/             设计与手册
```

核心库分工：

```
scan.py     物理扫描：标签与文本节点的精确区间
ir.py       块提取、内联标记、注音处理
render.py   回写与标记校验
package.py  EPUB 重建、字体、排版
translate.py 翻译批处理
revise.py   P2 自评 + P3 修订
bible.py    全书预读
names.py    术语唯一权威
parallel.py 并发
store.py    原子落盘
```

## 配置

`config/local.json`：

```json
{
  "provider": {"base_url": "...", "model": "...", "api_key": "..."},
  "budget": {"max_cost_cny": 30},
  "font": {"path": "C:/Windows/Fonts/simkai.ttf", "normalize_size": true}
}
```

- 任何 OpenAI 兼容接口都可以（DeepSeek、vLLM、Ollama）；
- 并发用环境变量：`EPUBTR_WORKERS=5`（默认 3）；
- 字体可选，不填则不内嵌。

## 已知限制

- **不支持 DRM**（LCP/ADEPT/Kindle），检测到直接拒绝；
- 内置默认字体是 Windows 楷体，**仅限个人使用**；分发请换成开源字体；
- 评测基线只覆盖 4 本书，换题材可能需要重新校准；
- 数字/日期检查噪声偏大，只作抽查参考。

## 文档

- [设计文档](docs/design.md) —— 分层架构与关键决策
- [中间表示规范](docs/ir.md) —— 无损回写怎么实现
- [操作手册](docs/manual.md) —— 从放书到打包

## 许可

MIT，见 [LICENSE](LICENSE)。仓库不含任何书籍文本、译文或评测数据。
