---
name: competitor_product_deep_dive
description: Deeply analyze one Amazon competitor ASIN with SellerSprite, Sif, reviews, and Reddit VOC; use for single-product breakout teardown, user/structure analysis, Hsia learnings, and explicit no-copy boundaries.
---

# 爆款深度拆解 Skill

## What It Does

围绕用户指定的一个 Amazon 竞品 ASIN 做产品研发级深拆，结合 SellerSprite 商品与评论证据、Sif ASIN 信号和 Reddit VOC，回答六个问题：

1. 这个款为什么卖？
2. 核心用户是谁？
3. 结构特征是什么？
4. 好评和差评说明了什么？
5. Hsia 能学什么？
6. 不应该照搬什么？

输出面向商品企划、设计、版型、材料和研发评审。它不是品类趋势报告，也不是多竞品排行榜；只围绕一个 ASIN 建立“产品机制 → 用户任务 → 评论验证 → 社区语境 → Hsia 决策”的证据链。

## When To Use

- 用户要求“爆款深度拆解”“单款竞品拆解”“单 ASIN 深拆”或“为什么这个款卖得好”。
- 用户给出 Amazon ASIN 或商品链接，希望分析核心用户、产品结构和评论反馈。
- 用户要求回答 Hsia 可以借鉴什么、哪些设计或做法不能照搬。
- 用户要求把 Amazon 评论与 Reddit 用户讨论交叉验证。
- 用户输入类似“深拆 Amazon US ASIN B0XXXXXXXXX，回答为什么卖、谁在买、结构特点和 Hsia 能学什么”。

## Required Inputs

| 字段 | 说明 |
| --- | --- |
| marketplace | Amazon 站点，例如 Amazon US / 美国站(com) |
| asin | 目标竞品的 10 位 Amazon ASIN；也可从用户提供的 `/dp/{ASIN}` 商品链接中提取 |

## Optional Defaults

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| brand | Hsia / 遐 | “能学什么/不能照搬什么”默认面向的自有品牌 |
| category |  | 优先从 SellerSprite ASIN 详情的类目路径推断，不要求用户预先填写 |
| review_sample_size | 500 | 每个星级组的去重评论读取安全上限；运行时从第 1 页自动翻页，优先读完 SellerSprite 可访问评论 |
| report_image_limit | 60 | 报告最多展示的去重评论区买家返图数；优先覆盖更多不同评论，再补同一评论的多张图 |
| reddit_post_limit | 20 | 每个 Reddit 查询的帖子目标数 |
| reddit_detail_limit | 8 | 进入详情页补充评论的帖子数 |
| reddit_comments_per_post | 20 | 每个 Reddit 帖子的评论样本上限 |
| time_range | year | 仅用于 Reddit VOC 默认观察最近一年；Amazon 评论不套用此时间窗，读取 SellerSprite 可访问的完整历史 |

## Missing Params

如果用户提供 Amazon 商品链接，先从 `/dp/`、`/gp/product/` 或链接中的 10 位 ASIN 自动提取 `asin`。只有既没有可识别 ASIN、也没有可解析商品链接时才调用 `ask_user`。

如果缺少 `marketplace`，先从域名推断站点，例如 amazon.com → Amazon US；无法推断时再调用 `ask_user`。不要因为缺少 `category`、竞品品牌或产品标题而反问，这些字段应先由 `sellersprite_asin_detail` 获取。

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | 加载当前 Skill |
| ask_user | system | 缺少 ASIN 或站点且无法推断时询问用户 |
| respond_to_user | system | 回答非任务型问题或解释当前状态 |
| build_competitor_product_report_data | required | 将单 ASIN 商品、评论、Sif 与 Reddit 证据编译为版本化、有界的 CompetitorProductReportData |
| render_html_report | required | 只基于 CompetitorProductReportData 与展示指令生成最终自包含 HTML 深拆报告 |
| synthesize_artifact | system | LangGraph 最终节点；发布已渲染的爆款深度拆解产物，不由 Planner 调用 |
| sellersprite_asin_detail | required | 获取目标商品身份、品牌、标题、主图、类目、价格、评分、变体、尺寸和 Listing 属性 |
| sellersprite_review | required | 一次调用内部分组翻页，完整获取正负评论、尺码/结构反馈和评论媒体证据 |
| sellersprite_keepa_info | conditional | 补充价格、BSR、评分数、卖家、父子体和生命周期历史，不把趋势等同因果 |
| sellersprite_asin_sales_trend | conditional | 需要验证销量趋势、常青性、季节性或父子体表现时使用 |
| sellersprite_product_research | conditional | ASIN 详情缺少变体、属性或图片字段时补充商品证据 |
| sif_market_get_asin_keyword_signals | required | 获取竞品主要需求词和流量承接背景，用于解释“为什么被发现和购买” |
| sif_ops_get_asin_sales_list | conditional | 获取 ASIN/颜色/尺码维度销量代理，识别真正承接需求的变体 |
| sif_ops_get_asin_sales_trend | conditional | 补充变体月度趋势和季节性证据 |
| reddit_voc | required | 获取品牌、产品任务、使用场景和品类痛点的社区用户语言 |
| sellersprite_market_research | disallowed | 本 Skill 专注单 ASIN，不扩展成品类市场趋势报告 |
| sellersprite_market_product_concentration | disallowed | 本 Skill 不做头部商品排行榜或集中度分析 |
| amazon_shelf | disallowed | 商品和评论证据统一使用 SellerSprite，避免混入口径不同的抓取结果 |
| tiktok_social | disallowed | 当前版本只加入 Reddit VOC，不扩展 TikTok 社媒分析 |
| media_rankings | disallowed | 当前版本不引入媒体榜单或网页文章 |

