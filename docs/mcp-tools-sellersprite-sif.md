# SellerSprite 与 SIF MCP Tool 输入输出总表

> 生成日期：2026-07-13  
> 数据依据：本机当前 MCP connector metadata + Insight Agent 运行时 catalog 实测  
> Connector 可见：SellerSprite 43 个，SIF 27 个，共 70 个  
> Insight Agent 实际注册：SellerSprite 43 个，SIF 26 个，共 69 个

## 1. 阅读说明

- **MCP 名称**：Codex/MCP connector 中的完整名称，例如 `mcp__sif__market_get_keyword_demand`。
- **Agent 名称**：Insight Agent 注册后使用 provider 前缀的名称，例如 `sif_market_get_keyword_demand`。
- 当前项目 `.env` 设置 `SIF_MCP_TOOLS=*`；SellerSprite 未单独收窄工具列表，运行时默认 `SELLERSPRITE_MCP_TOOLS=*`。
- SellerSprite connector 与项目运行时均注册 43 个工具。SIF schema/connector 可见 27 个，但项目适配器 `build_sif_tool_catalog()` 会显式排除 `ping`；因此当前 Agent 实际可选工具总数为 69 个。
- 输入部分来自当前 MCP 工具声明，字段名后带问号表示可选；没有问号的字段为必填。
- 两个 MCP 当前都把顶层返回类型声明为 `CallToolResult`。SIF 在工具描述中进一步列出了大部分业务返回字段；SellerSprite 多数工具只描述返回内容类别，没有提供机器可读的字段级 `outputSchema`。本文忠实保留这个差异，不推测未声明字段。
- 实际返回通常还可能包含 MCP 包装、状态、错误信息或 provider 新增字段。生产代码应做缺失字段兼容，不应只凭本文硬编码完整响应对象。

## 2. 工具索引

| Provider | Connector 可见 | Insight Agent 已注册 | 差异 |
| --- | ---: | ---: | --- |
| SellerSprite | 43 | 43 | 无 |
| SIF | 27 | 26 | 项目适配器显式排除 `ping` |

### 2.1 SellerSprite（43）

| 分类 | 工具 |
| --- | --- |
| ABA | `aba_research_monthly`、`aba_research_trend`、`aba_research_weekly` |
| ASIN 与销量 | `asin_coupon_trend`、`asin_detail`、`asin_detail_with_coupon_trend`、`asin_prediction`、`asin_sales_trend`、`bsr_prediction`、`keepa_info` |
| 商品发现 | `competitor_lookup`、`product_node`、`product_research` |
| 关键词与趋势 | `google_trend`、`keyword_miner`、`keyword_order`、`keyword_research`、`keyword_research_trends` |
| 类目市场 | `market_brand_concentration`、`market_ebc_distribution`、`market_listing_date_distribution`、`market_listing_trend_distribution`、`market_price_distribution`、`market_product_concentration`、`market_product_demand_trend`、`market_rating_distribution`、`market_ratings_count_distribution`、`market_research`、`market_research_statistics`、`market_seller_concentration`、`market_seller_country_distribution`、`market_seller_type_concentration` |
| 评论 | `review` |
| 商标 | `trademark_country_list`、`trademark_detail`、`trademark_list`、`trademark_stats` |
| 流量 | `traffic_extend`、`traffic_keyword`、`traffic_keyword_stat`、`traffic_listing`、`traffic_listing_stat`、`traffic_source` |

### 2.2 SIF（27）

| 分类 | 工具 |
| --- | --- |
| 广告 | `ads_get_ad_group_keyword_breakdown`、`ads_get_ad_group_traffic_trend`、`ads_get_asin_ad_feature_profile`、`ads_get_asin_ad_historical_feature_profile`、`ads_get_asin_ad_structure`、`ads_get_asin_ad_traffic_trend`、`ads_get_asin_ad_window_feature_profile`、`ads_get_asin_campaign_changes`、`ads_get_asin_campaign_contribution_overview`、`ads_get_campaign_contribution_breakdown`、`ads_get_campaign_structure`、`ads_get_campaign_traffic_trend` |
| 运营与流量 | `analyze_traffic_anomaly`、`ops_get_asin_sales_list`、`ops_get_asin_sales_trend`、`ops_get_asin_traffic_trend`、`ops_get_asin_traffic_trend_detail`、`ops_get_listing_keyword_distribution`、`ops_get_listing_traffic_overview`、`ops_get_listing_traffic_structure` |
| 市场与关键词 | `market_get_asin_keyword_signals`、`market_get_keyword_competition`、`market_get_keyword_demand`、`market_get_keyword_history`、`market_get_keyword_root_trend` |
| 系统 | `ping`、`sif_catalog` |

## 3. SellerSprite 工具

> SellerSprite 输出说明以当前 MCP 的自然语言描述为准。若需要稳定落库，建议先保存一次真实响应，再为项目建立版本化 response schema。

### 3.1 `aba_research_monthly`

- MCP 名称：`mcp__sellersprite__aba_research_monthly`
- Agent 名称：`sellersprite_aba_research_monthly`
- 分类：ABA
- 功能：用于在指定 Amazon 站点和时间点（按月）， 系统性发现【热门 / 异动 / 增长 / 潜力】关键词的分析工具。

**输入**

```ts
type Input = {
  request:{

    // 查询月份, 格式: yyyyMM
    date?: string;

    // 类目列表
    departments?: Array<string>;

    // 排除关键词
    excludeKeywords?: string;

    // 包含关键词
    includeKeywords?: string;

    // country code
    marketplace: string;

    // 最大点击量
    maxClicks?: number;

    // 最大转化占比
    maxConversionRate?: number;

    // 最大展示量
    maxImpressions?: number;

    // 最大点击集中度
    maxMonopolyClickRate?: number;

    // 最大排名增长率
    maxRankGrowthRate?: number;

    // 最大SPR
    maxSPR?: number;

    // 最大排名
    maxSearchRank?: number;

    // 最大搜索量
    maxSearches?: number;

    // 最大标题密度
    maxTitleDensity?: number;

    // 最大单词数
    maxWordCount?: number;

    // 最小点击量
    minClicks?: number;

    // 最小转化占比
    minConversionRate?: number;

    // 最小展示量
    minImpressions?: number;

    // 最小点击集中度
    minMonopolyClickRate?: number;

    // 最小排名增长率
    minRankGrowthRate?: number;

    // 最小SPR
    minSPR?: number;

    // 最小排名
    minSearchRank?: number;

    // 最小搜索量
    minSearches?: number;

    // 最小标题密度
    minTitleDensity?: number;

    // 最小单词数
    minWordCount?: number;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searches: 月搜索量
      // - keywordsIsHide: 月购买量
      // - searches_growth: 增长率
      // - yearly_growth_rate: 同比增长率
      // - growth_rate_trend_min: 近3个月增长率
      // - monopoly_click_rate: 点击集中度
      // - goods_value: 货流值
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 查询方式, 默认: 2
    // 可选值(必须严格使用下列数字值之一):
    // 1: 热门市场
    // 2: 异动市场
    // 3: 持续增长市场
    // 4: 快速飙升市场
    // 5: 潜力市场
    // 6: 长尾市场
    // 禁止使用未列出的值。
    searchModel?: number;

    // 每页条数
    size?: number;

  };
}
```

**输出**

用于在指定 Amazon 站点和时间点（按月），
系统性发现【热门 / 异动 / 增长 / 潜力】关键词的分析工具。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.2 `aba_research_trend`

- MCP 名称：`mcp__sellersprite__aba_research_trend`
- Agent 名称：`sellersprite_aba_research_trend`
- 分类：ABA
- 功能：ABA选品-关键词的趋势数据，包含：ABA排名和搜索量

**输入**

```ts
type Input = {

  keyword: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

  // 时间粒度
  // 可选值(仅填写字段名):
  // - W: 周
  // - M: 月
  timeGranularity?: string;

}
```

**输出**

ABA选品-关键词的趋势数据，包含：ABA排名和搜索量

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.3 `aba_research_weekly`

- MCP 名称：`mcp__sellersprite__aba_research_weekly`
- Agent 名称：`sellersprite_aba_research_weekly`
- 分类：ABA
- 功能：用于在指定 Amazon 站点和时间点（按周）， 系统性发现【热门 / 异动 / 增长 / 潜力】关键词的分析工具。

**输入**

```ts
type Input = {
  request:{

    // 查询日期, 格式: yyyyMMdd, 天必须为当周所在的周六
    date?: string;

    // 类目列表
    departments?: Array<string>;

    // 排除关键词
    excludeKeywords?: string;

    // 包含关键词
    includeKeywords?: string;

    // country code
    marketplace: string;

    // 最大点击量
    maxClicks?: number;

    // 最大转化占比
    maxConversionRate?: number;

    // 最大展示量
    maxImpressions?: number;

    // 最大点击集中度
    maxMonopolyClickRate?: number;

    // 最大排名增长率
    maxRankGrowthRate?: number;

    // 最大SPR
    maxSPR?: number;

    // 最大排名
    maxSearchRank?: number;

    // 最大搜索量
    maxSearches?: number;

    // 最大标题密度
    maxTitleDensity?: number;

    // 最大单词数
    maxWordCount?: number;

    // 最小点击量
    minClicks?: number;

    // 最小转化占比
    minConversionRate?: number;

    // 最小展示量
    minImpressions?: number;

    // 最小点击集中度
    minMonopolyClickRate?: number;

    // 最小排名增长率
    minRankGrowthRate?: number;

    // 最小SPR
    minSPR?: number;

    // 最小排名
    minSearchRank?: number;

    // 最小搜索量
    minSearches?: number;

    // 最小标题密度
    minTitleDensity?: number;

    // 最小单词数
    minWordCount?: number;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searches: 月搜索量
      // - keywordsIsHide: 月购买量
      // - searches_growth: 增长率
      // - yearly_growth_rate: 同比增长率
      // - growth_rate_trend_min: 近3个月增长率
      // - monopoly_click_rate: 点击集中度
      // - goods_value: 货流值
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 搜索增长率
    rankGrowthRate?: number;

    // 搜索增长量
    rankGrowthValue?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 搜索模式
    // 可选值(仅填写字段名):
    // 1: 热门市场
    // 2: 异动市场
    // 3: 持续增长市场
    // 4: 快速飙升市场
    // 5: 潜力市场
    // 6: 长尾市场
    // 禁止使用未列出的值。
    searchModel?: number;

    // 每页条数
    size?: number;

  };
}
```

**输出**

用于在指定 Amazon 站点和时间点（按周），
系统性发现【热门 / 异动 / 增长 / 潜力】关键词的分析工具。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.4 `asin_coupon_trend`

- MCP 名称：`mcp__sellersprite__asin_coupon_trend`
- Agent 名称：`sellersprite_asin_coupon_trend`
- 分类：ASIN 与销量
- 功能：查询指定 ASIN 在 Amazon 指定市场下的优惠价格信息。 返回 ASIN 原价、优惠类型（金额 / 百分比）、优惠金额， 以及计算后的最终成交价格。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

查询指定 ASIN 在 Amazon 指定市场下的优惠价格信息。
返回 ASIN 原价、优惠类型（金额 / 百分比）、优惠金额，
以及计算后的最终成交价格。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.5 `asin_detail`

- MCP 名称：`mcp__sellersprite__asin_detail`
- Agent 名称：`sellersprite_asin_detail`
- 分类：ASIN 与销量
- 功能：查询 Amazon 单个商品（ASIN）的完整详情信息。 返回商品的基础信息、类目结构、价格与促销、 评分与评论、卖家与配送方式、变体信息、 Listing 页面质量得分以及 Best Seller、Amazon's Choice 等运营标识。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

查询 Amazon 单个商品（ASIN）的完整详情信息。
返回商品的基础信息、类目结构、价格与促销、
评分与评论、卖家与配送方式、变体信息、
Listing 页面质量得分以及 Best Seller、Amazon's Choice 等运营标识。

适用于以下场景：
- 单 ASIN 商品深度分析
- 竞品拆解与对比
- 商品进入可行性评估
- 商品详情页质量与风险判断

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.6 `asin_detail_with_coupon_trend`

- MCP 名称：`mcp__sellersprite__asin_detail_with_coupon_trend`
- Agent 名称：`sellersprite_asin_detail_with_coupon_trend`
- 分类：ASIN 与销量
- 功能：查询指定 ASIN 在 Amazon 指定市场下的完整商品详情信息， 包括基础属性、类目、评分、卖家、价格、配送方式等， 并同时返回该 ASIN 的优惠（Coupon）价格趋势数据， 用于分析真实成交价变化及促销策略。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

查询指定 ASIN 在 Amazon 指定市场下的完整商品详情信息，
包括基础属性、类目、评分、卖家、价格、配送方式等，
并同时返回该 ASIN 的优惠（Coupon）价格趋势数据，
用于分析真实成交价变化及促销策略。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.7 `asin_prediction`

- MCP 名称：`mcp__sellersprite__asin_prediction`
- Agent 名称：`sellersprite_asin_prediction`
- 分类：ASIN 与销量
- 功能：查询指定 ASIN 在 Amazon 对应市场的商品基础信息及销量与销售额预测数据。 该接口返回 ASIN 近14个月的销量数据，并提供按日维度与月维度汇总的销量、销售额、价格及 BSR 等预测指标。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

查询指定 ASIN 在 Amazon 对应市场的商品基础信息及销量与销售额预测数据。
该接口返回 ASIN 近14个月的销量数据，并提供按日维度与月维度汇总的销量、销售额、价格及 BSR 等预测指标。

适用于以下场景：
- ASIN 销量趋势分析与判断
- 商品增长性与生命周期判断
- 竞品销售表现对比分析
- 选品评估

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.8 `asin_sales_trend`

