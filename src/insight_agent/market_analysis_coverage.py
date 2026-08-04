from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SUCCESS_STATUSES = {"ok", "partial_ok", "success", "completed"}


@dataclass(frozen=True)
class AnalysisDimension:
    dimension_id: str
    name: str
    market_question: str
    priority: str
    required_tool_groups: tuple[tuple[str, ...], ...]
    supporting_tools: tuple[str, ...]
    allowed_conclusion: str
    limitation: str


MARKET_ANALYSIS_DIMENSIONS: tuple[AnalysisDimension, ...] = (
    AnalysisDimension(
        "M01",
        "市场边界",
        "输入词是真实类目、功能型市场还是用户任务，纳入和排除范围是什么？",
        "P0",
        (("sellersprite_product_node", "sellersprite_asin_detail"), ("sif_market_get_keyword_root_trend",)),
        ("sellersprite_product_research", "sellersprite_competitor_lookup"),
        "定义 Amazon 节点、关键词需求边界和代理节点口径。",
        "节点商品数不等于细分市场容量；代理节点只能作为大类背景。",
    ),
    AnalysisDimension(
        "M02",
        "市场已兑现容量 VoM",
        "类目销量、销售额、均价、利润代理和新品贡献有多大？",
        "P0",
        (("sellersprite_market_research",), ("sellersprite_market_research_statistics",)),
        (),
        "描述第三方估算口径下的市场容量、成熟度和新品承载。",
        "销量、销售额和利润均为第三方代理，不是 Amazon 后台真实值。",
    ),
    AnalysisDimension(
        "M03",
        "搜索需求边界",
        "精确词之外还有多少长尾需求，单一入口是否低估整个需求市场？",
        "P0",
        (("sif_market_get_keyword_root_trend",),),
        ("sellersprite_keyword_miner",),
        "比较精确词与词根长尾规模，形成关键词簇。",
        "不同关键词可能重叠，未完成去重时不得相加为市场总量。",
    ),
    AnalysisDimension(
        "M04",
        "搜索需求规模 VoS",
        "搜索量、购买量、购买率和供需比处于什么水平？",
        "P0",
        (("sif_market_get_keyword_history",), ("sellersprite_keyword_research",)),
        ("sif_market_get_keyword_demand",),
        "量化 Amazon 站内需求水平和购买效率。",
        "搜索量不能直接换算为销量，购买率也不能替代 Listing 转化率。",
    ),
    AnalysisDimension(
        "M05",
        "需求趋势与生命周期",
        "需求正在增长、稳定、衰退还是处于季节波动？",
        "P0",
        (("sif_market_get_keyword_demand",), ("sellersprite_keyword_research_trends",)),
        ("sellersprite_aba_research_trend",),
        "判断需求方向、生命周期和行动时机。",
        "季节性至少需要两个可比周期。",
    ),
    AnalysisDimension(
        "M06",
        "周度关键词变化",
        "最近一周哪些词出现增长、异动、潜力或集中度变化？",
        "P0",
        (("sellersprite_aba_research_weekly",),),
        ("sellersprite_aba_research_monthly", "sif_market_get_keyword_history"),
        "识别近期增长词、异动词和热点迁移。",
        "单周异动不等于稳定趋势，必须与历史窗口对照。",
    ),
    AnalysisDimension(
        "M07",
        "关键词竞争结构",
        "流量是否被少数 ASIN 占据，关键词是否存在可进入空间？",
        "P0",
        (("sif_market_get_keyword_competition",),),
        ("sellersprite_keyword_research", "sellersprite_keyword_miner"),
        "描述点击集中度、Top ASIN 和关键词竞争门槛。",
        "低集中度不自动等于蓝海，高搜索量也不自动等于可进入。",
    ),
    AnalysisDimension(
        "M08",
        "节点需求质量",
        "页面浏览、商品数、搜索购买比和退货风险如何？",
        "P0",
        (("sellersprite_market_product_demand_trend",),),
        (),
        "比较当前节点与同类目的需求效率和风险水平。",
        "搜索购买比必须保留工具原始定义，不得改写为转化率。",
    ),
    AnalysisDimension(
        "M09",
        "商品集中度",
        "Top Listing 承载多少销量，市场由少数爆款还是分散商品组成？",
        "P0",
        (("sellersprite_market_product_concentration",),),
        ("sellersprite_competitor_lookup",),
        "判断头部商品主导程度和新品面对的商品壁垒。",
        "集中度是样本范围内指标，父子体和变体未去重时需降级。",
    ),
    AnalysisDimension(
        "M10",
        "品牌集中度",
        "头部品牌占比多高，新品牌是否仍有成长空间？",
        "P0",
        (("sellersprite_market_brand_concentration",),),
        (),
        "判断品牌心智和品牌层面的市场主导程度。",
        "品牌集中度不能单独证明消费者忠诚或品牌溢价。",
    ),
    AnalysisDimension(
        "M11",
        "卖家集中度",
        "销量是否集中在少数卖家，而不只是少数品牌？",
        "P0",
        (("sellersprite_market_seller_concentration",),),
        ("sellersprite_market_seller_type_concentration",),
        "判断卖家层面的竞争壁垒并与品牌集中度区分。",
        "同一卖家可能运营多个品牌，不能把卖家集中度当作品牌集中度。",
    ),
    AnalysisDimension(
        "M12",
        "价格带结构",
        "哪些价格带承载销量，各价格带的商品密度和销售效率如何？",
        "P0",
        (("sellersprite_market_price_distribution",),),
        ("sellersprite_asin_coupon_trend",),
        "识别主力价格带、竞争密度和待验证定价空间。",
        "价格带销量占比不等于消费者愿付价格，套装与折扣需单独校正。",
    ),
    AnalysisDimension(
        "M13",
        "质量成熟度",
        "不同评分值商品分别承载多少销量，市场质量是否成熟？",
        "P0",
        (("sellersprite_market_rating_distribution",),),
        ("sellersprite_review",),
        "描述评分值结构和不同质量层级的销售承载。",
        "低评分仍有销量只能产生改善假设，不能直接判定产品机会。",
    ),
    AnalysisDimension(
        "M14",
        "评论壁垒",
        "低评论数商品能否获得销量，新品面对多高的评价积累门槛？",
        "P0",
        (("sellersprite_market_ratings_count_distribution",),),
        ("sellersprite_market_product_concentration",),
        "判断评论积累结构和新品进入难度。",
        "历史评论数分布不是新品必须达到的确定阈值。",
    ),
    AnalysisDimension(
        "M15",
        "新品接受度",
        "近 6/12/24 个月商品能否获得销量，老品是否长期主导？",
        "P0",
        (("sellersprite_market_listing_date_distribution",),),
        ("sellersprite_market_listing_trend_distribution",),
        "判断新品销量承载和相对进入难度。",
        "上架时间与销量相关，不直接证明产品创新或消费者偏好。",
    ),
    AnalysisDimension(
        "M16",
        "生命周期结构",
        "不同上架年份商品的销售效率和平均评分如何？",
        "P0",
        (("sellersprite_market_listing_trend_distribution",),),
        ("sellersprite_market_listing_date_distribution",),
        "识别新品期、成长期、成熟期和长尾产品结构。",
        "生命周期判断必须保留绝对上架时间和样本窗口。",
    ),
    AnalysisDimension(
        "M17",
        "商品样本与范围复核",
        "功能型市场包含哪些真实商品，父子体和变体是否重复？",
        "P1",
        (("sellersprite_product_research",),),
        ("sellersprite_competitor_lookup", "sellersprite_asin_detail"),
        "建立可审计商品候选池并验证市场边界。",
        "只有 market_product_identity.v1 成功并输出 family_id 时才能披露统一池内的唯一商品家族数；不得外推为完整市场商品总数。",
    ),
    AnalysisDimension(
        "M18",
        "用户好差评与研发机会",
        "用户为什么购买、为什么不满意，产品失败机制是什么？",
        "P1",
        (("sellersprite_review",),),
        ("sellersprite_asin_detail",),
        "从分层评论样本中提炼购买理由、权衡点和失败机制。",
        "评论样本不能代表整个人群，商品页面评论总量也不是本轮样本量。",
    ),
    AnalysisDimension(
        "M19",
        "站外搜索趋势校验",
        "Google 搜索相对热度与 Amazon 站内需求方向是否一致，是否存在站外季节性或背离？",
        "P0",
        (("sellersprite_google_trend",),),
        (),
        "以独立相对指数校验站外需求方向、季节波动和与 Amazon 站内趋势的一致性。",
        "Google Trends 是指定关键词、地区和时间窗口内归一化的相对热度，不是绝对搜索量，不得与 Amazon 搜索量相加或直接换算销量。",
    ),
)


