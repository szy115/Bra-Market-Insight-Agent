import type { AnalyzeRequest } from "./api";
import type { Locale } from "./i18n";

export type ResearchSettings = Pick<AnalyzeRequest, "timeRange" | "limit" | "mode"> & {
  llmEvidencePosts: number;
  llmCommentSamplesPerPost: number;
  redditDetailLimit: number;
  redditCommentsPerPost: number;
  amazonProductLimit: number;
  amazonKeywordLimit: number;
  amazonDetailLimit: number;
  amazonDiscussionLimit: number;
  amazonReviewsPerProduct: number;
  amazonLlmProductLimit: number;
  amazonLlmReviewSamplesPerProduct: number;
  articleQueryLimit: number;
  articleResultsPerQuery: number;
  articleCandidateLimit: number;
  articleReadLimit: number;
  youtubeVideoLimit: number;
  youtubeTranscriptVideoLimit: number;
  youtubeCommentVideoLimit: number;
  youtubeCommentsPerVideo: number;
  tiktokVideoLimit: number;
  tiktokCommentsPerVideo: number;
};

const STORAGE_KEY = "insight-agent.research-settings";

export const defaultResearchSettings: ResearchSettings = {
  timeRange: "year",
  limit: 50,
  mode: "auto",
  llmEvidencePosts: 25,
  llmCommentSamplesPerPost: 4,
  redditDetailLimit: 8,
  redditCommentsPerPost: 20,
  amazonProductLimit: 20,
  amazonKeywordLimit: 8,
  amazonDetailLimit: 5,
  amazonDiscussionLimit: 5,
  amazonReviewsPerProduct: 5,
  amazonLlmProductLimit: 25,
  amazonLlmReviewSamplesPerProduct: 5,
  articleQueryLimit: 12,
  articleResultsPerQuery: 5,
  articleCandidateLimit: 20,
  articleReadLimit: 30,
  youtubeVideoLimit: 25,
  youtubeTranscriptVideoLimit: 5,
  youtubeCommentVideoLimit: 3,
  youtubeCommentsPerVideo: 10,
  tiktokVideoLimit: 20,
  tiktokCommentsPerVideo: 10,
};

const validTimeRanges = new Set<AnalyzeRequest["timeRange"]>(["day", "week", "month", "year", "all"]);
const validModes = new Set<AnalyzeRequest["mode"]>(["auto", "agent_reach", "oauth", "rss", "sample"]);