- MCP 名称：`mcp__sellersprite__asin_sales_trend`
- Agent 名称：`sellersprite_asin_sales_trend`
- 分类：ASIN 与销量
- 功能：查询指定 ASIN 的月度销售趋势数据 包含 ASIN 详细信息(返回商品的基础信息、类目结构、价格与促销、评分与评论、卖家与配送方式、变体信息、Listing 页面质量得分以及 Best Seller、Amazon's Choice 等运营标识) 以及父体和子体的销量、销售额、历史价格、平均价格等历史趋势指标

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

查询指定 ASIN 的月度销售趋势数据
包含 ASIN 详细信息(返回商品的基础信息、类目结构、价格与促销、评分与评论、卖家与配送方式、变体信息、Listing 页面质量得分以及 Best Seller、Amazon's Choice 等运营标识)
以及父体和子体的销量、销售额、历史价格、平均价格等历史趋势指标

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.9 `bsr_prediction`

- MCP 名称：`mcp__sellersprite__bsr_prediction`
- Agent 名称：`sellersprite_bsr_prediction`
- 分类：ASIN 与销量
- 功能：根据 Amazon 指定市场下的一级类目节点和大类 BSR 排名， 预测该 BSR 在当前类目中的日销量和近 30 天销量， 并返回对应 BSR 区间的销量预测明细， 用于评估类目热度和市场容量。

**输入**

```ts
type Input = {

  bsr: number;

  // 一级类目节点，查产品类目返回
  categoryId: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

根据 Amazon 指定市场下的一级类目节点和大类 BSR 排名，
预测该 BSR 在当前类目中的日销量和近 30 天销量，
并返回对应 BSR 区间的销量预测明细，
用于评估类目热度和市场容量。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.10 `competitor_lookup`

- MCP 名称：`mcp__sellersprite__competitor_lookup`
- Agent 名称：`sellersprite_competitor_lookup`
- 分类：商品发现
- 功能：查询 Amazon 商品列表数据，支持按市场、月份、品牌、卖家、ASIN、类目、关键词等条件筛选， 并返回商品的销量、销售额、BSR、价格、评分、卖家、类目、变体等核心运营指标。

**输入**

```ts
type Input = {
  request:{

    // asins, 最多只支持40个，如果超过40个, 需要拆分多次请求
    asins?: Array<string>;

    // brand name
    brand?: string;

    // 关键字，基于商品标题进行匹配
    keyword?: string;

    keywordEqual?: boolean;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // "匹配方式, 默认: 2
  // 可选值(必须严格使用下列数字值之一):
  // 1: 词组匹配
  // 2: 模糊匹配
  // 3: 精准匹配
  // 禁止使用未列出的值。
  matchType?: number;
  // 查询月份, 格式: yyyyMM
  month?: string;
  // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
  nodeIdPath?: string;
  // 类目节点查询方式
  nodeIdPathEqual?: boolean;
  // 排序
  order?: {
  // 排序类型
  desc?: boolean;
  // 排序字段。
  // 可选值(仅填写字段名):
  // - total_units: 月销量
  // - total_amount: 月销售额
  // - price: 价格
  // - rating: 评分
  // - reviews: 评分数
  // - profit: 毛利
  // - reviews_rate: 留评率
  // - available_date: 上架时间
  // - questions: Q&A
  // - total_units_growth: 月销量增长率
  // - total_amount_growth: 月销售额增长率
  // - reviews_increasement: 月新增评分数
  // - bsr_rank_cv: 近7天BSR增长数
  // - bsr_rank_cr: 近7天BSR增长率
  // 禁止使用未列出的值。
  field?: string;
};
  // 页码
  page?: number;
  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
  returnFields?: string;
  // seller name
  sellerName?: string;
  // 每页条数
  size?: number;
  // 是否查询变体ASIN，如果没有明确指定则要设置成: Y
  // 可选值(仅填写字段名):
  // - Y: exclude
  // - N: include
  variation?: string;
}; }
```

**输出**

查询 Amazon 商品列表数据，支持按市场、月份、品牌、卖家、ASIN、类目、关键词等条件筛选，
并返回商品的销量、销售额、BSR、价格、评分、卖家、类目、变体等核心运营指标。

适用于以下场景：
- 选品分析（找高销量 / 高增长商品）
- 类目或关键词下的商品调研
- 竞品监控（品牌 / 卖家 / ASIN 对比）
- 市场趋势与榜单分析

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.11 `google_trend`

- MCP 名称：`mcp__sellersprite__google_trend`
- Agent 名称：`sellersprite_google_trend`
- 分类：关键词与趋势
- 功能：用于查询 Google Trends 中指定关键词在特定市场的搜索热度变化趋势。

**输入**

```ts
type Input = {
  request:{

    // 搜索来源类型（枚举值）: web, shoppingCart
    googleProp?: string;

    // 关键字
    keyword?: string;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 按照月份
    monthly?: boolean;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

  };
}
```

**输出**

用于查询 Google Trends 中指定关键词在特定市场的搜索热度变化趋势。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.12 `keepa_info`

- MCP 名称：`mcp__sellersprite__keepa_info`
- Agent 名称：`sellersprite_keepa_info`
- 分类：ASIN 与销量
- 功能：获取指定 Amazon ASIN 的完整商品画像及多维度历史趋势数据(不含有销量数据)。

**输入**

```ts
type Input = {

  asin: string;

  // 是否仅返回每天最新的一条数据
  dailyLatest?: boolean;

  // 获取数据结束时间毫秒
  endTimestamp?: number;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

  // 获取数据的开始时间毫秒
  startTimestamp?: number;

}
```

**输出**

本工具用于对单个 ASIN 进行深度分析，同时返回商品的静态基础信息
与随时间变化的核心经营指标趋势数据，适用于选品评估、竞品分析、
定价与跟卖监控、Listing 健康度分析等专业卖家场景。

返回内容包括但不限于：
  - 商品基础信息：标题、品牌、图片、ASIN 链接、商品状态、是否可售
  - 类目与排名信息：大类 / 小类 BSR、类目节点路径及其历史变化
  - 价格相关趋势：售价、成交价、划线价、黄金购物车价格历史
  - 竞争环境指标：卖家数量变化、Buy Box 卖家 ID 历史
  - 用户反馈指标：评论数、评分值的历史趋势
  - 变体与父子体关系：父 ASIN、变体 ASIN 列表
  - 物流与成本信息：FBA 费用、商品尺寸、重量、包装信息

所有趋势字段均以标准时间序列结构返回（如 timePoint: 时间戳, value: 为对应的值），
  可直接用于趋势分析、图表展示或 AI 自动解读。

适用场景示例：
  - 分析某个 ASIN 的价格、BSR 和评论趋势是否健康
  - 判断商品销量潜力及生命周期阶段（增长 / 稳定 / 衰退）
  - 监控 Buy Box 价格与卖家竞争变化
  - 理解商品在类目体系中的定位及变体结构
  - 为 AI 生成选品建议、竞品对比结论或运营决策支持

当用户问题涉及「某一个 ASIN 的详情、趋势、变化、历史表现或综合分析时，应优先使用本工具。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.13 `keyword_miner`

- MCP 名称：`mcp__sellersprite__keyword_miner`
- Agent 名称：`sellersprite_keyword_miner`
- 分类：关键词与趋势
- 功能：Amazon 高级关键词流量与竞争分析工具（卖家决策级）。

**输入**

```ts
type Input = {
  request:{

    // 亚马逊推荐词
    amazonChoice?: boolean;

    // 排除的词
    excludeKeywords?: Array<string>;

    // 过滤词根
    // 可选值(必须严格使用下列数字值之一):
    // 0: 包含所有
    // 1: 只包含词根
    // 禁止使用未列出的值。
    filterRootWord?: number;

    // 查询月份, 格式: yyyyMM
    historyDate?: string;

    // 包含的词
    includeKeywords?: Array<string>;

    // 关键词（包含该词及其相关词的初始关键词列表）
    keyword?: string;

    // 批量查询传入关键词的数据，不包含和它相关关键词的数据（精准匹配，只会返回传入的关键词数据）
    keywordList?: Array<string>;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 最大广告竞品数
    maxAdProducts?: number;

    // 最大ppc竞价
    maxBid?: number;

    // 最大点击集中度
    maxMonopolyClickRate?: number;

    // 最大均价
    maxPrice?: number;

    // 最大商品数
    maxProducts?: number;

    // 最大购买量
    maxPurchases?: number;

    // 最大购买率
    maxPurchasesRate?: number;

    // 最大评分值
    maxRating?: number;

    // 最大评分数
    maxRatings?: number;

    // 最大相关度
    maxRelevancy?: number;

    // 最大SPR
    maxSPR?: number;

    // 最大搜索量
    maxSearch?: number;

    // 最大搜索排名
    maxSearchRank?: number;

    // 最大供需比
    maxSupplyDemandRatio?: number;

    // 最大标题密度
    maxTitleDensity?: number;

    // 最大单词个数
    maxWordCount?: number;

    // 最小广告竞品数
    minAdProducts?: number;

    // 最小ppc竞价
    minBid?: number;

    // 最小点击集中度
    minMonopolyClickRate?: number;

    // 最小均价
    minPrice?: number;

    // 最小商品数
    minProducts?: number;

    // 最小购买量
    minPurchases?: number;

    // 最小购买率
    minPurchasesRate?: number;

    // 最小评分值
    minRating?: number;

    // 最小评分数
    minRatings?: number;

    // 最小相关度
    minRelevancy?: number;

    // 最小SPR
    minSPR?: number;

    // 最小搜索量
    minSearch?: number;

    // 最小搜索排名
    minSearchRank?: number;

    // 最小供需比
    minSupplyDemandRatio?: number;

    // 最小标题密度
    minTitleDensity?: number;

    // 最小单词个数
    minWordCount?: number;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searches: 月搜索量
      // - keywordsIsHide: 月购买量
      // - searches_growth: 增长率
      // - yearly_growth_rate: 同比增长率
      // - growth_rate_trend_min: 近3个月增长率
      // - monopoly_click_rate: 点击集中度
      // - goods_value: 货流值
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

  };
}
```

**输出**

Amazon 高级关键词流量与竞争分析工具（卖家决策级）。

工具综合分析以下核心维度：
1. 需求强度：搜索量、购买量、购买率
2. 竞争强度：商品数、广告竞品数、标题密度、搜索排名
3. 垄断程度：点击集中度（monopolyClickRate）、SPR
4. 成本结构：PPC 竞价区间、平均售价
5. 相关性质量：关键词与市场的相关度、词长、类目匹配
6. 商业信号：是否为 Amazon Choice 关键词

返回结果应以“是否值得做”为核心进行解读：
- 搜索量高 + 购买率高：代表真实需求强
- 商品数高但点击集中度低：代表市场分散，存在机会
- SPR 较低：代表进入成本相对友好
- PPC 竞价低于均价承受范围：代表广告可控
- 标题密度低 + 相关度高：代表 SEO 切入空间大

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.14 `keyword_order`

- MCP 名称：`mcp__sellersprite__keyword_order`
- Agent 名称：`sellersprite_keyword_order`
- 分类：关键词与趋势
- 功能：基于 ASIN 的关键词反查工具，用于分析某个或多个 ASIN 在指定时间周期内，实际参与曝光与转化的关键词表现。

**输入**

```ts
type Input = {
  request:{

    // asin list
    asins: Array<string>;

    // 转化类型
    // 可选值(仅填写字段名):
    // - E: 转化优质词
    // - S: 转化平稳词
    // - L: 转化流失词
    // - I: 无效曝光词
    conversionType?: string;

    // 回溯类型. 可选值: W/M. 当 reverseType = 'W' 时, date 必须为 yyyyMMdd 格式, 且表示当周的周六. 当 reverseType = 'M' 时, date 必须为 yyyyMM 格式.
    date: string;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searchRank: 搜索量
      // - searchRankGrowthValue: 搜索量增长值
      // - searchRankGrowthRate:搜索量增长率
      // - sumClickRate: 点击率
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 反查模式
    // 可选值(仅填写字段名):
    // - W: 周
    // - M: 月
    reverseType: string;

    // 每页条数
    size?: number;

    // 是否查询变体ASIN
    // 可选值(仅填写字段名):
    // - Y: exclude
    // - N: include
    variation?: string;

  };
}
```

**输出**

基于 ASIN 的关键词反查工具，用于分析某个或多个 ASIN
在指定时间周期内，实际参与曝光与转化的关键词表现。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.15 `keyword_research`

- MCP 名称：`mcp__sellersprite__keyword_research`
- Agent 名称：`sellersprite_keyword_research`
- 分类：关键词与趋势
- 功能：专业级 Amazon 关键词市场与选品分析工具。

**输入**

```ts
type Input = {
  request:{

    // 查询类目，见关键词选品类目接口，传递code
    departments?: Array<string>;

    // 排除的关键字
    excludeKeywords?: string;

    // 关键词
    keywords?: string;

    // 市场周期
    marketPeriod?: string;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 最大点击集中度
    maxAraClickRate?: number;

    // 最大均价
    maxAvgPrice?: number;

    // 最大PPC竞价
    maxBid?: number;

    // 最大货流值
    maxGoodsValue?: number;

    // 最大商品数
    maxProducts?: number;

    // 最大购买率
    maxPurchaseRate?: number;

    // 最大购买量
    maxPurchases?: number;

    // 最大评分值
    maxRating?: number;

    // 最大评分数
    maxRatings?: number;

    // 最大月搜索量同比增长率
    maxSearchMonthCr?: number;

    // 最大月搜索量同比增长值
    maxSearchMonthCv?: number;

    // 最大月搜索量近3个月增长率
    maxSearchNearlyCr?: number;

    // 最大月搜索量近3个月增长值
    maxSearchNearlyCv?: number;

    // 最大月搜索量
    maxSearches?: number;

    // 最大月搜索量增长率
    maxSearchesCr?: number;

    // 最大供需比
    maxSupplyDemandRatio?: number;

    // 最大单词个数
    maxWordCount?: number;

    // 最小点击集中度
    minAraClickRate?: number;

    // 最小均价
    minAvgPrice?: number;

    // 最小PPC竞价
    minBid?: number;

    // 最小货流值
    minGoodsValue?: number;

    // 最小商品数
    minProducts?: number;

    // 最小购买率
    minPurchaseRate?: number;

    // 最小购买量
    minPurchases?: number;

    // 最小评分值
    minRating?: number;

    // 最小评分数
    minRatings?: number;

    // 最小月搜索量同比增长率
    minSearchMonthCr?: number;

    // 最小月搜索量同比增长值
    minSearchMonthCv?: number;

    // 最小月搜索量近3个月增长率
    minSearchNearlyCr?: number;

    // 最小月搜索量近3个月增长值
    minSearchNearlyCv?: number;

    // 最小月搜索量
    minSearches?: number;

    // 最小月搜索量增长率
    minSearchesCr?: number;

    // 最小供需比
    minSupplyDemandRatio?: number;

    // 最小单词个数
    minWordCount?: number;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searches: 月搜索量
      // - keywordsIsHide: 月购买量
      // - searches_growth: 增长率
      // - yearly_growth_rate: 同比增长率
      // - growth_rate_trend_min: 近3个月增长率
      // - monopoly_click_rate: 点击集中度
      // - goods_value: 货流值
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

    // 新细分市场
    withYearlyGrowth?: boolean;

  };
}
```

**输出**

专业级 Amazon 关键词市场与选品分析工具。

工具基于以下核心维度进行分析：
- 市场需求：月搜索量、购买量、搜索增长趋势
- 市场竞争：商品数量、供需比、头部垄断程度
- 转化能力：购买率、点击集中度、共享转化率
- 成本结构：平均售价、PPC 竞价区间
- 成熟度判断：市场周期、新兴或成熟细分市场

返回结果应从「卖家决策角度」进行解读：
- 搜索量高 + 供需比高：代表需求强且竞争相对可控
- 搜索增长率为正：代表市场处于上升期
- 购买率高：代表关键词具备真实成交能力
- PPC 竞价低 + 售价合理：代表广告和利润空间友好
- 点击集中度低：代表头部卖家垄断程度较弱，更易切入

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.16 `keyword_research_trends`

- MCP 名称：`mcp__sellersprite__keyword_research_trends`
- Agent 名称：`sellersprite_keyword_research_trends`
- 分类：关键词与趋势
- 功能：关键词选品-关键词的趋势数据，包含：搜索量，购买量，购买率，同比增长率，环比增长率，三个月增长率

**输入**

```ts
type Input = {

  keyword: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 查询月份, 格式: yyyyMM, 默认为: nearly
  month?: string;

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

关键词选品-关键词的趋势数据，包含：搜索量，购买量，购买率，同比增长率，环比增长率，三个月增长率

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.17 `market_brand_concentration`

- MCP 名称：`mcp__sellersprite__market_brand_concentration`
- Agent 名称：`sellersprite_market_brand_concentration`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的品牌集中度情况。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的品牌集中度情况。

通过传入对应站点（国家编码）、类目节点路径及筛选条件，返回该类目中头部 Listing 的
对各品牌的商品数量、新品数量、新品销量与销售额、总体销量与销售额及其占比进行统计分析。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.18 `market_ebc_distribution`

- MCP 名称：`mcp__sellersprite__market_ebc_distribution`
- Agent 名称：`sellersprite_market_ebc_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的A+视频分布 A+ 页面与商品视频内容对销量影响的内容配置效应评估。 在指定样本商品范围内，基于商品是否配置 A+ 页面及 Listing 主图下方的视频介绍进行组合分组， 系统性刻画四种内容配置状态下的商品数量结构及其对应的销量占比， 用于量化富内容展示在不同配置组合下对销量承载能力与转化效率的实际贡献。 该指标能够揭示 A+ 页面与视频内容在提升商品表现方面的边际效应及协同关系， 区分单一内容配置与组合配置对销量提升的差异影响， 从而辅助卖家判断内容投入的优先级与回报预期， 为 Listing 内容优化与资源投入决策提供结构化依据。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的A+视频分布
A+ 页面与商品视频内容对销量影响的内容配置效应评估。
在指定样本商品范围内，基于商品是否配置 A+ 页面及 Listing 主图下方的视频介绍进行组合分组，
系统性刻画四种内容配置状态下的商品数量结构及其对应的销量占比，
用于量化富内容展示在不同配置组合下对销量承载能力与转化效率的实际贡献。
该指标能够揭示 A+ 页面与视频内容在提升商品表现方面的边际效应及协同关系，
区分单一内容配置与组合配置对销量提升的差异影响，
从而辅助卖家判断内容投入的优先级与回报预期，
为 Listing 内容优化与资源投入决策提供结构化依据。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.19 `market_listing_date_distribution`

- MCP 名称：`mcp__sellersprite__market_listing_date_distribution`
- Agent 名称：`sellersprite_market_listing_date_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品上架时间分布与新品接受度。 在指定样本商品范围内，按照商品上架距今的时间区间进行分组， 统计各时间区间内的商品数量分布及其对应的销量占比， 并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量）， 用于衡量不同上架周期商品的整体销售效率。 该指标可用于判断市场中新品与老品的销量贡献结构， 评估买家对新品的接受程度及新品打造难度， 并辅助卖家选择合适的产品生命周期切入策略。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品上架时间分布与新品接受度。
在指定样本商品范围内，按照商品上架距今的时间区间进行分组，
统计各时间区间内的商品数量分布及其对应的销量占比，
并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量），
用于衡量不同上架周期商品的整体销售效率。
该指标可用于判断市场中新品与老品的销量贡献结构，
评估买家对新品的接受程度及新品打造难度，
并辅助卖家选择合适的产品生命周期切入策略。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.20 `market_listing_trend_distribution`

- MCP 名称：`mcp__sellersprite__market_listing_trend_distribution`
- Agent 名称：`sellersprite_market_listing_trend_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品上架时间分布与生命周期。 在指定样本商品范围内，按照商品的绝对上架时间进行区间划分， 统计各时间区间内的商品上架数量及其对应的销量占比， 并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量）， 用于衡量不同上架时期产品的整体销售效率。 同时提供各时间区间商品的平均评分值， 用于评估不同产品生命周期阶段的用户认可度。 该指标可辅助分析产品生命周期特征，判断市场成熟度与长期畅销能力， 并识别新品期、成长期及长尾产品在市场中的相对竞争优势。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品上架时间分布与生命周期。
在指定样本商品范围内，按照商品的绝对上架时间进行区间划分，
统计各时间区间内的商品上架数量及其对应的销量占比，
并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量），
用于衡量不同上架时期产品的整体销售效率。
同时提供各时间区间商品的平均评分值，
用于评估不同产品生命周期阶段的用户认可度。
该指标可辅助分析产品生命周期特征，判断市场成熟度与长期畅销能力，
并识别新品期、成长期及长尾产品在市场中的相对竞争优势。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.21 `market_price_distribution`

- MCP 名称：`mcp__sellersprite__market_price_distribution`
- Agent 名称：`sellersprite_market_price_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品价格区间分布与市场定价结构。 在指定样本商品范围内，基于商品价格进行区间化分析， 系统性刻画各价格区间的商品数量分布、销量占比及对应的平均销量占比（该区间销量占比 / 该区间商品数量）， 用于衡量不同价格层级在市场中的需求集中度、销售效率及竞争密度。 该指标能够反映买家对不同价格区间的真实接受程度， 并揭示价格区间与销量贡献之间的结构性关系。 结合各价格区间内商品的评分表现，可进一步识别具备差异化空间的定价带， 其中评分水平相对较低但销量仍具支撑的价格区间， 通常代表存在通过产品优化、定价策略调整或定位重塑实现切入的潜在机会。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品价格区间分布与市场定价结构。
在指定样本商品范围内，基于商品价格进行区间化分析，
系统性刻画各价格区间的商品数量分布、销量占比及对应的平均销量占比（该区间销量占比 / 该区间商品数量），
用于衡量不同价格层级在市场中的需求集中度、销售效率及竞争密度。
该指标能够反映买家对不同价格区间的真实接受程度，
并揭示价格区间与销量贡献之间的结构性关系。
结合各价格区间内商品的评分表现，可进一步识别具备差异化空间的定价带，
其中评分水平相对较低但销量仍具支撑的价格区间，
通常代表存在通过产品优化、定价策略调整或定位重塑实现切入的潜在机会。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.22 `market_product_concentration`

- MCP 名称：`mcp__sellersprite__market_product_concentration`
- Agent 名称：`sellersprite_market_product_concentration`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品集中度情况。

**输入**

```ts
type Input = {
  request:{

    // 过滤 ASIN
    asins?: Array<string>;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品集中度情况。

通过传入对应站点（国家编码）、类目节点路径及筛选条件，返回该类目中头部 Listing 的
排名、价格、品牌、卖家类型、上架时间、评分、评论数、销量、销售额
以及对应的销量占比与销额占比等核心指标。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.23 `market_product_demand_trend`

- MCP 名称：`mcp__sellersprite__market_product_demand_trend`
- Agent 名称：`sellersprite_market_product_demand_trend`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品需求趋势情况。 基于指定细分类目节点，提供该类目的核心市场指标，包括页面浏览量、商品总数、 退货率（市场平均值与同类目平均值）以及搜索购买比（市场平均值与同类目平均值）。 用于评估该细分类目的真实需求规模、用户购买转化效率及退货风险水平， 并通过与同类型类目的对比，判断当前类目在市场吸引力与竞争质量上的相对位置， 辅助卖家进行选品决策与类目进入可行性评估。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品需求趋势情况。
基于指定细分类目节点，提供该类目的核心市场指标，包括页面浏览量、商品总数、
退货率（市场平均值与同类目平均值）以及搜索购买比（市场平均值与同类目平均值）。
用于评估该细分类目的真实需求规模、用户购买转化效率及退货风险水平，
并通过与同类型类目的对比，判断当前类目在市场吸引力与竞争质量上的相对位置，
辅助卖家进行选品决策与类目进入可行性评估。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.24 `market_rating_distribution`

- MCP 名称：`mcp__sellersprite__market_rating_distribution`
- Agent 名称：`sellersprite_market_rating_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品评分值分布与市场成熟度评估。 在指定样本商品范围内，基于商品评分值进行区间划分， 系统性统计各评分值区间的商品数量分布、销量占比及评分数总量， 并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量）， 用于衡量不同质量层级商品在市场中的销售效率与真实需求承载能力。 该指标能够刻画类目内商品被市场认可的整体结构， 通过评分值分布判断市场成熟度及产品质量集中程度： 高评分值商品占比较高通常意味着类目成熟、用户认知稳定； 低评分值商品占比较高则可能反映市场仍处于优化空间较大的阶段， 适合具备产品改进与供应链整合能力的卖家进行差异化切入与升级。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品评分值分布与市场成熟度评估。
在指定样本商品范围内，基于商品评分值进行区间划分，
系统性统计各评分值区间的商品数量分布、销量占比及评分数总量，
并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量），
用于衡量不同质量层级商品在市场中的销售效率与真实需求承载能力。
该指标能够刻画类目内商品被市场认可的整体结构，
通过评分值分布判断市场成熟度及产品质量集中程度：
高评分值商品占比较高通常意味着类目成熟、用户认知稳定；
低评分值商品占比较高则可能反映市场仍处于优化空间较大的阶段，
适合具备产品改进与供应链整合能力的卖家进行差异化切入与升级。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.25 `market_ratings_count_distribution`

- MCP 名称：`mcp__sellersprite__market_ratings_count_distribution`
- Agent 名称：`sellersprite_market_ratings_count_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的商品评分数区间分布与新品进入难度。 在指定样本商品范围内，按照商品评分数进行区间划分（区间跨度可配置）， 统计各评分数区间内的商品数量分布及其对应的销量占比， 并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量）， 用于衡量不同评分数层级商品的整体销售效率。 该指标可用于分析类目内商品评分数的整体分布结构， 并从评分积累难度的角度判断新品进入门槛， 识别低评分数区间与高评分数区间在市场竞争中的相对优势。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的商品评分数区间分布与新品进入难度。
在指定样本商品范围内，按照商品评分数进行区间划分（区间跨度可配置），
统计各评分数区间内的商品数量分布及其对应的销量占比，
并计算各区间的平均销量占比（该区间销量占比 / 该区间商品数量），
用于衡量不同评分数层级商品的整体销售效率。
该指标可用于分析类目内商品评分数的整体分布结构，
并从评分积累难度的角度判断新品进入门槛，
识别低评分数区间与高评分数区间在市场竞争中的相对优势。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.26 `market_research`

- MCP 名称：`mcp__sellersprite__market_research`
- Agent 名称：`sellersprite_market_research`
- 分类：类目市场
- 功能：Amazon 类目市场分析工具，用于从“类目维度”评估市场规模、 竞争强度、盈利空间以及新品进入可行性。

**输入**

```ts
type Input = {
  request:{
    departmentKeyword?: string;
    marketplace: string;
    maxAmazonSelfProportion?: number;
    maxAvgBsr?: number;
    maxAvgPrice?: number;
    maxAvgProfit?: number;
    maxAvgRating?: number;
    maxAvgRatings?: number;
    maxAvgRevenue?: number;
    maxAvgSellers?: number;
    maxAvgUnits?: number;
    maxBrandCrn?: number;
    maxBrands?: number;
    maxEbcProportion?: number;
    maxFbaProportion?: number;
    maxFbmProportion?: number;
    maxGoodsCount?: number;
    maxGoodsCrn?: number;
    maxNewAvgPrice?: number;
    maxNewAvgRating?: number;
    maxNewAvgRatings?: number;
    maxNewAvgRevenue?: number;
    maxNewAvgUnits?: number;
    maxNewCount?: number;
    maxNewProportion?: number;
    maxSellerCrn?: number;
    maxSellers?: number;
    maxTopAvgBsr?: number;
    maxTopAvgRevenue?: number;
    maxTopAvgUnits?: number;
    maxVolume?: number;
    maxWeight?: number;
    minAmazonSelfProportion?: number;
    minAvgBsr?: number;
    minAvgPrice?: number;
    minAvgProfit?: number;
    minAvgRating?: number;
    minAvgRatings?: number;
    minAvgRevenue?: number;
    minAvgSellers?: number;
    minAvgUnits?: number;
    minBrandCrn?: number;
    minBrands?: number;
    minEbcProportion?: number;
    minFbaProportion?: number;
    minFbmProportion?: number;
    minGoodsCount?: number;
    minGoodsCrn?: number;
    minNewAvgPrice?: number;
    minNewAvgRating?: number;
    minNewAvgRatings?: number;
    minNewAvgRevenue?: number;
    minNewAvgUnits?: number;
    minNewCount?: number;
    minNewProportion?: number;
    minSellerCrn?: number;
    minSellers?: number;
    minTopAvgBsr?: number;
    minTopAvgRevenue?: number;
    minTopAvgUnits?: number;
    minVolume?: number;
    minWeight?: number;
    month?: string;
    newProduct?: number;
    nodeIdPath?: string;
    order?:{
      desc?: boolean;
      field?: string;
    };
    page?: number;
    returnFields?: string;
    sellerLocation?: string;
    size?: number;
    topNum?: number;
  };
}
```

**输出**

Amazon 类目市场分析工具，用于从“类目维度”评估市场规模、
竞争强度、盈利空间以及新品进入可行性。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.27 `market_research_statistics`

- MCP 名称：`mcp__sellersprite__market_research_statistics`
- Agent 名称：`sellersprite_market_research_statistics`
- 分类：类目市场
- 功能：Amazon 类目结构与机会分析工具（节点级）。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

Amazon 类目结构与机会分析工具（节点级）。

用于在“已明确类目节点”的前提下，系统分析该类目的：
- 市场规模与成熟度
- 头部 Listing 的竞争强度与垄断程度
- 新品在该类目中的生存与成长能力
- 平均价格、利润率、销量是否具备商业价值

典型使用场景：
- 选品前，对目标类目做深度市场验证
- 判断是否值得进入某一个细分节点
- 分析“做头部款”还是“做新品切入”

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.28 `market_seller_concentration`

- MCP 名称：`mcp__sellersprite__market_seller_concentration`
- Agent 名称：`sellersprite_market_seller_concentration`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的卖家集中度情况。 在指定样本商品范围内，计算头部卖家（如销量排名前 N 位卖家）的总销量 U， 并与样本商品总销量 A 进行对比，卖家集中度 = U / A。 该指标用于衡量类目销量是否高度集中在少数头部卖家手中， 比例越高，说明头部卖家垄断程度越强，市场竞争壁垒越高。 同时支持同级类目卖家集中度对比，用于判断当前类目相对于同级类目的竞争集中程度是否偏高或偏低。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的卖家集中度情况。
在指定样本商品范围内，计算头部卖家（如销量排名前 N 位卖家）的总销量 U，
并与样本商品总销量 A 进行对比，卖家集中度 = U / A。
该指标用于衡量类目销量是否高度集中在少数头部卖家手中，
比例越高，说明头部卖家垄断程度越强，市场竞争壁垒越高。
同时支持同级类目卖家集中度对比，用于判断当前类目相对于同级类目的竞争集中程度是否偏高或偏低。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.29 `market_seller_country_distribution`

- MCP 名称：`mcp__sellersprite__market_seller_country_distribution`
- Agent 名称：`sellersprite_market_seller_country_distribution`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的卖家所属地分布情况。 在指定样本商品范围内，按照卖家所属国家或地区进行分组， 统计各地区卖家的商品数量及其销量/销售额占比。 常用于判断市场是否由本土卖家或中国卖家占据主导地位， 或呈现多国卖家均衡竞争格局， 从而辅助评估市场竞争激烈程度、卖家集中度及潜在市场风险。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的卖家所属地分布情况。
在指定样本商品范围内，按照卖家所属国家或地区进行分组，
统计各地区卖家的商品数量及其销量/销售额占比。
常用于判断市场是否由本土卖家或中国卖家占据主导地位，
或呈现多国卖家均衡竞争格局，
从而辅助评估市场竞争激烈程度、卖家集中度及潜在市场风险。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.30 `market_seller_type_concentration`

- MCP 名称：`mcp__sellersprite__market_seller_type_concentration`
- Agent 名称：`sellersprite_market_seller_type_concentration`
- 分类：类目市场
- 功能：用于分析指定 Amazon 市场类目节点下的卖家发货类型竞争情况。 在指定样本商品范围内，按照卖家发货类型（如 Amazon 自营、FBA、FBM 等）进行分组， 统计各发货类型的 ASIN 数量占比及其对应的月销量占比， 用于判断不同发货方式在市场中的商品覆盖度与销量贡献度。 同时统计各发货类型商品的平均评分数及平均评分值， 用于评估不同发货方式在用户口碑与竞争力方面的表现。 该指标可辅助卖家选择合适的发货方式，并判断 Amazon 自营或特定发货类型带来的竞争压力。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 新品定义阈值（单位：月），用于指定将上架在该时间范围内的商品视为新品。可根据行业特性调整，如服装类通常为 1，母婴等长生命周期行业可设为 6
    newProduct?: number;

    // 产品所属的类目节点 ID, 例如： 2619525011:3741271， 通常通过查询【产品类目信息】获取，或由用户直接指定类目路径
    nodeIdPath: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 头部Listing数量, 做竞争分析时，一般是取头部产品和整体样本做对比，来判断市场竞争度/集中度, 卖家精灵默认是取头部前10商品
    topN?: number;

  };
}
```

**输出**

用于分析指定 Amazon 市场类目节点下的卖家发货类型竞争情况。
在指定样本商品范围内，按照卖家发货类型（如 Amazon 自营、FBA、FBM 等）进行分组，
统计各发货类型的 ASIN 数量占比及其对应的月销量占比，
用于判断不同发货方式在市场中的商品覆盖度与销量贡献度。
同时统计各发货类型商品的平均评分数及平均评分值，
用于评估不同发货方式在用户口碑与竞争力方面的表现。
该指标可辅助卖家选择合适的发货方式，并判断 Amazon 自营或特定发货类型带来的竞争压力。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.31 `product_node`

- MCP 名称：`mcp__sellersprite__product_node`
- Agent 名称：`sellersprite_product_node`
- 分类：商品发现
- 功能：查询 Amazon 产品类目信息的工具。 支持通过类目节点路径、类目名称、关键词或节点 ID 搜索类目， 并返回类目的层级路径、名称以及该类目下的商品数量。

**输入**

```ts
type Input = {
  request:{

    // 搜索关键字，nodeId或类目名称
    keyword?: string;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 类目节点 id 字符串
    nodeIdPath?: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

  };
}
```

**输出**

查询 Amazon 产品类目信息的工具。
支持通过类目节点路径、类目名称、关键词或节点 ID 搜索类目，
并返回类目的层级路径、名称以及该类目下的商品数量。

适用于以下场景：
- 根据关键词查找对应的 Amazon 类目
- 获取类目的完整层级结构
- 选品前评估类目规模（商品数量）
- 为后续商品搜索或筛选提供类目参数

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.32 `product_research`

- MCP 名称：`mcp__sellersprite__product_research`
- Agent 名称：`sellersprite_product_research`
- 分类：商品发现
- 功能：高级商品筛选工具，用于在 Amazon 指定市场中， 根据关键词、品牌、卖家、类目、价格区间、销量、销售额、 BSR 排名及增长、评分、评论数、利润率、配送方式等多维条件， 精准筛选符合特定商业条件的商品列表。

**输入**

```ts
type Input = {
  request:{
    availableMonth?: number;
    badgeAC?: string;
    badgeBS?: string;
    badgeNR?: string;
    dimensionType?: string;
    excludeBrands?: string;
    excludeKeywords?: string;
    excludeSellers?: string;
    filterSub?: string;
    fulfillment?: string;
    includeBrands?: string;
    includeSellers?: string;
    keyword?: string;
    marketplace: string;
    matchType?: number;
    maxAmzUnit?: number;
    maxBsr?: number;
    maxBsrCr?: number;
    maxBsrCv?: number;
    maxFba?: number;
    maxLqs?: number;
    maxPrice?: number;
    maxProfit?: number;
    maxRating?: number;
    maxRatings?: number;
    maxRatingsCv?: number;
    maxRevenue?: number;
    maxRevenueCr?: number;
    maxSellers?: number;
    maxSubBsrRank?: number;
    maxUnits?: number;
    maxUnitsCr?: number;
    maxVariations?: number;
    maxWeights?: number;
    minAmzUnit?: number;
    minBsr?: number;
    minBsrCr?: number;
    minBsrCv?: number;
    minFba?: number;
    minLqs?: number;
    minPrice?: number;
    minProfit?: number;
    minRating?: number;
    minRatings?: number;
    minRatingsCv?: number;
    minRevenue?: number;
    minRevenueCr?: number;
    minSellers?: number;
    minSubBsrRank?: number;
    minUnits?: number;
    minUnitsCr?: number;
    minVariations?: number;
    minWeights?: number;
    month?: string;
    nodeIdPath?: string;
    nodeIdPathEqual?: boolean;
    nodeIdPaths?: Array<string>;
    order?:{
      desc?: boolean;
      field?: string;
    };
    page?: number;
    returnFields?: string;
    sellerNation?: string;
    size?: number;
    variation?: string;
    weightUnit?: string;
  };
}
```

**输出**

高级商品筛选工具，用于在 Amazon 指定市场中，
根据关键词、品牌、卖家、类目、价格区间、销量、销售额、
BSR 排名及增长、评分、评论数、利润率、配送方式等多维条件，
精准筛选符合特定商业条件的商品列表。

适用于以下场景：
- 爆品 / 潜力品筛选
- 蓝海机会挖掘
- 条件化选品（价格、利润、销量、竞争度）
- 按规则扫描整个类目或关键词市场

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.33 `review`

- MCP 名称：`mcp__sellersprite__review`
- Agent 名称：`sellersprite_review`
- 分类：评论
- 功能：查询指定 Amazon ASIN 的商品评论列表，返回评论标题、评论内容、评分、评论人、评论时间等信息，用于获取商品的用户反馈和评价数据

**输入**

```ts
type Input = {

  asin: string;

  // 获取评论的结束时间毫秒
  endTimestamp?: number;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  page?: number;

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

  size?: number;

  // 评论星级
  // 可选值(仅填写字段名):
  // - 1: 一星
  // - 2: 二星
  // - 3: 三星
  // - 4: 四星
  // - 5: 五星
  starList?: Array<number>;

  // 获取评论的开始时间毫秒
  startTimestamp?: number;

  // 评论类型
  // 可选值(仅填写字段名):
  // - 1：图片评论
  // - 2：视频评论
  // - 3：VP评论
  // - 4：vine评论
  typeList?: Array<number>;

}
```

**输出**

查询指定 Amazon ASIN 的商品评论列表，返回评论标题、评论内容、评分、评论人、评论时间等信息，用于获取商品的用户反馈和评价数据

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.34 `trademark_country_list`

- MCP 名称：`mcp__sellersprite__trademark_country_list`
- Agent 名称：`sellersprite_trademark_country_list`
- 分类：商标
- 功能：查询支持商标的国家数据

**输入**

```ts
type Input = {
}
```

**输出**

查询支持商标的国家数据

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.35 `trademark_detail`

- MCP 名称：`mcp__sellersprite__trademark_detail`
- Agent 名称：`sellersprite_trademark_detail`
- 分类：商标
- 功能：查询商标的详细信息

**输入**

```ts
type Input = {

  // 商标编号
  brandId: string;

  // 查询商标国家编码
  office: string;

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
  returnFields?: string;

}
```

**输出**

查询商标的详细信息

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.36 `trademark_list`

- MCP 名称：`mcp__sellersprite__trademark_list`
- Agent 名称：`sellersprite_trademark_list`
- 分类：商标
- 功能：查询商标列表数据

**输入**

```ts
type Input = {
  request:{

    // 申请人
    applicant?: Array<string>;

    // 申请年份
    applicationYear?: Array<string>;

    // 品牌名
    brandName?: Array<string>;

    // 过期年份
    expiryYear?: Array<string>;

    // 图片base64
    imageBase64?: string;

    // 尼斯分类
    niceClass?: Array<number>;

    // 知识产权局，数据来自于 trademark_country_list
    office?: Array<string>;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。默认空
      // 可选值(仅填写字段名):
      // - applicationDate: 申请日期
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

    // 状态,（枚举值）：Registered, Pending, Expired, Ended, Unknown
    status?: Array<string>;

    // 查询文本 可模糊查询多个字段
    text: string;

  };
}
```

**输出**

查询商标列表数据

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.37 `trademark_stats`

- MCP 名称：`mcp__sellersprite__trademark_stats`
- Agent 名称：`sellersprite_trademark_stats`
- 分类：商标
- 功能：查询商标统计数据

**输入**

```ts
type Input = {
  request:{

    // 查询商标国家编码
    office: Array<string>;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 查询商标的名称
    text: string;

  };
}
```

**输出**

查询商标统计数据

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.38 `traffic_extend`

- MCP 名称：`mcp__sellersprite__traffic_extend`
- Agent 名称：`sellersprite_traffic_extend`
- 分类：流量
- 功能：用于在指定 Amazon 站点中，根据 ASIN、时间范围及多维筛选条件， 批量搜索并分析高价值关键词的工具。

**输入**

```ts
type Input = {
  request:{

    // 亚马逊推荐词
    amazonChoice?: boolean;

    // asins, 最多只支持20个，如果超过20个, 需要拆分多次请求
    asinList: Array<string>;

    // 排除的词
    excludeKeywords?: Array<string>;

    // 查询月份, 格式: yyyyMM
    historyDate?: string;

    // 包含的词
    includeKeywords?: Array<string>;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 最大广告竞品数
    maxAdProducts?: number;

    // 最大均价
    maxAvgPrice?: number;

    // 最大ppc竞价
    maxBid?: number;

    // 最大asin数
    maxCompetitors?: number;

    // 最大转化率
    maxConversionRate?: number;

    // 最大点击集中度
    maxMonopolyClickRate?: number;

    // 最大商品数
    maxProducts?: number;

    // 最大购买率
    maxPurchaseRate?: number;

    // 最大购买量
    maxPurchases?: number;

    // 最大SPR
    maxSPR?: number;

    // 最大搜索排名
    maxSearchRank?: number;

    // 最大月搜索量
    maxSearches?: number;

    // 最大供需比
    maxSupplyDemandRatio?: number;

    // 最大标题密度
    maxTitleDensity?: number;

    // 最大流量占比
    maxTrafficPercentage?: number;

    // 最大单词个数
    maxWordCount?: number;

    // 最小广告竞品数
    minAdProducts?: number;

    // 最小均价
    minAvgPrice?: number;

    // 最小ppc竞价
    minBid?: number;

    // 最小asin数
    minCompetitors?: number;

    // 最小转化率
    minConversionRate?: number;

    // 最小点击集中度
    minMonopolyClickRate?: number;

    // 最小商品数
    minProducts?: number;

    // 最小购买率
    minPurchaseRate?: number;

    // 最小购买量
    minPurchases?: number;

    // 最小SPR
    minSPR?: number;

    // 最小搜索排名
    minSearchRank?: number;

    // 最小月搜索量
    minSearches?: number;

    // 最小供需比
    minSupplyDemandRatio?: number;

    // 最小标题密度
    minTitleDensity?: number;

    // 最小流量占比
    minTrafficPercentage?: number;

    // 最小单词个数
    minWordCount?: number;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - trafficPercentage: 流量占比
      // - relationAsin: 相关ASIN
      // - searchesRank: ABA周排名
      // - searches: 月搜索量
      // - purchases: 月购买量
      // - purchaseRate: 购买率
      // - spr: spr
      // - titleDensity: 标题密度
      // - products: 商品数
      // - supplyDemandRatio: 供需比
      // - adProduct: 广告竞品数
      // - monopolyClickRate: 点击集中度
      // - bid: PPC竞价
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 查询方式, 默认: 2
    // 可选值(必须严格使用下列数字值之一):
    // 0: 所有变体
    // 1: 畅销变体
    // 2: 当前变体
    // 禁止使用未列出的值。
    queryType: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

  };
}
```

**输出**

用于在指定 Amazon 站点中，根据 ASIN、时间范围及多维筛选条件，
批量搜索并分析高价值关键词的工具。

返回结果包含：搜索量、购买量、转化率、PPC竞价、供需比、
广告竞争度、点击集中度、关联ASIN等核心商业指标，
可直接用于“是否值得投放 / 是否值得进入”的判断。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.39 `traffic_keyword`

- MCP 名称：`mcp__sellersprite__traffic_keyword`
- Agent 名称：`sellersprite_traffic_keyword`
- 分类：流量
- 功能：查询指定 ASIN 在 Amazon 指定市场下的搜索关键词表现数据， 支持近 30 天或指定历史月份， 返回 ASIN 实际获得曝光和流量的关键词列表， 包含搜索量、自然排名、广告排名、流量占比、转化表现及 PPC 竞价参考， 用于关键词挖掘、Listing 优化和广告投放分析。

**输入**

```ts
type Input = {
  request:{

    // asin
    asin: string;

    // 流量词类型
    // 可选值(仅填写字段名):
    // - naturalSearching: 自然搜索词
    // - amazonChoice: AC推荐词
    // - editorialRecommendations: ER推荐词
    // - fourStar: 四星推荐词
    // - highlyRated: HR推荐词
    // - sponsorBrand: 品牌推荐词
    // - sponsorVideo: 视频推荐词
    // - ads: SP广告词
    badges?: Array<string>;

    // 流量转化类型
    // 可选值(仅填写字段名):
    // - excellent: 转化优质词
    // - stable: 转化平稳词
    // - lost:转化流失词
    // - invalid:无效曝光词
    conversionKeywordTypes?: Array<string>;

    // 是否包含 Top10 ASIN
    includeTop10AsinData?: boolean;

    // 关键词
    keyword?: string;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - rankPosition: 自然排名
      // - adPosition: 广告排名
      // - createdTime: 创建时间
      // - searchesRank: 搜索量周排名
      // - searches: 月搜索量
      // - purchases: 月购买量
      // - purchaseRate: 购买率
      // - products: 商品数
      // - supplyDemandRatio: 供需比
      // - latest1daysAds: 广告竞品数
      // - bid: PPC竞价
      // - trafficPercentage: 流量占比
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

    // 流量占比类型
    // 可选值(仅填写字段名):
    // - primary: 主要流量词
    // - precise: 精准流量词
    // - preciseLongTail: 转化流失词
    trafficKeywordTypes?: Array<string>;

  };
}
```

**输出**

查询指定 ASIN 在 Amazon 指定市场下的搜索关键词表现数据，
支持近 30 天或指定历史月份，
返回 ASIN 实际获得曝光和流量的关键词列表，
包含搜索量、自然排名、广告排名、流量占比、转化表现及 PPC 竞价参考，
用于关键词挖掘、Listing 优化和广告投放分析。

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.40 `traffic_keyword_stat`

- MCP 名称：`mcp__sellersprite__traffic_keyword_stat`
- Agent 名称：`sellersprite_traffic_keyword_stat`
- 分类：流量
- 功能：Amazon ASIN 流量关键词结构【概览统计】工具。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 查询月份, 格式: yyyyMM, 默认为: nearly
  month?: string;

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

Amazon ASIN 流量关键词结构【概览统计】工具。

用于快速分析某个 ASIN 当前整体的流量关键词规模，
以及这些流量主要来源于：
- 自然搜索
- Amazon 官方推荐体系
- 各类广告（SP / 品牌广告 / 视频广告 / HR）

与“流量词明细接口”不同，
本工具只返回【统计级数据】，不返回具体关键词列表，
适合作为 AI 决策的第一步判断入口。

核心用途：
- 判断 ASIN 是否高度依赖广告获取流量
- 评估自然流量与广告流量的结构比例
- 快速对比多个 ASIN 的流量健康度
- 作为是否深入分析（调用明细接口）的前置筛选条件

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.41 `traffic_listing`

- MCP 名称：`mcp__sellersprite__traffic_listing`
- Agent 名称：`sellersprite_traffic_listing`
- 分类：流量
- 功能：查询指定 ASIN 在 Amazon 站内的关联商品列表，用于分析竞品结构与关联关系。

**输入**

```ts
type Input = {
  request:{

    // asin列表
    asinList: Array<string>;

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - rankPosition: 自然排名
      // - adPosition: 广告排名
      // - createdTime: 创建时间
      // - searchesRank: 搜索量周排名
      // - searches: 月搜索量
      // - purchases: 月购买量
      // - purchaseRate: 购买率
      // - products: 商品数
      // - supplyDemandRatio: 供需比
      // - latest1daysAds: 广告竞品数
      // - bid: PPC竞价
      // - trafficPercentage: 流量占比
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // 关联类型
    relations: Array<string>;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

    // 是否查询变体
    variations?: boolean;

  };
}
```

**输出**

查询指定 ASIN 在 Amazon 站内的关联商品列表，用于分析竞品结构与关联关系。

该工具基于 Amazon 站内关系模型，返回与目标 ASIN 存在
关联、竞品或同类关系的商品数据，包括销量、BSR、价格、
利润率、评分、卖家结构、变体信息等核心指标。

适用于以下场景：
- 查找目标 ASIN 的直接竞品与强关联商品
- 分析某个市场的头部商品结构与集中度
- 判断新品进入时将面对的主要对手
- 分析变体数量、卖家数量、品牌垄断程度

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.42 `traffic_listing_stat`

- MCP 名称：`mcp__sellersprite__traffic_listing_stat`
- Agent 名称：`sellersprite_traffic_listing_stat`
- 分类：流量
- 功能：Amazon ASIN 流量来源结构分析工具（免费 / 付费 + 关联类型分布）。

**输入**

```ts
type Input = {

  asin: string;

  // Amazon 站点
  marketplace: "US" | "JP" | "UK" | "DE" | "FR" | "IT" | "ES" | "CA" | "IN" | "MX" | "BR" | "AU" | "AE";

  // 查询月份, 格式: yyyyMM, 默认为: nearly
  month?: string;

  // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin
  returnFields?: string;

}
```

**输出**

Amazon ASIN 流量来源结构分析工具（免费 / 付费 + 关联类型分布）。

本工具用于统计某个 ASIN 当前所获得的全部流量来源，
并从两个核心维度进行拆解：
1. 免费流量 vs 付费流量的整体占比
2. 不同流量“关联类型”（relation）的数量分布

这是一个【结构型统计接口】，不返回具体关键词或 ASIN 明细，
只用于判断“流量是如何被获取的”。

核心用途：
- 判断 ASIN 是否高度依赖广告或付费引流
- 分析免费流量（自然、关联、推荐）的贡献程度
- 快速识别 ASIN 的主要流量获取模式
- 辅助评估投放策略是否健康、是否具备自然增长能力

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

### 3.43 `traffic_source`

- MCP 名称：`mcp__sellersprite__traffic_source`
- Agent 名称：`sellersprite_traffic_source`
- 分类：流量
- 功能：Amazon 流量关键词结构分析工具（ASIN / 关键词维度）。

**输入**

```ts
type Input = {
  request:{

    // Amazon 站点代码（枚举值）：US, JP, UK, DE, FR, IT, ES, CA, IN, MX, BR, AU, AE
    marketplace: string;

    // 查询月份, 格式: yyyyMM
    month?: string;

    // 排序
    order?:{

      // 排序类型
      desc?: boolean;

      // 排序字段。
      // 可选值(仅填写字段名):
      // - searchfrequencyrank: 现排名
      // - cprExact: spr
      // - titleDensityExact: 标题密度
      // - searches: 搜索量周排名
      // 禁止使用未列出的值。
      field?: string;

    };

    // 页码
    page?: number;

    // asin 或者 关键词
    q: string;

    // 指定返回的字段，多个字段用逗号隔开。不指定则返回所有字段。例如：asin,title,price,totalUnits,totalAmount
    returnFields?: string;

    // 每页条数
    size?: number;

  };
}
```

**输出**

Amazon 流量关键词结构分析工具（ASIN / 关键词维度）。

用于分析某个 ASIN 或关键词在指定月份内：
- 实际带来流量的关键词总量
- 不同来源（自然搜索 / 官方推荐 / 广告）的流量词分布
- 广告词、品牌词、推荐词在整体流量中的占比
- ASIN 当前的基础商品信息与类目背景

适用场景：
- 竞品流量结构分析
- 判断 ASIN 是否“靠广告堆起来”
- 广告投放与自然 SEO 策略制定
- 流量词挖掘与优先级判断

**输出 schema 状态**：顶层仅声明 `CallToolResult`，当前 MCP metadata 未提供字段级 `outputSchema`。

## 4. SIF 工具

> SIF 的工具说明提供了较完整的返回字段。通用错误码包括：`INVALID_REQUEST`、`UNAUTHORIZED`、`FORBIDDEN`、`TOOL_NOT_FOUND`、`RATE_LIMITED`、`INTERNAL_ERROR`。

### 4.1 `ads_get_ad_group_keyword_breakdown`

- MCP 名称：`mcp__sif__ads_get_ad_group_keyword_breakdown`
- Agent 名称：`sif_ads_get_ad_group_keyword_breakdown`
- 分类：广告
- 功能：查询单个广告组在指定周的关键词明细，包含每个关键词的流量占比以及该关键词在哪些 ASIN 上展示。 触发时机：已知目标广告组（adGroupId）后，需要进一步拆解该广告组内部哪些关键词贡献了流量、以及这些关键词与哪些变体 ASIN 绑定时使用。

**输入**

```ts
type Input = {

  // 目标广告组 ID，支持 fakeAdId 或 encryptAdId
  adGroupId: string;

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 目标 campaign ID，支持 encryptCampaignId 或 fakeCampaignId
  campaignId: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 目标周的起始日期，格式 yyyy-MM-dd
  date: string;

}
```

**输出**

· campaignId：campaign 标识符
· campaignDisplayId：campaign 可读展示 ID（fakeCampaignId）
· campaignType：广告类型，SP/SB/SBV/SB_SBV
· adGroupId：广告组 ID
· date：目标周起始日期
· displayAsins[]：该广告组在该周展示的全部去重 ASIN 列表
· keywords[]：该广告组的关键词明细列表
  · keyword：关键词原文
  · translateKeyword：关键词翻译
  · trafficShareWithinAdGroup：该词在广告组内的流量占比（0~1）
  · displayAsins[]：该关键词在该广告组中展示的 ASIN 列表
注意：
  · campaignId 支持 encryptCampaignId 和 fakeCampaignId；adGroupId 支持 fakeAdId 和 encryptAdId。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.2 `ads_get_ad_group_traffic_trend`

- MCP 名称：`mcp__sif__ads_get_ad_group_traffic_trend`
- Agent 名称：`sif_ads_get_ad_group_traffic_trend`
- 分类：广告
- 功能：查询单个广告组从创建至今的完整历史流量趋势，可附带用户选中窗口的上下文便于对比定位。 触发时机：从 campaign 级别的窗口拆解中选定目标广告组后，需要查看该广告组在整个生命周期内的流量走势，判断异常是短暂波动还是持续趋势时使用。

**输入**

```ts
type Input = {

  // AdGroup 标识；支持短展示 ID 或加密 ID，例如 CCL4
  adGroupId: string;

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // Campaign 标识；支持短展示 ID 或加密 ID，例如 SUBD
  campaignId: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 可选：选中该广告组的窗口结束日期，用于记录进入上下文
  selected_end_date?: string;

  // 可选：选中该广告组的窗口开始日期，用于记录进入上下文
  selected_start_date?: string;

}
```

**输出**

· campaignId：campaign 标识符
· campaignDisplayId：campaign 展示用 ID（fakeCampaignId）
· campaignType：广告类型，如 SP / SB / SBV
· adGroupId：广告组标识符
· trendScope：固定为 'lifecycle'，表示覆盖生命周期全段
· trafficTrend[]：按周序列的流量趋势
  · date：周起始日期
  · traffic：该周曝光量
  · trafficChange：与上周曝光量的绝对差值
  · trafficChangeRate：与上周曝光量的相对变化率
· selectedWindow：标注的关注窗口（仅传入 selected_start_date 或 selected_end_date 时返回）
  · start_date：窗口起始日
  · end_date：窗口截止日
注意：
  · campaignId 支持 encryptCampaignId 和 fakeCampaignId；adGroupId 支持 fakeAdId 和 encryptAdId。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.3 `ads_get_asin_ad_feature_profile`

- MCP 名称：`mcp__sif__ads_get_asin_ad_feature_profile`
- Agent 名称：`sif_ads_get_asin_ad_feature_profile`
- 分类：广告
- 功能：ads_get_asin_ad_window_feature_profile 的兼容别名，执行逻辑完全相同。 触发时机：仅用于兼容旧版客户端调用，新场景请优先使用 ads_get_asin_ad_window_feature_profile。

**输入**

```ts
type Input = {

  // 广告类型过滤，可选 SP/SB/SBV/SB_SBV, enums: [SP, SB, SBV, SB_SBV]
  ad_type?: string;

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间窗口结束日期，格式 yyyy-MM-dd
  end_date: string;

  // 时间窗口开始日期，格式 yyyy-MM-dd
  start_date: string;

}
```

**输出**

· 集中度指标：campaign 集中度分布特征
· 渠道结构信号：各广告类型贡献比例与结构变化
· 投放节奏判断：窗口内投放的稳定性与节奏特征
· 注意：不含最终诊断文本，诊断逻辑由调用方（LLM）完成
注意：
  · 与 ads_get_asin_ad_window_feature_profile 返回完全相同的窗口期广告特征画像。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.4 `ads_get_asin_ad_historical_feature_profile`

- MCP 名称：`mcp__sif__ads_get_asin_ad_historical_feature_profile`
- Agent 名称：`sif_ads_get_asin_ad_historical_feature_profile`
- 分类：广告
- 功能：基于 ASIN 的历史全量广告数据，生成长期广告特征画像，描述投放节奏、渠道组合、集中度和增长轨迹。 触发时机：广告深度分析时优先调用，用于理解该 ASIN 的长期广告结构演变、成熟度判断和渠道策略脉络，为后续窗口级分析提供背景参照。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间粒度，仅支持 week/month；默认 week, enums: [week, month]
  granularity?: string;

  // 返回文本字段语言；默认 en, enums: [en, zh]
  lang?: string;

}
```

**输出**

· 投放节奏：历史全程的广告活跃程度与周期性规律
· campaign 集中度：头部 campaign 在历史中的流量占比分布
· 渠道组合分布：SP / SB / SBV 各渠道的历史贡献比例
· 增长轨迹：广告曝光量在历史维度的整体增长趋势信号
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.5 `ads_get_asin_ad_structure`

- MCP 名称：`mcp__sif__ads_get_asin_ad_structure`
- Agent 名称：`sif_ads_get_asin_ad_structure`
- 分类：广告
- 功能：查询某 ASIN 的广告结构总览，统计历史全量范围内各广告类型的 campaign 数量。 触发时机：广告分析开始时首先调用，用于快速估算该 ASIN 的整体广告规模和类型分布，判断是否值得深入分析。

**输入**

```ts
type Input = {

  // 目标 ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间粒度，仅支持 week/month（默认 week）, enums: [week, month]
  granularity?: string;

}
```

**输出**

· asin：目标 ASIN
· country：站点代码
· structureScope：固定为 'historical'，表示覆盖历史全量数据
· ad_types[]：各广告类型明细列表
  · type：广告类型，SP/SB/SBV
  · campaign_count：该类型历史累计 campaign 数量
· total_campaign_count：所有类型 campaign 总数
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.6 `ads_get_asin_ad_traffic_trend`

- MCP 名称：`mcp__sif__ads_get_asin_ad_traffic_trend`
- Agent 名称：`sif_ads_get_asin_ad_traffic_trend`
- 分类：广告
- 功能：查询某 ASIN 历史全量的广告流量趋势，按 SP/SB/SBV 三个渠道分别输出曝光量时序。 触发时机：需要初步定位广告流量变化发生的时间窗口，或需要判断哪个广告渠道（SP/SB/SBV）的曝光出现了明显变化时使用。

**输入**

```ts
type Input = {

  // 目标 ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间粒度：week / month, enums: [week, month]
  granularity: string;

}
```

**输出**

· asin：目标 ASIN
· country：站点代码
· metric：固定为 'impressions'，表示曝光量
· granularity：实际使用的时间粒度
· trend[]：按时间粒度分桶的曝光量序列
  · date：分桶起始日期
  · SP：SP 渠道曝光量
  · SB：SB 渠道曝光量
  · SBV：SBV 渠道曝光量
· trend_analysis：预计算的渠道趋势判断
  · SP_trend：SP 渠道趋势
  · SB_trend：SB 渠道趋势
  · SBV_trend：SBV 渠道趋势
  · overall_trend：三渠道合计趋势
  · dominant_channel：近期主力渠道
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.7 `ads_get_asin_ad_window_feature_profile`

- MCP 名称：`mcp__sif__ads_get_asin_ad_window_feature_profile`
- Agent 名称：`sif_ads_get_asin_ad_window_feature_profile`
- 分类：广告
- 功能：基于 ASIN 广告数据，生成指定时间窗口内的广告特征画像，描述窗口期内的结构、集中度、投放节奏和稳定性。 触发时机：识别到异常流量窗口后，需要深入分析该窗口内广告侧发生了什么变化（campaign 集中度是否异常、哪个渠道贡献突出、是否存在结构性切换）时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间粒度：week / month, enums: [week, month]
  granularity: string;

}
```

**输出**

· 集中度指标：窗口期内 campaign 集中度分布，判断流量是否高度依赖少数 campaign
· 渠道结构信号：窗口期内各广告类型贡献比例，识别渠道结构性切换
· 投放节奏判断：窗口期内投放的稳定性，判断是否存在突然启停行为
· 注意：不含最终诊断文本，诊断逻辑由调用方（LLM）完成
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.8 `ads_get_asin_campaign_changes`

- MCP 名称：`mcp__sif__ads_get_asin_campaign_changes`
- Agent 名称：`sif_ads_get_asin_campaign_changes`
- 分类：广告
- 功能：查询某 ASIN 在历史各周内新上线的 campaign 变更事件，即 campaign_created 事件列表。 触发时机：发现流量趋势出现拐点后，用于核实流量异常是否与新 campaign 上线的时间节点吻合，以排除或确认广告结构变更因素。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

}
```

**输出**

· asin：目标 ASIN
· country：站点代码
· campaign_changes[]：campaign 变更事件列表
  · date：变更周的起始日期
  · change_type：变更类型，固定为 'campaign_created'
  · ad_type：广告类型，SP / SB / SBV 之一
  · campaign_id：新上线的 campaign ID
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.9 `ads_get_asin_campaign_contribution_overview`

- MCP 名称：`mcp__sif__ads_get_asin_campaign_contribution_overview`
- Agent 名称：`sif_ads_get_asin_campaign_contribution_overview`
- 分类：广告
- 功能：基于曝光得分，查询某 ASIN 在指定时间窗口内各 campaign 的贡献总览，按贡献从高到低排序。 触发时机：识别到流量趋势异常窗口后，作为第一个下钻入口，用于快速定位在该窗口内哪些 campaign 贡献了最多广告曝光。

**输入**

```ts
type Input = {

  // 广告类型过滤，可选 SP/SB/SBV/SB_SBV；用于匹配单条类型轨道的贡献口径, enums: [SP, SB, SBV, SB_SBV]
  ad_type?: string;

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country: string;

  // 时间窗口结束日期，格式 yyyy-MM-dd
  end_date: string;

  // 返回条数，范围 1~200，默认 20
  limit?: number;

  // 时间窗口开始日期，格式 yyyy-MM-dd
  start_date: string;

}
```

**输出**

· asin：目标 ASIN
· country：站点代码
· metric：固定为 'exposure_score'，表示基于曝光得分排序
· start_date：查询起始日
· end_date：查询截止日
· ad_type：广告类型过滤值（仅在传入时返回）
· campaigns[]：campaign 贡献列表，按 contribution_score 从高到低排序
  · campaign_id：campaign 加密 ID
  · campaign_display_id：campaign 可读展示 ID（fakeCampaignId）
  · campaign_name：campaign 名称
  · ad_type：广告类型，SP/SB/SBV/SB_SBV
  · created_date：campaign 创建日期
  · contribution_score：曝光得分，数值越高表示该周期内曝光越多
  · share：该 campaign 占窗口内总曝光的比例（0~1）
  · contribution_tier：贡献等级：dominant（>=30%）/major（>=10%）/supporting（>=3%）/minor（<3%）
  · rank：贡献排名，从 1 开始
注意：
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.10 `ads_get_campaign_contribution_breakdown`

- MCP 名称：`mcp__sif__ads_get_campaign_contribution_breakdown`
- Agent 名称：`sif_ads_get_campaign_contribution_breakdown`
- 分类：广告
- 功能：查询某 campaign 在单个自然周内的贡献明细，支持按 keyword 或 ad_group 维度拆解。 触发时机：从贡献总览中锁定目标 campaign 后，需要进一步查看该 campaign 内哪些关键词或广告组在该周承载了流量，或查看关键词级别的排名历史和搜索趋势时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 拆解维度：keyword 或 ad_group, enums: [keyword, ad_group]
  breakdown_by: string;

  // Campaign 标识；支持短展示 ID 或加密 ID，例如 SUBD
  campaignId: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 周窗口结束日期，必须等于 start_date + 6 天
  end_date: string;

  // 返回数量限制；keyword 模式直接截断，ad_group 模式在全量聚合后截断
  limit?: number;

  // 周窗口开始日期，必须传周日（SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天），格式 yyyy-MM-dd，如 '2026-03-29'
  start_date: string;

}
```

**输出**

· campaignId：campaign 标识符
· campaignDisplayId：campaign 可读展示 ID
· campaignType：广告类型，SP/SB/SBV/SB_SBV
· timeRange：实际查询时间范围，含 start_date 和 end_date
· breakdown_by：固定为 'keyword' 或 'ad_group'
· items[]：明细列表（keyword 维度）
  · keyword：关键词原文
  · translateKeyword：关键词翻译
  · traffic：该词在该周的曝光得分
  · trafficShare：该词占该 campaign 本周总曝光的比例
  · trafficChange：本周曝光得分与上周的变化量
  · trafficChangeRate：本周曝光得分与上周的变化率
  · adRankHistory：广告排名历史
  · naturalRankHistory：自然排名历史
  · searchTrend：搜索趋势
· items[]：广告组汇总列表（ad_group 维度）
  · adGroupId：广告组 ID
  · traffic：该广告组本周总曝光得分
  · trafficShare：占该 campaign 本周总曝光的比例
  · trafficChange：曝光变化量
  · trafficChangeRate：曝光变化率
  · keywordCount：该广告组本周覆盖的关键词数量
注意：
  · start_date 必须传周日（SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天），end_date 必须等于 start_date + 6 天，否则请求报错。
  · campaignId 支持 encryptCampaignId 和 fakeCampaignId 两种格式。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.11 `ads_get_campaign_structure`

- MCP 名称：`mcp__sif__ads_get_campaign_structure`
- Agent 名称：`sif_ads_get_campaign_structure`
- 分类：广告
- 功能：查询单个 campaign 的历史广告组结构，列出该 campaign 下所有广告组的详情。 触发时机：从 ASIN 广告结构总览中定位到某个 campaign 后，需要进一步了解该 campaign 由哪些广告组构成、各组历史累计覆盖的变体数和关键词数时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // Campaign 标识；支持短展示 ID 或加密 ID，例如 HLLE
  campaignId: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

}
```

**输出**

· campaignId：campaign 标识符（优先 fakeCampaignId）
· campaignDisplayId：campaign 可读展示 ID（fakeCampaignId）
· campaignType：广告类型，SP/SB/SBV/SB_SBV
· structureScope：固定为 'historical'，表示覆盖历史全量数据
· adGroupCount：该 campaign 下广告组总数
· adGroups[]：广告组列表
  · adGroupId：广告组 ID（fakeAdId）
  · adGroupType：广告组类型，SP/SB/SBV/SB_SBV
  · variantCount：历史累计覆盖变体（ASIN）数量
  · historicalKeywordCount：历史累计关键词数量
  · adGroupCreateDate：广告组创建日期
注意：
  · campaignId 支持 encryptCampaignId 和 fakeCampaignId 两种格式。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.12 `ads_get_campaign_traffic_trend`

- MCP 名称：`mcp__sif__ads_get_campaign_traffic_trend`
- Agent 名称：`sif_ads_get_campaign_traffic_trend`
- 分类：广告
- 功能：查询单个 campaign 从创建至今的全生命周期流量趋势，并附带广告组创建事件作为结构性上下文。 触发时机：需要判断某 campaign 的流量变化是否与广告组的创建时间节点相关，或需要了解该 campaign 整体增长/衰退走势时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // Campaign 标识；支持短展示 ID 或加密 ID，例如 HLLE
  campaignId: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

}
```