def _tool_evidence_ids(tool_results: list[dict[str, Any]]) -> dict[str, list[str]]:
    evidence: dict[str, list[str]] = {}
    for index, tool in enumerate(tool_results, start=1):
        if not isinstance(tool, dict):
            continue
        evidence.setdefault(str(tool.get("name") or ""), []).append(f"E{index:02d}")
    return evidence


def evaluate_market_analysis_coverage(
    tool_results: list[dict[str, Any]],
    *,
    category_node_id: str = "",
) -> dict[str, Any]:
    successful = {
        str(tool.get("name") or "")
        for tool in tool_results
        if isinstance(tool, dict) and str(tool.get("status") or "") in SUCCESS_STATUSES
    }
    called = {str(tool.get("name") or "") for tool in tool_results if isinstance(tool, dict)}
    evidence_by_tool = _tool_evidence_ids(tool_results)
    dimensions: list[dict[str, Any]] = []
    for definition in MARKET_ANALYSIS_DIMENSIONS:
        groups = [set(group) for group in definition.required_tool_groups]
        satisfied_groups = [group for group in groups if group & successful]
        if definition.dimension_id == "M01" and category_node_id:
            satisfied_groups = [groups[0], *[group for group in satisfied_groups if group != groups[0]]]
        any_relevant_called = bool(
            called
            & {
                tool
                for group in definition.required_tool_groups
                for tool in group
            }
        )
        if len(satisfied_groups) == len(groups):
            status = "covered"
        elif definition.priority == "P1" and not any_relevant_called:
            status = "not_triggered"
        elif satisfied_groups or any_relevant_called:
            status = "partial"
        else:
            status = "missing"
        used_tools = sorted(
            successful
            & {
                *definition.supporting_tools,
                *(tool for group in definition.required_tool_groups for tool in group),
            }
        )
        record = asdict(definition)
        record.update(
            {
                "status": status,
                "used_tools": used_tools,
                "evidence_ids": list(
                    dict.fromkeys(
                        evidence_id
                        for tool in used_tools
                        for evidence_id in evidence_by_tool.get(tool, [])
                    )
                ),
                "missing_tool_groups": [
                    sorted(group)
                    for group in groups
                    if group not in satisfied_groups
                ],
            }
        )
        dimensions.append(record)

    p0 = [item for item in dimensions if item["priority"] == "P0"]
    return {
        "schema_version": "market_analysis_coverage.v1",
        "summary": {
            "p0_total": len(p0),
            "p0_covered": sum(item["status"] == "covered" for item in p0),
            "p0_partial": sum(item["status"] == "partial" for item in p0),
            "p0_missing": sum(item["status"] == "missing" for item in p0),
            "p1_triggered": sum(item["priority"] == "P1" and item["status"] != "not_triggered" for item in dimensions),
        },
        "dimensions": dimensions,
    }


