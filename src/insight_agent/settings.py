from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.getenv("INSIGHT_AGENT_HOME", Path.cwd())).resolve()
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
LLM_PROVIDERS_PATH = PACKAGE_DIR / "data" / "llm_providers.json"

SECRET_PLACEHOLDERS = {
    "",
    "sk-xxx",
    "xxx",
    "your-key",
    "your-api-key",
    "your-client-id",
    "your_client_id",
    "your-client-secret",
    "your_client_secret",
}
DEFAULT_REDDIT_USER_AGENT = "InsightAgentRedditDemo/0.1 by yourname"
DEFAULT_RESEARCH_MODE = "auto"
DEFAULT_RESEARCH_TIME_RANGE = "year"
DEFAULT_RESEARCH_POST_LIMIT = 50
MAX_RESEARCH_POST_LIMIT = 500
DEFAULT_LLM_EVIDENCE_POSTS = 12
DEFAULT_LLM_COMMENT_SAMPLES_PER_POST = 5
DEFAULT_AMAZON_PRODUCT_LIMIT = 20
MAX_AMAZON_PRODUCT_LIMIT = 100
DEFAULT_AMAZON_KEYWORD_LIMIT = 8
MAX_AMAZON_KEYWORD_LIMIT = 20
DEFAULT_AMAZON_DETAIL_LIMIT = 5
DEFAULT_AMAZON_DISCUSSION_LIMIT = 5
DEFAULT_AMAZON_REVIEWS_PER_PRODUCT = 5
DEFAULT_AMAZON_LLM_PRODUCT_LIMIT = 25
DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT = 5
DEFAULT_WEB_SEARCH_PROVIDER = "agent_reach"