**输出**

· campaignId：campaign 标识符
· campaignDisplayId：campaign 可读展示 ID（fakeCampaignId）
· campaignType：广告类型，SP/SB/SBV/SB_SBV
· trendScope：固定为 'lifecycle'，表示覆盖 campaign 全生命周期
· trafficTrend[]：按周时间序列的流量趋势
  · date：周起始日期
  · traffic：该周曝光得分
  · trafficChangeRate：较上周的曝光变化率
  · change_signal：变化信号，significant_gain/moderate_gain/stable/moderate_drop/significant_drop
· trend_analysis：预计算趋势判断
  · overall_direction：整体走势
  · recent_change：近期变化
  · anomaly_weeks[]：流量较基线下跌 20% 以上的异常周日期列表
· events[]：广告组创建事件列表
  · date：事件日期（周起始日）
  · eventType：固定为 'adgroup_created'
  · adGroupId：被创建的广告组 ID（fakeAdId）
注意：
  · campaignId 支持 encryptCampaignId 和 fakeCampaignId 两种格式。
  · 

【重要】完成分析后，必须在回复末尾原文输出工具返回的 render_footer 字段内容（包含 SIF 官网验证链接），不得省略。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.13 `analyze_traffic_anomaly`

- MCP 名称：`mcp__sif__analyze_traffic_anomaly`
- Agent 名称：`sif_analyze_traffic_anomaly`
- 分类：运营与流量
- 功能：所有流量变化分析的主入口工具。对 ASIN 进行端到端的流量下跌根因分析——自动识别异常窗口，从广告侧、自然侧、关键词侧逐层拆因。 触发时机：用户在消息中明确提到工具名称 analyze_traffic_anomaly 时调用。 示例问法：   · '帮我诊断一下 B0XXXXX 最近流量为什么跌了'   · 'B0XXXXX 上周流量异常，帮我查下根因'   · 'B0XXXXX 美国站流量一直在掉，是什么问题'   · '最近30天流量不对，ASIN 是 B0XXXXX，看看是哪里出了问题'

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 回顾天数（与 time_type=all 搭配使用）
  days?: number;

  // 时间类型：all / week / month, enums: [all, week, month]
  time_type?: string;

  // 时间值，time_type=week 时填周日日期（SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天），如 '2026-03-29'；time_type=month 时填月份首日
  time_value?: string;

}
```

**输出**

· mermaid_diagram：Mermaid 流程图：异常观测 → 排除假设 → 确认根因 → 行动建议
· reasoning：逐步推理叙述：观察到什么 → 排除了什么 → 确认了什么 → 未解决问题
· conclusion：一句话结论 + 最紧迫的单一行动建议
注意：
  · 判断逻辑仍在持续迭代中，结论为方向性判断，建议结合实际情况验证。
  · 本工具不用于单纯展示原始数据——如需查看原始数据，请使用 ops_get_asin_traffic_trend。
  · 内部自动执行完整分析链：趋势 + 结构 + 关键词 + 需求 + 竞争，无需额外调用其他工具。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.14 `market_get_asin_keyword_signals`

- MCP 名称：`mcp__sif__market_get_asin_keyword_signals`
- Agent 名称：`sif_market_get_asin_keyword_signals`
- 分类：市场与关键词
- 功能：针对任意 ASIN（自有或竞品）进行关键词级流量信号分析。返回主要关键词的流量贡献、渠道依赖度（自然 vs 付费）、自然排名稳定性及健康分级。 触发时机：四条入口：(1) 流量诊断——traffic_structure 返回 natural_declining/both_declining_* 后定位根因关键词；(2) 竞品侦察——了解竞品流量由哪些关键词驱动及其薄弱点；(3) 选词候选——调 competition 前发现候选词；(4) 健康巡检——定期检查关键词占位。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 是否使用 listing search 口径（默认 false）
  listingSearch?: boolean;

  // 时间类型：lately / week / month, enums: [lately, week, month]
  time_type?: string;

  // 时间值：lately→'7' 或 '30'（默认 '7'）；week→周日日期如 '2026-03-29'（SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）；month→月份首日如 '2026-03-01'
  time_value?: string;

  // 返回关键词数量（默认 50，最大 300）
  topN?: number;

}
```