export function loadResearchSettings(): ResearchSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultResearchSettings;
    const parsed = JSON.parse(raw) as Partial<ResearchSettings>;
    const timeRange = validTimeRanges.has(parsed.timeRange as AnalyzeRequest["timeRange"])
      ? (parsed.timeRange as AnalyzeRequest["timeRange"])
      : defaultResearchSettings.timeRange;
    const mode = validModes.has(parsed.mode as AnalyzeRequest["mode"])
      ? (parsed.mode as AnalyzeRequest["mode"])
      : defaultResearchSettings.mode;
    const limit = Number(parsed.limit);
    const llmEvidencePosts = Number(parsed.llmEvidencePosts);
    const llmCommentSamplesPerPost = Number(parsed.llmCommentSamplesPerPost);
    const redditDetailLimit = Number(parsed.redditDetailLimit);
    const redditCommentsPerPost = Number(parsed.redditCommentsPerPost);
    const amazonProductLimit = Number(parsed.amazonProductLimit);
    const amazonKeywordLimit = Number(parsed.amazonKeywordLimit);
    const amazonDetailLimit = Number(parsed.amazonDetailLimit);
    const amazonDiscussionLimit = Number(parsed.amazonDiscussionLimit);
    const amazonReviewsPerProduct = Number(parsed.amazonReviewsPerProduct);
    const amazonLlmProductLimit = Number(parsed.amazonLlmProductLimit);
    const amazonLlmReviewSamplesPerProduct = Number(parsed.amazonLlmReviewSamplesPerProduct);
    const articleQueryLimit = Number(parsed.articleQueryLimit);
    const articleResultsPerQuery = Number(parsed.articleResultsPerQuery);
    const articleCandidateLimit = Number(parsed.articleCandidateLimit);
    const articleReadLimit = Number(parsed.articleReadLimit);
    const youtubeVideoLimit = Number(parsed.youtubeVideoLimit);
    const youtubeTranscriptVideoLimit = Number(parsed.youtubeTranscriptVideoLimit);
    const youtubeCommentVideoLimit = Number(parsed.youtubeCommentVideoLimit);
    const youtubeCommentsPerVideo = Number(parsed.youtubeCommentsPerVideo);
    const tiktokVideoLimit = Number(parsed.tiktokVideoLimit);
    const tiktokCommentsPerVideo = Number(parsed.tiktokCommentsPerVideo);
    return {
      timeRange,
      mode,
      limit: Number.isFinite(limit) ? Math.max(5, Math.min(500, Math.round(limit))) : defaultResearchSettings.limit,
      llmEvidencePosts: Number.isFinite(llmEvidencePosts)
        ? Math.max(1, Math.min(100, Math.round(llmEvidencePosts)))
        : defaultResearchSettings.llmEvidencePosts,
      llmCommentSamplesPerPost: Number.isFinite(llmCommentSamplesPerPost)
        ? Math.max(0, Math.min(50, Math.round(llmCommentSamplesPerPost)))
        : defaultResearchSettings.llmCommentSamplesPerPost,
      redditDetailLimit: Number.isFinite(redditDetailLimit)
        ? Math.max(0, Math.min(100, Math.round(redditDetailLimit)))
        : defaultResearchSettings.redditDetailLimit,
      redditCommentsPerPost: Number.isFinite(redditCommentsPerPost)
        ? Math.max(0, Math.min(200, Math.round(redditCommentsPerPost)))
        : defaultResearchSettings.redditCommentsPerPost,
      amazonProductLimit: Number.isFinite(amazonProductLimit)
        ? Math.max(1, Math.min(100, Math.round(amazonProductLimit)))
        : defaultResearchSettings.amazonProductLimit,
      amazonKeywordLimit: Number.isFinite(amazonKeywordLimit)
        ? Math.max(1, Math.min(20, Math.round(amazonKeywordLimit)))
        : defaultResearchSettings.amazonKeywordLimit,
      amazonDetailLimit: Number.isFinite(amazonDetailLimit)
        ? Math.max(0, Math.min(100, Math.round(amazonDetailLimit)))
        : defaultResearchSettings.amazonDetailLimit,
      amazonDiscussionLimit: Number.isFinite(amazonDiscussionLimit)
        ? Math.max(0, Math.min(100, Math.round(amazonDiscussionLimit)))
        : defaultResearchSettings.amazonDiscussionLimit,
      amazonReviewsPerProduct: Number.isFinite(amazonReviewsPerProduct)
        ? Math.max(0, Math.min(100, Math.round(amazonReviewsPerProduct)))
        : defaultResearchSettings.amazonReviewsPerProduct,
      amazonLlmProductLimit: Number.isFinite(amazonLlmProductLimit)
        ? Math.max(1, Math.min(100, Math.round(amazonLlmProductLimit)))
        : defaultResearchSettings.amazonLlmProductLimit,
      amazonLlmReviewSamplesPerProduct: Number.isFinite(amazonLlmReviewSamplesPerProduct)
        ? Math.max(0, Math.min(50, Math.round(amazonLlmReviewSamplesPerProduct)))
        : defaultResearchSettings.amazonLlmReviewSamplesPerProduct,
      articleQueryLimit: Number.isFinite(articleQueryLimit)
        ? Math.max(1, Math.min(30, Math.round(articleQueryLimit)))
        : defaultResearchSettings.articleQueryLimit,
      articleResultsPerQuery: Number.isFinite(articleResultsPerQuery)
        ? Math.max(1, Math.min(20, Math.round(articleResultsPerQuery)))
        : defaultResearchSettings.articleResultsPerQuery,
      articleCandidateLimit: Number.isFinite(articleCandidateLimit)
        ? Math.max(1, Math.min(80, Math.round(articleCandidateLimit)))
        : defaultResearchSettings.articleCandidateLimit,
      articleReadLimit: Number.isFinite(articleReadLimit)
        ? Math.max(1, Math.min(80, Math.round(articleReadLimit)))
        : defaultResearchSettings.articleReadLimit,
      youtubeVideoLimit: Number.isFinite(youtubeVideoLimit)
        ? Math.max(1, Math.min(50, Math.round(youtubeVideoLimit)))
        : defaultResearchSettings.youtubeVideoLimit,
      youtubeTranscriptVideoLimit: Number.isFinite(youtubeTranscriptVideoLimit)
        ? Math.max(0, Math.min(20, Math.round(youtubeTranscriptVideoLimit)))
        : defaultResearchSettings.youtubeTranscriptVideoLimit,
      youtubeCommentVideoLimit: Number.isFinite(youtubeCommentVideoLimit)
        ? Math.max(0, Math.min(20, Math.round(youtubeCommentVideoLimit)))
        : defaultResearchSettings.youtubeCommentVideoLimit,
      youtubeCommentsPerVideo: Number.isFinite(youtubeCommentsPerVideo)
        ? Math.max(0, Math.min(50, Math.round(youtubeCommentsPerVideo)))
        : defaultResearchSettings.youtubeCommentsPerVideo,
      tiktokVideoLimit: Number.isFinite(tiktokVideoLimit)
        ? Math.max(1, Math.min(30, Math.round(tiktokVideoLimit)))
        : defaultResearchSettings.tiktokVideoLimit,
      tiktokCommentsPerVideo: Number.isFinite(tiktokCommentsPerVideo)
        ? Math.max(1, Math.min(50, Math.round(tiktokCommentsPerVideo)))
        : defaultResearchSettings.tiktokCommentsPerVideo,
    };
  } catch {
    return defaultResearchSettings;
  }
}

