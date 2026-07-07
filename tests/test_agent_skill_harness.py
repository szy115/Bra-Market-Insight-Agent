from insight_agent.agent_skill_harness import (
    allowed_data_tools_for_skill,
    evaluate_tool_policy,
    parse_evidence_contract,
    parse_tool_policy,
    validate_evidence_contract,
)

SAMPLE_SKILL = """
# Sample Skill

## Tool Policy

| tool | policy | reason |
| --- | --- | --- |
| load_skill | system | Load the Skill |
| amazon_shelf | required | Shelf evidence |
| reddit_voc | allowed | User language |
| tiktok_social | conditional | Social validation |
| media_rankings | disallowed | Not needed |

## Evidence Contract

| evidence_id | tool | required_when | min_success | severity | if_missing | artifact_requirement |
| --- | --- | --- | --- | --- | --- | --- |
| amazon | amazon_shelf | always | 1 | block | call_missing_tool | Need Amazon shelf evidence |
| reddit | reddit_voc | prompt_mentions:Reddit,用户 | 1 | warn | continue_with_gap | Mark Reddit gap |
| tiktok | tiktok_social | param_present:need_tiktok | 1 | warn | continue_with_gap | Mark TikTok gap |
"""


def test_parse_tool_policy_and_evidence_contract() -> None:
    policy = parse_tool_policy(SAMPLE_SKILL)
    contract = parse_evidence_contract(SAMPLE_SKILL)

    assert policy[1] == {"tool": "amazon_shelf", "policy": "required", "reason": "Shelf evidence"}
    assert contract[0]["evidence_id"] == "amazon"
    assert contract[0]["min_success"] == 1
    assert contract[1]["required_when"] == "prompt_mentions:Reddit,用户"


def test_tool_policy_allows_declared_tools_and_blocks_disallowed_or_unlisted() -> None:
    skill = {"tool_policy": parse_tool_policy(SAMPLE_SKILL)}

    assert allowed_data_tools_for_skill(
        skill,
        ["amazon_shelf", "reddit_voc", "tiktok_social", "media_rankings", "unknown_tool"],
    ) == ["amazon_shelf", "reddit_voc", "tiktok_social"]
    assert evaluate_tool_policy(skill, "amazon_shelf").allowed is True
    assert evaluate_tool_policy(skill, "media_rankings").allowed is False
    assert evaluate_tool_policy(skill, "unknown_tool").allowed is False


def test_evidence_contract_blocks_required_gap_and_warns_conditional_gap() -> None:
    skill = {"evidence_contract": parse_evidence_contract(SAMPLE_SKILL)}

    blocked = validate_evidence_contract(
        skill,
        prompt="分析 Reddit 用户声音",
        params={"need_tiktok": True},
        tools=[],
        success_statuses={"ok", "partial_ok"},
    )

    assert blocked["status"] == "blocked"
    assert [gap["evidence_id"] for gap in blocked["block_gaps"]] == ["amazon"]
    assert {gap["evidence_id"] for gap in blocked["warn_gaps"]} == {"reddit", "tiktok"}

    warned = validate_evidence_contract(
        skill,
        prompt="分析 Reddit 用户声音",
        params={},
        tools=[{"name": "amazon_shelf", "status": "ok"}],
        success_statuses={"ok", "partial_ok"},
    )

    assert warned["status"] == "warn"
    assert [gap["evidence_id"] for gap in warned["warn_gaps"]] == ["reddit"]
