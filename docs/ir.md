# IR 规范：文档中间表示与无损回写

> 状态：v1 草案（可直接照着实现）
> 上位文档：`design.md` §4.2；决策：`decisions.md`
> **这一层是整个项目的合同。写错一次，后面全部要返工。**

---

## 1. 目标与不变量

**目标**：把 EPUB 里的 XHTML 变成"可翻译的段落 + 可还原的骨架"，翻完能百分之百还原结构。

把它写成可断言的**不变量（invariant）**，实现是否合格只看向量：

| # | 不变量 | 检查方式 |
|---|---|---|
| I1 | 未翻译的字节，输出与输入完全相同 | `raw` 与 `out` 逐字节 diff，只允许被替换区间不同 |
| I2 | 标签序列（名称、属性、顺序、引号、空白）不变 | 扫描两边的标签事件流，逐项比对；**ruby 内部（rb/rt/rp）例外**，见 §9.2 |
| I3 | 文本节点的**数量与顺序**不变 | 扫描两边文本节点，比对归属 |
| I4 | 每个可译文本恰好被一个 Block 覆盖，不重不漏 | 区间并集 == 全部可译文本节点区间 |
| I5 | 内联标记可逆：`source` 能精确还原 Span 集合 | 解析 `source` 得到的标记 == `spans` |
| I6 | opaque 区域（脚注、pre、script）零改动 | 区间哈希比对 |
| I7 | 实体往返：`unescape(escape(t)) == t` | 属性测试 |
| I8 | 失败必须"降级为保留原文"，绝不输出坏 XHTML | 校验器拒写 |

**I1 是底线。** 只有"非文本节点逐字节相同"才叫无损；"看起来一样"不算。

---

## 2. 双视图：为什么不能只用 DOM

三个诱惑都要拒绝：

| 做法 | 为什么不行 |
|---|---|
| lxml 解析 → 改文本 → `etree.tostring()` | 重新序列化会改属性顺序、自闭合写法、实体转义、命名空间前缀、缩进。**I1/I2 直接破** |
| BeautifulSoup | 同上，且会"修复"它认为不合法的结构 |
| `html.parser.getpos()` | 返回的是"上一个标签的位置"，不是文本节点起点，不可靠 |

正确做法是**两个视图 + 对齐**：

```
物理视图（scanner）  ← 唯一的真相来源
  在 raw 字符串上逐字符扫描，产出：标签事件 + 文本节点区间 + 元素树 + 精确 offset

语义视图（lxml）     ← 只用来查语义
  epub:type / role / class / href / 命名空间 / xml:lang

对齐：两边的元素按"文档序"一一对应（index 相同即同一个元素）
```

- **写**只走物理视图（原始标签串照抄）；
- **读语义**只走 lxml；
- 两边元素数不一致 → 直接失败并报错，不做猜测。

> 这比"纯 scanner"多写约 80 行，但换来 epub:type、命名空间这些语义的可靠性；比"纯 lxml"多的是精确区间。两边都不可替代。

---

## 3. 扫描器（scanner）规范

### 3.1 输入输出

输入：一个 XHTML 文件的 UTF-8 字符串（`raw`）。
输出：

```python
@dataclass
class ScanResult:
    root: ScanElem
    elements: list[ScanElem]        # 文档序，仅真实元素（不含注释/PI）
    texts: list[ScanText]           # 文档序，全部文本节点
    declarations: list[tuple[int,int]]  # <?xml?>, <!DOCTYPE>, <![CDATA[..]]>, 注释

@dataclass
class ScanElem:
    index: int
    tag: str
    attrs_raw: str                  # 属性原文，一个字符都不改
    open_start: int; open_end: int  # 开标签在原串中的 [start, end)
    close_start: int; close_end: int  # 闭标签；自闭合时与 open 重合
    self_closing: bool
    parent: ScanElem | None
    children: list[ScanElem | ScanText]
    depth: int

@dataclass
class ScanText:
    start: int; end: int            # 在原串中的区间
    parent: ScanElem
    raw: str                        # 原样
    text: str                       # unescape 之后
```

### 3.2 状态机

逐字符扫描，遇到 `<` 分派：

```
'<!--'          → 注释，吞到 '-->'
'<![CDATA['     → 吞到 ']]>'，内容记为一个"原样文本节点"
'<?'            → PI，吞到 '?>'
'<!'            → DOCTYPE / 声明，吞到 '>'（若含 '[' 则吞到匹配的 ']' 后的 '>'）
'</name ...>'   → 闭标签
'<name ...>'    → 开标签
'<name ... />'  → 自闭合
```

