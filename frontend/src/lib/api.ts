export type DataMode = "auto" | "agent_reach" | "oauth" | "rss" | "sample";

export interface AnalyzeRequest {
  category: string;
  timeRange: "day" | "week" | "month" | "year" | "all";
  limit: number;
  mode: DataMode;
  useLlm: boolean;
  bypassCache?: boolean;
}

export interface EvidencePost {
  id: string;
  title: string;
  excerpt: string;
  subreddit: string;
  url: string;
  created_utc: string;
  score: number | null;
  comments: number | null;
  comment_items?: Array<{
    id?: string;
    author?: string | null;
    text?: string;
    score?: number | null;
    created_at?: string;
    url?: string;
  }>;
  source: string;
}

export interface PainPoint {
  topic: string;
  count: number;
  share: number;
  examples: Array<{
    title: string;
    subreddit: string;
    url: string;
    snippet: string;
  }>;
}

export interface CountItem {
  name: string;
  count: number;
}

export interface Opportunity {
  title: string;
  detail: string;
}

export interface LlmAnalysis {
  enabled: boolean;
  status: "ok" | "unavailable" | "not_requested";
  message?: string;
  provider?: string;
  model?: string;
  result?: {
    executive_summary?: string;
    strategic_takeaways?: string[];
    opportunity_areas?: Array<{
      title: string;
      rationale: string;
      confidence: string;
      evidence_urls: string[];
    }>;
    evidence_audit?: string[];
    data_gaps?: string[];
  };
  usage?: Record<string, number>;
}

export interface AnalysisReport {
  category: string;
  generated_at: string;
  source_mode: string;
  warnings: string[];
  coverage: {
    posts: number;
    subreddits: number;
    confidence: string;
    top_subreddits: CountItem[];
  };
  data_volume: {
    requested_posts: number;
    collected_posts: number;
    source_mode: string;
    comment_enrichment_post_limit: number;
    comments_per_enriched_post_limit: number;
    posts_with_collected_comments: number;
    collected_comments: number;
    llm_requested: boolean;
    ai_evidence_post_limit: number;
    ai_evidence_posts: number;
    ai_comment_samples_per_post_limit: number;
    ai_comment_samples: number;
  };
  market_signal: {
    score: number;
    summary: string;
  };
  sentiment: {
    positive: number;
    neutral: number;
    negative: number;
    positive_share: number;
    negative_share: number;
  };
  pain_points: PainPoint[];
  brands: CountItem[];
  sizes: CountItem[];
  trend: Array<{ month: string; count: number }>;
  opportunities: Opportunity[];
  posts: EvidencePost[];
  method: {
    query: string;
    notes: string[];
  };
  llm_analysis: LlmAnalysis;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  api_key_env?: string | null;
  base_url_env: string;
  default_model: string;
  default_base_url: string;
  api_key_required: boolean;
}

export interface LLMSettings {
  provider: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  api_key_configured: boolean;
  api_key_required: boolean;
  temperature: number;
  timeout_seconds: number;
  env_path: string;
  providers: LLMProviderOption[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  temperature: number;
  timeout_seconds: number;
}

export interface RedditSettings {
  client_id: string;
  client_id_configured: boolean;
  client_secret_configured: boolean;
  user_agent: string;
  oauth_ready: boolean;
  env_path: string;
}

export interface UpdateRedditSettingsRequest {
  client_id?: string;
  client_secret?: string;
  clear_client_id?: boolean;
  clear_client_secret?: boolean;
  user_agent: string;
}

export interface ResearchDefaults {
  mode: DataMode;
  timeRange: AnalyzeRequest["timeRange"];
  limit: number;
  maxPostLimit: number;
  llmEvidencePosts: number;
  llmCommentSamplesPerPost: number;
  env_path: string;
}

export interface UpdateResearchDefaultsRequest {
  mode: DataMode;
  timeRange: AnalyzeRequest["timeRange"];
  limit: number;
  llmEvidencePosts: number;
  llmCommentSamplesPerPost: number;
}

export interface AgentReachHealth {
  agent_reach_installed: boolean;
  opencli_installed: boolean;
  opencli_connected: boolean;
  rdt_installed: boolean;
  agent_reach_path: string;
  opencli_path: string;
  rdt_path: string;
  ready: boolean;
  recommended_backend: string;
}

export interface AgentReachSettings {
  enabled: boolean;
  backend: "auto" | "opencli" | "rdt";
  timeout_seconds: number;
  detail_limit: number;
  comments_per_post: number;
  env_path: string;
  health: AgentReachHealth;
}

export interface AgentReachReconnectResult {
  ok: boolean;
  message: string;
  health: AgentReachHealth;
  restart: {
    code: number | null;
    stdout: string;
    stderr: string;
  };
  profiles: {
    code: number | null;
    stdout: string;
    stderr: string;
  };
}

export interface UpdateAgentReachSettingsRequest {
  enabled: boolean;
  backend: "auto" | "opencli" | "rdt";
  timeout_seconds: number;
  detail_limit: number;
  comments_per_post: number;
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new ApiError(data.error || data.detail || `HTTP ${response.status}`, response.status);
  }
  return data as T;
}

export const api = {
  analyze: (body: AnalyzeRequest) =>
    request<AnalysisReport>("/api/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getLLMSettings: () => request<LLMSettings>("/api/settings/llm"),
  updateLLMSettings: (body: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/api/settings/llm", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getRedditSettings: () => request<RedditSettings>("/api/settings/reddit"),
  updateRedditSettings: (body: UpdateRedditSettingsRequest) =>
    request<RedditSettings>("/api/settings/reddit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getResearchSettings: () => request<ResearchDefaults>("/api/settings/research"),
  updateResearchSettings: (body: UpdateResearchDefaultsRequest) =>
    request<ResearchDefaults>("/api/settings/research", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getAgentReachSettings: () => request<AgentReachSettings>("/api/settings/agent-reach"),
  updateAgentReachSettings: (body: UpdateAgentReachSettingsRequest) =>
    request<AgentReachSettings>("/api/settings/agent-reach", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reconnectAgentReach: () =>
    request<AgentReachReconnectResult>("/api/settings/agent-reach/reconnect", {
      method: "POST",
    }),
};
