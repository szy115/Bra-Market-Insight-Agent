from __future__ import annotations

from ._provider_shared import ProviderCapabilityFamily

SELLERSPRITE_AGENT_TOOL_PREFIX = "sellersprite_"
SELLERSPRITE_CAPABILITY_FAMILY = ProviderCapabilityFamily(
    agent_tool_prefix=SELLERSPRITE_AGENT_TOOL_PREFIX,
    provider_label="SellerSprite",
    source="sellersprite_mcp",
    auth_env_names=(
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
    ),
    result_contract_id="sellersprite_result.v1",
    default_summary="SellerSprite MCP returned structured evidence.",
)
