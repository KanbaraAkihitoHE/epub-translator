# epub-translator

[![CI](https://github.com/KanbaraAkihitoHE/epub-translator/actions/workflows/ci.yml/badge.svg)](https://github.com/KanbaraAkihitoHE/epub-translator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

把日文小说 EPUB 翻译成中文 EPUB 的流水线。面向长篇文学文本，重点解决三个工程问题：

- **结构保真**：只替换文本，其余字节保持不变；
- **术语一致**：人名、专名在正文、标题、目录、注释中统一；
- **歧义保留**：原文刻意模糊处不补写、不解释。

## 特性

| 能力 | 说明 |
|---|---|
| 无损回写 | 在原始 XHTML 字符串上做区间替换，不重建 DOM；实测四本长篇结构差异为 0 |
| 全书级知识 | 预读生成人物表、术语表、风格指南与风险清单，翻译时注入 |
| 多遍翻译 | 草稿 → 自评 → 局部修订 → 润色，只对高风险内容多跑 |
| 自动质检 | 结构、术语、标点、未译残留、跨章一致性、数字日期 |
| 人工审校 | 本地 Web 界面：问题清单跳转、修订差异、术语编辑、一键重新打包 |
| 可恢复 | 内容哈希缓存、按篇落盘、断点续跑、并发（默认 3 路） |

## 工作方式

```
EPUB ──► 体检 ──► 预读 ──► 翻译 ──► 修订 ──► 润色 ──► 质检 ──► 重建 EPUB
           │        │                    │
           │        └─ 人物表/术语表/风险清单（注入每一轮翻译）
           └─ DRM 检测、结构清点
```

每个阶段产出独立文件，可单独执行，也可用 `pipeline.py` 串联。

## 安装

需要 Python 3.11 及以上。

```bash
pip install -r requirements.txt
```

## 快速开始

```bash
# 1. 配置：复制模板并填入任意 OpenAI 兼容接口的 key
cp config/local.example.json config/local.json

# 2. 环境自检
python tools/doctor.py

# 3. 将无 DRM 的 EPUB 放入 assets/samples/，然后一条命令跑完
python tools/pipeline.py "assets/samples/book.epub"
```

产物位于 `out/`。任一步中断后重新执行同一命令即可续跑，已完成的章节会跳过。

## 命令

| 命令 | 作用 |
|---|---|
| `python tools/pipeline.py <epub>` | 全流程 |
| `python tools/doctor.py` | 环境自检（依赖、配置、目录、端口） |
| `python tools/epub_report.py <epub>` | 体检：DRM、字数、注音、图片、章节 |
| `python tools/preread.py <epub>` | 生成人物表、术语表、风险清单 |
| `python tools/translate_book.py <epub>` | 整本翻译 |
| `python tools/revise_book.py <epub>` | 自评与局部重写 |
| `python tools/polish.py <epub>` | 润色；加 `--long` 强化长段落语体 |
| `python tools/autofix.py <epub>` | 自动重译术语/假名异常段 |
| `python tools/build_epub.py <epub>` | 重建 EPUB |
| `python tools/verify_epub.py <out> <src>` | 结构同构校验 |
| `python tools/review_server.py` | 启动审校服务（仅本机） |

### 审校界面

```bash
python tools/review_server.py
# 浏览器打开 http://127.0.0.1:8765
```

服务只监听本机，需要在本地启动，其他机器无法访问。界面提供问题清单（标点、术语、未译、待重译）、日文原文对照、修订差异、段落编辑与重新打包。

## 配置

`config/local.json`：

```json
{
  "provider": {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key": "sk-..."
  },
  "budget": { "max_cost_cny": 30 },
  "font": { "path": "", "normalize_size": true }
}
```

- 支持任意 OpenAI 兼容接口（DeepSeek、vLLM、Ollama 等）；
- 并发：`EPUBTR_WORKERS` 环境变量，默认 3；
- 字体：将 `.ttf`/`.otf` 放入 `assets/fonts/` 即自动内嵌；留空则不内嵌。

## 目录结构

```
assets/samples/   原书
assets/fonts/     可选字体
kb/<书名>/        术语表、风格指南、预读设定
work/<书名>/      译文与修订版
out/              成品 EPUB
reports/<书名>/   质检报告
src/epubtr/       核心库
tools/            命令行工具
docs/             设计与手册
```

核心模块：

```
scan.py       物理扫描：标签与文本节点的精确区间
ir.py         块提取、内联标记、注音处理
render.py     回写与标记校验
package.py    EPUB 重建、字体、排版
translate.py  翻译批处理
revise.py     自评与修订
bible.py      全书预读
names.py      术语解析
parallel.py   并发
store.py      原子落盘
```

## 质量检查

`verify_epub.py` 与审校界面覆盖以下检查：

- 结构同构（非文本节点逐字节一致）；
- 术语一致性（同一实体全书唯一译名）；
- 标点配对（支持日文跨段对话）；
- 未译残留（假名比例）；
- 跨章人名一致性；
- 数字与日期比对（噪声较大，仅作抽查）。

四本日文长篇（合计约 1.2 万字段落）的结构校验结果均为 0 差异。

## 限制

- 不处理 DRM（Readium LCP、Adobe ADEPT、Kindle），检测到即拒绝；
- 默认字体取自系统，分发前需替换为可再分发字体；
- 评测基线覆盖四本书，题材变化较大时需要重新校准；
- 数字/日期检查存在误报，仅用于人工抽查。

## 文档

- [设计文档](docs/design.md)
- [中间表示规范](docs/ir.md)
- [操作手册](docs/manual.md)

## 贡献

1. 保持结构保真：任何改动都不得使 `verify_epub.py` 出现结构差异；
2. 术语只有一个权威：新增产出文字的链路必须经过 `NameResolver`；
3. 失败可恢复：写文件使用 `store.save_json`，长任务支持断点续跑；
4. 测试通过：`python -m unittest discover -s tests`。

提交前请检查 `git status --short`，确保未包含书籍、译文或 API 密钥。

## 许可

MIT，详见 [LICENSE](LICENSE)。仓库不包含任何书籍文本、译文或评测数据。