属性解析必须**尊重引号**：`alt="a>b"` 里的 `>` 不是标签结束。实现上先做一次"找配对的 `>`"，扫描时维护引号状态（`'` / `"`），遇到未闭合引号不结束。

XHTML 空元素（`br hr img input meta link area base col embed param source track wbr`）即使写成 `<br>` 也按自闭合处理。

容忍策略：闭标签不匹配时，向上弹栈直到匹配；找不到则忽略该闭标签并记一条 warning。**坏 HTML 不能炸，但必须留痕。**

### 3.3 文本节点切分规则

- 两个标签之间的连续字符 = 一个文本节点（不做任何合并/拆分）；
- 注释、CDATA、PI 两侧的文本**不合并**，保持物理边界；
- 文本节点即使全是空白也保留（它们是原文的一部分，回写时原样留着）。

---

## 4. 数据模型

### 4.1 Doc / Block / Span

```python
@dataclass
class Doc:
    href: str                # 在 zip 内的路径
    raw: str                 # 原始 XHTML 字符串，只读
    raw_sha256: str
    elements: list[ScanElem]
    blocks: list[Block]
    opaque: list[OpaqueSpan]

@dataclass
class Block:
    uid: str                 # 全局唯一：ch03-d02-b017
    doc_href: str
    index: int               # 文档内序号，从 0 开始
    tag: str                 # p / h1 / li / td ...
    kind: str                # para | heading | list_item | caption | cell | blockquote
    open_raw: str            # "<p class=\"indent\">"  原样，含所有属性
    close_raw: str           # "</p>"
    content_start: int       # 内容区间，回写时被整体替换
    content_end: int
    spans: tuple[Span, ...]  # 内联元素，按出现顺序
    source: str              # 带占位符的可译文本
    risk_tags: tuple[str, ...] = ()

@dataclass
class Span:
    sid: int
    tag: str                 # ruby / em / a / img / br ...
    open_raw: str; close_raw: str
    open_start: int; open_end: int
    close_start: int; close_end: int
    self_closing: bool
    verbatim: bool           # True = 内部文本不翻译，原样回填
    ruby_rt: str | None = None      # 注音文本
    ruby_policy: str | None = None  # drop | keep | note
```

### 4.2 Block 的判定规则

```
BLOCK_TAGS = {p, div, h1..h6, li, dd, dt, td, th, blockquote,
              figcaption, aside, section, article, header, footer, caption, pre}
```

一个元素是 Block，当且仅当：

1. `tag ∈ BLOCK_TAGS`；
2. 它**没有** Block 类型的后代（即"叶子块"）；
3. 它含有至少一个非纯空白的文本节点（或含非 verbatim 内联元素）。

第 2 条保证块之间**互不嵌套、区间互不重叠**——这样回写才能从后往前一次性替换。

`pre` / `code` 例外：整块 opaque，不产生 Block。

### 4.3 uid 规则

```
ch{spine_index:02d}-d{doc_index:02d}-b{block_index:03d}
```

uid 只用于进程内定位与日志；**缓存键不直接用 uid**（见 §10），否则插入一段就会全错位。

---

## 5. 内联标记协议

### 5.1 语法

```
⟦i12⟧      开标记，sid=12
⟦/i12⟧     闭标记，sid=12
⟦v12⟧      自闭合元素，sid=12
```

用 `U+27E6 / U+27E7`（数学白方括号），因为极少出现在日文正文里，且 tokenizer 稳定。

规则：

- 开闭必须**正确嵌套**，不允许交叉；
- 一个 sid 在 `source` 中只能出现一对（或一个 `v`）；
- `source` 解析出的 sid 集合必须与 `spans` 完全相等（I5）；
- 正文里如果真出现 `⟦`（极罕见），提取时转义为 `⟦⟦`，回写时还原。

### 5.2 各类元素的映射

| 元素 | 标记 | 内部文本 | 回写 |
|---|---|---|---|
| `<em>/<b>/<i>/<span>` | `⟦i⟧…⟦/i⟧` | 参与翻译 | 原标签串照抄，内部为译文 |
| `<ruby>` | `⟦i⟧base⟦/i⟧` + 元数据 | base 参与翻译，rt 不进 source | 按 policy 重建（§9） |
| `<a epub:type="noteref">` | `⟦i⟧⟦/i⟧`（空对） | **不翻译**（verbatim） | 原标签 + 原内部文本 |
| `<img>/<br>/<hr>` | `⟦v⟧` | 无 | 原标签串照抄 |
| `<sup>/<sub>` | 同 span | 参与翻译 | 同 span |
| 嵌套 ruby（ruby 在 em 内） | 正常嵌套 | — | 逐层还原 |

