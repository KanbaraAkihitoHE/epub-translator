# 已有工作调研（Prior Art）：日文 EPUB → 中文高质量翻译

> 调研日期：2026-11-18。仓库 star / 许可 / 最近推送均为当日经 GitHub REST API 实测（`api.github.com/repos/...`），不是记忆值；star 会变，引用时请注明日期。
> 标注 **【未核实】** = 仅见文档/二手描述，未读源码或未实测；**【推断】** = 由已核实事实推出。
> 本文服务于 `docs/design.md`，只回答三个问题：哪些能直接用、哪些必须自己造、哪里有坑。

## ① 结论摘要：最该借鉴的 5 件事

1. **段级翻译 + 前后窗口，不要逐句。** WMT23 对 18 个语向（含日语）的人工评测显示，整段输入在误译、语法、风格一致性上全面优于逐句，但漏译等关键错误仍会出现（[Karpinska & Iyyer, WMT 2023](https://aclanthology.org/2023.wmt-1.41/)）。这与我们"以段为单元、块内可重组"的决策一致，也说明 **前后各 2 段的窗口是零主语的最小必需上下文**。
2. **全书术语表 + 机器强制，而不是提示词。** [Tolmach](https://github.com/KazKozDev/book-translator) 把术语分成 `exact / inflectable / preferred` 三类规则，并让"修订模型"只提小编辑、由独立 verifier 对照原文逐条核验；[bilingual_book_maker](https://github.com/yihong0618/bilingual_book_maker) 的 `--glossary` 只是 pinned 行。WMT 术语赛道多年的结论是"提示词不够，需要约束解码/两阶段/后校验"（如 [DuTerm, WMT25](https://aclanthology.org/2025.wmt-1.112/)）。→ 我们的 `must/should/free + forbidden` 要用**确定性校验**兜底。
3. **多遍流水线已被独立验证，但要按风险分档。** Google 的"研究→起草→修订→校对"分步法在 10 个语向上显著优于零样本（[Translating Step-by-Step, 2024](https://arxiv.org/abs/2409.06790)）；TransAgents 用 CEO/资深编辑/译者/审校多角色做整本文学翻译，人工与 LLM 偏好均胜基线（[TACL 2025](https://aclanthology.org/2025.tacl-1.42/)）。但两者都是**全量多遍**，成本不可接受；我们 P2/P3 只跑红旗是正确取舍。
4. **"回写不破坏结构"是市场空白，也是我们的护城河。** 现有工具的回写路径无非三种：走 Calibre 转换管线重排（Ebook Translator）、解析 HTML 后整篇重写（bilingual_book_maker，默认只翻 `<p>`；具体实现未读源码）、让另一个 LLM 把译文填回 XML（oomol 的 `fill_llm`）。**没有发现任何一个项目宣称/实现"未改动文本节点逐字节不变"**（基于 README 与文档判断，未逐行读全部源码）→ design.md 的 D1（原文串区间替换）是真正的差异化。
5. **评测：MQM 式错误分类 + 抽样人工为主，COMET 只做回归信号。** WMT 近年的人评以 MQM 为黄金标准（[WMT24 Metrics 使用 MQM](https://aclanthology.org/2024.wmt-1.2/)）；而 EAMT 2026 的实验显示，自动指标与 LLM-as-judge 在"文学创造性"上与专业译者判断**相关性很差**（[Creativity Bias](https://aclanthology.org/2026.eamt-1.43/)）。我们的 E-OMIT/E-ADD/E-MIS 分类法方向正确，但不要用 COMET 当发布门。

## ② 开源工具对比表

| 名称 | 链接 | 做什么 | 可借鉴点 | 局限 | 活跃度 / 许可（2026-11-18） |
|---|---|---|---|---|---|
| bilingual_book_maker | [GitHub](https://github.com/yihong0618/bilingual_book_maker) | epub/txt/md/srt/pdf → 双语书，多 LLM provider | **两级上下文**：window 模式前后段、session 模式整章历史并在 8k 时压成 ~300 token handoff 摘要；`--glossary` 术语行；`--translate-tags`/plan-classify 决定翻哪些标签；`--resume`；并发章节 | 默认只翻 `<p>`，ruby/内联标记无专门策略；术语靠提示词；无文学/风险概念 | 9,945★，MIT，2026-10-30 |
| Ebook Translator（Calibre 插件） | [GitHub](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin) / [主页](https://translator.bookfere.com) | Calibre 插件，48 种输入 / 20 种输出，多引擎（Google/ChatGPT/Gemini/DeepL），可保留原文 | 借 Calibre 生态覆盖格式；翻译缓存；Advanced/Batch 双模式；多书并行 | 走 Calibre 转换管线，**必然重排标记**（推断）；无全书上下文/术语；GPL-3.0 传染 | 2,691★，GPL-3.0，2026-11-13 |
| oomol-lab/epub-translator | [GitHub](https://github.com/oomol-lab/epub-translator) | pip 包，EPUB → 双语/单语，三种插入模式 | group ≤2600 token；`translation_llm` + `fill_llm` 双模型；`APPEND_BLOCK` 双语版式；自定义 prompt | 结构保真交给 LLM 回填 XML（脆弱）；无 glossary/跨章记忆；README 未提 ruby | 883★，MIT，2026-09-18 |
| TranslateBooksWithLLMs (TBL) | [GitHub](https://github.com/hydropix/TranslateBooksWithLLMs) | 桌面/Web，EPUB/SRT/DOCX/PDF/TXT/PGN，本地 Ollama 或云 | 450 token 分块 + 段间上下文；checkpoint 续跑；style preset；auto glossary；`--refine` 第二遍润色；多 key 轮换 | 术语无强制校验；无推理/文学专用策略；PDF 不保版式 | 2,600★，AGPL-3.0，2026-11-17 |
| Tolmach（book-translator） | [GitHub](https://github.com/KazKozDev/book-translator) | 本地 Ollama 整本书翻译 + 三栏审校台 + EPUB 输出 | **全书 glossary 规则**（exact/inflectable/preferred + notes）；小编辑 + 独立 verifier；质量检查含 chrF/LaBSE/COMET-Kiwi；审校台 "Needs review" 过滤 | README 以 en→ru 为主要示例（支持含中日在内 11 语）；EPUB 输出保真细节未核实；本地模型天花板 | 131★，AGPL-3.0，2026-10-11 |
| docutranslate | [GitHub](https://github.com/xunbu/docutranslate) | 多格式（pdf/docx/xlsx/md/txt/json/epub/srt）翻译库 + 服务 | EPUB workflow；`insert_mode` = replace/append/prepend；自动术语表；Python API | 通用文档定位，非文学；上下文/术语注入细节未公开 | 1,375★，MPL-2.0，2026-11-01 |
| sharplab/epub-translator | [GitHub](https://github.com/sharplab/epub-translator) | Java/Quarkus + DeepL，段落下方插入译文 | 最小可用双语排版；CLI 极简 | 仅 DeepL；无上下文/术语；仅双语 | 176★，Apache-2.0，2026-11-16 |
| quantrancse/epub-translator | [GitHub](https://github.com/quantrancse/epub-translator) | Google Translate + 自定义词典，保留结构 | 极简回写思路；译后词典替换 | 机翻质量；词典是字符串替换；已基本停更 | 301★，MIT，2025-06-27 |
| Immersive Translate | [Chrome 商店](https://chromewebstore.google.com/detail/immersive-translate-ai-we/bpoadfkcbjbfhfodiogcnhhhpibjhbnh) / [源码](https://github.com/immersive-translate/immersive-translate) | 浏览器扩展 + 文件翻译（EPUB/PDF/TXT/字幕），双语/单语下载 | 产品化的双语排版与用户预期；EPUB 一键翻译的体验 | 仓库无 license（源码可见≠开源）；PDF Pro 等闭源付费；无术语表/上下文控制（未见文档） | 19,829★，无许可，2026-11-13 |
| AozoraEpub3（非翻译，参考实现） | [GitHub](https://github.com/hmdev/AozoraEpub3) | 青空文庫文本 → EPUB，处理 ruby 与竖排 | ruby 标注转 XHTML 的具体做法；竖排 CSS 经验 | Java 老项目，已基本停更；不涉及翻译 | 230★，2026-02 后无推送 |

**共性结论**：① 双语输出是标配（bbm / oomol / docutranslate / Ebook Translator / sharplab），单语反而不是主流；② 术语表开始普及，但"强制一致"只有 Tolmach 做了 verifier；③ 没有任何项目针对**推理小说的诡计保护**（歧义保留、禁止增译、性别隐藏）做机制设计——这是空白。

## ③ 方法与论文

| 主题 | 工作 | 关键结论 / 可借鉴 | 局限 |
|---|---|---|---|
| 上下文综述 | [A survey of context in NMT and its evaluation](https://www.cambridge.org/core/journals/natural-language-processing/article/survey-of-context-in-neural-machine-translation-and-its-evaluation/875C3E2DEAAB8845A0F05988D5A18B55)（NLP 期刊，2025） | 把上下文分为句间、世界知识、术语三类；评测也必须带上下文 | 综述，无新方法 |
| 超长上下文 NMT | [Handling Very Long Contexts in NMT: a Survey](https://inria.hal.science/hal-04652584v1) | 长文档的指代、体、一致性是核心难点；分块+记忆是主流工程解 | 偏 NMT 架构，非 LLM 提示工程 |
| 段 vs 句 | [Karpinska & Iyyer, WMT 2023](https://aclanthology.org/2023.wmt-1.41/) | 整段翻译优于逐句；关键错误（漏译）仍存在，人工干预必要 | 只测 GPT-3.5 时代模型 |
| 多智能体文学翻译 | [TransAgents, TACL 2025](https://aclanthology.org/2025.tacl-1.42/) | 角色分工 + 翻译指南 + 审校流程，长文本偏好胜基线；提出 MHP/BLP 两种评测 | 成本极高；d-BLEU 反而低，说明指标失真 |
| 分步翻译 | [Translating Step-by-Step, 2024](https://arxiv.org/abs/2409.06790) | 预研究→起草→修订→校对，10 语向显著提升；**支持我们的 P0–P5 设计** | 全量多遍，未做风险路由 |
| 译后编辑 + 长上下文 | [Do LLMs Truly Benefit from Longer Context in APE?](https://doi.org/10.36227/techrxiv.176107895.57699371)（预印本） | 文档上下文能提升 APE；但开源模型对长上下文敏感，无关段落会"下毒" | 预印本，未同行评审 |
| 术语约束 | [DuTerm, WMT25](https://aclanthology.org/2025.wmt-1.112/)、[RWS, WMT26](https://aclanthology.org/2026.wmt-main.112/) | 两阶段（术语感知 NMT + LLM 提示）与"术语+片段注入"均有效；**纯提示不稳定** | 面向技术文档，非文学 |
| 文学赛道 | [WMT24 Discourse-Level Literary Translation](http://www2.statmt.org/wmt24/pdf/2024.wmt-1.58.pdf) | 已有中英网络小说文档级赛道与行业人评标准；日→中推理小说无人做 | 语向/体裁都不同 |

**对我们的直接含义**：段级+窗口、全书摘要、分步修订都有文献支撑；但"多遍"必须与"风险路由/预算"绑定，否则成本爆炸。术语必须机制化（prompt + 确定性校验 + 必要时强制替换），这与 design.md 的 D4 一致，但实现强度要高于现有开源项目。

## ④ 日→中语言资源

- **青空文庫**（[官网](https://www.aozora.gr.jp/)）：日本公有领域文学的最大语料库；[注記一覧](https://www.aozora.gr.jp/annotation/) 规定 ruby 写法 `｜漢字《かんじ》`（跨字种时用 `｜` 定界），并给出 XHTML 转换规则（[ruby 节](https://www.aozora.gr.jp/annotation/etc.html#ruby)）。**关键经验**：青空文庫自己曾用 complex-ruby 标注左右 ruby，因浏览器显示问题**已退回 simple-ruby**——我们的 ruby 处理应只依赖 `<ruby><rb><rt><rp>` 简单结构。
- **版权边界**：日本 2018-12-30 起（TPP11）保护期延至死后 70 年，2017 年底前已进入公有领域的作品不复活（[日本弁理士会解说](https://www.jpaa.or.jp/activity/teaching/language)）。黄金集只能选确已公版的作品，且需逐篇核对。
- **全量镜像现状**：`github.com/aozorabunko/aozorabunko` 在 2026-11-18 经 API 返回 **404**（已不可用）；替代：HuggingFace [globis-university/aozorabunko-clean](https://huggingface.co/datasets/globis-university/aozorabunko-clean)（已清洗、含 meta）、GitHub [aozorahack/aozorabunko_text](https://github.com/aozorahack/aozorabunko_text)（105★，2023 后少更新）。
- **日中平行语料**：ASPEC-JC 约 **68 万句对**，日文科学论文摘要→中文人工翻译，需接受许可（[ASPEC 官网](http://lotus.kuee.kyoto-u.ac.jp/ASPEC/)）；文学/口语域不匹配，只适合做术语与句法冷启动。通用域可用 [OPUS](https://opus.nlpl.eu/)（ja-zh 字幕等，质量参差）与 [Tatoeba](https://tatoeba.org/en/downloads)（CC-BY，小规模）。
- **敬语**：文化審議会《敬語の指針》（2007）把敬语分 5 类：尊敬語 / 謙譲語I / 謙譲語II（丁重語）/ 丁寧語 / 美化語（[PDF](https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/keigo_tosin.pdf)）。可直接转成 style_guide 的"敬语等级 → 中文表达"映射表。
- **警衔**：警視総監、警視監、警視長、警視正、警視、警部、警部補、巡査部長、巡査 共 9 级（[警視庁](https://www.keishicho.metro.tokyo.lg.jp/book/shigoto/kaikyuu/)）；警察庁有官方英文对译通達（[PDF](https://www.npa.go.jp/laws/notification/kanbou/jinji/kaikyuunoeiyaku.pdf)），可做"日/中/英"三列术语表，避免"警部补/副警部"混用。
- **法医词汇**：死斑、死後硬直、角膜混濁、死後経過時間推定等有标准表述与时间表，可参考日本医師会/大学法医学讲义（[徳島県医師会 PDF](https://www.tokushima.med.or.jp/affiliate/images/20260125kenan/kenan2026-honpen.pdf)）；建议只提取术语与定义，不引入其案例。
- **零主语**：日语零代名词研究有长期积累（如[言語処理学会誌 2022](https://www.jstage.jst.go.jp/article/jnlp/29/2/29_493/_pdf)）；工程上最有效的仍是"前瞻窗口 + 人物在场表 + 不确定就不补主语"，与 design.md 4.5.2 一致。
- **ruby/竖排工具**：AozoraEpub3（上表）与 `aozoraconv`（[GitHub](https://github.com/takahashim/aozoraconv)，1★，2017）可作青空注記→XHTML 的参考实现。

## ⑤ 评测

- **MQM**：当前人评的事实标准，层级化错误类型 + 严重度加权，已与 ISO 5060 对齐（[MQM 官网](https://www.themqm.org/)）；WMT 人评直接采用（[WMT24 Metrics](https://aclanthology.org/2024.wmt-1.2/)）。我们的 E-* 分类法应显式映射到 MQM 的 accuracy/fluency/terminology/style 四支，方便对外解释。
- **自动指标**：[COMET](https://arxiv.org/abs/2009.09025)（[代码](https://github.com/Unbabel/COMET)，790★，Apache-2.0）是句级回归相关最强的基线；[xCOMET](https://arxiv.org/abs/2310.10482) 增加错误 span 检测，可用于"哪一句可能有问题"的粗筛；[GEMBA-MQM](https://aclanthology.org/2023.wmt-1.64/) 用 GPT-4 直接输出 MQM 错误 span，无需参考译文；[MetricX](https://github.com/google-research/metricx)（154★）是另一家族。
- **文学评测的现实**：EAMT 2026 的 [Creativity Bias](https://aclanthology.org/2026.eamt-1.43/) 发现自动指标与 LLM-as-judge 在"创造性/创造性偏移"上与专业文学译者判断**相关性差**；结论是不能用它们替代人评。WMT24 文学赛道则坚持行业人评标准（见上表）。
- **建议**：发布门 = 硬校验 100% + 红旗人工 + 抽样通读；COMET/xCOMET 只在**同一本书、同一模型家族**内做版本回归（分数下降即报警），绝不跨书比较，也不作为质量结论。

## ⑥ EPUB 技术参考

- **规范状态**：EPUB 3.3 于 2023-05-25 成为 W3C Recommendation（[新闻稿](https://www.w3.org/2023/05/pressrelease-epub33-rec.html.en)），现行版本页标注 2026-01-13（[EPUB 3.3](https://www.w3.org/TR/epub-33/)）；EPUB 3.4 目前是 Candidate Recommendation Draft（2026-11-16，[epub-34](https://www.w3.org/TR/epub-34/)）。**注意**：[EPUBCheck v5.4.0](https://github.com/w3c/epubcheck) 已按 EPUB 3.4 校验 EPUB 3 文件，因此"epubcheck 通过"≠"只用了 3.3 特性"。
- **容器**：`mimetype` 必须是 ZIP 第一个文件、不压缩不加密、无 BOM；`META-INF/container.xml` 指向 OPF；`META-INF/encryption.xml` **同时用于字体混淆**（IDPF/Adobe），规范明确"obfuscation is not encryption"（[EPUB 3.3 §4.2.6.3.2/§4.4](https://www.w3.org/TR/epub-33/)）。
- **DRM 判定（重要修正）**：**不能见到 `encryption.xml` 就判定 DRM**——字体混淆也会写这个文件。真正的 DRM 信号是 `META-INF/license.lcpl`（Readium LCP，AES-256）或 `encryption.xml` 中 LCP/ADEPT 的 `RetrievalMethod`（[LCP 处理模型](https://readium.org/lcp-specs/lcp-license-processing-model)、[Readium DRM 检测讨论](https://github.com/readium/architecture/discussions/166)）。Kindle 商店书是 AZW/KFX 私有容器，本就不属于 EPUB 链路；Kobo 商店书同理（平台侧格式细节未逐条核实，但"不处理 DRM"的策略不变）。策略仍是"检测到即拒绝"，但检测逻辑要按上述信号分级，并把"纯字体混淆"标为可处理。
- **ruby**：EPUB 内容文档用 HTML 的简单 ruby（`ruby/rb/rt/rp`）；`rp` 是给不支持 ruby 的旧阅读系统的括号回退，EPUB 3.3 明确阅读系统应 ruby-aware（[EPUB 3.3](https://www.w3.org/TR/epub-33/)）。W3C 的 [Ruby Annotation](https://www.w3.org/TR/ruby/)（2001 REC）定义了 complex ruby，但浏览器支持差、青空文庫已弃用；**不要为"左右 ruby/多列 ruby"设计复杂结构**，遇到就降级为括注。
- **竖排**：`writing-mode: vertical-rl` + `spine@page-progression-direction="rtl"`；旧阅读器认 `-epub-writing-mode` 前缀（EPUB 3.3 附录 E，[规范](https://www.w3.org/TR/epub-33/)），CSS 标准见 [Writing Modes 3](https://www.w3.org/TR/css-writing-modes-3/)。实操坑：XHTML 未 `<link>` 引入 CSS、或只写 prefix 属性，都会导致 KDP/Kindle 上竖排"看起来对、行距/缩进/ruby 位置全错"（[Zenn 実測記事](https://zenn.dev/sora_proj/articles/00df70244f9425)）。我们转横排时，除覆盖 `writing-mode`，还要把 `page-progression-direction` 改回 `ltr`，否则翻页方向会反。
- **脚注**：`epub:type="noteref"` / `"footnote"` 成对，属于 EPUB Structural Semantics Vocabulary（[SSV 1.1](https://www.w3.org/TR/epub-ssv-11/)）；新增译注应插在同一 footnote 区并续编号，避免破坏 popup 机制。
- **校验命令**：`epubcheck out.epub --json report.json` 可机器读；CI 里应把 error 数作为硬门（用法见 [README](https://github.com/w3c/epubcheck)）。

## ⑦ 对我们的启示

**可以直接用（省 1–2 周）**

| 事项 | 来源 | 用法 |
|---|---|---|
| epubcheck 5.4 + JSON 报告 | W3C | build 后硬门；同时记录 warning 趋势 |
| 段级+窗口的上下文组装 | Karpinska 2023 / bbm session 模式 | 前 2 段 + 后 2 段 + ~300 token 滚动摘要 |
| 术语三级规则 | Tolmach | `must`(=exact)/`should`(=preferred)/`free`，另加 `forbidden` 与 `inflectable` 标记 |
| 敬语 5 类映射 | 文化審議会 | 直接写进 `style_guide.md`，作为 P4 的硬约束 |
| 警衔 9 级中日英表 | 警視庁 + 警察庁 | 预置 glossary 种子，减少冷启动错误 |
| MQM 错误类型 | themqm.org | 把 E-* 映射到 MQM，方便人评与对外沟通 |
| 分步翻译流程 | Google 2409.06790 | 验证 P0–P5 顺序；P2 自评用 GEMBA-MQM 式 span 输出 |

**必须自己造（现有项目都没有）**

1. **逐字节保真的回写**：`raw` 原文串 + 文本节点区间 + 从后往前替换；验收标准"非文本节点零 diff"。现有工具全部重排或让模型回填，无法复用。
2. **ruby 语义判定**：读音 ruby 删除、当て字/義訓/人名特殊读法保留并加括注；没有现成工具做这个分类，需词典 + 规则 + 模型兜底。
3. **诡计保护机制**：`gender: hidden` 禁用性别代词、双关/字谜保留原文+译注、`E-AMB` 一票否决；学术与开源均无先例，只能自研。
4. **风险分级路由与预算**：按对话密度、敬语密度、术语密度、风险标签打分，决定跑几遍；这是成本可控的关键。
5. **术语的确定性执行**：`must` 级 forbidden 词零出现、人名全书唯一、数字集合包含关系；不能只靠 prompt。
6. **竖排→横排的 CSS 覆盖层**：不改原 CSS，另加 `translator.css`，同时翻转 `page-progression-direction`；未找到开源先例。
7. **中文双语审校 UI**：Tolmach 有类似三栏审校台，但面向 en→ru、无推理风险队列；交互需自研。

**坑（按踩中概率排序）**

- **让 LLM 回填 XML**（oomol 路线）：模型一旦少一个标签/改一个属性，格式就坏，且重试也未必修好；保真不能交给生成模型。
- **走 Calibre 转换管线**（Ebook Translator 路线）：格式覆盖广，但中间表示会重写 HTML/CSS，ruby、`epub:type`、注释大概率丢失（推断）。
- **只翻 `<p>`**（bbm 默认）：标题、图注、脚注、列表、`alt` 全会漏；必须做"可译元素白名单 + 体检报告"。
- **逐句翻译**：语篇错误显著增加（Karpinska），且中文合并句会破坏对齐。
- **纯提示词术语表**：模型会漂移；WMT 术语赛道反复证明需要约束或后校验。
- **整本书塞进长上下文**：APE 论文显示开源模型对长上下文敏感、无关段落会干扰；窗口+摘要更稳。
- **用 COMET 当发布门**：文学/创造性维度相关性差（Creativity Bias），且 ja→zh 参考译文稀缺。
- **见 `encryption.xml` 就报 DRM**：字体混淆很常见，会误杀大量正常书；按 `license.lcpl` / RetrievalMethod 分级。
- **complex ruby**：浏览器与阅读器支持差，青空文庫已弃用；遇到就降级，不要建模。
- **竖排 CSS 半套**：只改 `writing-mode` 不改 `page-progression-direction`，或 XHTML 没 link CSS，会在 KDP 上翻车（Zenn 实测）。
- **版权**：只处理合法获得/公有领域副本；黄金集用青空文庫需逐篇确认死后 70 年规则。

**开放问题（建议作者拍板）**：双语对照版是否作为 v1 输出（现有工具多为双语，但排版成本高）；译注密度默认阈值；是否用本地模型跑 P1 草稿以降本。

---

### 核查清单（便于复核）

- 工具数据：`https://api.github.com/repos/{owner}/{repo}`（star / license / pushed_at），2026-11-18。
- 规范文本：EPUB 3.3 / 3.4、Ruby Annotation、CSS Writing Modes 3、EPUB SSV 1.1（均为 w3.org）。
- 论文：ACL Anthology 与 arXiv 页面逐条打开核对标题/作者/年份；预印本已标注。
- 明确未核实：各工具源码级的 ruby/内联标签处理；Tolmach 的 EPUB 输出保真度；Immersive Translate 的文件翻译内部实现；Calibre 管线的具体重写行为（标为【推断】）。