**输出**

· primary_signals：核心信号分区
  · declining[]：贡献变化最大的负向前3关键词
  · gaining[]：贡献变化最大的正向前3关键词
  · rank_gaps[]：自然排名断档的前3关键词（不稳定信号）
· secondary_signals：次要信号区
  · hint：溢出关键词的中文提示
  · keywords：完整次要列表
· top_keywords[]：按流量份额排序的完整列表
  · keyword：关键词
  · keyword_health：core/at_risk/volatile/paid_dependent/standard
  · rank_evolution：stable/improving/declining/volatile/gap_detected/no_organic
  · contri_change：流量贡献变化量
  · click_share：点击份额
  · top3_click_share：Top3 点击集中度（>0.5=被垄断）
  · sp_rank：SP 广告排名
  · sp_campaign_id：SP 广告活动 ID（可关联 ads_get_campaign_structure）
  · sb_rank：SB 广告排名
  · sbv_rank：SBV 广告排名
注意：
  · 本工具 = ASIN 级信号（特定关键词上的流量变化与排名状态）；market_get_keyword_competition = 市场级判断（竞争格局、可进入性）。
  · 不要仅凭 contri_change 推断市场可进入性——那是竞争工具的职责范围。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.15 `market_get_keyword_competition`

- MCP 名称：`mcp__sif__market_get_keyword_competition`
- Agent 名称：`sif_market_get_keyword_competition`
- 分类：市场与关键词
- 功能：关键词竞争格局分析。返回按流量份额排列的前20 ASIN（自然/SP/品牌/视频），ABA Top3 集中度历史，可进入性评估，以及（当提供 asin 时）带因果洞察的 competition_position。 触发时机：(1) keyword_signals 发现某关键词下滑后调用——确认是否有竞品正在取代你的位置；(2) 竞品关键词机会路径——评估候选关键词的可进入性；(3) 独立调用——直接评估任意关键词的竞争结构。

