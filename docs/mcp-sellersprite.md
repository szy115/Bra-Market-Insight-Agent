# SellerSprite MCP Integration

This project can expose SellerSprite MCP tools to the Agent with the `sellersprite_` prefix.

## Configuration

Set these values in `.env`:

```env
SELLERSPRITE_MCP_URL=https://mcp.sellersprite.com/mcp
SELLERSPRITE_MCP_SECRET_KEY=
```

The SellerSprite MCP config shape is:

```json
{
  "mcpServers": {
    "sellersprite-mcp": {
      "type": "streamableHttp",
      "url": "https://mcp.sellersprite.com/mcp",
      "description": "SellerSpriteMCP",
      "headers": {
        "secret-key": "Your Secret"
      }
    }
  }
}
```

Optional:

```env
SELLERSPRITE_MCP_TOOLS=*
```

Use `SELLERSPRITE_MCP_TOOLS=tool_a,tool_b` to expose only a curated subset. The default is `*`, which exposes every tool returned by SellerSprite `tools/list` after authentication.

## Exposed Tool Names

SellerSprite MCP tool names are exposed as Agent tools by prefixing `sellersprite_`.

Examples:

| SellerSprite MCP tool | Agent tool |
| --- | --- |
| `keyword_research` | `sellersprite_keyword_research` |
| `market_research` | `sellersprite_market_research` |

The actual list depends on SellerSprite `tools/list`. Ask the Agent "你可以调用哪些工具？" after setting `SELLERSPRITE_MCP_SECRET_KEY` to verify the runtime catalog.

## Skill Usage

Use SellerSprite tools in `Tool Policy` when the Skill needs SellerSprite market, keyword, product, or competitor evidence.

```md
| sellersprite_market_research | conditional | 用户要求卖家精灵市场规模、类目、关键词或竞品量化数据时调用 |
```

Use SellerSprite tools in `Evidence Contract` when the final report must disclose whether this evidence was collected.

```md
| sellersprite_market_data | sellersprite_market_research | prompt_mentions:卖家精灵,SellerSprite,市场规模,关键词需求,竞品数据 | 1 | warn | continue_with_gap | 如果 SellerSprite 证据缺失，报告不得声称已验证卖家精灵市场数据 |
```

## Result Handling

SellerSprite tool results are normalized into the existing Agent tool result shape:

```json
{
  "name": "sellersprite_market_research",
  "label": "SellerSprite: market_research",
  "status": "ok",
  "summary": "SellerSprite returned structured evidence.",
  "input": {},
  "data": {}
}
```

If authentication is missing or rejected, the tool returns `needs_user_action` and the Agent should mark SellerSprite data as unavailable rather than inventing quantitative evidence.