export function saveResearchSettings(settings: ResearchSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export function describeResearchSettings(settings: ResearchSettings, locale: Locale = "en"): string {
  const timeLabels: Record<Locale, Record<AnalyzeRequest["timeRange"], string>> = {
    zh: {
      day: "过去 1 天",
      week: "过去 1 周",
      month: "过去 1 个月",
      year: "过去 1 年",
      all: "全部时间",
    },
    en: {
      day: "Past day",
      week: "Past week",
      month: "Past month",
      year: "Past year",
      all: "All time",
    },
  };
  const modeLabels: Record<Locale, Record<AnalyzeRequest["mode"], string>> = {
    zh: {
      auto: "自动数据源",
      agent_reach: "Agent Reach",
      oauth: "OAuth",
      rss: "RSS",
      sample: "示例数据",
    },
    en: {
      auto: "Auto source",
      agent_reach: "Agent Reach",
      oauth: "OAuth",
      rss: "RSS",
      sample: "Sample",
    },
  };
  const limitText = locale === "zh" ? `最多 ${settings.limit} 条帖子` : `${settings.limit} posts max`;
  return `${modeLabels[locale][settings.mode]} · ${timeLabels[locale][settings.timeRange]} · ${limitText}`;
}

export function describeAmazonResearchSettings(settings: ResearchSettings, locale: Locale = "en"): string {
  if (locale === "zh") {
    return `Amazon · ${settings.amazonKeywordLimit} 个关键词 × 每词 ${settings.amazonProductLimit} 个商品`;
  }
  return `Amazon · ${settings.amazonKeywordLimit} keywords × ${settings.amazonProductLimit} products each`;
}

export function describeArticleResearchSettings(settings: ResearchSettings, locale: Locale = "en"): string {
  if (locale === "zh") {
    return `文章 · ${settings.articleQueryLimit} 个搜索词 × 每词 ${settings.articleResultsPerQuery} 条，候选 ${settings.articleCandidateLimit} 个`;
  }
  return `Articles · ${settings.articleQueryLimit} queries × ${settings.articleResultsPerQuery} results, ${settings.articleCandidateLimit} candidates`;
}

export function describeYoutubeResearchSettings(settings: ResearchSettings, locale: Locale = "en"): string {
  if (locale === "zh") {
    return `YouTube · ${settings.youtubeVideoLimit} 个视频，字幕 ${settings.youtubeTranscriptVideoLimit} 个，评论 ${settings.youtubeCommentVideoLimit} × ${settings.youtubeCommentsPerVideo}`;
  }
  return `YouTube · ${settings.youtubeVideoLimit} videos, captions ${settings.youtubeTranscriptVideoLimit}, comments ${settings.youtubeCommentVideoLimit} × ${settings.youtubeCommentsPerVideo}`;
}

export function describeTikTokResearchSettings(settings: ResearchSettings, locale: Locale = "en"): string {
  if (locale === "zh") {
    return `TikTok · ${settings.tiktokVideoLimit} 个视频，逐条进详情页，每条 ${settings.tiktokCommentsPerVideo} 条评论`;
  }
  return `TikTok · ${settings.tiktokVideoLimit} videos, detail pages, ${settings.tiktokCommentsPerVideo} comments each`;
}
