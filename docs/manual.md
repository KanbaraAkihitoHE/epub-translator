# 操作手册

> 面向使用者（你），不涉及代码结构。命令都在项目根目录执行。
> Python 用仓库自带的解释器，下文记作 `python`。

## 0. 一句话流程

```
放书 → 体检 → 预读 → 确认术语 → 翻译 → 修订 → 润色 → 质检（可跳过）→ 打包 → 读
```

其中**只有"确认术语"必须你看一眼**，其余都能自动跑。

也可以一条命令跑完：

```bash
python tools/pipeline.py assets/samples/xxx.epub
python tools/gui.py                                   # 图形界面
python tools/translate_text.py 片段.txt --title "第三章" --glossary 失恋  # 只翻一段
```

已完成的步骤会自动跳过；哪一步崩了，修好后重新执行同一条命令即可续上。

开工前先自检环境：

```bash
python tools/doctor.py
```

## 1. 目录约定

```
assets/samples/   放原书 epub
kb/<书名>/        glossary.json 术语表、style.md 风格、auto_bible.json 预读、fixes.json 统一替换
work/<书名>/      译文（rev/ 是修订后的版本）
out/              成品 epub
docs/             各种报告
config/local.json API key 与字体设置（勿外传）
```

## 2. 每一步怎么做

### 2.1 放书

把 `.epub` 丢进 `assets/samples/`。只支持无 DRM 的 EPUB。

### 2.2 体检（可选）

```
python tools/epub_report.py assets/samples/xxx.epub
```

看三件事：有没有 DRM、多少段、有没有注音/脚注。报告写到 `reports/<书名>/inspect.md`，多本汇总在 `reports/_shared/samples-report.md`。

### 2.3 预读（必做，约 3 分钟）

```
python tools/preread.py assets/samples/xxx.epub
```

产出：
- `kb/<书名>/auto_bible.json`：梗概、人物、术语、风险；
- `kb/<书名>/glossary.json`：自动生成的初版术语表。

**看一眼 `reports/<书名>/preread.md`**，重点看人物表有没有把作者和角色搞混（发生过）。

### 2.4 确认术语（唯一必须人工的一步）

打开审校界面：`python tools/review_server.py`，浏览器开 `http://127.0.0.1:8765`。

- 左边「待确认绰号」：这些是预读发现、但术语表里没有的别名。填个中文名点保存即可；
- 左边「术语表」：已确认的条目，看到不对就地改；
- **没有要改的？直接关掉，不用做任何操作。** 不改 = 用自动生成的版本，也能跑。

系列作品要把上一本的术语合并过来：

```
python tools/alias_glossary.py assets/samples/xxx.epub   # 生成绰号候选
```

合并系列术语目前是手动脚本，见 roadmap。

### 2.5 翻译（约 15–25 分钟）

```
python tools/translate_book.py assets/samples/xxx.epub
```

断点续跑：已完成的篇会跳过。中断了重新执行即可。

### 2.6 标题（1 分钟）

```
python tools/translate_titles.py assets/samples/xxx.epub
```

标题单独翻译，结果在 `work/<书名>/titles.json`。**注意**：标题链路不读术语表，容易出现「雾子/桐子」这种不一致，生成后扫一眼。

### 2.7 修订（约 10–15 分钟）

```
python tools/revise_book.py assets/samples/xxx.epub
```

只自动改「准确性 + 严重」的问题；风格问题只记录不自动改。改坏的会被拒绝（标记校验）。

### 2.8 质检（可选，按需）

```
python tools/qa_report.py        assets/samples/xxx.epub   # 假名残留、长度异常
python tools/consistency.py      assets/samples/xxx.epub   # 跨章人名/术语一致性
python tools/check_numbers.py    assets/samples/xxx.epub   # 数字/日期（噪声大）
python tools/polish.py           assets/samples/xxx.epub   # 中文润色（按审校标记）
python tools/polish.py           assets/samples/xxx.epub --long  # 额外强化长段落语体
python tools/autofix.py          assets/samples/xxx.epub   # 自动重译术语/假名异常段
python tools/audit_revisions.py  assets/samples/xxx.epub --apply  # 复核已有修订，不可信的回退初稿
python tools/verify_epub.py out/xxx.zh.epub assets/samples/xxx.epub  # 成品结构校验
```

报告都在 `reports/<书名>/`。**不想逐份读没关系**，这些是抽查工具，不是必过关卡。

### 2.9 统一错译名（发现问题时）

1. 把「错误写法 → 正确写法」写进 `kb/<书名>/fixes.json`；
2. 执行 `python tools/normalize.py assets/samples/xxx.epub`；
3. 重新打包。

### 2.10 打包

```
python tools/build_epub.py assets/samples/xxx.epub
```

产物在 `out/`。也可以在审校界面点右下角「重新打包」。

## 3. 审校界面怎么用

### 3.1 三种情形

| 情形 | 操作 |
|---|---|
| 有想改的术语 | 术语表里改，点保存 → 重新打包 |
| 有想改的段落 | 可疑段落里改译文，点保存 → 重新打包 |
| **什么都不想改** | 什么也不点，直接重新打包，或不管它 |

界面是"按需修改"，不改不会破坏任何东西。

### 3.2 保存的两件事

- 术语保存 → 写 `glossary.json`，**只影响下次翻译**，已翻好的段落不会自动改（要批量改，用 2.9 的 fixes.json）；
- 段落保存 → 写 `rev/<篇>.json`，下次打包生效。

## 4. 四个必须人工的节点

1. 预读后：人物表有没有明显错误；
2. 术语确认：绰号/人名定名；
3. 标题生成后：扫一眼有没有和正文冲突的译名；
4. 成品后：随便翻两页，看排版和字体是否正常。

## 5. 常见问题

**Q：重跑会不会覆盖我的修改？**
`normalize.py` 会改 `rev/`，其余工具只读不写 `rev/`。重新翻译只补缺失的篇。

**Q：改完 prompt 要全部重翻吗？**
要。目前没有内容哈希缓存，改 prompt 等于从头来。这是已知待改进项。

**Q：为什么有的段落还是日文？**
多半是标记校验失败后保留原文，或旧译文与新版 IR 不匹配。用 `qa_report.py` 找出来，在界面里直接改。

**Q：字体能分享吗？**
内嵌的是 Windows 楷体，仅限个人使用；分发需换开源字体（见 roadmap）。

**Q：成本怎么估？**
每万字约 ¥0.3–0.5（含修订）。一本 10 万字约 ¥3–5。

## 6. 数据

- `config/local.json` 里有 API key，不要提交、不要外传；
- `work/` 可重跑，`kb/` 是资产（术语/风格），**备份 kb/**；
- `out/` 是成品。
