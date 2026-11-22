# epub-translator · 日文 EPUB 翻译工具

把日文小说 EPUB 转成高质量中文 EPUB 的流水线：结构不破坏、术语统一、支持人工审校。

A pipeline that translates Japanese novels (EPUB) into Chinese EPUB — lossless structure, consistent terminology, human review built in.

```text
彼は窓の外を見ていた。雨が降っていた。
        ↓
他望着窗外。雨一直下着。
```

## 功能

| 功能 | 说明 |
|---|---|
| 结构无损 | 在原始 XHTML 字符串上做区间替换，只换文字；非文本节点逐字节不变 |
| 术语统一 | 预读生成人物表/术语表，正文、标题、目录、人名注记共用一份权威 |
| 歧义保留 | 字谜、谐音、叙述性诡计不"本地化"；该含糊的地方不补写、不解释 |
| 多遍翻译 | 草稿 → 自评 → 局部修订 → 润色；只对高风险内容多跑 |
| 自动质检 | 结构、术语、标点、未译残留、跨章一致性、数字日期 |
| 人工审校 | 本地网页：问题清单跳转、修订差异、术语编辑、一键重新打包 |
| 断点续跑 | 内容哈希缓存 + 按篇落盘，中断后重跑自动跳过已完成部分 |

## 安装

需要 Python 3.11+。

```bash
git clone https://github.com/KanbaraAkihitoHE/epub-translator.git
cd epub-translator
pip install -r requirements.txt
```

## 使用

### 1. 配置

```bash
cp config/local.example.json config/local.json
```

填入任意 OpenAI 兼容接口（DeepSeek、vLLM、Ollama 均可）。密钥只保存在本机，已在 `.gitignore` 中。

### 2. 自检

```bash
python tools/doctor.py
```

检查依赖、配置、目录与端口。

### 3. 跑一本书

```bash
# 把无 DRM 的 EPUB 放进 assets/samples/
python tools/pipeline.py "assets/samples/book.epub"
```

产物在 `out/book.zh.epub`，可直接用阅读器打开。任一步中断后重新执行同一命令即可续跑。

### 4. 审校（可选）

```bash
python tools/review_server.py
# 浏览器打开 http://127.0.0.1:8765
```

只监听本机。界面里可以按问题清单逐条修改，改完点"重新打包"。

### 图形界面

```bash
tools/gui.py            # 或双击 启动.bat
```

三个页签：整本翻译、片段文本、审校服务。

### 只翻一节

没有 EPUB 也可以，纯文本直接翻：

```bash
python tools/translate_text.py section.txt --title "第三章" --glossary 书名
```

输出 `out/section.zh.txt`；加 `--epub` 同时生成 EPUB。

### 分步执行

```bash
python tools/epub_report.py    assets/samples/book.epub  # 体检：DRM、字数、注音、图片
python tools/preread.py        assets/samples/book.epub  # 预读：人物/术语/风险
python tools/translate_book.py assets/samples/book.epub  # 翻译
python tools/revise_book.py    assets/samples/book.epub  # 自评 + 局部重写
python tools/polish.py         assets/samples/book.epub  # 润色（--long 强化长段落）
python tools/autofix.py        assets/samples/book.epub  # 自动重译异常段
python tools/build_epub.py     assets/samples/book.epub  # 重建 EPUB
python tools/verify_epub.py out/book.zh.epub assets/samples/book.epub
```

## 输入

- EPUB 2 / EPUB 3，竖排或横排均可；
- **必须无 DRM**（Readium LCP、Adobe ADEPT、Kindle 均不支持）；
- 注音（ruby）默认丢弃，只保留被注文字；
- 图片、脚注、目录、封面原样保留。

## 输出

```
out/
└─ book.zh.epub                 # 成品：单语中文、横排、内嵌字体

work/book/
├─ 000.json …                   # 逐篇译文（含原文哈希）
└─ rev/                         # 修订版

kb/book/
├─ auto_bible.json              # 预读设定：人物、术语、风险
├─ glossary.json                # 术语表（唯一权威）
├─ style.md                     # 风格指南
└─ fixes.json                   # 可选：批量替换表

reports/book/
├─ inspect.md                   # 体检
├─ qa.md                        # 质检
├─ consistency.md               # 跨章一致性
└─ punctuation.md               # 标点
```

## 可选功能

### 系列记忆

同作者或同系列的新书，可以继承前作术语：

```bash
python tools/merge_series.py 新书.epub --from 前作.epub
```

冲突时前作优先，并写入 `reports/<书>/series-merge.md` 供复核。

### 长段落语体强化

```bash
python tools/polish.py book.epub --long
```

只处理 130 字以上的段落，去翻译腔、调整节奏，不改事实。

### 并发

```bash
set EPUBTR_WORKERS=5     # Windows
export EPUBTR_WORKERS=5  # Linux / macOS
```

默认 3 路。实测 3 路约为串行的 2.5 倍。

### 字体

把 `.ttf` / `.otf` 放进 `assets/fonts/` 即自动内嵌，也可在 `config/local.json` 的 `font.path` 指定。推荐开源楷体（如霞鹜文楷）。

## 配置项

| 文件 | 作用 |
|---|---|
| `config/local.json` | 接口地址、模型、Key、预算、字体 |
| `kb/<书>/glossary.json` | 术语表：`ja` / `zh` / `variants` |
| `kb/<书>/style.md` | 风格指南，注入每次翻译 |
| `assets/fonts/` | 可选字体目录 |

`config/local.json` 示例：

```json
{
  "provider": {
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key": "sk-your-key"
  },
  "budget": { "max_cost_cny": 30 },
  "font": { "path": "", "normalize_size": true }
}
```

## 目录结构

```text
epub-translator/
├─ src/epubtr/          # 核心库
│  ├─ scan.py           # 物理扫描：标签与文本节点的精确区间
│  ├─ ir.py             # 块提取、内联标记、注音处理
│  ├─ render.py         # 回写与标记校验
│  ├─ package.py        # EPUB 重建、字体、排版
│  ├─ translate.py      # 翻译批处理
│  ├─ revise.py         # 自评与修订
│  ├─ bible.py          # 全书预读
│  ├─ names.py          # 术语唯一的解析入口
│  ├─ parallel.py       # 并发
│  └─ store.py          # 原子落盘
├─ tools/               # 命令行工具
├─ tests/               # 单元测试
├─ docs/                # 设计与手册
├─ assets/samples/      # 原书（不进仓库）
└─ config/              # 配置模板
```

## 质量检查

`verify_epub.py` 与审校界面覆盖：

- 结构同构：非文本节点逐字节一致；
- 术语一致性：同一实体全书唯一译名；
- 标点配对：支持日文跨段对话；
- 未译残留：假名比例检测；
- 跨章人名一致性；
- 数字与日期比对（误报较多，仅作抽查）。

四本日文长篇（13,304 段）结构校验均为 0 差异，平均保真评分 4.68 / 5。

## 已知限制

- 不支持 DRM，检测到即拒绝；
- 默认字体取自系统，分发前请替换为可再分发字体；
- 评测基线覆盖四本书，题材差异大时需重新校准；
- 数字/日期检查噪声较大，只作人工抽查；
- 只处理 EPUB，不解析 PDF / 扫描件 / 网页连载。

## 版权说明

- 本工具只做翻译与排版，**不附带任何书籍文本或译文**；
- 使用者需自行确保对所处理书籍拥有合法使用权；
- 仓库不含 API Key、个人路径或用户数据。

## License

MIT，详见 [LICENSE](LICENSE)。