## Recommended Tool Use

1. 检查并标准化 `marketplace`、`asin`；ASIN 统一大写。不要要求用户补充 SellerSprite 能返回的品牌、标题或类目。
2. 先调用 `sellersprite_asin_detail`。确认返回 ASIN 与目标一致，保留主图、标题、品牌、类目路径、价格、评分、评论量、父子体、变体、尺寸重量、材料/属性、badge 和可用 Listing 字段。
3. 对目标 ASIN 只调用一次 `sellersprite_review`，不要传 `starList`。单 ASIN 深拆运行时会在一次工具结果内部拆成低星 `[1,2,3]` 和高星 `[4,5]` 两组，对每组从第 1 页自动递增 `page`、跨页去重，直到达到该组 `source_total`、`review_sample_size` 安全上限，或遇到空页、重复页、接口错误、100 页硬保护。不要给 Amazon 评论传入 Reddit 的 `time_range`，也不要为了高低星再次调用相同 ASIN。
4. 读取一次工具结果中的 `review_sampling.buckets.low_star` 与 `review_sampling.buckets.high_star`，分别记录 `source_total`、`collected_unique_count`、`coverage_rate`、`page_count`、`complete` 和 `stop_reason`。只有两个分组都 `complete=true` 才能写“已读完可访问评论”；否则必须说明未覆盖数量和停止原因，不能把首屏/首几页称为完整样本。保留每条评论的星级、日期、标题、正文、尺码/颜色 SKU 和媒体 URL；不要把商品页总评分数、SellerSprite 可访问总数和实际读取数混为一谈。
5. 数据收集完成后结束 Planner 阶段。LangGraph 的 `report_data_builder` 节点调用 `build_competitor_product_report_data`，把完整评论证据、`report_image_limit` 和有界 `metric_facts` 编译进版本化、有界的 CompetitorProductReportData；随后 `data_analysis` 只从固定竞品指标目录选择可算指标并由脚本校验计算，`insight_synthesis` 只把有证据的一级/二级指标组织成“观察 → 解释 → 产品影响 → 研发动作”并绑定真实 `evidence_ids`，`chart_render` 只读取有界 `chart_specs` 并固定调用本机 Flint MCP，`html_render` 只接收增强后的对象、`insight_narrative`、已编译图表与展示指令。运行时从评论 `images` 字段去重选图，并在模板的 `INSIGHT_AGENT_REVIEW_GALLERY` 锚点注入唯一一个“评论区买家返图”画廊：先覆盖不同评论，再补同一评论多图，最多 `report_image_limit` 张。不得拿商品主图、视频缩略图或模型生成图片冒充评论返图。
6. 调用 `sif_market_get_asin_keyword_signals`，只用于识别竞品承接的核心需求词、自然/付费依赖和需求入口。调用 `sif_ops_get_asin_sales_list` 或趋势工具时，把数据写成销量代理/趋势证据，不宣称后台真实销量。
7. 需要判断生命周期或价格/排名稳定性时调用 `sellersprite_keepa_info` 或 `sellersprite_asin_sales_trend`。不要仅凭 BSR、评论数或一段趋势断言某个结构导致销量。
8. 商品身份明确后调用 `reddit_voc`，依次使用以下查询层级：
   - 第一层：`品牌 + 产品系列/标题中的稳定型号词`，寻找该竞品直接讨论。
   - 第二层：`品牌 + 末级品类`，寻找品牌级体验和口碑。
   - 第三层：`末级品类 + 核心用户任务/痛点`，补充相邻用户语境。
   Reddit 没有直接提及 ASIN 时，必须把证据标记为“品牌级”或“品类邻近 VOC”，不得冒充该商品买家反馈。