`verbatim=True` 的元素：source 里只留一对空标记，模型看到的是"这里有个占位符"，不需要也无法改动它。

### 5.3 为什么 ruby 要用配对标记而不是单个占位符

因为 base 文本必须参与翻译并**保持位置**。若把 `<ruby>雨<rt>あめ</rt></ruby>` 压成一个 `⟦v⟧`，模型就丢了"雨"这个词，译文里这个位置会消失。用 `⟦i⟧雨⟦/i⟧`，模型译成 `⟦i⟧雨⟦/i⟧` 或 `⟦i⟧雨水⟦/i⟧`，位置天然保留。

---

## 6. 提取算法

```python
def extract(doc: Doc, lxml_root, scan: ScanResult) -> list[Block]:
    assert len(real_elements(lxml_root)) == len(scan.elements)   # 对齐前提
    blocks = []
    for i, (lel, sel) in enumerate(zip(real_elements(lxml_root), scan.elements)):
        if sel.tag not in BLOCK_TAGS:            continue
        if has_block_descendant(lel):            continue
        if is_opaque(lel):                       continue      # §8
        if not has_translatable_text(sel):       continue

        spans, source = build_spans_and_source(sel)
        blocks.append(Block(
            uid=f"ch{doc.ch:02d}-d{doc.d:02d}-b{len(blocks):03d}",
            doc_href=doc.href, index=len(blocks),
            tag=sel.tag, kind=KIND.get(sel.tag, "para"),
            open_raw=sel.open_raw, close_raw=sel.close_raw,
            content_start=sel.open_end, content_end=sel.close_start,
            spans=tuple(spans), source=source,
        ))
    assert_partition(doc, blocks)                # I4
    return blocks
```

`build_spans_and_source` 递归遍历块的直接子节点：

```python
def walk(node) -> str:
    out = []
    for child in node.children:
        if isinstance(child, ScanText):
            out.append(unescape(child.raw))
        else:
            sid = register_span(child)           # 分配 sid，记录 open/close 区间
            if is_void(child):
                out.append(f"⟦v{sid}⟧")
            elif is_verbatim(child):
                out.append(f"⟦i{sid}⟧⟦/i{sid}⟧")
            elif child.tag == "ruby":
                base, rt = split_ruby(child)
                out.append(f"⟦i{sid}⟧{walk_text(base)}⟦/i{sid}⟧")
            else:
                out.append(f"⟦i{sid}⟧{walk(child)}⟦/i{sid}⟧")
    return "".join(out)
```

**空白归一**（只作用于 `source`，不改 `raw`）：

1. 连续空白（含换行、全角空格以外的制表）压成一个半角空格；
2. 若空格两侧都是 CJK 字符 → 删除该空格（日文原文的换行缩进不应变成中文空格）；
3. 首尾空白删除。

---

## 7. 回写算法

### 7.1 主流程

```python
def rewrite(doc: Doc, translations: dict[str, str]) -> str:
    edits = []
    for b in doc.blocks:
        target = translations.get(b.uid)
        if target is None:                        # 没译：原样保留（I8 的降级）
            continue
        try:
            inner = render(b, target)
        except MarkerError as e:
            log_reject(b, e)
            continue                              # 拒绝写入，保留原文
        edits.append((b.content_start, b.content_end, inner))

    out = doc.raw
    for start, end, inner in sorted(edits, reverse=True):   # 从后往前，偏移不失效
        out = out[:start] + inner + out[end:]
    return out
```

**关键**：只替换 `content_start..content_end`，开闭标签一个字节都不碰。

### 7.2 render

```python
def render(block: Block, target: str) -> str:
    tokens = tokenize(target)                     # text | open | close | void
    validate(tokens, block.spans)                 # 结构 + 配对 + 完整性
    paras = split_paragraphs(tokens)              # 按空行切，且每段标记自平衡
    return "\n".join(
        "".join(emit(tok, block) for tok in para) for para in paras
    )

def emit(tok, block):
    if tok.kind == "text":  return escape(tok.text)
    if tok.kind == "open":  return span(block, tok.sid).open_raw
    if tok.kind == "close": return span(block, tok.sid).close_raw
    if tok.kind == "void":  return span(block, tok.sid).open_raw
```

