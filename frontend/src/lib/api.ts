export type DataMode = "auto" | "agent_reach" | "oauth" | "rss" | "sample";

export interface AnalyzeRequest {
  category: string;
  timeRange: "day" | "week" | "month" | "year" | "all";
  limit: number;
  mode: DataMode;
  useLlm: boolean;
  bypassCache?: boolean;
  amazonKeywordLimit?: number;
  redditDetailLimit?: number;
  redditCommentsPerPost?: number;
  youtubeTranscriptVideoLimit?: number;
  youtubeCommentVideoLimit?: number;
  youtubeCommentsPerVideo?: number;
  tiktokCommentsPerVideo?: number;
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

export interface AmazonProduct {
  rank: number | null;
  asin: string;
  title: string;
  brand: string;
  product_url: string;
  image_url: string;
  price_text: string;
  price_value: number | null;
  currency: string;
  rating_text: string;
  rating_value: number | null;
  review_count_text: string;
  review_count: number | null;
  badges: string[];
  is_sponsored: boolean;
  breadcrumbs: string[];
  bullet_points: string[];
  availability: string;
  seller: string;
  review_samples: Array<{
    id?: string;
    title: string;
    body: string;
    url?: string;
    rating_value: number | null;
    rating_text: string;
    author: string;
    date_text: string;
    verified_purchase: boolean;
  }>;
  source_url: string;
  fetched_at: string;
}

export interface AmazonReport {
  category: string;
  query: string;
  queries: string[];
  generated_at: string;
  source_mode: string;
  warnings: string[];
  confidence: string;
  metrics: {
    products: number;
    products_with_price: number;
    price_min: number | null;
    price_max: number | null;
    price_avg: number | null;
    products_with_rating: number;
    rating_avg: number | null;
    total_review_count: number;
    products_with_review_count: number;
    sponsored_count: number;
    review_samples: number;
    products_with_review_samples: number;
  };
  data_volume: {
    requested_products: number;
    requested_products_per_query: number;
    query_count: number;
    queries: string[];
    per_query_counts: Array<{ query: string; count: number }>;
    raw_collected_products: number;
    collected_products: number;
    unique_products: number;
    source_mode: string;
    detail_product_limit: number;
    discussion_product_limit: number;
    products_with_review_samples: number;
    collected_review_samples: number;
    llm_requested: boolean;
    ai_product_limit: number;
    ai_products: number;
    ai_review_samples_per_product_limit: number;
    ai_review_samples: number;
  };
  brands: CountItem[];
  price_bands: CountItem[];
  products: AmazonProduct[];
  method: {
    query: string;
    notes: string[];
  };
  llm_analysis: LlmAnalysis;
}

export interface ArticleAnalyzeRequest {
  category: string;
  urls: string[];
  limit?: number;
  bypassCache?: boolean;
}

export interface ArticleItem {
  title: string;
  url: string;
  domain: string;
  source_type: "media_article" | "media_review" | "public_ranking" | "industry_report" | string;
  authority_score: number;
  authority_level: "High" | "Medium" | "Low" | string;
  authority_evidence: string[];
  cautions: string[];
  brand_mentions: string[];
  product_signals: string[];
  evidence_snippets: string[];
  readable_chars: number;
  fetched_at: string;
}

export interface ArticleReport {
  category: string;
  generated_at: string;
  source_mode: string;
  source: {
    source_name: string;
    source_type: string;
    status: "ready" | "partial" | "unavailable" | "failed";
    collected_items_count: number;
    evidence_items_count: number;
    last_run_at: string;
    failure_reason: string;
    next_action: string;
  };
  data_volume: {
    requested_articles: number;
    collected_articles: number;
    failed_articles: number;
    high_authority_articles: number;
    medium_authority_articles: number;
    low_authority_articles: number;
    evidence_snippets: number;
  };
  summary: {
    top_domains: CountItem[];
    top_brands: CountItem[];
    top_signals: CountItem[];
    source_types: CountItem[];
  };
  articles: ArticleItem[];
  warnings: string[];
  method: {
    query: string;
    notes: string[];
  };
}

export interface YouTubeCommentSample {
  id: string;
  author: string;
  text: string;
  like_count: number | null;
  timestamp: number | null;
}

export interface YouTubeVideo {
  id: string;
  title: string;
  url: string;
  channel: string;
  channel_url: string;
  duration_seconds: number | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  upload_date: string;
  description: string;
  thumbnail: string;
  tags: string[];
  transcript: string;
  transcript_chars: number;
  comment_samples: YouTubeCommentSample[];
  fetched_at: string;
}

export interface YouTubeReport {
  category: string;
  generated_at: string;
  source_mode: string;
  warnings: string[];
  confidence: string;
  source: {
    source_name: string;
    source_type: string;
    status: "ready" | "partial" | "unavailable" | "failed" | string;
    collected_items_count: number;
    evidence_items_count: number;
    last_run_at: string;
    failure_reason: string;
    next_action: string;
  };
  data_volume: {
    requested_videos: number;
    collected_videos: number;
    transcript_video_limit: number;
    videos_with_transcripts: number;
    transcript_chars: number;
    comment_video_limit: number;
    comments_per_video_limit: number;
    comment_samples: number;
  };
  metrics: {
    videos: number;
    channels: number;
    total_views: number;
    videos_with_view_count: number;
    average_views: number | null;
    total_likes: number;
    videos_with_like_count: number;
    total_comment_count: number;
    videos_with_comment_count: number;
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
  channels: CountItem[];
  pain_points: PainPoint[];
  brands: CountItem[];
  product_signals: CountItem[];
  videos: YouTubeVideo[];
  method: {
    query: string;
    notes: string[];
  };
  llm_analysis: LlmAnalysis;
}

export interface TikTokCommentSample {
  id: string;
  author: string;
  text: string;
  like_count: number | null;
  created_at: string;
}

export interface TikTokVideo {
  id: string;
  title: string;
  url: string;
  caption: string;
  author: string;
  author_url: string;
  cover_url: string;
  hashtags: string[];
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  save_count: number | null;
  published_at: string;
  comment_samples: TikTokCommentSample[];
  fetched_at: string;
}

export interface TikTokReport {
  category: string;
  generated_at: string;
  source_mode: string;
  warnings: string[];
  confidence: string;
  source: {
    source_name: string;
    source_type: string;
    status: "ready" | "partial" | "unavailable" | "failed" | string;
    collected_items_count: number;
    evidence_items_count: number;
    last_run_at: string;
    failure_reason: string;
    next_action: string;
  };
  data_volume: {
    requested_videos: number;
    collected_videos: number;
    detail_pages_visited: number;
    comments_per_video_limit: number;
    comment_samples: number;
    videos_with_comment_samples: number;
  };
  metrics: {
    videos: number;
    authors: number;
    total_views: number;
    videos_with_view_count: number;
    average_views: number | null;
    total_likes: number;
    videos_with_like_count: number;
    total_comment_count: number;
    videos_with_comment_count: number;
    total_shares: number;
    videos_with_share_count: number;
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
  authors: CountItem[];
  hashtags: CountItem[];
  pain_points: PainPoint[];
  brands: CountItem[];
  product_signals: CountItem[];
  videos: TikTokVideo[];
  method: {
    query: string;
    notes: string[];
  };
  llm_analysis: LlmAnalysis;
}

export interface TikTokLoginBrowserResponse {
  ok: boolean;
  status: string;
  profile_dir: string;
  chrome_path: string;
  url?: string;
  message: string;
}

export interface ArticleDiscoveryRequest {
  category: string;
  queryLimit?: number;
  resultsPerQuery?: number;
  candidateLimit?: number;
  includeIndustryReports?: boolean;
  bypassCache?: boolean;
}

export interface ArticleDiscoveryCandidate {
  title: string;
  url: string;
  domain: string;
  snippet: string;
  provider: string;
  query: string;
  rank: number;
  score: number;
  source_type: "media_article" | "media_review" | "public_ranking" | "industry_report" | string;
  reasons: string[];
  published: string;
}

export interface ArticleDiscoveryReport {
  category: string;
  generated_at: string;
  source_mode: string;
  source: {
    source_name: string;
    source_type: string;
    status: "ready" | "partial" | "unavailable" | "failed";
    collected_items_count: number;
    evidence_items_count: number;
    last_run_at: string;
    failure_reason: string;
    next_action: string;
  };
  data_volume: {
    query_count: number;
    results_per_query: number;
    raw_results: number;
    unique_results: number;
    candidate_count: number;
    per_query_counts: Array<{ query: string; count: number }>;
  };
  queries: string[];
  candidates: ArticleDiscoveryCandidate[];
  warnings: string[];
  method: {
    notes: string[];
  };
}

export interface InsightCitation {
  id: string;
  source: "reddit" | "amazon" | "web";
  kind: "post" | "comment" | "product" | "review" | string;
  title: string;
  url: string;
  excerpt: string;
  reference: string;
}

export interface CombinedInsightItem {
  title: string;
  detail: string;
  citations: InsightCitation[];
}

export interface CombinedEvidenceChainItem {
  claim: string;
  detail: string;
  citations: InsightCitation[];
}

export interface CombinedInsightReport {
  category: string;
  generated_at: string;
  warnings: string[];
  data_summary: {
    reddit_posts: number;
    reddit_comments: number;
    amazon_products: number;
    amazon_review_samples: number;
    evidence_items: number;
  };
  verdict: {
    text: string;
    citations: InsightCitation[];
  };
  opportunities: CombinedInsightItem[];
  risks: CombinedInsightItem[];
  rd_recommendations: CombinedInsightItem[];
  brand_communication: CombinedInsightItem[];
  evidence_chain: CombinedEvidenceChainItem[];
  data_gaps: CombinedInsightItem[];
  llm_analysis: {
    enabled: boolean;
    status: "ok" | "unavailable" | "not_requested";
    message?: string;
    provider?: string;
    model?: string;
    usage?: Record<string, number>;
  };
}

export interface CompetitorDiscoveryBrief {
  brand: string;
  market: string;
  category: string;
  coreKeywords: string;
  targetPriceBand: string;
  upgradePriceBand: string;
  coreSizes: string;
  coreUsers: string;
  brandDirection: string;
}

export interface CompetitorScoreWeights {
  briefMatch: number;
  priceFit: number;
  sizeMatch: number;
  marketProof: number;
  reviewEvidence: number;
  queryCoverage: number;
  tiktokProof: number;
}

export interface CompetitorDiscoveryRequest {
  query?: string;
  brief?: CompetitorDiscoveryBrief;
  scoreWeights?: CompetitorScoreWeights;
  limit: number;
  amazonKeywordLimit: number;
  candidateLimit?: number;
  bypassCache?: boolean;
}

export interface CompetitorCandidate {
  id: string;
  platform: string;
  brand: string;
  title: string;
  price_text: string;
  price_value: number | null;
  rating_value: number | null;
  review_count: number | null;
  badges: string[];
  is_sponsored: boolean;
  product_url: string;
  image_url: string;
  asin: string;
  matched_queries: string[];
  score: number;
  score_breakdown?: Array<{
    key: string;
    raw_points: number;
    weight: number;
    points: number;
  }>;
  priority: "High" | "Medium" | "Low";
  breakout_tier?: "strong_breakout" | "needs_tiktok_validation" | "watchlist" | "low_evidence" | string;
  breakout_label?: string;
  breakout_reasons?: string[];
  tiktok_validation?: CompetitorTikTokValidation | null;
  why_worth_tracking: string[];
  risks: string[];
  claim_evidence: string[];
  review_evidence: Array<{
    text: string;
    rating_value: number | null;
    verified_purchase: boolean;
  }>;
  suggested_status: string;
}

export interface CompetitorTikTokValidation {
  status: "verified" | "directional" | "weak" | "no_signal" | string;
  label: string;
  score: number;
  query: string;
  source_mode: string;
  generated_at: string;
  requested_videos: number;
  comments_per_video_limit: number;
  video_count: number;
  relevant_video_count: number;
  total_views: number;
  total_likes: number;
  comment_samples: number;
  matched_terms: string[];
  video_evidence: Array<{
    title: string;
    url: string;
    author: string;
    view_count: number | null;
    like_count: number | null;
    comment_count: number | null;
    matched_terms: string[];
    snippet: string;
    comment_samples: Array<{
      author: string;
      text: string;
      like_count: number | null;
    }>;
  }>;
  reasons: string[];
  risks: string[];
  warnings: string[];
}

export interface CompetitorDiscoveryReport {
  query: string;
  brief?: CompetitorDiscoveryBrief;
  score_weights?: CompetitorScoreWeights;
  generated_at: string;
  source_mode: string;
  source: {
    source_name: string;
    source_type: string;
    status: "ready" | "partial" | "unavailable" | "failed";
    collected_items_count: number;
    evidence_items_count: number;
    last_run_at: string;
    failure_reason: string;
    next_action: string;
  };
  data_volume: {
    requested_products: number;
    requested_products_per_query: number;
    query_count: number;
    queries: string[];
    per_query_counts: Array<{ query: string; count: number }>;
    raw_collected_products: number;
    unique_products: number;
    excluded_products?: number;
    candidate_count: number;
    strong_breakout_candidates?: number;
    needs_tiktok_validation_candidates?: number;
    low_evidence_candidates?: number;
  };
  summary: {
    candidate_count: number;
    high_priority: number;
    medium_priority: number;
    strong_breakout?: number;
    needs_tiktok_validation?: number;
    low_evidence?: number;
    brands: CountItem[];
  };
  candidates: CompetitorCandidate[];
  warnings: string[];
  method: {
    notes: string[];
  };
}

export interface CompetitorTikTokVerifyRequest {
  candidate: CompetitorCandidate;
  brief?: CompetitorDiscoveryBrief;
  scoreWeights?: CompetitorScoreWeights;
  limit?: number;
  tiktokCommentsPerVideo?: number;
  bypassCache?: boolean;
}

export interface CompetitorTikTokVerifyResponse {
  candidate: CompetitorCandidate;
  validation: CompetitorTikTokValidation;
  videos: TikTokVideo[];
  warnings: string[];
  method: {
    query: string;
    notes: string[];
  };
}

export interface CompetitorDeepDiveRequest {
  candidate: CompetitorCandidate;
  runId?: string;
  category?: string;
  brief?: CompetitorDiscoveryBrief;
  redditLimit?: number;
  redditDetailLimit?: number;
  redditCommentsPerPost?: number;
  amazonReviewLimit?: number;
  webCandidateLimit?: number;
  aiReviewLimit?: number;
  aiRedditPostLimit?: number;
  timeRange?: AnalyzeRequest["timeRange"];
  mode?: DataMode;
  useLlm: boolean;
  locale: "zh" | "en";
  bypassCache?: boolean;
}

export interface CompetitorCancelRequest {
  runId: string;
}

export interface CompetitorCancelResponse {
  ok: boolean;
  run_id: string;
  terminated_processes: number;
  message: string;
}

export interface CompetitorDeepDiveItem {
  title: string;
  detail: string;
  citations: InsightCitation[];
}

export interface CompetitorDeepDiveEvidenceChainItem {
  claim: string;
  detail: string;
  citations: InsightCitation[];
}

export interface CompetitorDeepDiveReport {
  category: string;
  generated_at: string;
  source_mode: string;
  source_status: {
    amazon: "ready" | "partial" | "unavailable" | "failed" | string;
    reddit: "ready" | "partial" | "unavailable" | "failed" | string;
    web: "ready" | "partial" | "unavailable" | "failed" | string;
  };
  warnings: string[];
  product: AmazonProduct & Partial<CompetitorCandidate>;
  data_volume: {
    amazon_reviews_requested: number;
    amazon_reviews_collected: number;
    reddit_posts_requested: number;
    reddit_posts_collected: number;
    reddit_detail_posts_requested?: number;
    reddit_comments_per_post_requested?: number;
    reddit_comments_collected: number;
    web_candidates: number;
    web_sources_read: number;
    ai_review_limit: number;
    ai_reviews: number;
    ai_reddit_post_limit: number;
    ai_reddit_posts: number;
    ai_evidence_items: number;
  };
  sales_proxy: {
    signals: Array<{ name: string; value: string; interpretation: string }>;
    confidence: string;
    caveats: string[];
  };
  amazon: {
    product: AmazonProduct & Partial<CompetitorCandidate>;
    review_samples: AmazonProduct["review_samples"];
    warnings: string[];
  };
  reddit: AnalysisReport;
  web: {
    source_mode: string;
    queries: string[];
    candidates: ArticleDiscoveryCandidate[];
    articles: ArticleItem[];
    warnings: string[];
    data_volume: {
      query_count: number;
      raw_results: number;
      candidate_count: number;
      readable_sources: number;
      failed_sources: number;
      per_query_counts: Array<{ query: string; count: number }>;
    };
  };
  evidence_pool: InsightCitation[];
  verdict: { text: string; citations: InsightCitation[] };
  breakout_assessment: CompetitorDeepDiveItem[];
  why_it_sells: CompetitorDeepDiveItem[];
  user_love: CompetitorDeepDiveItem[];
  user_complaints: CompetitorDeepDiveItem[];
  rd_teardown: CompetitorDeepDiveItem[];
  brand_communication: CompetitorDeepDiveItem[];
  sales_proxy_interpretation: CompetitorDeepDiveItem[];
  risks: CompetitorDeepDiveItem[];
  evidence_chain: CompetitorDeepDiveEvidenceChainItem[];
  data_gaps: CompetitorDeepDiveItem[];
  llm_analysis: {
    enabled: boolean;
    status: "ok" | "unavailable" | "not_requested";
    message?: string;
    provider?: string;
    model?: string;
    usage?: Record<string, number>;
  };
  method: {
    query: string;
    notes: string[];
  };
}

export interface CombinedInsightRequest {
  category: string;
  reddit_report?: AnalysisReport | null;
  amazon_report?: AmazonReport | null;
  useLlm: boolean;
  locale: "zh" | "en";
}

export interface ResearchHistorySummary {
  id: string;
  category: string;
  saved_at: string;
  summary: string;
  has_reddit: boolean;
  has_amazon: boolean;
  has_youtube: boolean;
  has_tiktok: boolean;
  has_combined: boolean;
  has_articles: boolean;
  reddit_posts: number;
  amazon_products: number;
  youtube_videos: number;
  tiktok_videos: number;
  article_count: number;
  evidence_items: number;
}

export interface ResearchHistoryItem extends ResearchHistorySummary {
  reddit_report?: AnalysisReport | null;
  amazon_report?: AmazonReport | null;
  youtube_report?: YouTubeReport | null;
  tiktok_report?: TikTokReport | null;
  combined_report?: CombinedInsightReport | null;
  article_report?: ArticleReport | null;
}

export interface ResearchHistoryList {
  items: ResearchHistorySummary[];
  storage_path: string;
  deleted_id?: string;
}

export interface ResearchHistoryResponse {
  item: ResearchHistoryItem;
  storage_path: string;
}

export interface SaveResearchHistoryRequest {
  category: string;
  reddit_report?: AnalysisReport | null;
  amazon_report?: AmazonReport | null;
  youtube_report?: YouTubeReport | null;
  tiktok_report?: TikTokReport | null;
  combined_report?: CombinedInsightReport | null;
  article_report?: ArticleReport | null;
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

export interface MCPDataSourceCredential {
  id: string;
  label: string;
  env_name: string;
  configured: boolean;
}

export interface MCPSettings {
  env_path: string;
  sources: MCPDataSourceCredential[];
}

export interface UpdateMCPSettingsRequest {
  credentials: Record<string, { value?: string; clear?: boolean }>;
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
  amazonProductLimit: number;
  maxAmazonProductLimit: number;
  amazonKeywordLimit: number;
  maxAmazonKeywordLimit: number;
  amazonDetailLimit: number;
  amazonDiscussionLimit: number;
  amazonReviewsPerProduct: number;
  amazonLlmProductLimit: number;
  amazonLlmReviewSamplesPerProduct: number;
  env_path: string;
}

export interface UpdateResearchDefaultsRequest {
  mode: DataMode;
  timeRange: AnalyzeRequest["timeRange"];
  limit: number;
  llmEvidencePosts: number;
  llmCommentSamplesPerPost: number;
  amazonProductLimit: number;
  amazonKeywordLimit: number;
  amazonDetailLimit: number;
  amazonDiscussionLimit: number;
  amazonReviewsPerProduct: number;
  amazonLlmProductLimit: number;
  amazonLlmReviewSamplesPerProduct: number;
}

export interface AgentReachHealth {
  agent_reach_installed: boolean;
  node_installed: boolean;
  npm_installed: boolean;
  mcporter_installed: boolean;
  mcporter_exa_configured: boolean;
  web_search_ready: boolean;
  opencli_installed: boolean;
  opencli_connected: boolean;
  rdt_installed: boolean;
  agent_reach_path: string;
  node_path: string;
  npm_path: string;
  mcporter_path: string;
  mcporter_config_path: string;
  exa_mcp_url: string;
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

export interface WebSearchProviderOption {
  name: "brave" | "tavily" | "google_cse" | string;
  label: string;
  api_key_env: string;
  requires_search_engine_id: boolean;
  search_engine_id_env?: string | null;
}

export interface WebSearchSettings {
  provider: "brave" | "tavily" | "google_cse" | string;
  api_key_env: string;
  api_key_configured: boolean;
  api_key_required: boolean;
  requires_search_engine_id: boolean;
  search_engine_id_env?: string | null;
  search_engine_id: string;
  search_engine_id_configured: boolean;
  env_path: string;
  providers: WebSearchProviderOption[];
}

export interface UpdateWebSearchSettingsRequest {
  provider: string;
  api_key?: string;
  clear_api_key?: boolean;
  search_engine_id?: string;
  clear_search_engine_id?: boolean;
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

export interface AgentRunRequest {
  prompt: string;
  agentMode: "market" | "competitor";
  runId?: string;
  category?: string;
  locale?: "zh" | "en";
  useLlm?: boolean;
  bypassCache?: boolean;
  agentToolTimeoutSeconds?: number;
  continueRunId?: string;
  skillId?: string;
  params?: Record<string, unknown>;
}

export interface AgentToolResult {
  name: string;
  label: string;
  status:
    | "ok"
    | "partial_ok"
    | "empty"
    | "retryable_error"
    | "retry_exhausted"
    | "timeout"
    | "fatal_error"
    | "needs_user_action"
    | "needs_input"
    | "blocked"
    | "error";
  outcome?: string;
  summary: string;
  duration_ms: number;
  input?: Record<string, unknown>;
  data: Record<string, unknown>;
  recovery?: Record<string, unknown>;
  file_path?: string;
}

export interface AgentRunEvent {
  id: string;
  run_id?: string;
  seq: number;
  type: "input" | "planner" | "skill" | "tool" | "artifact" | "message";
  status: "ok" | "error" | "skipped" | "running" | "needs_input";
  title: string;
  message: string;
  timestamp: string;
  tool?: string;
  duration_ms?: number;
  data?: Record<string, unknown>;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  file_path?: string;
}

export interface AgentRunResponse {
  run_id: string;
  generated_at: string;
  status?: "ok" | "needs_input";
  response_type?: "artifact" | "message" | "needs_input";
  mode: "market" | "competitor";
  category: string;
  prompt: string;
  planner: {
    enabled: boolean;
    status: "ok" | "unavailable" | "not_requested";
    message?: string;
    provider?: string;
    model?: string;
    usage?: Record<string, number>;
  };
  events: AgentRunEvent[];
  tools: AgentToolResult[];
  evidence_gaps?: Array<{
    evidence_id: string;
    tool: string;
    required_when: string;
    min_success: number;
    observed_success: number;
    severity: string;
    if_missing: string;
    artifact_requirement: string;
  }>;
  artifact?: {
    title: string;
    executive_summary: string;
    key_findings: string[];
    opportunities: string[];
    risks: string[];
    next_steps: string[];
    evidence_gaps?: Array<Record<string, unknown>>;
    prompt?: string;
  };
  message?: {
    role: "assistant";
    content: string;
  };
  llm_analysis: {
    enabled: boolean;
    status: "ok" | "unavailable" | "not_requested";
    message?: string;
    provider?: string;
    model?: string;
    usage?: Record<string, number>;
  };
  file_path?: string;
  output_files?: AgentOutputFileMeta[];
  skill?: {
    skill_id?: string | null;
    name?: string | null;
    status?: string;
    params?: Record<string, unknown>;
    missing_params?: string[];
    file_path?: string;
  };
  pending?: {
    continue_run_id?: string;
    skill_id?: string | null;
    resolved_params?: Record<string, unknown>;
    missing_params?: string[];
    questions?: Array<{
      field: string;
      label: string;
      question: string;
      suggestions?: string[];
    }>;
    message?: string;
  };
}

export interface AgentRunStreamHandlers {
  onEvent?: (event: AgentRunEvent) => void;
  onResult?: (result: AgentRunResponse) => void;
}

export interface AgentRunStateResponse {
  run_id: string;
  status: "running" | "ok" | "needs_input" | "error";
  updated_at?: string;
  events: AgentRunEvent[];
  error?: string;
  result?: AgentRunResponse;
  progress?: {
    prompt?: string;
    mode?: "market" | "competitor";
    category?: string;
    tools?: AgentToolResult[];
    output_files?: AgentOutputFileMeta[];
  };
}

export interface AgentOutputFileMeta {
  type: "skill" | "tool" | "artifact" | "events" | "run" | string;
  label: string;
  name: string;
  path: string;
  summary?: string;
}

export interface AgentOutputFileResponse {
  name: string;
  path: string;
  format?: "json" | "markdown" | "html";
  content: unknown;
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

async function runAgentStream(body: AgentRunRequest, handlers: AgentRunStreamHandlers = {}): Promise<AgentRunResponse> {
  const response = await fetch("/api/agent/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    const data = text ? JSON.parse(text) : {};
    throw new ApiError(data.error || data.detail || `HTTP ${response.status}`, response.status);
  }
  if (!response.body) {
    throw new ApiError("Streaming response is not available in this browser.", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: AgentRunResponse | null = null;

  function handleBlock(block: string) {
    const lines = block.split(/\r?\n/);
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (!dataLines.length) return;
    const payload = JSON.parse(dataLines.join("\n"));
    if (eventName === "event") {
      handlers.onEvent?.(payload as AgentRunEvent);
      return;
    }
    if (eventName === "result") {
      finalResult = payload as AgentRunResponse;
      handlers.onResult?.(finalResult);
      return;
    }
    if (eventName === "error") {
      throw new ApiError(payload.error || "Agent stream failed", response.status);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\n\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      if (block.trim()) handleBlock(block);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) handleBlock(buffer);
  if (!finalResult) {
    throw new ApiError("Agent stream ended without a final result.", response.status);
  }
  return finalResult;
}

export const api = {
  runAgent: (body: AgentRunRequest) =>
    request<AgentRunResponse>("/api/agent/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runAgentStream,
  getAgentRunState: (runId: string) =>
    request<AgentRunStateResponse>(`/api/agent/runs/${encodeURIComponent(runId)}`),
  readAgentOutputFile: (path: string) =>
    request<AgentOutputFileResponse>(`/api/agent/output-file?path=${encodeURIComponent(path)}`),
  getLLMSettings: () => request<LLMSettings>("/api/settings/llm"),
  updateLLMSettings: (body: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/api/settings/llm", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getMCPSettings: () => request<MCPSettings>("/api/settings/mcp"),
  updateMCPSettings: (body: UpdateMCPSettingsRequest) =>
    request<MCPSettings>("/api/settings/mcp", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
