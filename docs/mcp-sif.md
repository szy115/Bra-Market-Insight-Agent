# Sif MCP Integration

Sif MCP docs: `https://mcp.sif.com/#tools`

This project exposes selected Sif MCP tools to the Agent with the `sif_` prefix.

## Configuration

Set these values in `.env`:

```env
SIF_MCP_URL=https://mcp.sif.com/mcp
SIF_MCP_SCHEMA_URL=https://mcp.sif.com/mcp-api/tool-schema.json
SIF_MCP_TOKEN=
```

Optional:

```env
SIF_MCP_TOOLS=market_get_keyword_demand,market_get_keyword_history,market_get_keyword_root_trend,market_get_keyword_competition,market_get_asin_keyword_signals,ops_get_asin_sales_list,ops_get_asin_sales_trend
```

Use `SIF_MCP_TOOLS=*` to expose all Sif MCP tools. The default is intentionally curated to avoid overwhelming the model.

## Exposed Tool Names

Sif MCP tool names are exposed as Agent tools by prefixing `sif_`.

Examples:

| Sif MCP tool | Agent tool |
| --- | --- |
| `market_get_keyword_demand` | `sif_market_get_keyword_demand` |
| `market_get_keyword_history` | `sif_market_get_keyword_history` |
| `market_get_keyword_competition` | `sif_market_get_keyword_competition` |
| `market_get_asin_keyword_signals` | `sif_market_get_asin_keyword_signals` |
| `ops_get_asin_sales_list` | `sif_ops_get_asin_sales_list` |

## Skill Usage

Use Sif tools in `Tool Policy` when the Skill needs quantitative Amazon demand, ABA, keyword competition, ASIN keyword, or sales proxy evidence.

```md
| sif_market_get_keyword_demand | conditional | 用户要求 ABA、搜索量或关键词需求阶段时补充 Sif 关键词需求证据 |
```

Use Sif tools in `Evidence Contract` when the final report must disclose whether this evidence was collected.

```md
| sif_keyword_demand | sif_market_get_keyword_demand | prompt_mentions:ABA,搜索量,需求量,搜索热度 | 1 | warn | continue_with_gap | 如果 Sif 关键词需求证据缺失，报告不得声称已验证搜索量或 ABA 需求阶段 |
```

## Result Handling

Sif tool results are normalized into the existing Agent tool result shape:

```json
{
  "name": "sif_market_get_keyword_demand",
  "label": "Sif: market_get_keyword_demand",
  "status": "ok",
  "summary": "Sif returned keyword evidence for 1 keyword(s).",
  "input": {"keywords": ["minimizer bra"], "country": "US"},
  "data": {}
}
```

If authentication is missing or rejected, the tool returns `needs_user_action` and the Agent should mark the Sif data as unavailable rather than inventing quantitative evidence.

Sif tool descriptions may require preserving a `render_footer` verification string. The adapter keeps this field in `data` so the final Artifact can cite or display it when present.