- 文本转义：`&`→`&amp;`、`<`→`&lt;`（`>` 不转，`.` 不转）；
- 中文标点在**这里之后**做一次归一（`、`→`，` 等，见 `style_guide`），但**不得改动标记**；
- 段落切分：模型用空行 `\n\n` 表示分段。每段必须标记自平衡，否则整块不切分（合并成一段），并记 warning。

### 7.3 校验（写入前必过）

```python
def validate(tokens, spans):
    ids = {s.sid for s in spans}
    seen_open, seen_close, stack = set(), set(), []
    for t in tokens:
        if t.kind == "open":
            if t.sid not in ids: raise MarkerError("UNKNOWN", t.sid)
            if t.sid in seen_open: raise MarkerError("DUP", t.sid)
            seen_open.add(t.sid); stack.append(t.sid)
        elif t.kind == "close":
            if not stack or stack[-1] != t.sid: raise MarkerError("NEST", t.sid)
            stack.pop(); seen_close.add(t.sid)
        elif t.kind == "void":
            if t.sid not in ids: raise MarkerError("UNKNOWN", t.sid)
    if stack:                        raise MarkerError("UNCLOSED", stack[-1])
    if seen_open != ids:             raise MarkerError("MISSING", ids - seen_open)
    if seen_open != seen_close:      raise MarkerError("CLOSE_MISSING", seen_open - seen_close)
```

失败处理顺序（**绝不写出坏文件**）：

```
重试同块（带错误提示，最多 2 次）
  → 降级逐句翻译（每句单独渲染，标记缺失的句子保留原文）
  → 整块保留原文 + 标记 failed
```

---

## 8. opaque 区域

以下元素/区域**不产生 Block、不进翻译队列、回写时原样保留**：

| 区域 | 判定 |
|---|---|
| 原书脚注 | `aside[epub:type~="footnote"]`、`[role="doc-footnote"]`（Q12/O5） |
| 代码/预格式 | `pre`、`code` |
| 脚本与样式 | `script`、`style` |
| 矢量/公式 | `svg`、`math` |
| 模板 | `template` |
| 注音文本 | `<rt>`（单独处理，见 §9） |
| 声明 | `<?xml?>`、`<!DOCTYPE>`、注释、CDATA |

opaque 区域在提取时记录 `[start, end)`，回写后做**区间哈希比对**（I6）。若发生变化，说明算法有 bug，直接失败。

---

## 9. 注音（ruby）处理

### 9.1 两种 ruby，必须都支持

| 形态 | 例 | 处理 |
|---|---|---|
| 单 rb | `<ruby><rb>学</rb><rt>まなび</rt></ruby>` | 原样保留 rb/rt，只替换 base 文本 |
| **多 rb（一字一注）** | `<ruby><rb>薩</rb><rt>さつ</rt><rb>次</rb><rt>じ</rt></ruby>` | base = 各 rb 文本拼接；**归一为** `<ruby>译文<rt>合并读音</rt></ruby>` |
| 无 rb | `<ruby>漢字<rt>かんじ</rt></ruby>` | 原样保留 |
| 复杂 ruby / 左右 ruby | — | 降级括注，不建模（D10） |

多 rb 形态在真实日文书里极为常见（三本样书中占 84%–100% 的 ruby），**如果按"不支持"整块保留，等于所有人名都不译**。这是实测发现的第一个真实陷阱。

### 9.2 归一带来的例外

多 rb 归一成单 rb 会改变 ruby 内部标签，因此 I2 的结构比对必须先把 ruby 内部折叠掉——只检查"`<ruby>` 这个壳还在不在、位置对不对"（实现：`scan.canonical_tags`）。这是全项目**唯一**允许的标签序列变化，且只发生在 ruby 内部。

### 9.3 判定顺序（重要：诡计优先）

```
1. 查 risk.yaml / book_bible：该位置或该角色名是否被标 trick_clue / name_reading？
   → 是：policy = keep（无条件保留），跳过下面所有判断
2. 判定注音是"读音"还是"语义"：
   a. rt 全为假名，且 base 的常见读法 == rt → reading → policy = drop（中文不需要）
   b. 其余 → semantic → policy = keep 或 note
3. 人名/地名首次出现 → note（保留原词 + 首现括注）
```

> 第 1 步必须在最前。否则"名字读法是线索"的书会被规则 2a 误删——这是泄底级别的事故。

### 9.4 回写形态
```
policy = drop   → 只输出 base 的译文，删除整个 ruby
policy = keep   → <ruby>译词<rt>原文读音</rt></ruby>
policy = note   → 译词（原文：base，读作 rt），首次出现加译注
```