9. 将“核心用户”写成证据支持的任务型用户群，不编造年龄、收入或人口画像。至少描述：身体/适配需求、购买任务、穿着场景、当前替代方案、最怕失败的体验。
10. 将结构特征拆成：覆盖/轮廓系统、支撑系统、调节与穿脱、材料与工艺、尺码/变体、衣下效果。每条标记证据等级：`商品明确字段`、`品牌 claim`、`图片可见`、`评论验证`、`Reddit 邻近 VOC`、`分析推断`。
11. 用证据链回答“为什么卖”：需求入口 → 用户任务 → 产品解法 → 评论验证 → 热度/趋势背景。相关性不能写成因果；证据不足时使用“可能”“待验证”。
12. 将 Hsia 结论分成三组：`可迁移原则`、`需要样衣验证`、`不应照搬`。不应照搬至少说明：竞品既有痛点、依赖特定品牌资产/供应链的做法、与 Hsia 用户/版型不匹配的结构、未经验证的 claim、可能形成外观同质化的识别性设计。不要把本报告写成法律侵权判断。
13. 证据足够后，Planner 停止发出工具调用，表示源数据阶段完成。运行时自动执行 `report_data_builder -> data_analysis -> insight_synthesis -> chart_render -> html_render ->（report_review 与 report_red_team 并行）-> approval_join -> 必要时 html_revision -> synthesize_artifact`，并使用随 Skill 加载的 `assets/report-template.html` 作为单 ASIN 产品拆解结构合同。事实 `report_review` 与独立 `report_red_team` 同时执行并由 `approval_join` 汇合；任一分支首轮未通过时返工并同时开始第二轮，第二轮仍未通过时再返工一次并直接发布，不发起第三轮审批或红队。Planner 不调用这些报告节点（包括 insight_synthesis、report_review、report_red_team 与 approval_join）。`chart_render` 的单图失败只触发确定性图表降级。必须填充模板、保留全部 `data-required-section` 和唯一的 `INSIGHT_AGENT_REVIEW_GALLERY` 注入锚点；HTML 失败、模板章节缺失或出现重复返图模块时暴露错误，不生成通用报告兜底。
14. `report_red_team` 不获得源数据工具，只依据当前 HTML、完整裁剪后的 ReviewReportData 与本 Skill 合同在当轮给出 approve/revise；证据不足时收窄、改写或移除当前结论，补数建议仅留给下一次任务，不触发本轮 Builder 或报告链重跑。

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| product_identity | sellersprite_asin_detail | always | 1 | block | call_missing_tool | 缺少目标商品身份、主图和基础属性时不得生成单品深拆 |
| review_base | sellersprite_review | always | 1 | block | call_missing_tool | 一次成功结果必须内含低星与高星两个分页分组；缺少评论结果时不得回答好评、差评、核心用户或已验证结构痛点 |
| review_coverage | sellersprite_review | always | 1 | warn | continue_with_gap | 报告必须从单次结果披露两个星级组的可访问总数、去重实读数、覆盖率、页数、是否完整和停止原因 |
| asin_keyword_signals | sif_market_get_asin_keyword_signals | always | 1 | warn | continue_with_gap | 缺少 ASIN 关键词信号时不得断言商品依靠哪些需求词或流量结构成功 |
| asin_sales_proxy | sif_ops_get_asin_sales_list | always | 1 | warn | continue_with_gap | 缺少销量代理时只能用评分、评论量、badge 和排名描述公开热度 |
| reddit_user_voc | reddit_voc | always | 1 | warn | continue_with_gap | Reddit 为空时必须说明未找到直接或邻近社区 VOC，不得编造用户讨论 |
| competitor_product_report_data | build_competitor_product_report_data | always | 1 | block | call_missing_tool | 最终 HTML 前必须先把本轮源证据编译为 CompetitorProductReportData，禁止原始 MCP 结果直送 renderer |
| final_html_report | render_html_report | always | 1 | block | call_missing_tool | 最终产物必须只基于 CompetitorProductReportData，并满足随 Skill 提供的 HTML 模板全部必需章节 |

## Output Rules

