import type { Locale } from "./i18n";

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function sourceLabel(mode: string, locale: Locale = "en"): string {
  const labels: Record<Locale, Record<string, string>> = {
    zh: {
      agent_reach: "Agent Reach 实时数据",
      oauth: "Reddit OAuth 实时数据",
      rss: "Reddit RSS 实时数据",
      sample: "示例兜底数据",
    },
    en: {
      agent_reach: "Agent Reach",
      oauth: "Live Reddit OAuth",
      rss: "Live Reddit RSS",
      sample: "Sample fallback",
    },
  };
  return labels[locale][mode] || mode || (locale === "zh" ? "未知来源" : "Unknown source");
}

export function confidenceLabel(value: string, locale: Locale = "en"): string {
  const key = value?.toLowerCase().trim();
  const labels: Record<Locale, Record<string, string>> = {
    zh: {
      high: "高",
      medium: "中等",
      low: "低",
      "demo only": "仅示例",
    },
    en: {
      high: "High",
      medium: "Medium",
      low: "Low",
      "demo only": "Demo only",
    },
  };
  return labels[locale][key] || value || (locale === "zh" ? "未知" : "Unknown");
}

export function shortDate(value: string, locale: Locale = "en"): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value || (locale === "zh" ? "未知" : "unknown");
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
  }).format(date);
}