`<rp>` 随 ruby 一起删或保留，不单独处理。

---

## 10. 缓存与幂等

```python
key = sha256(
    block.source + "\x00" +
    json(spans_semantic(b.spans)) + "\x00" +   # 只取 tag/attrs 的语义摘要
    glossary_version + "\x00" +
    prompt_version + "\x00" +
    model_id + "\x00" + params_hash
)
```

- 键里**不放 uid、不放章节号**：文字相同即命中，插入段落不会让缓存集体失效；
- 输出另存 `raw_sha256`，用于快速判断整份文档是否可跳过；
- 同一 block 允许多个版本（draft / revised / polished），用 `variant` 区分。

---

## 11. 边界用例（必须逐条写测试）

| # | 用例 | 期望 |
|---|---|---|
| 1 | 普通 `<p>text</p>` | 正常翻译替换 |
| 2 | 段内 `<em>`/`<b>` | 标记保留，位置随译文 |
| 3 | 读音 ruby | 删除 ruby，保留译词 |
| 4 | 当て字 ruby | 保留 + 括注 |
| 5 | 诡计 ruby（risk 标记） | 强制保留，优先级最高 |
| 6 | ruby 嵌在 `<em>` 内 | 两层标记正确嵌套 |
| 7 | `<a epub:type="noteref">1</a>` | verbatim，内部"1"不变 |
| 8 | `<aside epub:type="footnote">` | opaque，零改动 |
| 9 | `<img>` + `<figcaption>` | img 是 void 标记；caption 是独立 Block |
| 10 | `<br/>` | void 标记，位置保留 |
| 11 | 注释 `<!-- -->` | 原样保留 |
| 12 | CDATA | 原样保留 |
| 13 | 实体 `&amp;` `&#12354;` `&nbsp;` | 往返一致（I7） |
| 14 | `<pre>` 俳句/代码 | opaque，不翻译 |
| 15 | 表格 `<td>` | 每个 td 一个 Block |
| 16 | 纯空白段 | 不产生 Block，原样保留 |
| 17 | 属性含 `>`（`alt="a>b"`） | 扫描器不截断 |
| 18 | 自闭合 `<br />` 与 `<br>` | 等价处理 |
| 19 | XML 声明 + DOCTYPE | 不动 |
| 20 | 嵌套 `<div>` 树 | 只取叶子块，区间不重叠 |
| 21 | 中英混排 + 全角空格 | 空白归一正确 |
| 22 | 未闭合标签（坏书） | 容错 + warning，不崩 |
| 23 | 一段被译成两段 | 按标记平衡切分，各自套原标签 |
| 24 | 译文丢失标记 | 拒绝写入 → 降级 → 保留原文 |
| 25 | 竖排 class（`vrtl` 等） | 不影响文本提取 |
| 26 | 同一段多个 ruby | sid 独立，互不干扰 |
| 27 | `<ruby>` 内嵌套 `<span>` | 按不支持的复杂结构降级括注 |
| 28 | 空 `<p></p>` | 跳过 |

---

## 12. 验收

### 12.1 三条硬指标

1. **恒等往返**：把 `identity` 翻译（译文 = 原文）喂进去，输出必须与输入**逐字节相同**。随机生成 1000 个嵌套结构跑属性测试。
2. **结构同构**：真实样书上，标签事件流 diff == 0，opaque 区间哈希 diff == 0。
3. **epubcheck 0 error**。

### 12.2 故障注入

- 随机删掉译文里的一个标记 → 必须被拒绝且不写坏文件；
- 随机交换两个标记的顺序 → 必须报 NEST；
- 随机让模型返回空字符串 → 保留原文，记 failed。

---

## 13. 实现顺序（建议）

| 步骤 | 产出 | 验证 |
|---|---|---|
| 1 | scanner + 树 + 区间 | 28 个边界用例全过 |
| 2 | lxml 对齐 | 元素数一致率 100%（20 本书） |
| 3 | Block 提取 + source 生成 | 恒等往返通过 |
| 4 | 回写 + 校验 | 故障注入全拒 |
| 5 | ruby 三策略 | 诡计用例优先命中 |
| 6 | opaque 保护 | 区间哈希不变 |

---

## 14. 待定

- 短篇集"作品级"切分的判定规则（`epub:type="titlepage"` / 单独 title 页 / 人工覆盖）；
- 合并相邻 Block（日文一句一段 → 中文合并）是否要做：v1 不做，只允许拆段；
- `epub:type` 前缀映射：需要解析 `xmlns:epub`，缺省按规范固定 URI 处理。