- 最终报告必须逐条回答六个问题：为什么卖、核心用户、结构特征、好评/差评、Hsia 能学什么、不应该照搬什么。
- Renderer 只能消费 `competitor_product_report_data.v1` 与展示指令；不得接收原始 MCP/tool results。
- 必须保留模板定义的 `executive`、`product-baseline`、`positioning`、`product-system`、`fit-voc`、`comparison`、`genes`、`hsia-actions` 八个章节。某项无证据时省略依赖它的行、结论或局部模块，不生成证据缺口章节。
- 首屏必须展示商品主图、品牌、标题、ASIN、价格、评分、评论量、类目和一句话产品判断；字段缺失时明确标注，不使用替代图片。
- “为什么卖”至少给出三层证据：商品/结构证据、评论证据、需求或社区语境；缺少任一层时降低置信度。
- 核心用户只能基于评论 SKU/场景、商品定位和 Reddit 语言归纳为任务型用户，不得虚构年龄、职业、收入或人群规模。
- 好评与差评必须分开，分别列主题、实际样本数、代表性证据、可能根因和置信度；单条评论不得扩写为普遍结论。
- 评论章节和首屏样本摘要必须读取 `review_sampling.buckets`，分别展示高星与低星组的 `可访问总数 / 去重实读数 / 覆盖率 / 页数`。仅当两组 `complete=true` 时才可声明“已读完 SellerSprite 可访问评论”；达到安全上限不等于读完。
- 评论分析必须使用报告输入中全部 `data.items`，不得只取前 12 条、首屏、带图评论或少数代表评论后再推断主题频次。代表性引文可以精简展示，但主题计数的分母必须是全部去重实读评论。
- `fit-voc` 最终只能有一个由运行时注入的“评论区买家返图”画廊。模型必须保留模板中的 `INSIGHT_AGENT_REVIEW_GALLERY` 锚点，不得自行生成返图画廊、返图卡片或重复的评论图片 `<img>`。运行时画廊负责展示去重图片数、可用去重图片总数、带图评论数、星级、评论标题与可用 SKU；图片只能来自 `sellersprite_review.data.items[].images`。
- 商品评论与 Reddit VOC 必须分源呈现。只有明确品牌/产品提及时才能称为竞品直接 VOC，品类讨论必须标为邻近证据。
- 结构判断必须区分可观察事实与推断。没有拆解图、实物测量或明确材料字段时，不得断言内部结构、克重、弹性参数或工艺规格。
- Hsia“能学什么”写可迁移的用户问题、设计原则和验证实验，不直接复制竞品外观、结构组合、文案或 claim。
- “不应该照搬”必须说明不复制的对象、证据理由、潜在产品风险和 Hsia 替代方向；不得给出未经法律检索的侵权结论。
- 每个重要判断附邻近证据锚点，例如 `[E05 · sellersprite_review · ASIN · 2星]` 或 `[R03 · Reddit · 品类邻近VOC]`。
- 不得编造销量、搜索量、人口画像、市场规模、评论原文、商品图片、结构参数或因果关系。
- 报告不扩展成品类趋势、Top 商品排行榜、广告投放、Listing SEO、A+、促销、库存或 FBA 成本建议。
- Evidence Contract 的 warn 缺口只冻结依赖它的结论并保留在内部运行元数据，不进入最终 HTML。

### HTML Report Style Reference

- 使用随 Skill 提供的 `assets/report-template.html`。模板负责固定阅读层级和必需章节，LLM 负责用本轮单 ASIN 证据替换全部占位内容。
- 输出完整、自包含、单文件 HTML，使用内联 CSS 和少量内联 JavaScript；不加载外部脚本、样式、字体或 CDN。
- 页面采用单栏产品评审稿布局，不生成右侧目录、侧边栏或营销 Hero。桌面正文最大宽度约 1180px，移动端自然单列。
- 首屏使用“商品主图 + 商品身份 + 一句话判断 + 六问结论摘要”。商品图保持完整可辨识，使用工具证据中的 URL，并显示来源。
- 正文固定包含：`为什么卖`、`核心用户`、`结构特征`、`好评与差评`、`Reddit VOC`、`Hsia 能学什么`、`不应该照搬`；验证动作放在对应结论附近，不单设缺口章节。
- 用“需求入口 → 用户任务 → 产品解法 → 评论验证 → 商业背景”流程图表达成功机制；使用 HTML/CSS 或内联 SVG，不依赖图表库。
- 结构特征使用矩阵表，列为：系统、可观察特征、用户作用、支持证据、证据等级、待验证项。
- 好评/差评并排展示，移动端上下排列；每侧显示样本数、主题频次、严重度、代表性短证据和可能根因。
- 好评/差评与痛点根因矩阵之后保留 `INSIGHT_AGENT_REVIEW_GALLERY` 锚点，由运行时在此注入唯一的响应式返图画廊。模型不得设计或输出第二个图片区。
- Reddit 区分“商品直接提及”“品牌级讨论”“品类邻近 VOC”，使用不同标签，禁止混写。
- Hsia 结论使用三栏：绿色“可迁移原则”、橙色“需要验证”、红色“不应照搬”；每条包含理由和下一步样衣/用户验证动作。
- 页面使用白底、深色正文、轻边框；橙色强调机会、绿色表示证据支持、红色表示风险、灰色表示待验证。避免卡片套卡片。
- 不展示工具成功率、原始 JSON、执行按钮或调试信息。