def int_setting(values: dict[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(values.get(key, str(default)) or default)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class LLMProvider:
    name: str
    label: str
    api_key_env: str | None
    base_url_env: str
    default_model: str
    default_base_url: str
    api_key_required: bool = True


@dataclass(frozen=True)
class WebSearchProvider:
    name: str
    label: str
    api_key_env: str = ""
    requires_search_engine_id: bool = False
    search_engine_id_env: str | None = None


@dataclass(frozen=True)
class MCPDataSourceCredential:
    id: str
    label: str
    canonical_env: str
    accepted_env_names: tuple[str, ...]


WEB_SEARCH_PROVIDERS = [
    WebSearchProvider("agent_reach", "Agent Reach / Exa Search"),
    WebSearchProvider("brave", "Brave Search API", "BRAVE_SEARCH_API_KEY"),
    WebSearchProvider("tavily", "Tavily Search API", "TAVILY_API_KEY"),
    WebSearchProvider("google_cse", "Google Programmable Search", "GOOGLE_CSE_API_KEY", True, "GOOGLE_CSE_ID"),
]
WEB_SEARCH_PROVIDER_BY_NAME = {provider.name: provider for provider in WEB_SEARCH_PROVIDERS}

MCP_DATA_SOURCE_CREDENTIALS = (
    MCPDataSourceCredential(
        id="sellersprite",
        label="SellerSprite",
        canonical_env="SELLERSPRITE_MCP_SECRET_KEY",
        accepted_env_names=(
            "SELLERSPRITE_MCP_SECRET_KEY",
            "SELLERSPRITE_SECRET_KEY",
            "SELLERSPRITE_API_KEY",
        ),
    ),
    MCPDataSourceCredential(
        id="sif",
        label="Sif",
        canonical_env="SIF_MCP_TOKEN",
        accepted_env_names=("SIF_MCP_TOKEN", "SIF_API_KEY", "SIF_TOKEN"),
    ),
)
MCP_DATA_SOURCE_BY_ID = {source.id: source for source in MCP_DATA_SOURCE_CREDENTIALS}


def load_llm_providers() -> list[LLMProvider]:
    raw = json.loads(LLM_PROVIDERS_PATH.read_text(encoding="utf-8"))
    providers = [LLMProvider(**item) for item in raw]
    names = [provider.name for provider in providers]
    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate LLM provider names in provider config")
    return providers


LLM_PROVIDERS = load_llm_providers()
LLM_PROVIDER_BY_NAME = {provider.name: provider for provider in LLM_PROVIDERS}


def strip_env_value(value: str) -> str:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def read_env_values(path: Path | None = None) -> dict[str, str]:
    env_path = path or ENV_PATH
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            values[key.strip()] = strip_env_value(value)
    return values


def read_settings_values() -> dict[str, str]:
    values = read_env_values(ENV_EXAMPLE_PATH)
    values.update(read_env_values(ENV_PATH))
    for key, value in os.environ.items():
        if key.startswith(
            (
                "OPENAI_",
                "OPENROUTER_",
                "DEEPSEEK_",
                "DASHSCOPE_",
                "GEMINI_",
                "BRAVE_",
                "TAVILY_",
                "GOOGLE_CSE_",
                "OLLAMA_",
                "INSIGHT_",
                "REDDIT_",
                "AGENT_REACH_",
                "AMAZON_",
                "SELLERSPRITE_",
                "SIF_",
            )
        ):
            values[key] = value
    return values


def configured_secret(value: str | None) -> bool:
    normalized = (value or "").strip().strip('"').strip("'")
    return bool(normalized) and normalized.lower() not in SECRET_PLACEHOLDERS


def format_env_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("Environment values cannot contain newlines")
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def ensure_env_file() -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Created by Insight Agent settings.\n", encoding="utf-8")


def write_env_values(updates: dict[str, str]) -> None:
    ensure_env_file()
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        candidate = stripped[1:].lstrip() if stripped.startswith("#") else stripped
        if "=" not in candidate:
            continue
        key = candidate.split("=", 1)[0].strip()
        if key in updates and key not in seen:
            lines[index] = f"{key}={format_env_value(updates[key])}"
            seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Updated from Web UI")
        for key in missing:
            lines.append(f"{key}={format_env_value(updates[key])}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def selected_provider(values: dict[str, str] | None = None) -> LLMProvider:
    env_values = values or read_settings_values()
    name = env_values.get("INSIGHT_LLM_PROVIDER", "openai").strip().lower()
    return LLM_PROVIDER_BY_NAME.get(name, LLM_PROVIDER_BY_NAME["openai"])


def selected_web_search_provider(values: dict[str, str] | None = None) -> WebSearchProvider:
    env_values = values or read_settings_values()
    name = env_values.get("INSIGHT_WEB_SEARCH_PROVIDER", DEFAULT_WEB_SEARCH_PROVIDER).strip().lower()
    return WEB_SEARCH_PROVIDER_BY_NAME.get(name, WEB_SEARCH_PROVIDER_BY_NAME[DEFAULT_WEB_SEARCH_PROVIDER])


def build_llm_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    env_values = values or read_settings_values()
    provider = selected_provider(env_values)
    api_key = env_values.get(provider.api_key_env or "", "") if provider.api_key_env else ""
    return {
        "provider": provider.name,
        "model_name": env_values.get("INSIGHT_LLM_MODEL", provider.default_model),
        "base_url": env_values.get(provider.base_url_env, provider.default_base_url),
        "api_key_env": provider.api_key_env,
        "api_key_configured": configured_secret(api_key) if provider.api_key_env else not provider.api_key_required,
        "api_key_required": provider.api_key_required,
        "temperature": float(env_values.get("INSIGHT_LLM_TEMPERATURE", "0.2") or 0.2),
        "timeout_seconds": int(env_values.get("INSIGHT_LLM_TIMEOUT", "90") or 90),
        "env_path": ".env",
        "providers": [asdict(provider) for provider in LLM_PROVIDERS],
    }


def mcp_data_source_secret(source: MCPDataSourceCredential, values: dict[str, str]) -> str:
    for env_name in source.accepted_env_names:
        value = values.get(env_name, "")
        if configured_secret(value):
            return value
    return ""


def build_mcp_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    env_values = values if values is not None else read_settings_values()
    return {
        "env_path": ".env",
        "sources": [
            {
                "id": source.id,
                "label": source.label,
                "env_name": source.canonical_env,
                "configured": bool(mcp_data_source_secret(source, env_values)),
            }
            for source in MCP_DATA_SOURCE_CREDENTIALS
        ],
    }


def build_web_search_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    env_values = values or read_settings_values()
    provider = selected_web_search_provider(env_values)
    api_key = env_values.get(provider.api_key_env, "") if provider.api_key_env else ""
    search_engine_id = env_values.get(provider.search_engine_id_env or "", "") if provider.search_engine_id_env else ""
    return {
        "provider": provider.name,
        "api_key_env": provider.api_key_env,
        "api_key_configured": True if not provider.api_key_env else configured_secret(api_key),
        "api_key_required": bool(provider.api_key_env),
        "requires_search_engine_id": provider.requires_search_engine_id,
        "search_engine_id_env": provider.search_engine_id_env,
        "search_engine_id": search_engine_id if configured_secret(search_engine_id) else "",
        "search_engine_id_configured": configured_secret(search_engine_id) if provider.requires_search_engine_id else True,
        "env_path": ".env",
        "providers": [asdict(provider) for provider in WEB_SEARCH_PROVIDERS],
    }


def update_web_search_settings(payload: dict[str, Any]) -> dict[str, Any]:
    provider_name = str(payload.get("provider") or DEFAULT_WEB_SEARCH_PROVIDER).strip().lower()
    provider = WEB_SEARCH_PROVIDER_BY_NAME.get(provider_name)
    if provider is None:
        raise ValueError("Unsupported web search provider")

    current = read_settings_values()
    updates = {
        "INSIGHT_WEB_SEARCH_PROVIDER": provider.name,
    }

    clear_api_key = bool(payload.get("clear_api_key"))
    api_key = str(payload.get("api_key") or "").strip()
    if provider.api_key_env:
        if clear_api_key:
            updates[provider.api_key_env] = ""
        elif api_key:
            updates[provider.api_key_env] = api_key if configured_secret(api_key) else ""
        elif configured_secret(current.get(provider.api_key_env)):
            updates[provider.api_key_env] = current[provider.api_key_env]

    if provider.search_engine_id_env:
        clear_search_engine_id = bool(payload.get("clear_search_engine_id"))
        search_engine_id = str(payload.get("search_engine_id") or "").strip()
        if clear_search_engine_id:
            updates[provider.search_engine_id_env] = ""
        elif search_engine_id:
            updates[provider.search_engine_id_env] = search_engine_id
        elif configured_secret(current.get(provider.search_engine_id_env)):
            updates[provider.search_engine_id_env] = current[provider.search_engine_id_env]

    write_env_values(updates)
    env_values = read_env_values(ENV_PATH)
    sync_runtime_env(values=env_values)
    return build_web_search_settings_response(env_values)


def update_llm_settings(payload: dict[str, Any]) -> dict[str, Any]:
    provider_name = str(payload.get("provider") or "").strip().lower()
    provider = LLM_PROVIDER_BY_NAME.get(provider_name)
    if provider is None:
        raise ValueError("Unsupported LLM provider")

    model_name = str(payload.get("model_name") or "").strip()
    if not model_name:
        raise ValueError("Model name is required")

    temperature = float(payload.get("temperature", 0.2))
    if temperature < 0 or temperature > 2:
        raise ValueError("Temperature must be between 0 and 2")

    timeout_seconds = int(payload.get("timeout_seconds", 90))
    if timeout_seconds < 1 or timeout_seconds > 600:
        raise ValueError("Timeout must be between 1 and 600 seconds")

    base_url = str(payload.get("base_url") or provider.default_base_url).strip().rstrip("/")
    updates = {
        "INSIGHT_LLM_PROVIDER": provider.name,
        "INSIGHT_LLM_MODEL": model_name,
        provider.base_url_env: base_url,
        "INSIGHT_LLM_TEMPERATURE": str(temperature),
        "INSIGHT_LLM_TIMEOUT": str(timeout_seconds),
    }

    clear_api_key = bool(payload.get("clear_api_key"))
    api_key = str(payload.get("api_key") or "").strip()
    if provider.api_key_env:
        current = read_settings_values().get(provider.api_key_env, "")
        if clear_api_key:
            updates[provider.api_key_env] = ""
        elif api_key:
            updates[provider.api_key_env] = api_key if configured_secret(api_key) else ""
        elif configured_secret(current):
            updates[provider.api_key_env] = current

    write_env_values(updates)
    sync_runtime_env(provider, read_env_values(ENV_PATH))
    return build_llm_settings_response(read_env_values(ENV_PATH))


def update_mcp_settings(payload: dict[str, Any]) -> dict[str, Any]:
    credentials = payload.get("credentials")
    if not isinstance(credentials, dict):
        raise ValueError("MCP credentials payload is required")

    unknown_sources = set(credentials) - set(MCP_DATA_SOURCE_BY_ID)
    if unknown_sources:
        raise ValueError(f"Unsupported MCP data source: {sorted(unknown_sources)[0]}")

    current = read_settings_values()
    updates: dict[str, str] = {}
    for source in MCP_DATA_SOURCE_CREDENTIALS:
        entry = credentials.get(source.id, {})
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid credential payload for {source.id}")
        clear_secret = bool(entry.get("clear"))
        secret = str(entry.get("value") or "").strip()
        if secret and not configured_secret(secret):
            raise ValueError(f"Invalid credential value for {source.id}")
        if clear_secret:
            for env_name in source.accepted_env_names:
                updates[env_name] = ""
        elif secret:
            updates[source.canonical_env] = secret
        else:
            existing_secret = mcp_data_source_secret(source, current)
            if existing_secret:
                updates[source.canonical_env] = existing_secret

    if updates:
        write_env_values(updates)
    env_values = read_env_values(ENV_PATH)
    sync_runtime_env(values=env_values)
    return build_mcp_settings_response(env_values)


def build_research_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    env_values = values or read_settings_values()
    mode = env_values.get("INSIGHT_RESEARCH_MODE", DEFAULT_RESEARCH_MODE).strip().lower()
    if mode not in {"auto", "agent_reach", "oauth", "rss", "sample"}:
        mode = DEFAULT_RESEARCH_MODE
    time_range = env_values.get("INSIGHT_RESEARCH_TIME_RANGE", DEFAULT_RESEARCH_TIME_RANGE).strip().lower()
    if time_range not in {"day", "week", "month", "year", "all"}:
        time_range = DEFAULT_RESEARCH_TIME_RANGE
    return {
        "mode": mode,
        "timeRange": time_range,
        "limit": int_setting(
            env_values,
            "INSIGHT_RESEARCH_POST_LIMIT",
            DEFAULT_RESEARCH_POST_LIMIT,
            5,
            MAX_RESEARCH_POST_LIMIT,
        ),
        "maxPostLimit": MAX_RESEARCH_POST_LIMIT,
        "llmEvidencePosts": int_setting(
            env_values,
            "INSIGHT_LLM_EVIDENCE_POSTS",
            DEFAULT_LLM_EVIDENCE_POSTS,
            1,
            100,
        ),
        "llmCommentSamplesPerPost": int_setting(
            env_values,
            "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST",
            DEFAULT_LLM_COMMENT_SAMPLES_PER_POST,
            0,
            50,
        ),
        "amazonProductLimit": int_setting(
            env_values,
            "AMAZON_PRODUCT_LIMIT",
            DEFAULT_AMAZON_PRODUCT_LIMIT,
            1,
            MAX_AMAZON_PRODUCT_LIMIT,
        ),
        "maxAmazonProductLimit": MAX_AMAZON_PRODUCT_LIMIT,
        "amazonKeywordLimit": int_setting(
            env_values,
            "AMAZON_KEYWORD_LIMIT",
            DEFAULT_AMAZON_KEYWORD_LIMIT,
            1,
            MAX_AMAZON_KEYWORD_LIMIT,
        ),
        "maxAmazonKeywordLimit": MAX_AMAZON_KEYWORD_LIMIT,
        "amazonDetailLimit": int_setting(
            env_values,
            "AMAZON_DETAIL_LIMIT",
            DEFAULT_AMAZON_DETAIL_LIMIT,
            0,
            100,
        ),
        "amazonDiscussionLimit": int_setting(
            env_values,
            "AMAZON_DISCUSSION_LIMIT",
            DEFAULT_AMAZON_DISCUSSION_LIMIT,
            0,
            100,
        ),
        "amazonReviewsPerProduct": int_setting(
            env_values,
            "AMAZON_REVIEWS_PER_PRODUCT",
            DEFAULT_AMAZON_REVIEWS_PER_PRODUCT,
            0,
            100,
        ),
        "amazonLlmProductLimit": int_setting(
            env_values,
            "AMAZON_LLM_PRODUCT_LIMIT",
            DEFAULT_AMAZON_LLM_PRODUCT_LIMIT,
            1,
            100,
        ),
        "amazonLlmReviewSamplesPerProduct": int_setting(
            env_values,
            "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
            DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT,
            0,
            50,
        ),
        "env_path": ".env",
    }


def update_research_settings(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or DEFAULT_RESEARCH_MODE).strip().lower()
    if mode not in {"auto", "agent_reach", "oauth", "rss", "sample"}:
        raise ValueError("Research mode must be auto, agent_reach, oauth, rss, or sample")

    time_range = str(payload.get("timeRange") or DEFAULT_RESEARCH_TIME_RANGE).strip().lower()
    if time_range not in {"day", "week", "month", "year", "all"}:
        raise ValueError("Research time range must be day, week, month, year, or all")

    limit = int(payload.get("limit", DEFAULT_RESEARCH_POST_LIMIT))
    if limit < 5 or limit > MAX_RESEARCH_POST_LIMIT:
        raise ValueError(f"Post limit must be between 5 and {MAX_RESEARCH_POST_LIMIT}")

    llm_evidence_posts = int(payload.get("llmEvidencePosts", DEFAULT_LLM_EVIDENCE_POSTS))
    if llm_evidence_posts < 1 or llm_evidence_posts > 100:
        raise ValueError("AI evidence posts must be between 1 and 100")

    llm_comment_samples = int(payload.get("llmCommentSamplesPerPost", DEFAULT_LLM_COMMENT_SAMPLES_PER_POST))
    if llm_comment_samples < 0 or llm_comment_samples > 50:
        raise ValueError("AI comment samples per post must be between 0 and 50")

    amazon_product_limit = int(payload.get("amazonProductLimit", DEFAULT_AMAZON_PRODUCT_LIMIT))
    if amazon_product_limit < 1 or amazon_product_limit > MAX_AMAZON_PRODUCT_LIMIT:
        raise ValueError(f"Amazon product limit must be between 1 and {MAX_AMAZON_PRODUCT_LIMIT}")

    amazon_keyword_limit = int(payload.get("amazonKeywordLimit", DEFAULT_AMAZON_KEYWORD_LIMIT))
    if amazon_keyword_limit < 1 or amazon_keyword_limit > MAX_AMAZON_KEYWORD_LIMIT:
        raise ValueError(f"Amazon keyword limit must be between 1 and {MAX_AMAZON_KEYWORD_LIMIT}")

    amazon_detail_limit = int(payload.get("amazonDetailLimit", DEFAULT_AMAZON_DETAIL_LIMIT))
    if amazon_detail_limit < 0 or amazon_detail_limit > 100:
        raise ValueError("Amazon detail product limit must be between 0 and 100")

    amazon_discussion_limit = int(payload.get("amazonDiscussionLimit", DEFAULT_AMAZON_DISCUSSION_LIMIT))
    if amazon_discussion_limit < 0 or amazon_discussion_limit > 100:
        raise ValueError("Amazon discussion product limit must be between 0 and 100")

    amazon_reviews_per_product = int(payload.get("amazonReviewsPerProduct", DEFAULT_AMAZON_REVIEWS_PER_PRODUCT))
    if amazon_reviews_per_product < 0 or amazon_reviews_per_product > 100:
        raise ValueError("Amazon reviews per product must be between 0 and 100")

    amazon_llm_product_limit = int(payload.get("amazonLlmProductLimit", DEFAULT_AMAZON_LLM_PRODUCT_LIMIT))
    if amazon_llm_product_limit < 1 or amazon_llm_product_limit > 100:
        raise ValueError("Amazon AI product limit must be between 1 and 100")

    amazon_llm_review_samples = int(
        payload.get("amazonLlmReviewSamplesPerProduct", DEFAULT_AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT)
    )
    if amazon_llm_review_samples < 0 or amazon_llm_review_samples > 50:
        raise ValueError("Amazon AI review samples per product must be between 0 and 50")

    updates = {
        "INSIGHT_RESEARCH_MODE": mode,
        "INSIGHT_RESEARCH_TIME_RANGE": time_range,
        "INSIGHT_RESEARCH_POST_LIMIT": str(limit),
        "INSIGHT_LLM_EVIDENCE_POSTS": str(llm_evidence_posts),
        "INSIGHT_LLM_COMMENT_SAMPLES_PER_POST": str(llm_comment_samples),
        "AMAZON_PRODUCT_LIMIT": str(amazon_product_limit),
        "AMAZON_KEYWORD_LIMIT": str(amazon_keyword_limit),
        "AMAZON_DETAIL_LIMIT": str(amazon_detail_limit),
        "AMAZON_DISCUSSION_LIMIT": str(amazon_discussion_limit),
        "AMAZON_REVIEWS_PER_PRODUCT": str(amazon_reviews_per_product),
        "AMAZON_LLM_PRODUCT_LIMIT": str(amazon_llm_product_limit),
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT": str(amazon_llm_review_samples),
    }
    write_env_values(updates)
    env_values = read_env_values(ENV_PATH)
    sync_runtime_env(values=env_values)
    return build_research_settings_response(env_values)


def build_reddit_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    env_values = values or read_settings_values()
    client_id = env_values.get("REDDIT_CLIENT_ID", "")
    client_secret = env_values.get("REDDIT_CLIENT_SECRET", "")
    user_agent = env_values.get("REDDIT_USER_AGENT", DEFAULT_REDDIT_USER_AGENT)
    return {
        "client_id": client_id if configured_secret(client_id) else "",
        "client_id_configured": configured_secret(client_id),
        "client_secret_configured": configured_secret(client_secret),
        "user_agent": user_agent or DEFAULT_REDDIT_USER_AGENT,
        "oauth_ready": configured_secret(client_id) and configured_secret(client_secret),
        "env_path": ".env",
    }


def build_agent_reach_settings_response(values: dict[str, str] | None = None) -> dict[str, Any]:
    from .ingestion.agent_reach import agent_reach_health

    env_values = values or read_settings_values()
    health = agent_reach_health()
    return {
        "enabled": env_values.get("AGENT_REACH_ENABLED", "1").strip().lower() not in {"0", "false", "no"},
        "backend": env_values.get("AGENT_REACH_BACKEND", "opencli"),
        "timeout_seconds": int(env_values.get("AGENT_REACH_TIMEOUT", "90") or 90),
        "detail_limit": int(env_values.get("AGENT_REACH_DETAIL_LIMIT", "8") or 8),
        "comments_per_post": int(env_values.get("AGENT_REACH_COMMENTS_PER_POST", "20") or 20),
        "env_path": ".env",
        "health": health,
    }


def update_agent_reach_settings(payload: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    backend = str(payload.get("backend") or "opencli").strip().lower()
    if backend not in {"auto", "opencli", "rdt"}:
        raise ValueError("Agent Reach backend must be auto, opencli, or rdt")

    timeout_seconds = int(payload.get("timeout_seconds", 90))
    if timeout_seconds < 10 or timeout_seconds > 600:
        raise ValueError("Agent Reach timeout must be between 10 and 600 seconds")

    detail_limit = int(payload.get("detail_limit", 8))
    if detail_limit < 0 or detail_limit > 100:
        raise ValueError("Agent Reach detail limit must be between 0 and 100")

    comments_per_post = int(payload.get("comments_per_post", 20))
    if comments_per_post < 0 or comments_per_post > 200:
        raise ValueError("Comments per post must be between 0 and 200")

    updates = {
        "AGENT_REACH_ENABLED": "1" if enabled else "0",
        "AGENT_REACH_BACKEND": backend,
        "AGENT_REACH_TIMEOUT": str(timeout_seconds),
        "AGENT_REACH_DETAIL_LIMIT": str(detail_limit),
        "AGENT_REACH_COMMENTS_PER_POST": str(comments_per_post),
    }
    write_env_values(updates)
    env_values = read_env_values(ENV_PATH)
    sync_runtime_env(values=env_values)
    return build_agent_reach_settings_response(env_values)


def update_reddit_settings(payload: dict[str, Any]) -> dict[str, Any]:
    user_agent = str(payload.get("user_agent") or DEFAULT_REDDIT_USER_AGENT).strip()
    if not user_agent:
        raise ValueError("Reddit user agent is required")

    current = read_settings_values()
    updates = {
        "REDDIT_USER_AGENT": user_agent,
    }

    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    clear_client_id = bool(payload.get("clear_client_id"))
    clear_client_secret = bool(payload.get("clear_client_secret"))

    if clear_client_id:
        updates["REDDIT_CLIENT_ID"] = ""
    elif client_id:
        updates["REDDIT_CLIENT_ID"] = client_id
    elif configured_secret(current.get("REDDIT_CLIENT_ID")):
        updates["REDDIT_CLIENT_ID"] = current["REDDIT_CLIENT_ID"]

    if clear_client_secret:
        updates["REDDIT_CLIENT_SECRET"] = ""
    elif client_secret:
        updates["REDDIT_CLIENT_SECRET"] = client_secret
    elif configured_secret(current.get("REDDIT_CLIENT_SECRET")):
        updates["REDDIT_CLIENT_SECRET"] = current["REDDIT_CLIENT_SECRET"]

    write_env_values(updates)
    env_values = read_env_values(ENV_PATH)
    sync_runtime_env(values=env_values)
    return build_reddit_settings_response(env_values)


def sync_runtime_env(provider: LLMProvider | None = None, values: dict[str, str] | None = None) -> None:
    env_values = values or read_settings_values()
    selected = provider or selected_provider(env_values)
    for key, value in env_values.items():
        if value:
            os.environ[key] = value

    os.environ["INSIGHT_LLM_PROVIDER"] = selected.name
    os.environ["INSIGHT_LLM_MODEL"] = env_values.get("INSIGHT_LLM_MODEL", selected.default_model)
    os.environ["INSIGHT_LLM_BASE_URL"] = env_values.get(selected.base_url_env, selected.default_base_url)
    if selected.api_key_env:
        api_key = env_values.get(selected.api_key_env, "")
        if configured_secret(api_key):
            os.environ["INSIGHT_LLM_API_KEY"] = api_key
        else:
            os.environ.pop("INSIGHT_LLM_API_KEY", None)
    else:
        os.environ["INSIGHT_LLM_API_KEY"] = env_values.get("INSIGHT_LLM_API_KEY", "ollama")

    for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"):
        value = env_values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    for key in (
        "AGENT_REACH_ENABLED",
        "AGENT_REACH_BACKEND",
        "AGENT_REACH_TIMEOUT",
        "AGENT_REACH_DETAIL_LIMIT",
        "AGENT_REACH_COMMENTS_PER_POST",
        "AGENT_REACH_VENV",
        "AGENT_REACH_BIN_DIR",
    ):
        value = env_values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    for key in (
        "AMAZON_OPENCLI_ENABLED",
        "AMAZON_OPENCLI_TIMEOUT",
        "AMAZON_PRODUCT_LIMIT",
        "AMAZON_KEYWORD_LIMIT",
        "AMAZON_DETAIL_LIMIT",
        "AMAZON_DISCUSSION_LIMIT",
        "AMAZON_REVIEWS_PER_PRODUCT",
        "AMAZON_LLM_PRODUCT_LIMIT",
        "AMAZON_LLM_REVIEW_SAMPLES_PER_PRODUCT",
    ):
        value = env_values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    for key in (
        "INSIGHT_WEB_SEARCH_PROVIDER",
        "BRAVE_SEARCH_API_KEY",
        "TAVILY_API_KEY",
        "GOOGLE_CSE_API_KEY",
        "GOOGLE_CSE_ID",
    ):
        value = env_values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    for key in (
        "SELLERSPRITE_MCP_SECRET_KEY",
        "SELLERSPRITE_SECRET_KEY",
        "SELLERSPRITE_API_KEY",
        "SIF_MCP_TOKEN",
        "SIF_API_KEY",
        "SIF_TOKEN",
    ):
        value = env_values.get(key, "")
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)