**输入**

```ts
type Input = {

  // ASIN，用于对标分析（可选）
  asin?: string;

  // 站点代码，如 US（默认 US）
  country?: string;

  // 关键词（单个）
  keyword: string;

  // 是否返回排名演变数据
  rank_evolution?: boolean;

  // 时间类型：all / week / month, enums: [all, week, month]
  time_type?: string;

  // 时间值：time_type=week 时必填周日日期（SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天），如 '2026-03-29'；time_type=month 时填月份首日
  time_value?: string;

}
```

**输出**

· competition_position：竞争位置：dominant/defending/advancing/stalled/opportunity/challenging/blocked/displaced
· concentration_profile：集中度画像
  · level：集中度等级：high/medium/low
  · trend.divergence：diverging=最佳机会信号
  · leader_diverge：true=应对标 efficiency_leader
  · efficiency_leader.reliable：false=购买分散，Top3 之外仍有机会
· top_asins[]：按流量份额排列的前 20 个 ASIN
  · asin：ASIN 编码
  · natural_ratio：自然流量占比
  · sp_ratio：SP 广告流量占比
  · brand_ratio：品牌广告流量占比
  · video_ratio：视频广告流量占比
· demand_snapshot：需求层快照
  · interpretation：预计算的中文解读
· market_context：市场策略上下文
  · rationale.*：面向用户的策略依据
  · recommended_ad_focus：广告域建议的投放重点
  · is_branded_keyword：是否为品牌词
