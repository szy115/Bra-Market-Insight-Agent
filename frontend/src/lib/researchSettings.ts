import type { AnalyzeRequest } from "./api";
import type { Locale } from "./i18n";

export type ResearchSettings = Pick<AnalyzeRequest, "timeRange" | "limit" | "mode"> & {
  amazonProductLimit: number;
  amazonKeywordLimit: number;
};

const STORAGE_KEY = "insight-agent.research-settings";

export const defaultResearchSettings: ResearchSettings = {
  timeRange: "year",
  limit: 50,
  mode: "auto",
  amazonProductLimit: 20,
  amazonKeywordLimit: 8,
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
    const amazonProductLimit = Number(parsed.amazonProductLimit);
    const amazonKeywordLimit = Number(parsed.amazonKeywordLimit);
    return {
      timeRange,
      mode,
      limit: Number.isFinite(limit) ? Math.max(5, Math.min(500, Math.round(limit))) : defaultResearchSettings.limit,
      amazonProductLimit: Number.isFinite(amazonProductLimit)
        ? Math.max(1, Math.min(100, Math.round(amazonProductLimit)))
        : defaultResearchSettings.amazonProductLimit,
      amazonKeywordLimit: Number.isFinite(amazonKeywordLimit)
        ? Math.max(1, Math.min(20, Math.round(amazonKeywordLimit)))
        : defaultResearchSettings.amazonKeywordLimit,
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