def build_tool_methodology(
    tool_results: list[dict[str, Any]],
    tool_descriptions: dict[str, str],
) -> list[dict[str, Any]]:
    dimension_by_tool: dict[str, list[AnalysisDimension]] = {}
    for definition in MARKET_ANALYSIS_DIMENSIONS:
        for tool in {
            *definition.supporting_tools,
            *(item for group in definition.required_tool_groups for item in group),
        }:
            dimension_by_tool.setdefault(tool, []).append(definition)

    methodology: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tool_results:
        tool_name = str(tool.get("name") or "") if isinstance(tool, dict) else ""
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        definitions = dimension_by_tool.get(tool_name, [])
        methodology.append(
            {
                "tool": tool_name,
                "role": "methodology_only",
                "mcp_description": str(tool_descriptions.get(tool_name) or ""),
                "analysis_dimensions": [item.dimension_id for item in definitions],
                "market_questions": [item.market_question for item in definitions],
                "allowed_conclusions": [item.allowed_conclusion for item in definitions],
                "limitations": [item.limitation for item in definitions],
            }
        )
    return methodology


def build_market_dimension_results(
    analysis_coverage: dict[str, Any],
    chart_manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    charts_by_dimension = {
        str(item.get("dimension_id") or ""): item
        for item in chart_manifest
        if isinstance(item, dict) and item.get("dimension_id")
    }
    results: list[dict[str, Any]] = []
    for item in analysis_coverage.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        dimension_id = str(item.get("dimension_id") or "")
        chart = charts_by_dimension.get(dimension_id) or {
            "dimension_id": dimension_id,
            "chart_status": "missing_data",
            "reason": "No chart contract was compiled for this analysis dimension.",
        }
        results.append(
            {
                "dimension_id": dimension_id,
                "name": item.get("name"),
                "market_question": item.get("market_question"),
                "priority": item.get("priority"),
                "analysis_status": item.get("status"),
                "used_tools": item.get("used_tools") or [],
                "evidence_ids": item.get("evidence_ids") or [],
                "allowed_conclusion": item.get("allowed_conclusion"),
                "limitation": item.get("limitation"),
                "chart": {
                    "chart_id": chart.get("chart_id"),
                    "title": chart.get("title"),
                    "type": chart.get("type"),
                    "status": chart.get("chart_status"),
                    "reason": chart.get("reason"),
                    "evidence_ids": chart.get("evidence_ids") or [],
                },
            }
        )
    return results