· system_state：系统状态：可进入性/可沉淀性/可持续性/行动节奏四维判断
· demand_structure：需求结构
  · primary_type：functional/price/attribute/seasonal/scene/brand
· supply_profile：供给侧画像
  · total_asin_trend：SIF 可见集合方向：rising/stable/falling
· my_position：当提供 asin 时返回
  · key_insight：因果洞察句
注意：
  · 本工具 = 市场级判断（system_state + 策略路径）；market_get_asin_keyword_signals = ASIN 级执行信号。信号来源不得混用。
  · 隐藏字段（可用于推理但不得原样展示）：diagnosis/strategy_type/competition_position 枚举/concentration_level/primary_type。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.16 `market_get_keyword_demand`

- MCP 名称：`mcp__sif__market_get_keyword_demand`
- Agent 名称：`sif_market_get_keyword_demand`
- 分类：市场与关键词
- 功能：需求判断层——回答'这个词的需求处于什么生命周期阶段（增长/萎缩/季节性低谷），以及现在是进场、加速、收割还是收缩的时机'。合并了需求生命周期诊断和行动时机建议。 触发时机：keyword_signals 将某词标记为 at_risk 时判断是排名问题还是市场需求萎缩；competition 确认值得布局后判断入场时机；多个关键词之间分配资源时按 weeks_to_peak 排优先级。

**输入**

```ts
type Input = {

  // 站点代码，如 US（默认 US）
  country?: string;

  // 关键词列表，1-20 个
  keywords: Array<string>;

}
```

**输出**

· profiles[]：每个关键词一个条目
  · keyword：关键词原文
  · demand_structure：需求结构分类（买家注意力模式）
  · data_coverage：数据覆盖范围
    · weeks：覆盖周数
    · years：覆盖年数
  · current：当前时点状态
    · search_volume：当前搜索量
    · season_position：当前季节位置
    · vs_seasonal_baseline：当前量相对季节基线的偏差
  · trend：长期趋势
    · direction：趋势方向：growing/declining/stable
    · yoy_change：同比变化率
    · annual_decay_rate：年均衰减率
    · strength：趋势强弱：strong/moderate/weak
    · momentum：近期动量：accelerating/stable/peaking_reversing/recovering/recent_weakening
  · seasonality：季节性特征
    · strength：季节性强度：high/moderate/low
    · peak_months：历史峰值月份列表
    · trough_months：历史低谷月份列表
    · amplitude：峰谷振幅
  · diagnosis：需求生命周期诊断标签
  · interpretation：系统生成的中文解读
  · current_phase：当前季节性周期阶段：rising/peak/falling/trough
  · weeks_to_peak：距下一个峰值还有多少周（0=已在峰值）
  · action_hint：当前应采取的行动建议（面向用户）
  · seasonal_strength：时机信号可靠程度：high/moderate/low/insufficient
· timing_summary[]：按 weeks_to_peak 升序排列的摘要（最紧迫排最前）
  · keyword：关键词
  · weeks_to_peak：距峰值周数
  · action_hint：行动建议
注意：
  · action_phase 是内部标签，不得直接展示给用户，始终以 action_hint 作为面向用户的建议。
  · diagnosis 含义：growing=增长 / peaking_reversing=见顶回落 / recovering=回暖 / recent_weakening=早期预警 / mature_stable=成熟稳定 / seasonal_dip=正常淡季 / structural_declining=结构性下滑 / structural_declining_seasonal_dip=下滑+淡季

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.17 `market_get_keyword_history`

- MCP 名称：`mcp__sif__market_get_keyword_history`
- Agent 名称：`sif_market_get_keyword_history`
- 分类：市场与关键词
- 功能：需求量化层——返回精确词维度的需求原始数字：每期的 ABA 搜索量、ABA 排名、Top3 点击集中度和转化集中度。不做判断，只呈现数字。 触发时机：用户直接问搜索量或 ABA 排名等具体数字时首选；demand 工具给出诊断后想看原始数字核实时；需要对比多个关键词的搜索量大小时；需要了解流量是否被少数竞品垄断时。

**输入**

```ts
type Input = {

  // 站点代码，如 US（默认 US）
  country?: string;

  // 时间粒度：week / month（默认 week）, enums: [week, month]
  granularity?: string;

  // 关键词列表，1-10 个
  keywords: Array<string>;

}
```

**输出**

· keywords[]：每个关键词一个条目
  · keyword：关键词原文
  · data_points：历史数据点总数
  · dates[]：时间周期列表（升序）
  · volumes[]：每期 ABA 搜索量
  · ranks[]：每期 ABA 排名（0=未入榜）
  · top3_click_shares[]：每期 Top3 点击集中度（0-1）：>0.6=高度集中 / 0.3-0.6=中等 / <0.3=分散
  · top3_conversion_shares[]：每期 Top3 转化集中度（0-1）
  · latest：最新一期快照
    · date：最新数据日期
    · volume：最新搜索量
    · rank：最新 ABA 排名（0=未入榜）
    · top3_asins[]：最新 Top3 点击 ASIN 列表
    · top3_click_share：最新点击集中度
    · top3_conversion_share：最新转化集中度
注意：
  · 转化集中度远高于点击集中度 = 品牌黏性强，用户心智已被占领。
  · latest.rank=0 时说明该词当前未进入 ABA 排名，搜索量可能较低或数据暂缺。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.18 `market_get_keyword_root_trend`

- MCP 名称：`mcp__sif__market_get_keyword_root_trend`
- Agent 名称：`sif_market_get_keyword_root_trend`
- 分类：市场与关键词
- 功能：需求边界层——回答'这个词背后的整个市场有多大，买家需求是集中在精确词上，还是分散在大量长尾变体词里'。同时返回精确词搜索量和词根综合量，判断需求集中程度。 触发时机：用户评估一个词的市场潜力时需要看总盘子；精确词搜索量下降时判断是整个市场萎缩还是需求转移到长尾词；做选词规划时评估词根是否值得系统性铺设长尾变体。

**输入**

```ts
type Input = {

  // 站点代码，如 US（默认 US）
  country?: string;

  // 时间粒度：week / month（默认 week）, enums: [week, month]
  granularity?: string;

  // 关键词（单个）
  keyword: string;

}
```

**输出**

· keyword：关键词原文
· data_points：历史数据点总数
· dates[]：时间周期列表（升序）
· keyword_search_volumes[]：精确词每期 ABA 搜索量
· keyword_ranks[]：精确词每期 ABA 排名（0=未入榜）
· ext_search_volumes[]：词根下所有变体词每期综合搜索量
· latest：最新一期快照
  · date：最新数据日期
  · keyword_search_volume：精确词最新搜索量
  · keyword_rank：精确词最新 ABA 排名
  · ext_search_volume：词根综合搜索量最新值
  · coverage_ratio：精确词搜索量/词根综合量（0-1）：>0.8=需求集中 / 0.4-0.8=各占一部分 / <0.4=高度分散
注意：
  · coverage_ratio < 0.4 时主动说明需求高度分散，建议系统性布局长尾变体词。
  · 精确词量下降但词根综合量平稳/上升 = 需求未消失只是转移到长尾词；两条线同步下降 = 整个品类萎缩。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.19 `ops_get_asin_sales_list`

- MCP 名称：`mcp__sif__ops_get_asin_sales_list`
- Agent 名称：`sif_ops_get_asin_sales_list`
- 分类：运营与流量
- 功能：以列表视图查询一个或多个 ASIN 的销量数据，返回各变体的销量、价格、属性及月度趋势迷你图。 触发时机：用户希望对比各变体销量、按销量排序变体，或按 ASIN 查看销量明细时使用。

**输入**

```ts
type Input = {

  // 一个或多个待查询的 ASIN 列表
  asins: Array<string>;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 是否降序排列（默认 true）
  desc?: boolean;

  // 分组维度：asin / color / size, enums: [asin, color, size]
  dimension?: string;

  // 页码（默认 1）
  pageNum?: number;

  // 每页条数（默认 20，最大 100）
  pageSize?: number;

  // 排序字段：boughtInPastMonth / boughtInMonth / pasinBoughtInPastMonth, enums: [boughtInPastMonth, boughtInMonth, pasinBoughtInPastMonth]
  sortBy?: string;

  // 时间窗口类型：latelyDay / week / month（注意：week 必须传该周周日日期，如 '2026-03-29'，SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）, enums: [latelyDay, week, month]
  timePieceType?: string;

  // 时间窗口值：latelyDay 填天数如 '30'，week 填周日日期如 '2026-03-29'，month 填月份首日如 '2026-03-01'
  timePieceValue?: string;

}
```

**输出**

· total：符合条件的 ASIN 总数
· list[]：变体销量数据列表
  · asin：变体 ASIN
  · price：当前价格
  · color：颜色属性
  · size：尺码属性
  · boughtInPastMonth：近30天销量
  · boughtInMonth：当月销量
  · monthlyTrend[]：月度销量趋势迷你图数据点

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.20 `ops_get_asin_sales_trend`

- MCP 名称：`mcp__sif__ops_get_asin_sales_trend`
- Agent 名称：`sif_ops_get_asin_sales_trend`
- 分类：运营与流量
- 功能：查看 ASIN Listing 下各变体的月度销量历史趋势，用于分析销量走势和季节性规律。 触发时机：用户希望查看销量趋势走势、对比各变体的历史销量，或了解销量季节性规律时使用。

**输入**

```ts
type Input = {

  // 主 ASIN，例如 B0CLPGQWNB
  asin: string;

  // 指定要查询的变体 ASIN 列表（可选）
  asins?: Array<string>;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 分组维度：asin / color / size / material_type, enums: [asin, color, size, material_type]
  dimension?: string;

  // 页码（默认 1）
  pageNum?: number;

  // 每页条数（默认 20，最大 100）
  pageSize?: number;

  // 时间类型：latelyDay / week / month（注意：week 必须传该周周日日期，如 '2026-03-29'，SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）, enums: [latelyDay, week, month]
  timePieceType?: string;

  // 时间值：latelyDay 填天数，week 填周日日期如 '2026-03-29'，month 填月份首日如 '2026-03-01'
  timePieceValue?: string;

}
```

**输出**

· list[]：按变体或维度分组的销量时间序列
  · asin：变体 ASIN
  · dimension：分组维度值（如颜色/尺码）
  · months[]：月度销量数据点
    · date：月份（yyyy-MM）
    · sales：该月销量

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.21 `ops_get_asin_traffic_trend`

- MCP 名称：`mcp__sif__ops_get_asin_traffic_trend`
- Agent 名称：`sif_ops_get_asin_traffic_trend`
- 分类：运营与流量
- 功能：查看 ASIN 的流量趋势时间序列，按周期返回总流量分数及自然/广告渠道拆解。 触发时机：用户明确要求查看原始流量数据或趋势走势时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B01NBNDC1T
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 是否对齐开始时间
  dateAlignment?: boolean;

  // 是否返回 Keepa 相关信息
  fetchKeepa?: boolean;

  // 是否返回得分相关信息
  fetchScore?: boolean;

  // 时间粒度, enums: [day, week, month]
  granularity?: string;

  // 最近天数窗口，>=0
  lastDays?: number;

  // 最近月数窗口，可选 1/2/3/6/12/24，默认 3
  lastMonths?: number;

  // 是否使用 listingSearch 口径
  listingSearch?: boolean;

}
```

**输出**

· dates[]：时间点列表
· scores[]：各时间点总流量分数
· channelBreakdown[]：各时间点渠道拆解
  · natural：自然流量分数
  · ad：广告流量分数
  · sp：SP 常规广告分数
  · recSp：SP 推荐广告分数
  · sb：SB 广告分数
  · sbv：SBV 广告分数

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.22 `ops_get_asin_traffic_trend_detail`

- MCP 名称：`mcp__sif__ops_get_asin_traffic_trend_detail`
- Agent 名称：`sif_ops_get_asin_traffic_trend_detail`
- 分类：运营与流量
- 功能：查看 ASIN 在指定时间窗口内的关键词级流量明细，按关键词分页返回各渠道排名与分数拆解。 触发时机：用户明确要求查看某个时间窗口内的原始关键词级流量数据时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B01NBNDC1T
  asin: string;

  // 变化类型筛选
  changeType?: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 是否倒序
  desc: boolean;

  // 指定周期开始时间的第一天，day：yyyy-MM-dd，week：yyyy-MM-dd（仅支持周日，当周数据有T+1延迟），month：yyyy-MM
  endDay: string;

  // 额外过滤条件
  filter?: string;

  // 时间粒度（下钻建议使用 day）, enums: [day, week, month]
  granularity: string;

  // 周期间隔值
  interval?: number;

  // 流量类型, enums: [all, nf, ad, sp, recSp, sb, sbv]
  keywordType?: string;

  // 最近月数窗口
  lastMonths?: number;

  // 页码，>=1
  pageNum: number;

  // 分页大小，建议 <=200
  pageSize: number;

  // 关键词过滤
  searchKeyword?: string;

  // 排序字段，如 searchesRank
  sortBy?: string;

  // 业务类型
  type?: string;

}
```

**输出**

· total：符合条件的关键词总条数
· list[]：分页的关键词行数据
  · keyword：关键词文本
  · totalScore：该关键词总流量分数
  · naturalScore：自然流量分数
  · adScore：广告流量分数
  · naturalRank：自然搜索排名
  · spRank：SP 广告排名
  · sbRank：SB 广告排名
注意：
  · 不适用于诊断或根因分析——如需根因分析，请使用 analyze_traffic_anomaly。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.23 `ops_get_listing_keyword_distribution`

- MCP 名称：`mcp__sif__ops_get_listing_keyword_distribution`
- Agent 名称：`sif_ops_get_listing_keyword_distribution`
- 分类：运营与流量
- 功能：查看各变体的关键词数量分布，返回每个变体在自然流量、SP、SB、SBV 各渠道中覆盖的流量词数量。 触发时机：用户询问各变体的关键词覆盖情况、哪个变体词量更多，或想查看反查流量词在各变体间的分布时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 分组维度：asin / color / size
  dimension?: string;

  // 页码
  pageNum?: number;

  // 分页大小
  pageSize?: number;

  // 展示模式：1=关键词数量 / 2=流量曝光分数（默认 1）
  showType?: number;

  // 排序字段
  sortBy?: string;

  // 时间类型：latelyDay / week / month（注意：week 必须传该周周日日期，如 '2026-03-29'，SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）, enums: [latelyDay, week, month]
  timePieceType?: string;

  // 时间值：latelyDay 填天数，week 填周日日期如 '2026-03-29'，month 填月份首日如 '2026-03-01'
  timePieceValue?: string;

}
```

**输出**

· total：变体总数
· list[]：各变体关键词分布行数据
  · asin：变体 ASIN
  · dimensionValue：分组维度值（如颜色/尺码）
  · total：覆盖的总词数
  · natural：自然流量词数
  · ad：广告词总数（含所有广告渠道）
  · sp：SP 常规广告词数
  · rec：SP 推荐广告词数
  · brand：SB 广告词数
  · vedio：SBV 广告词数

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.24 `ops_get_listing_traffic_overview`

- MCP 名称：`mcp__sif__ops_get_listing_traffic_overview`
- Agent 名称：`sif_ops_get_listing_traffic_overview`
- 分类：运营与流量
- 功能：查看 Listing 级别的自然流量与广告流量占比，按渠道（SP常规/SP推荐/SB/SBV）拆解总分，并返回推荐专栏来源分布。 触发时机：用户询问流量构成、自然/广告占比，或哪种广告类型带来的流量最多时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 是否使用 listing search 口径
  isListingSearch?: boolean;

  // 时间类型：latelyDay / week / month（注意：week 必须传该周周日日期，如 '2026-03-29'，SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）, enums: [latelyDay, week, month]
  timePieceType?: string;

  // 时间值：latelyDay 填 '7' 或 '30'；week 填周日日期如 '2026-03-29'；month 填月份首日如 '2026-03-01'
  timePieceValue?: string;

}
```

**输出**

· overview：自然/广告流量汇总概览
  · totalScore：总流量分数
  · naturalScore：自然流量分数及占比
  · adScore：广告总流量分数及占比
· adChannelBreakdown：广告渠道拆解
  · spScore：SP 常规广告分数
  · recSpScore：SP 推荐广告分数
  · sbScore：SB 广告分数
  · sbvScore：SBV 广告分数
· recSourceDistribution[]：推荐专栏来源分布
  · source：来源类型
  · score：该来源的流量分数
  · ratio：占比

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.25 `ops_get_listing_traffic_structure`

- MCP 名称：`mcp__sif__ops_get_listing_traffic_structure`
- Agent 名称：`sif_ops_get_listing_traffic_structure`
- 分类：运营与流量
- 功能：查看 Listing 内各变体的流量结构拆解，返回每个变体在自然流量、SP、SB、SBV 渠道中各自的分数与占比。 触发时机：用户询问哪个变体获得流量最多、各变体之间的流量分布情况，或想按变体对比自然流量与广告依赖程度时使用。

**输入**

```ts
type Input = {

  // ASIN，例如 B0CLPGQWNB
  asin: string;

  // 站点代码（country字段），如 US(美国) / UK(英国) / DE(德国) / CA(加拿大) / JP(日本) / FR(法国) / ES(西班牙) / IT(意大利) / MX(墨西哥) / AU(澳大利亚) / AE(阿联酋) / BR(巴西) / SA(沙特阿拉伯)（默认 US）
  country?: string;

  // 维度
  dimension?: string;

  // 页码
  pageNum?: number;

  // 分页大小
  pageSize?: number;

  // 排序字段
  sortBy?: string;

  // 时间类型：latelyDay / week / month（注意：week 必须传该周周日日期，如 '2026-03-29'，SIF 数据以周日为每周第一天，当周数据因T+1延迟不可用，如需查当周请使用近7天）, enums: [latelyDay, week, month]
  timePieceType?: string;

  // 时间值：latelyDay 填 '7' 或 '30'；week 填周日日期如 '2026-03-29'；month 填月份首日如 '2026-03-01'
  timePieceValue?: string;

}
```

**输出**

· total：变体总数
· list[]：各变体流量结构行数据
  · asin：变体 ASIN
  · dimensionValue：分组维度值（如颜色/尺码）
  · totalScore：总流量分数
  · nfs：自然流量分数
  · ads：广告总流量分数
  · sps：SP 常规广告分数
  · recs：SP 推荐广告分数
  · sbs：SB 广告分数
  · sbvs：SBV 广告分数

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.26 `ping`

- MCP 名称：`mcp__sif__ping`
- Agent 名称：`sif_ping`（理论映射名，当前 Insight Agent 未注册）
- 分类：系统
- 当前状态：MCP connector/schema 可见；项目 `build_sif_tool_catalog()` 显式排除，Agent 未注册
- 功能：检查 SIF MCP 服务是否连通，建议在接入或排障开始时调用。

**输入**

```ts
type Input = {
}
```

**输出**

当前工具说明未给出字段级返回清单；返回类型为 `CallToolResult`。

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

### 4.27 `sif_catalog`

- MCP 名称：`mcp__sif__sif_catalog`
- Agent 名称：`sif_sif_catalog`
- 分类：系统
- 功能：返回 SIF MCP 所有可用工具的分类目录。 触发时机：用户询问'有哪些工具' / '能做什么' / '功能列表' / '工具介绍' 时使用。

**输入**

```ts
type Input = {
}
```

**输出**

· title：目录标题
· categories：按大类+子类组织的工具列表，每个分类含简要说明
· tip：引导语

**输出 schema 状态**：顶层声明为 `CallToolResult`；上面的业务字段来自当前 SIF tool description。

## 5. 对 Insight Agent 的使用建议

1. 在 Skill 的 `Tool Policy` 中使用 Agent 名称，不要写 MCP connector 名称。
2. 保存每次工具调用的 `tool_name`、输入参数、采集时间、站点、统计周期和原始响应。
3. SellerSprite 返回先通过适配器归一化，再进入分析层；不要让 Skill 直接依赖未声明的深层字段。
4. SIF 的 `market_*`、`ops_*`、`ads_*` 分属市场、运营结果和广告域，跨域结论必须由分析层综合，不能把一个域的信号冒充另一个域的结果。
5. 同一 ASIN 或关键词由两个 provider 返回时，保留字段级来源与时间口径，不要静默覆盖。
6. MCP 服务端升级后重新生成本表，并用真实响应回归测试关键适配器。
7. 如需让 Agent 主动做 SIF 连通性检查，需要修改项目适配器，允许 `build_sif_tool_catalog()` 注册 `ping`。
