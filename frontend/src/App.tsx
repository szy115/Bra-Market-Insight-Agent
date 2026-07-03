import {
  ArrowLeft,
  BarChart3,
  Bot,
  CalendarRange,
  Database,
  Download,
  FileText,
  FlaskConical,
  FolderOpen,
  KeyRound,
  Languages,
  Lightbulb,
  Link2,
  Loader2,
  Megaphone,
  MessageSquare,
  Radar,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldAlert,
  ShoppingBag,
  Sparkles,
  Square,
  Target,
  Trash2,
  Youtube,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type AgentReachSettings,
  type AgentRunResponse,
  type AnalysisReport,
  type AnalyzeRequest,
  type ArticleDiscoveryCandidate,
  type ArticleDiscoveryReport,
  type ArticleReport,
  type AmazonReport,
  type CombinedInsightItem,
  type CombinedInsightReport,
  type CombinedEvidenceChainItem,
  type CompetitorCandidate,
  type CompetitorDeepDiveItem,
  type CompetitorDeepDiveReport,
  type CompetitorDiscoveryBrief,
  type CompetitorDiscoveryReport,
  type CompetitorScoreWeights,
  type InsightCitation,
  type LLMSettings,
  type RedditSettings,
  type ResearchDefaults,
  type ResearchHistoryItem,
  type ResearchHistorySummary,
  type TikTokReport,
  type WebSearchSettings,
  type YouTubeReport,
} from "./lib/api";
import { confidenceLabel, pct, shortDate, sourceLabel } from "./lib/format";
import { formatMessage, loadLocale, makeTranslator, saveLocale, type Locale, type Translator } from "./lib/i18n";
import {
  describeAmazonResearchSettings,
  describeArticleResearchSettings,
  describeResearchSettings,
  describeTikTokResearchSettings,
  describeYoutubeResearchSettings,
  loadResearchSettings,
  saveResearchSettings,
  type ResearchSettings,
} from "./lib/researchSettings";
import { CoverageChart, SentimentChart, TopicBarChart, TrendChart } from "./components/charts";

type Page = "agent" | "research" | "competitors" | "settings";
type ResearchSource = "reddit" | "amazon" | "youtube" | "tiktok" | "combined" | "articles";
type SourceSettingsSource = Exclude<ResearchSource, "combined">;
type CompetitorTab = "discovery" | "monitoring";
type CompetitorDeepDivePreset = "fast" | "standard" | "deep";
type HistoryReportTab = "combined" | "reddit" | "amazon" | "youtube" | "tiktok" | "articles";
type AgentArtifactTab = "market" | "draft" | "output";
type AgentSkillId =
  | "market_trend"
  | "breakout_discovery"
  | "breakout_teardown"
  | "amazon_reviews"
  | "tiktok_validation"
  | "article_rankings";
type AgentPromptTemplateId = "market_insight_weekly" | "breakout_competitor_tiktok";
type AgentPromptTemplate = {
  id: AgentPromptTemplateId;
  mode: "market" | "competitor";
  title: string;
  description: string;
  prompt: string;
  sources: string[];
};
type ResearchLaunchIntent = {
  source: ResearchSource;
  category?: string;
  openHistory?: boolean;
  nonce: number;
};
type CompetitorLaunchIntent = {
  tab: CompetitorTab;
  nonce: number;
};
type LocalizedProps = {
  locale: Locale;
  t: Translator;
};
type ResearchSession = {
  category: string;
  activeSource: ResearchSource;
  articleUrls: string;
  redditReport: AnalysisReport | null;
  amazonReport: AmazonReport | null;
  youtubeReport: YouTubeReport | null;
  tiktokReport: TikTokReport | null;
  articleDiscoveryReport: ArticleDiscoveryReport | null;
  articleReport: ArticleReport | null;
  combinedReport: CombinedInsightReport | null;
};
type CompetitorSession = {
  activeCompetitorTab: CompetitorTab;
  discoveryBrief: CompetitorDiscoveryBrief;
  scoreWeights: CompetitorScoreWeights;
  productLimit: number;
  bypassCache: boolean;
  discoveryReport: CompetitorDiscoveryReport | null;
  monitoringCandidates: CompetitorCandidate[];
  deepDiveReports: Record<string, CompetitorDeepDiveReport>;
  selectedDeepDiveKey: string;
  deepDivePreset: CompetitorDeepDivePreset;
};

const RESEARCH_SESSION_KEY = "insight-agent.research-session";
const COMPETITOR_SESSION_KEY = "insight-agent.competitor-session";
const DEFAULT_AGENT_CATEGORY = "minimizer bra";

const DEFAULT_COMPETITOR_DISCOVERY_BRIEF: CompetitorDiscoveryBrief = {
  brand: "Hsia / 遐",
  market: "美国",
  category: "大胸显小 / Minimizer Bra",
  coreKeywords: "minimizer bra, full coverage bra, large bust bra, supportive bra",
  targetPriceBand: "$49-$69",
  upgradePriceBand: "$59-$79",
  coreSizes: "D-G",
  coreUsers: "大胸、通勤、显小、支撑、舒适、外穿平滑",
  brandDirection: "好看、支撑、显小的大胸文胸",
};

const DEFAULT_COMPETITOR_SCORE_WEIGHTS: CompetitorScoreWeights = {
  briefMatch: 1,
  priceFit: 1.35,
  sizeMatch: 1,
  marketProof: 1,
  reviewEvidence: 1,
  queryCoverage: 1,
  tiktokProof: 1,
};

const COMPETITOR_SCORE_WEIGHT_KEYS = Object.keys(DEFAULT_COMPETITOR_SCORE_WEIGHTS) as Array<keyof CompetitorScoreWeights>;
const DEFAULT_COMPETITOR_DEEP_DIVE_PRESET: CompetitorDeepDivePreset = "standard";
const COMPETITOR_DEEP_DIVE_PRESET_KEYS: CompetitorDeepDivePreset[] = ["fast", "standard", "deep"];
const COMPETITOR_DEEP_DIVE_PRESETS: Record<CompetitorDeepDivePreset, {
  amazonReviewLimit: number;
  redditLimit: number;
  redditDetailLimit: number;
  redditCommentsPerPost: number;
  webCandidateLimit: number;
  aiReviewLimit: number;
  aiRedditPostLimit: number;
}> = {
  fast: {
    amazonReviewLimit: 30,
    redditLimit: 25,
    redditDetailLimit: 5,
    redditCommentsPerPost: 10,
    webCandidateLimit: 3,
    aiReviewLimit: 20,
    aiRedditPostLimit: 10,
  },
  standard: {
    amazonReviewLimit: 60,
    redditLimit: 50,
    redditDetailLimit: 10,
    redditCommentsPerPost: 15,
    webCandidateLimit: 4,
    aiReviewLimit: 35,
    aiRedditPostLimit: 15,
  },
  deep: {
    amazonReviewLimit: 120,
    redditLimit: 80,
    redditDetailLimit: 20,
    redditCommentsPerPost: 20,
    webCandidateLimit: 6,
    aiReviewLimit: 50,
    aiRedditPostLimit: 25,
  },
};

function loadResearchSession(): ResearchSession {
  const fallback: ResearchSession = {
    category: "wireless bras for large bust",
    activeSource: "combined",
    articleUrls: "",
    redditReport: null,
    amazonReport: null,
    youtubeReport: null,
    tiktokReport: null,
    articleDiscoveryReport: null,
    articleReport: null,
    combinedReport: null,
  };
  try {
    const raw = localStorage.getItem(RESEARCH_SESSION_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ResearchSession>;
    const activeSource: ResearchSource = parsed.activeSource === "reddit"
      || parsed.activeSource === "amazon"
      || parsed.activeSource === "youtube"
      || parsed.activeSource === "tiktok"
      || parsed.activeSource === "articles"
      ? parsed.activeSource
      : "combined";
    return {
      category: typeof parsed.category === "string" && parsed.category.trim() ? parsed.category : fallback.category,
      activeSource,
      articleUrls: typeof parsed.articleUrls === "string" ? parsed.articleUrls : fallback.articleUrls,
      redditReport: parsed.redditReport || null,
      amazonReport: parsed.amazonReport || null,
      youtubeReport: parsed.youtubeReport || null,
      tiktokReport: parsed.tiktokReport || null,
      articleDiscoveryReport: parsed.articleDiscoveryReport || null,
      articleReport: parsed.articleReport || null,
      combinedReport: parsed.combinedReport || null,
    };
  } catch {
    return fallback;
  }
}

function saveResearchSession(session: ResearchSession): void {
  try {
    localStorage.setItem(RESEARCH_SESSION_KEY, JSON.stringify(session));
  } catch {
    // Large research runs can exceed browser quota; the live in-memory report still remains usable.
  }
}

function boundedInteger(value: unknown, fallback: number, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function boundedNumber(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = typeof value === "string" ? Number(value) : value;
  if (typeof numeric !== "number" || !Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, numeric));
}

function normalizeCompetitorBrief(value: unknown, fallbackQuery?: string): CompetitorDiscoveryBrief {
  const raw = value && typeof value === "object" ? value as Partial<CompetitorDiscoveryBrief> : {};
  const next = { ...DEFAULT_COMPETITOR_DISCOVERY_BRIEF };
  (Object.keys(next) as Array<keyof CompetitorDiscoveryBrief>).forEach((key) => {
    const fieldValue = raw[key];
    if (typeof fieldValue === "string" && fieldValue.trim()) {
      next[key] = fieldValue.trim();
    }
  });
  if (fallbackQuery && !raw.coreKeywords) {
    next.coreKeywords = fallbackQuery;
  }
  return next;
}

function normalizeCompetitorScoreWeights(value: unknown): CompetitorScoreWeights {
  const raw = value && typeof value === "object" ? value as Partial<CompetitorScoreWeights> : {};
  const next = { ...DEFAULT_COMPETITOR_SCORE_WEIGHTS };
  COMPETITOR_SCORE_WEIGHT_KEYS.forEach((key) => {
    next[key] = Number(boundedNumber(raw[key], next[key], 0, 3).toFixed(2));
  });
  return next;
}

function loadCompetitorSession(): CompetitorSession {
  const fallback: CompetitorSession = {
    activeCompetitorTab: "discovery",
    discoveryBrief: DEFAULT_COMPETITOR_DISCOVERY_BRIEF,
    scoreWeights: DEFAULT_COMPETITOR_SCORE_WEIGHTS,
    productLimit: 20,
    bypassCache: false,
    discoveryReport: null,
    monitoringCandidates: [],
    deepDiveReports: {},
    selectedDeepDiveKey: "",
    deepDivePreset: DEFAULT_COMPETITOR_DEEP_DIVE_PRESET,
  };
  try {
    const raw = localStorage.getItem(COMPETITOR_SESSION_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<CompetitorSession>;
    const oldQuery = typeof (parsed as { discoveryQuery?: unknown }).discoveryQuery === "string"
      ? (parsed as { discoveryQuery: string }).discoveryQuery
      : "";
    return {
      activeCompetitorTab: parsed.activeCompetitorTab === "monitoring" ? "monitoring" : fallback.activeCompetitorTab,
      discoveryBrief: normalizeCompetitorBrief(parsed.discoveryBrief, oldQuery),
      scoreWeights: normalizeCompetitorScoreWeights(parsed.scoreWeights),
      productLimit: boundedInteger(parsed.productLimit, fallback.productLimit, 1, 100),
      bypassCache: Boolean(parsed.bypassCache),
      discoveryReport: parsed.discoveryReport || null,
      monitoringCandidates: Array.isArray(parsed.monitoringCandidates) ? parsed.monitoringCandidates : fallback.monitoringCandidates,
      deepDiveReports: parsed.deepDiveReports && typeof parsed.deepDiveReports === "object" ? parsed.deepDiveReports : fallback.deepDiveReports,
      selectedDeepDiveKey: typeof parsed.selectedDeepDiveKey === "string" ? parsed.selectedDeepDiveKey : fallback.selectedDeepDiveKey,
      deepDivePreset: COMPETITOR_DEEP_DIVE_PRESET_KEYS.includes(parsed.deepDivePreset as CompetitorDeepDivePreset)
        ? (parsed.deepDivePreset as CompetitorDeepDivePreset)
        : fallback.deepDivePreset,
    };
  } catch {
    return fallback;
  }
}

function saveCompetitorSession(session: CompetitorSession): void {
  try {
    localStorage.setItem(COMPETITOR_SESSION_KEY, JSON.stringify(session));
  } catch {
    // Keep the live page state even if the browser refuses a larger stored report.
  }
}

function parseArticleUrls(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => {
      if (!/^https?:\/\//i.test(item) || seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

export function App() {
  const [page, setPage] = useState<Page>("agent");
  const [locale, setLocale] = useState<Locale>(() => loadLocale());
  const [researchSettings, setResearchSettings] = useState<ResearchSettings>(() => loadResearchSettings());
  const [researchLaunchIntent, setResearchLaunchIntent] = useState<ResearchLaunchIntent | null>(null);
  const [competitorLaunchIntent, setCompetitorLaunchIntent] = useState<CompetitorLaunchIntent | null>(null);
  const t = useMemo(() => makeTranslator(locale), [locale]);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  useEffect(() => {
    Promise.all([api.getResearchSettings(), api.getAgentReachSettings()])
      .then(([settings, agentReach]) => {
        updateResearchSettings({
          mode: settings.mode,
          timeRange: settings.timeRange,
          limit: settings.limit,
          llmEvidencePosts: settings.llmEvidencePosts,
          llmCommentSamplesPerPost: settings.llmCommentSamplesPerPost,
          redditDetailLimit: agentReach.detail_limit,
          redditCommentsPerPost: agentReach.comments_per_post,
          amazonProductLimit: settings.amazonProductLimit,
          amazonKeywordLimit: settings.amazonKeywordLimit,
          amazonDetailLimit: settings.amazonDetailLimit,
          amazonDiscussionLimit: settings.amazonDiscussionLimit,
          amazonReviewsPerProduct: settings.amazonReviewsPerProduct,
          amazonLlmProductLimit: settings.amazonLlmProductLimit,
          amazonLlmReviewSamplesPerProduct: settings.amazonLlmReviewSamplesPerProduct,
        });
      })
      .catch(() => {
        // Local storage defaults still keep the demo usable if the API is unavailable.
      });
  }, []);

  function updateResearchSettings(next: Partial<ResearchSettings>) {
    setResearchSettings((current) => {
      const merged = { ...current, ...next };
      saveResearchSettings(merged);
      return merged;
    });
  }

  function updateLocale(next: Locale) {
    setLocale(next);
    saveLocale(next);
  }

  function openResearchSource(source: ResearchSource, category = DEFAULT_AGENT_CATEGORY, openHistory = false) {
    setResearchLaunchIntent({ source, category, openHistory, nonce: Date.now() });
    setPage("research");
  }

  function openCompetitorTab(tab: CompetitorTab) {
    setCompetitorLaunchIntent({ tab, nonce: Date.now() });
    setPage("competitors");
  }

  return (
    <div className={`app-shell${page === "agent" ? " agent-shell" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">IA</div>
          <div>
            <h1>Insight Agent</h1>
            <p>{t("brand.subtitle")}</p>
          </div>
        </div>
        <nav className="nav">
          <button className={page === "agent" ? "active" : ""} onClick={() => setPage("agent")}>
            <Sparkles size={17} /> <span>{t("nav.agent")}</span>
          </button>
          <button className={page === "research" ? "active" : ""} onClick={() => setPage("research")}>
            <BarChart3 size={17} /> <span>{t("nav.research")}</span>
          </button>
          <button className={page === "competitors" ? "active" : ""} onClick={() => setPage("competitors")}>
            <Target size={17} /> <span>{t("nav.competitors")}</span>
          </button>
          <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}>
            <Settings size={17} /> <span>{t("nav.settings")}</span>
          </button>
        </nav>
        <div className="language-switch" aria-label="Language">
          <Languages size={16} />
          <button className={locale === "zh" ? "active" : ""} type="button" onClick={() => updateLocale("zh")}>
            {t("language.zh")}
          </button>
          <button className={locale === "en" ? "active" : ""} type="button" onClick={() => updateLocale("en")}>
            {t("language.en")}
          </button>
        </div>
        <div className="sidebar-note">
          <Bot size={16} />
          <span>{t("sidebar.note")}</span>
        </div>
      </aside>

      <main className="workspace">
        {page === "agent" ? (
          <SimpleAgentPage
            locale={locale}
            onOpenCompetitors={openCompetitorTab}
            onOpenResearch={openResearchSource}
            t={t}
          />
        ) : null}
        <div className={page === "research" ? "" : "page-hidden"} aria-hidden={page !== "research"}>
          <ResearchPage
            launchIntent={researchLaunchIntent}
            locale={locale}
            onResearchSettingsChange={updateResearchSettings}
            researchSettings={researchSettings}
            t={t}
          />
        </div>
        <div className={page === "competitors" ? "" : "page-hidden"} aria-hidden={page !== "competitors"}>
          <CompetitorsPage launchIntent={competitorLaunchIntent} locale={locale} t={t} />
        </div>
        {page === "settings" ? (
          <SettingsPage
            locale={locale}
            t={t}
            onResearchSettingsChange={updateResearchSettings}
          />
        ) : null}
      </main>
    </div>
  );
}

function buildAgentPromptTemplates(t: Translator): AgentPromptTemplate[] {
  return [
    {
      id: "market_insight_weekly",
      mode: "market",
      title: t("agent.template.market.title"),
      description: t("agent.template.market.description"),
      prompt: `${t("agent.template.market.task")}\n\n${t("agent.template.market.workflow")}`,
      sources: ["Reddit", "Amazon"],
    },
    {
      id: "breakout_competitor_tiktok",
      mode: "competitor",
      title: t("agent.template.competitor.title"),
      description: t("agent.template.competitor.description"),
      prompt: `${t("agent.template.competitor.task")}\n\n${t("agent.template.competitor.workflow")}`,
      sources: ["Amazon", "TikTok"],
    },
  ];
}

function SimpleAgentPage({
  locale,
  onOpenCompetitors,
  onOpenResearch,
  t,
}: {
  onOpenCompetitors: (tab: CompetitorTab) => void;
  onOpenResearch: (source: ResearchSource, category?: string, openHistory?: boolean) => void;
} & LocalizedProps) {
  const promptTemplates = useMemo(() => buildAgentPromptTemplates(t), [t]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<AgentPromptTemplateId>("market_insight_weekly");
  const selectedTemplate = promptTemplates.find((template) => template.id === selectedTemplateId) || promptTemplates[0]!;
  const [agentMode, setAgentMode] = useState<"market" | "competitor">(selectedTemplate.mode);
  const [prompt, setPrompt] = useState(selectedTemplate.prompt);
  const [artifactTab, setArtifactTab] = useState<AgentArtifactTab>("market");
  const [result, setResult] = useState<AgentRunResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const artifactJson = result ? JSON.stringify(result, null, 2) : "";
  const artifactTitle = result?.artifact.title || t("agent.simpleTitle");
  const artifactTabs: Array<{ id: AgentArtifactTab; label: string }> = [
    { id: "market", label: t("agent.tab.market") },
    { id: "draft", label: t("agent.tab.draft") },
    { id: "output", label: t("agent.tab.output") },
  ];

  function applyPromptTemplate(template: AgentPromptTemplate) {
    setSelectedTemplateId(template.id);
    setAgentMode(template.mode);
    setPrompt(template.prompt);
    setArtifactTab("draft");
  }

  async function runAgent(event?: FormEvent) {
    event?.preventDefault();
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) return;
    setLoading(true);
    setError(null);
    setArtifactTab("output");
    try {
      const response = await api.runAgent({
        prompt: cleanPrompt,
        agentMode,
        category: DEFAULT_AGENT_CATEGORY,
        locale,
        useLlm: true,
        agentToolTimeoutSeconds: 600,
      });
      setResult(response);
      setArtifactTab("market");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("agent.runError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="agent-minimal-page">
      <header className="agent-minimal-head">
        <button type="button" className="icon-only-button" onClick={() => onOpenResearch("combined", DEFAULT_AGENT_CATEGORY)}>
          <ArrowLeft size={17} />
        </button>
        <h2>{artifactTitle}</h2>
        <button type="button" className="icon-only-button" onClick={() => result ? downloadText(`${slugify(result.artifact.title)}.json`, artifactJson, "application/json") : undefined}>
          <Download size={17} />
        </button>
      </header>

      <div className="agent-minimal-grid">
        <section className="agent-chat-pane">
          <div className="agent-chat-scroll">
            <div className="agent-active-template">
              <Sparkles size={15} />
              <div>
                <span>{selectedTemplate.title}</span>
                <p>{selectedTemplate.description}</p>
              </div>
            </div>
            <div className="agent-message user">{prompt}</div>
            <div className="agent-tool-toggle">
              <Link2 size={15} />
              <span>{formatMessage(t("agent.toolCalls"), { count: result?.tools.length ?? (loading ? 3 : 0) })}</span>
            </div>
            {loading ? (
              <div className="agent-message assistant">
                <Loader2 className="spin" size={17} />
                <span>{t("agent.running")}</span>
              </div>
            ) : null}
            {error ? <div className="alert danger">{error}</div> : null}
            {result ? (
              <>
                <div className="agent-tool-list">
                  {result.tools.map((tool) => (
                    <div className={`agent-tool-call ${tool.status}`} key={tool.name}>
                      <span>{tool.label}</span>
                      <b>{tool.status === "ok" ? t("agent.toolOk") : t("agent.toolError")}</b>
                      <p>{tool.summary}</p>
                    </div>
                  ))}
                </div>
                <div className="agent-message assistant">
                  <strong>{result.artifact.title}</strong>
                  <p>{result.artifact.executive_summary}</p>
                </div>
              </>
            ) : !loading ? (
              <div className="agent-message assistant subtle">{t("agent.emptyConversation")}</div>
            ) : null}
          </div>

          <form className="agent-bottom-composer" onSubmit={runAgent}>
            <div className="agent-template-picker" aria-label={t("agent.template.label")}>
              <span>{t("agent.template.label")}</span>
              {promptTemplates.map((template) => (
                <button
                  className={selectedTemplateId === template.id ? "active" : ""}
                  key={template.id}
                  type="button"
                  onClick={() => applyPromptTemplate(template)}
                >
                  {template.title}
                </button>
              ))}
            </div>
            <div className="agent-input-box">
              <textarea
                aria-label={t("agent.promptLabel")}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={t("agent.promptPlaceholder")}
                rows={4}
              />
              <button type="submit" disabled={loading || !prompt.trim()} title={t("agent.send")}>
                {loading ? <Loader2 className="spin" size={18} /> : <Sparkles size={18} />}
              </button>
            </div>
          </form>
        </section>

        <section className="agent-artifact-pane">
          <div className="artifact-tabs minimal" role="tablist" aria-label={t("agent.artifactTabs")}>
            {artifactTabs.map((tab) => (
              <button
                className={artifactTab === tab.id ? "active" : ""}
                key={tab.id}
                type="button"
                onClick={() => setArtifactTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="agent-artifact-body">
            {artifactTab === "market" ? (
              <AgentArtifactSummary result={result} t={t} />
            ) : null}
            {artifactTab === "draft" ? (
              <AgentDraftView
                mode={agentMode}
                onOpenCompetitors={onOpenCompetitors}
                onOpenResearch={onOpenResearch}
                prompt={prompt}
                result={result}
                t={t}
              />
            ) : null}
            {artifactTab === "output" ? (
              result ? <pre className="artifact-json minimal"><code>{artifactJson}</code></pre> : <AgentArtifactPlaceholder loading={loading} t={t} />
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function AgentArtifactPlaceholder({ loading, t }: { loading: boolean; t: Translator }) {
  return (
    <div className="agent-artifact-placeholder">
      {loading ? <Loader2 className="spin" size={20} /> : <Sparkles size={20} />}
      <p>{loading ? t("agent.outputLoading") : t("agent.outputEmpty")}</p>
    </div>
  );
}

function AgentArtifactSummary({ result, t }: { result: AgentRunResponse | null; t: Translator }) {
  if (!result) return <AgentArtifactPlaceholder loading={false} t={t} />;
  return (
    <div className="agent-artifact-summary">
      <p className="eyebrow">{result.mode === "competitor" ? t("agent.mode.competitor") : t("agent.mode.market")}</p>
      <h3>{result.artifact.title}</h3>
      <p className="summary-text">{result.artifact.executive_summary}</p>
      <AgentArtifactList title={t("agent.findings")} items={result.artifact.key_findings} />
      <AgentArtifactList title={t("combined.opportunities")} items={result.artifact.opportunities} />
      <AgentArtifactList title={t("combined.risks")} items={result.artifact.risks} />
      <AgentArtifactList title={t("agent.nextSteps")} items={result.artifact.next_steps} />
    </div>
  );
}

function AgentArtifactList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="agent-artifact-section">
      <h4>{title}</h4>
      <ul>
        {(items || []).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function AgentDraftView({
  mode,
  onOpenCompetitors,
  onOpenResearch,
  prompt,
  result,
  t,
}: {
  mode: "market" | "competitor";
  onOpenCompetitors: (tab: CompetitorTab) => void;
  onOpenResearch: (source: ResearchSource, category?: string, openHistory?: boolean) => void;
  prompt: string;
  result: AgentRunResponse | null;
  t: Translator;
}) {
  const plannedTools = result?.tools.map((tool) => tool.label) || [];
  return (
    <div className="agent-draft-view">
      <div className="agent-draft-prompt">
        <span>{t("agent.promptLabel")}</span>
        <p>{prompt}</p>
      </div>
      <div className="agent-draft-tools">
        {plannedTools.length
          ? plannedTools.map((tool) => <span key={tool}>{tool}</span>)
          : <span>{t("agent.promptRoutedTools")}</span>}
      </div>
      <div className="artifact-action-grid minimal-actions">
        <button type="button" onClick={() => onOpenResearch("combined", DEFAULT_AGENT_CATEGORY)}>
          <Sparkles size={16} />
          {t("agent.openIntegrated")}
        </button>
        <button type="button" onClick={() => onOpenCompetitors("discovery")}>
          <Target size={16} />
          {t("agent.openDiscovery")}
        </button>
        <button type="button" onClick={() => onOpenResearch("articles", DEFAULT_AGENT_CATEGORY)}>
          <FileText size={16} />
          {t("agent.openArticles")}
        </button>
        <button type="button" onClick={() => onOpenCompetitors("monitoring")}>
          <Radar size={16} />
          {t("agent.openTeardown")}
        </button>
      </div>
    </div>
  );
}

function AgentPage({
  locale,
  onOpenCompetitors,
  onOpenResearch,
  onOpenSettings,
  t,
}: {
  onOpenCompetitors: (tab: CompetitorTab) => void;
  onOpenResearch: (source: ResearchSource, category?: string, openHistory?: boolean) => void;
  onOpenSettings: () => void;
} & LocalizedProps) {
  const [prompt, setPrompt] = useState(t("agent.defaultPrompt"));
  const [artifactPrompt, setArtifactPrompt] = useState(t("agent.defaultPrompt"));
  const [artifactTab, setArtifactTab] = useState<AgentArtifactTab>("market");
  const [artifactGeneratedAt, setArtifactGeneratedAt] = useState(() => new Date().toISOString());
  const artifactPayload = useMemo(
    () => buildAgentArtifactPayload(artifactPrompt, artifactGeneratedAt),
    [artifactPrompt, artifactGeneratedAt],
  );
  const artifactJson = JSON.stringify(artifactPayload, null, 2);
  const sourceChips = ["Amazon", "Reddit", "TikTok", "YouTube", t("source.articles"), "Google Search"];
  const skills: Array<{
    id: AgentSkillId;
    title: string;
    body: string;
    icon: ReactNode;
    sources: string[];
    actionLabel: string;
    action: () => void;
  }> = [
    {
      id: "market_trend",
      title: t("agent.skill.marketTrend"),
      body: t("agent.skill.marketTrendBody"),
      icon: <BarChart3 size={18} />,
      sources: ["Reddit", "Amazon"],
      actionLabel: t("agent.openIntegrated"),
      action: () => onOpenResearch("combined", DEFAULT_AGENT_CATEGORY),
    },
    {
      id: "breakout_discovery",
      title: t("agent.skill.breakoutDiscovery"),
      body: t("agent.skill.breakoutDiscoveryBody"),
      icon: <Target size={18} />,
      sources: ["Amazon", "TikTok"],
      actionLabel: t("agent.openDiscovery"),
      action: () => onOpenCompetitors("discovery"),
    },
    {
      id: "breakout_teardown",
      title: t("agent.skill.breakoutTeardown"),
      body: t("agent.skill.breakoutTeardownBody"),
      icon: <Radar size={18} />,
      sources: ["Amazon", "Reddit", t("source.articles")],
      actionLabel: t("agent.openTeardown"),
      action: () => onOpenCompetitors("monitoring"),
    },
    {
      id: "amazon_reviews",
      title: t("agent.skill.amazonReviews"),
      body: t("agent.skill.amazonReviewsBody"),
      icon: <ShoppingBag size={18} />,
      sources: ["Amazon"],
      actionLabel: t("agent.openAmazon"),
      action: () => onOpenResearch("amazon", DEFAULT_AGENT_CATEGORY),
    },
    {
      id: "tiktok_validation",
      title: t("agent.skill.tiktokValidation"),
      body: t("agent.skill.tiktokValidationBody"),
      icon: <Megaphone size={18} />,
      sources: ["TikTok"],
      actionLabel: t("agent.openTikTok"),
      action: () => onOpenResearch("tiktok", DEFAULT_AGENT_CATEGORY),
    },
    {
      id: "article_rankings",
      title: t("agent.skill.articleRankings"),
      body: t("agent.skill.articleRankingsBody"),
      icon: <FileText size={18} />,
      sources: [t("source.articles"), "Google Search"],
      actionLabel: t("agent.openArticles"),
      action: () => onOpenResearch("articles", DEFAULT_AGENT_CATEGORY),
    },
  ];
  const artifactTabs: Array<{ id: AgentArtifactTab; label: string }> = [
    { id: "market", label: t("agent.tab.market") },
    { id: "draft", label: t("agent.tab.draft") },
    { id: "output", label: t("agent.tab.output") },
  ];
  const marketCards = [
    {
      title: t("agent.market.amazon"),
      body: t("agent.market.amazonBody"),
      icon: <ShoppingBag size={17} />,
      actionLabel: t("agent.openAmazon"),
      action: () => onOpenResearch("amazon", DEFAULT_AGENT_CATEGORY),
    },
    {
      title: t("agent.market.reddit"),
      body: t("agent.market.redditBody"),
      icon: <MessageSquare size={17} />,
      actionLabel: t("agent.openReddit"),
      action: () => onOpenResearch("reddit", DEFAULT_AGENT_CATEGORY),
    },
    {
      title: t("agent.market.tiktok"),
      body: t("agent.market.tiktokBody"),
      icon: <Megaphone size={17} />,
      actionLabel: t("agent.openTikTok"),
      action: () => onOpenResearch("tiktok", DEFAULT_AGENT_CATEGORY),
    },
    {
      title: t("agent.market.articles"),
      body: t("agent.market.articlesBody"),
      icon: <FileText size={17} />,
      actionLabel: t("agent.openArticles"),
      action: () => onOpenResearch("articles", DEFAULT_AGENT_CATEGORY),
    },
  ];

  function generateArtifact(event?: FormEvent) {
    event?.preventDefault();
    setArtifactPrompt(prompt.trim() || t("agent.defaultPrompt"));
    setArtifactGeneratedAt(new Date().toISOString());
    setArtifactTab("draft");
  }

  function applyPromptPreset(value: string) {
    setPrompt(value);
    setArtifactPrompt(value);
    setArtifactGeneratedAt(new Date().toISOString());
    setArtifactTab("market");
  }

  return (
    <div className="page agent-page">
      <section className="agent-hero">
        <div className="agent-hero-copy">
          <p className="eyebrow">{t("agent.eyebrow")}</p>
          <h2>{t("agent.title")}</h2>
          <p>{t("agent.description")}</p>
          <div className="agent-source-strip">
            {sourceChips.map((item) => <span key={item}>{item}</span>)}
          </div>
        </div>
        <form className="agent-composer" onSubmit={generateArtifact}>
          <textarea
            aria-label={t("agent.promptLabel")}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={t("agent.promptPlaceholder")}
            rows={4}
          />
          <div className="agent-prompt-actions">
            <button type="button" onClick={() => applyPromptPreset(t("agent.preset.market"))}>
              {t("agent.preset.marketLabel")}
            </button>
            <button type="button" onClick={() => applyPromptPreset(t("agent.preset.competitor"))}>
              {t("agent.preset.competitorLabel")}
            </button>
            <button type="button" onClick={() => applyPromptPreset(t("agent.preset.review"))}>
              {t("agent.preset.reviewLabel")}
            </button>
            <button type="submit">
              <Sparkles size={16} />
              {t("agent.generateArtifact")}
            </button>
          </div>
        </form>
      </section>

      <section className="agent-artifact-shell">
        <aside className="artifact-chat-panel">
          <div className="artifact-chat-bubble">{artifactPrompt}</div>
          <div className="artifact-tool-line">
            <Link2 size={16} />
            <span>{formatMessage(t("agent.toolCalls"), { count: 7 })}</span>
          </div>
          <div className="artifact-chat-result">
            <strong>{t("agent.artifactReady")}</strong>
            <p>{t("agent.artifactReadyBody")}</p>
          </div>
          <div className="artifact-action-grid">
            <button type="button" onClick={() => onOpenResearch("combined", DEFAULT_AGENT_CATEGORY)}>
              <Sparkles size={16} />
              {t("agent.openIntegrated")}
            </button>
            <button type="button" onClick={() => onOpenCompetitors("discovery")}>
              <Target size={16} />
              {t("agent.openDiscovery")}
            </button>
            <button type="button" onClick={() => onOpenResearch("articles", DEFAULT_AGENT_CATEGORY)}>
              <FileText size={16} />
              {t("agent.openArticles")}
            </button>
            <button type="button" onClick={() => onOpenResearch("combined", DEFAULT_AGENT_CATEGORY, true)}>
              <FolderOpen size={16} />
              {t("history.open")}
            </button>
          </div>
        </aside>

        <section className="artifact-viewer">
          <div className="artifact-viewer-head">
            <div>
              <p className="eyebrow">{t("agent.artifactEyebrow")}</p>
              <h3>{t("agent.artifactTitle")}</h3>
              <span>{shortDate(artifactGeneratedAt, locale)}</span>
            </div>
            <div className="artifact-viewer-actions">
              <button
                type="button"
                onClick={() => downloadText("hsia-minimizer-bra-market-artifact.json", artifactJson, "application/json")}
                title={t("agent.downloadArtifact")}
              >
                <Download size={16} />
              </button>
              <button type="button" onClick={onOpenSettings} title={t("nav.settings")}>
                <Settings size={16} />
              </button>
            </div>
          </div>
          <div className="artifact-tabs" role="tablist" aria-label={t("agent.artifactTabs")}>
            {artifactTabs.map((tab) => (
              <button
                className={artifactTab === tab.id ? "active" : ""}
                key={tab.id}
                type="button"
                onClick={() => setArtifactTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {artifactTab === "market" ? (
            <div className="artifact-market-grid">
              {marketCards.map((card) => (
                <article className="artifact-market-card" key={card.title}>
                  <div>
                    <span>{card.icon}</span>
                    <h4>{card.title}</h4>
                  </div>
                  <p>{card.body}</p>
                  <button type="button" onClick={card.action}>{card.actionLabel}</button>
                </article>
              ))}
              <article className="artifact-market-card emphasis">
                <div>
                  <span><Target size={17} /></span>
                  <h4>{t("agent.market.competitor")}</h4>
                </div>
                <p>{t("agent.market.competitorBody")}</p>
                <button type="button" onClick={() => onOpenCompetitors("discovery")}>{t("agent.openDiscovery")}</button>
              </article>
              <article className="artifact-market-card emphasis">
                <div>
                  <span><Radar size={17} /></span>
                  <h4>{t("agent.market.teardown")}</h4>
                </div>
                <p>{t("agent.market.teardownBody")}</p>
                <button type="button" onClick={() => onOpenCompetitors("monitoring")}>{t("agent.openTeardown")}</button>
              </article>
            </div>
          ) : null}

          {artifactTab === "draft" ? (
            <div className="artifact-draft">
              <div className="artifact-brief-grid">
                {Object.entries({
                  [t("competitors.briefBrand")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.brand,
                  [t("competitors.briefMarket")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.market,
                  [t("competitors.briefCategory")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.category,
                  [t("competitors.briefKeywords")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.coreKeywords,
                  [t("competitors.briefTargetPrice")]: `${DEFAULT_COMPETITOR_DISCOVERY_BRIEF.targetPriceBand} / ${DEFAULT_COMPETITOR_DISCOVERY_BRIEF.upgradePriceBand}`,
                  [t("competitors.briefSizes")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.coreSizes,
                  [t("competitors.briefUsers")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.coreUsers,
                  [t("competitors.briefDirection")]: DEFAULT_COMPETITOR_DISCOVERY_BRIEF.brandDirection,
                }).map(([label, value]) => (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <div className="artifact-task-list">
                <article>
                  <Search size={16} />
                  <div>
                    <h4>{t("agent.task.discovery")}</h4>
                    <p>{t("agent.task.discoveryBody")}</p>
                  </div>
                </article>
                <article>
                  <ShieldAlert size={16} />
                  <div>
                    <h4>{t("agent.task.validation")}</h4>
                    <p>{t("agent.task.validationBody")}</p>
                  </div>
                </article>
                <article>
                  <Lightbulb size={16} />
                  <div>
                    <h4>{t("agent.task.output")}</h4>
                    <p>{t("agent.task.outputBody")}</p>
                  </div>
                </article>
              </div>
            </div>
          ) : null}

          {artifactTab === "output" ? (
            <pre className="artifact-json"><code>{artifactJson}</code></pre>
          ) : null}
        </section>
      </section>

      <section className="agent-skill-grid" aria-label={t("agent.skills")}>
        {skills.map((skill) => (
          <article className="agent-skill-card" key={skill.id}>
            <div className="agent-skill-icon">{skill.icon}</div>
            <h3>{skill.title}</h3>
            <p>{skill.body}</p>
            <div className="agent-skill-sources">
              {skill.sources.map((source) => <span key={`${skill.id}-${source}`}>{source}</span>)}
            </div>
            <button type="button" onClick={skill.action}>
              {skill.actionLabel}
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}

function buildAgentArtifactPayload(prompt: string, generatedAt: string) {
  return {
    artifact_type: "market_research_task",
    title: "Hsia US minimizer bra market research",
    prompt,
    generated_at: generatedAt,
    brand_brief: DEFAULT_COMPETITOR_DISCOVERY_BRIEF,
    data_sources: [
      { name: "Amazon product pages", route: "Research > Amazon Products", status: "connected" },
      { name: "Amazon search results", route: "Breakout Competitors > Discovery", status: "connected" },
      { name: "Amazon user reviews", route: "Research > Amazon Products / Breakout Teardown", status: "connected" },
      { name: "TikTok / TikTok Shop related content", route: "Research > TikTok Social / Competitor TikTok validation", status: "connected" },
      { name: "US media reviews", route: "Research > Media / Ranking Articles", status: "connected" },
      { name: "Competitor official sites", route: "Breakout Competitors > Teardown web sources", status: "connected" },
      { name: "Google search results", route: "Research > Article discovery", status: "connected" },
      { name: "Public ranking articles", route: "Research > Media / Ranking Articles", status: "connected" },
    ],
    tasks: [
      "Generate integrated market insight from Reddit and Amazon evidence",
      "Discover breakout competitors from Amazon evidence gates",
      "Cross-validate candidates with TikTok videos and detail-page comments",
      "Read media reviews, public rankings, and accessible reports",
      "Confirm competitors into teardown and produce R&D learnings",
    ],
    outputs: [
      "market_insight_brief",
      "breakout_competitor_candidates",
      "tiktok_validation_cards",
      "article_authority_evidence",
      "competitor_teardown_report",
    ],
  };
}

function CompetitorsPage({ launchIntent, locale, t }: {
  launchIntent?: CompetitorLaunchIntent | null;
} & LocalizedProps) {
  const [initialSession] = useState<CompetitorSession>(() => loadCompetitorSession());
  const [activeCompetitorTab, setActiveCompetitorTab] = useState<CompetitorTab>(initialSession.activeCompetitorTab);
  const [discoveryBrief, setDiscoveryBrief] = useState<CompetitorDiscoveryBrief>(initialSession.discoveryBrief);
  const [scoreWeights, setScoreWeights] = useState<CompetitorScoreWeights>(initialSession.scoreWeights);
  const [productLimit, setProductLimit] = useState(initialSession.productLimit);
  const [bypassCache, setBypassCache] = useState(initialSession.bypassCache);
  const [discoveryReport, setDiscoveryReport] = useState<CompetitorDiscoveryReport | null>(initialSession.discoveryReport);
  const [monitoringCandidates, setMonitoringCandidates] = useState<CompetitorCandidate[]>(initialSession.monitoringCandidates);
  const [deepDiveReports, setDeepDiveReports] = useState<Record<string, CompetitorDeepDiveReport>>(initialSession.deepDiveReports);
  const [selectedDeepDiveKey, setSelectedDeepDiveKey] = useState(initialSession.selectedDeepDiveKey);
  const [deepDivePreset, setDeepDivePreset] = useState<CompetitorDeepDivePreset>(initialSession.deepDivePreset);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [deepDiveLoadingKey, setDeepDiveLoadingKey] = useState<string | null>(null);
  const [deepDiveError, setDeepDiveError] = useState<string | null>(null);
  const [deepDiveMessage, setDeepDiveMessage] = useState<string | null>(null);
  const [tiktokVerificationLoadingKey, setTikTokVerificationLoadingKey] = useState<string | null>(null);
  const [tiktokVerificationMessage, setTikTokVerificationMessage] = useState<string | null>(null);
  const deepDiveAbortRef = useRef<AbortController | null>(null);
  const deepDiveRunIdRef = useRef<string | null>(null);

  useEffect(() => {
    saveCompetitorSession({
      activeCompetitorTab,
      discoveryBrief,
      scoreWeights,
      productLimit,
      bypassCache,
      discoveryReport,
      monitoringCandidates,
      deepDiveReports,
      selectedDeepDiveKey,
      deepDivePreset,
    });
  }, [
    activeCompetitorTab,
    discoveryBrief,
    scoreWeights,
    productLimit,
    bypassCache,
    discoveryReport,
    monitoringCandidates,
    deepDiveReports,
    selectedDeepDiveKey,
    deepDivePreset,
  ]);

  useEffect(() => {
    if (!launchIntent) return;
    setActiveCompetitorTab(launchIntent.tab);
  }, [launchIntent?.nonce, launchIntent?.tab]);

  useEffect(() => () => cancelDeepDive(), []);

  function updateDiscoveryBrief(field: keyof CompetitorDiscoveryBrief, value: string) {
    setDiscoveryBrief((current) => ({ ...current, [field]: value }));
  }

  function updateScoreWeight(field: keyof CompetitorScoreWeights, value: number) {
    setScoreWeights((current) => ({
      ...current,
      [field]: Number(boundedNumber(value, current[field], 0, 3).toFixed(2)),
    }));
  }

  async function runDiscovery(event?: FormEvent) {
    event?.preventDefault();
    const normalizedBrief = normalizeCompetitorBrief(discoveryBrief);
    const normalizedScoreWeights = normalizeCompetitorScoreWeights(scoreWeights);
    const normalizedProductLimit = boundedInteger(productLimit, 20, 1, 100);
    setDiscoveryBrief(normalizedBrief);
    setScoreWeights(normalizedScoreWeights);
    setProductLimit(normalizedProductLimit);
    setDiscoveryLoading(true);
    setDiscoveryError(null);
    try {
      const report = await api.discoverCompetitors({
        brief: normalizedBrief,
        scoreWeights: normalizedScoreWeights,
        limit: normalizedProductLimit,
        amazonKeywordLimit: 8,
        bypassCache,
      });
      setDiscoveryReport(report);
    } catch (err) {
      setDiscoveryError(err instanceof Error ? err.message : t("competitors.discoveryError"));
    } finally {
      setDiscoveryLoading(false);
    }
  }

  function isMonitoringCandidate(candidate: CompetitorCandidate): boolean {
    const key = competitorCandidateKey(candidate);
    return monitoringCandidates.some((item) => competitorCandidateKey(item) === key);
  }

  function addMonitoringCandidate(candidate: CompetitorCandidate) {
    setMonitoringCandidates((current) => {
      const key = competitorCandidateKey(candidate);
      if (current.some((item) => competitorCandidateKey(item) === key)) return current;
      return [...current, candidate];
    });
  }

  function cancelDeepDive(message?: string) {
    const runId = deepDiveRunIdRef.current;
    deepDiveAbortRef.current?.abort();
    deepDiveAbortRef.current = null;
    deepDiveRunIdRef.current = null;
    if (runId) {
      void api.cancelCompetitorAnalysis({ runId }).catch(() => {
        // The browser-side abort already stopped the UI; backend cancellation is best effort.
      });
    }
    setDeepDiveLoadingKey(null);
    if (message) {
      setDeepDiveMessage(message);
    }
  }

  function removeMonitoringCandidate(candidate: CompetitorCandidate) {
    const key = competitorCandidateKey(candidate);
    if (deepDiveLoadingKey === key) {
      cancelDeepDive(t("competitors.deepDiveStoppedAfterRemove"));
    }
    setMonitoringCandidates((current) => current.filter((item) => competitorCandidateKey(item) !== key));
    setDeepDiveReports((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    if (selectedDeepDiveKey === key) {
      setSelectedDeepDiveKey("");
    }
  }

  function replaceCompetitorCandidate(updatedCandidate: CompetitorCandidate) {
    const key = competitorCandidateKey(updatedCandidate);
    setDiscoveryReport((current) => current ? {
      ...current,
      candidates: current.candidates.map((candidate) => (
        competitorCandidateKey(candidate) === key ? updatedCandidate : candidate
      )),
    } : current);
    setMonitoringCandidates((current) => current.map((candidate) => (
      competitorCandidateKey(candidate) === key ? updatedCandidate : candidate
    )));
  }

  async function verifyCandidateOnTikTok(candidate: CompetitorCandidate) {
    const key = competitorCandidateKey(candidate);
    setTikTokVerificationLoadingKey(key);
    setTikTokVerificationMessage(null);
    setDeepDiveError(null);
    try {
      const result = await api.verifyCompetitorTikTok({
        candidate,
        brief: discoveryBrief,
        scoreWeights,
        limit: 8,
        tiktokCommentsPerVideo: 8,
        bypassCache,
      });
      replaceCompetitorCandidate(result.candidate);
      setTikTokVerificationMessage(formatMessage(t("competitors.tiktokValidated"), {
        label: result.validation.label,
        videos: result.validation.video_count,
        comments: result.validation.comment_samples,
      }));
    } catch (err) {
      setDeepDiveError(err instanceof Error ? err.message : t("competitors.tiktokValidationError"));
    } finally {
      setTikTokVerificationLoadingKey(null);
    }
  }

  async function runDeepDive(candidate: CompetitorCandidate) {
    const key = competitorCandidateKey(candidate);
    if (deepDiveLoadingKey) {
      cancelDeepDive();
    }
    const runId = createRunId("competitor");
    const controller = new AbortController();
    deepDiveRunIdRef.current = runId;
    deepDiveAbortRef.current = controller;
    setDeepDiveLoadingKey(key);
    setDeepDiveError(null);
    setDeepDiveMessage(null);
    setSelectedDeepDiveKey(key);
    const preset = COMPETITOR_DEEP_DIVE_PRESETS[deepDivePreset];
    try {
      const report = await api.analyzeCompetitor({
        candidate,
        runId,
        category: discoveryBrief.category,
        brief: discoveryBrief,
        redditLimit: preset.redditLimit,
        redditDetailLimit: preset.redditDetailLimit,
        redditCommentsPerPost: preset.redditCommentsPerPost,
        amazonReviewLimit: preset.amazonReviewLimit,
        webCandidateLimit: preset.webCandidateLimit,
        aiReviewLimit: preset.aiReviewLimit,
        aiRedditPostLimit: preset.aiRedditPostLimit,
        timeRange: "all",
        mode: "auto",
        useLlm: true,
        locale,
        bypassCache,
      }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDeepDiveReports((current) => ({ ...current, [key]: report }));
    } catch (err) {
      if (controller.signal.aborted) {
        setDeepDiveMessage(t("competitors.deepDiveStopped"));
        return;
      }
      setDeepDiveError(err instanceof Error ? err.message : t("competitors.deepDiveError"));
    } finally {
      if (deepDiveRunIdRef.current === runId) {
        deepDiveAbortRef.current = null;
        deepDiveRunIdRef.current = null;
        setDeepDiveLoadingKey(null);
      }
    }
  }

  const status = discoveryReport
    ? formatMessage(t("competitors.statusWithCandidates"), { count: discoveryReport.summary.candidate_count })
    : t("competitors.ready");
  const collectionSummary = discoveryReport
    ? formatMessage(t("competitors.collectionSummaryWithData"), {
      products: discoveryReport.source.collected_items_count,
      candidates: discoveryReport.summary.candidate_count,
    })
    : t("competitors.collectionSummaryDefault");
  const scoreWeightItems = COMPETITOR_SCORE_WEIGHT_KEYS.map((key) => ({
    key,
    label: t(`competitors.weight.${key}`, key),
  }));
  const activeDeepDivePreset = COMPETITOR_DEEP_DIVE_PRESETS[deepDivePreset];
  const selectedDeepDiveReport = selectedDeepDiveKey ? deepDiveReports[selectedDeepDiveKey] : null;
  const discoveryBuckets = discoveryReport ? [
    {
      key: "strong_breakout",
      title: t("competitors.bucket.strong"),
      subtitle: t("competitors.bucket.strongSubtitle"),
      candidates: discoveryReport.candidates.filter((candidate) => candidate.breakout_tier === "strong_breakout"),
    },
    {
      key: "needs_tiktok_validation",
      title: t("competitors.bucket.tiktok"),
      subtitle: t("competitors.bucket.tiktokSubtitle"),
      candidates: discoveryReport.candidates.filter((candidate) => candidate.breakout_tier === "needs_tiktok_validation" || candidate.breakout_tier === "watchlist"),
    },
    {
      key: "low_evidence",
      title: t("competitors.bucket.low"),
      subtitle: t("competitors.bucket.lowSubtitle"),
      candidates: discoveryReport.candidates.filter((candidate) => !candidate.breakout_tier || candidate.breakout_tier === "low_evidence"),
    },
  ].filter((bucket) => bucket.candidates.length) : [];

  return (
    <div className="page competitors-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">{t("competitors.eyebrow")}</p>
          <h2>{t("competitors.title")}</h2>
          <p>{t("competitors.description")}</p>
        </div>
        <div className="status-pill">{status}</div>
      </header>

      <div className="source-tabs" role="tablist" aria-label="Competitors">
        <button
          className={activeCompetitorTab === "discovery" ? "active" : ""}
          type="button"
          onClick={() => setActiveCompetitorTab("discovery")}
        >
          <Search size={16} />
          {t("competitors.discoveryTab")}
        </button>
        <button
          className={activeCompetitorTab === "monitoring" ? "active" : ""}
          type="button"
          onClick={() => setActiveCompetitorTab("monitoring")}
        >
          <Radar size={16} />
          {t("competitors.monitoringTab")}
        </button>
      </div>

      {activeCompetitorTab === "discovery" ? (
        <form className="competitor-brief-panel" onSubmit={runDiscovery} noValidate>
          <div className="competitor-brief-grid">
            <label className="brief-field">
              <span>{t("competitors.briefBrand")}</span>
              <input
                value={discoveryBrief.brand}
                onChange={(event) => updateDiscoveryBrief("brand", event.target.value)}
              />
            </label>
            <label className="brief-field">
              <span>{t("competitors.briefMarket")}</span>
              <input
                value={discoveryBrief.market}
                onChange={(event) => updateDiscoveryBrief("market", event.target.value)}
              />
            </label>
            <label className="brief-field">
              <span>{t("competitors.briefCategory")}</span>
              <input
                value={discoveryBrief.category}
                onChange={(event) => updateDiscoveryBrief("category", event.target.value)}
              />
            </label>
            <label className="brief-field wide">
              <span>{t("competitors.briefKeywords")}</span>
              <textarea
                value={discoveryBrief.coreKeywords}
                onChange={(event) => updateDiscoveryBrief("coreKeywords", event.target.value)}
                rows={3}
              />
            </label>
            <label className="brief-field">
              <span>{t("competitors.briefTargetPrice")}</span>
              <input
                value={discoveryBrief.targetPriceBand}
                onChange={(event) => updateDiscoveryBrief("targetPriceBand", event.target.value)}
              />
            </label>
            <label className="brief-field">
              <span>{t("competitors.briefUpgradePrice")}</span>
              <input
                value={discoveryBrief.upgradePriceBand}
                onChange={(event) => updateDiscoveryBrief("upgradePriceBand", event.target.value)}
              />
            </label>
            <label className="brief-field">
              <span>{t("competitors.briefSizes")}</span>
              <input
                value={discoveryBrief.coreSizes}
                onChange={(event) => updateDiscoveryBrief("coreSizes", event.target.value)}
              />
            </label>
            <label className="brief-field wide">
              <span>{t("competitors.briefUsers")}</span>
              <textarea
                value={discoveryBrief.coreUsers}
                onChange={(event) => updateDiscoveryBrief("coreUsers", event.target.value)}
                rows={3}
              />
            </label>
            <label className="brief-field wide">
              <span>{t("competitors.briefDirection")}</span>
              <textarea
                value={discoveryBrief.brandDirection}
                onChange={(event) => updateDiscoveryBrief("brandDirection", event.target.value)}
                rows={3}
              />
            </label>
          </div>
          <div className="competitor-score-panel">
            <div className="competitor-score-head">
              <span>{t("competitors.scoreWeightsTitle")}</span>
              <button className="score-reset-button" type="button" onClick={() => setScoreWeights(DEFAULT_COMPETITOR_SCORE_WEIGHTS)}>
                <RefreshCw size={14} />
                {t("competitors.resetWeights")}
              </button>
            </div>
            <div className="score-weight-grid">
              {scoreWeightItems.map((item) => (
                <label className="score-weight-field" key={item.key}>
                  <span>
                    {item.label}
                    <b>{scoreWeights[item.key].toFixed(2)}x</b>
                  </span>
                  <input
                    max={3}
                    min={0}
                    onChange={(event) => updateScoreWeight(item.key, Number(event.target.value))}
                    step={0.25}
                    type="range"
                    value={scoreWeights[item.key]}
                  />
                </label>
              ))}
            </div>
          </div>
          <div className="competitor-brief-actions">
          <label className="compact-number-field">
            <span>{t("competitors.productLimit")}</span>
            <input
              type="number"
              min={1}
              max={100}
              step={1}
              value={productLimit}
              onChange={(event) => setProductLimit(Number(event.target.value))}
            />
          </label>
          <div className="collection-summary">
            <Radar size={16} />
            <span>{collectionSummary}</span>
          </div>
          <label className="cache-toggle" title={t("research.bypassCacheNote")}>
            <input
              type="checkbox"
              checked={bypassCache}
              onChange={(event) => setBypassCache(event.target.checked)}
            />
            <span>{t("research.bypassCache")}</span>
          </label>
          <button type="submit" disabled={discoveryLoading}>
            {discoveryLoading ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
            {discoveryLoading ? t("competitors.discoveryRunning") : t("competitors.runDiscovery")}
          </button>
          </div>
        </form>
      ) : null}

      {discoveryError ? <div className="alert danger">{discoveryError}</div> : null}
      {discoveryLoading ? <LoadingPanel text={t("competitors.discoveryLoading")} /> : null}

      {!discoveryLoading && activeCompetitorTab === "discovery" ? (
        <section className="panel wide competitor-mode-panel">
          <PanelTitle title={t("competitors.discoveryTitle")} subtitle={t("competitors.discoverySubtitle")} />
          <div className="competitor-mode-grid">
            <article className="list-card">
              <h4>{t("competitors.discoveryInputs")}</h4>
              <p>{t("competitors.discoveryInputsValue")}</p>
            </article>
            <article className="list-card">
              <h4>{t("competitors.discoveryOutput")}</h4>
              <p>{t("competitors.discoveryOutputValue")}</p>
            </article>
            <article className="list-card">
              <h4>{t("competitors.discoverySourceTitle")}</h4>
              <p>{t("competitors.discoverySourceBody")}</p>
            </article>
          </div>
        </section>
      ) : null}

      {!discoveryLoading && activeCompetitorTab === "monitoring" && !monitoringCandidates.length ? (
        <section className="empty-state competitor-empty-state">
          <Radar size={36} />
          <h3>{t("competitors.monitoringEmptyTitle")}</h3>
          <p>{t("competitors.monitoringEmptyBody")}</p>
          <button type="button" onClick={() => setActiveCompetitorTab("discovery")}>
            <Search size={17} />
            {t("competitors.goDiscovery")}
          </button>
        </section>
      ) : null}

      {!discoveryLoading && activeCompetitorTab === "discovery" && discoveryReport ? (
        <section className="panel wide competitor-results-panel">
          <PanelTitle
            title={t("competitors.resultsTitle")}
            subtitle={formatMessage(t("competitors.resultsSubtitle"), {
              candidates: discoveryReport.summary.candidate_count,
              source: discoveryReport.source.source_name,
            })}
          />
          <div className="competitor-audit-grid">
            <div>
              <span>{t("competitors.sourceStatus")}</span>
              <strong>{discoveryReport.source.status}</strong>
              <p>{discoveryReport.source.next_action}</p>
            </div>
            <div>
              <span>{t("competitors.collectedProducts")}</span>
              <strong>{formatInteger(discoveryReport.source.collected_items_count)}</strong>
              <p>{formatMessage(t("competitors.queryCount"), { count: discoveryReport.data_volume.query_count })}</p>
            </div>
            <div>
              <span>{t("competitors.filteredProducts")}</span>
              <strong>{formatInteger(discoveryReport.data_volume.excluded_products || 0)}</strong>
              <p>{formatMessage(t("competitors.filteredProductsNote"), { count: discoveryReport.data_volume.excluded_products || 0 })}</p>
            </div>
            <div>
              <span>{t("competitors.strongBreakout")}</span>
              <strong>{formatInteger(discoveryReport.summary.strong_breakout || 0)}</strong>
              <p>{formatMessage(t("competitors.needTikTokValidation"), { count: discoveryReport.summary.needs_tiktok_validation || 0 })}</p>
            </div>
          </div>
          {discoveryReport.warnings.length ? (
            <div className="alert subtle">{discoveryReport.warnings.join(" ")}</div>
          ) : null}
          <div className="competitor-bucket-list">
            {discoveryBuckets.map((bucket) => (
              <section className="competitor-bucket-section" key={bucket.key}>
                <div className="competitor-bucket-head">
                  <div>
                    <h4>{bucket.title}</h4>
                    <p>{bucket.subtitle}</p>
                  </div>
                  <span>{bucket.candidates.length}</span>
                </div>
                <div className="competitor-result-list">
                  {bucket.candidates.map((candidate, index) => {
                    const candidateKey = competitorCandidateKey(candidate);
                    return (
                      <CompetitorCandidateCard
                        actionDisabled={isMonitoringCandidate(candidate)}
                        actionLabel={isMonitoringCandidate(candidate) ? t("competitors.addedToMonitoring") : t("competitors.addToTeardown")}
                        candidate={candidate}
                        key={`${candidate.id}-${index}`}
                        onAction={() => addMonitoringCandidate(candidate)}
                        onTikTokAction={() => verifyCandidateOnTikTok(candidate)}
                        t={t}
                        tiktokActionLabel={candidate.tiktok_validation ? t("competitors.revalidateTikTok") : t("competitors.validateTikTok")}
                        tiktokActionLoading={tiktokVerificationLoadingKey === candidateKey}
                      />
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </section>
      ) : null}

      {!discoveryLoading && activeCompetitorTab === "monitoring" && monitoringCandidates.length ? (
        <section className="panel wide competitor-results-panel">
          <PanelTitle
            title={t("competitors.monitoringResultsTitle")}
            subtitle={formatMessage(t("competitors.monitoringResultsSubtitle"), {
              count: monitoringCandidates.length,
            })}
          />
          <div className="deep-dive-preset-panel">
            <div>
              <strong>{t("competitors.deepDivePreset")}</strong>
              <p>{formatMessage(t("competitors.deepDivePresetSummary"), {
                amazon: activeDeepDivePreset.amazonReviewLimit,
                reddit: activeDeepDivePreset.redditLimit,
                detail: activeDeepDivePreset.redditDetailLimit,
                comments: activeDeepDivePreset.redditCommentsPerPost,
                web: activeDeepDivePreset.webCandidateLimit,
                aiReviews: activeDeepDivePreset.aiReviewLimit,
                aiPosts: activeDeepDivePreset.aiRedditPostLimit,
              })}</p>
            </div>
            <div className="deep-dive-preset-buttons" role="group" aria-label={t("competitors.deepDivePreset")}>
              {COMPETITOR_DEEP_DIVE_PRESET_KEYS.map((presetKey) => (
                <button
                  aria-pressed={deepDivePreset === presetKey}
                  className={deepDivePreset === presetKey ? "active" : ""}
                  disabled={Boolean(deepDiveLoadingKey)}
                  key={presetKey}
                  onClick={() => setDeepDivePreset(presetKey)}
                  type="button"
                >
                  {t(`competitors.preset.${presetKey}`)}
                </button>
              ))}
            </div>
          </div>
          <div className="competitor-result-list">
            {monitoringCandidates.map((candidate, index) => {
              const candidateKey = competitorCandidateKey(candidate);
              return (
                <CompetitorCandidateCard
                  actionLabel={t("competitors.removeFromTeardown")}
                  candidate={candidate}
                  key={`${candidate.id}-${index}`}
                  onAction={() => removeMonitoringCandidate(candidate)}
                  onTikTokAction={() => verifyCandidateOnTikTok(candidate)}
                  secondaryActionIcon={deepDiveLoadingKey === candidateKey ? "stop" : "sparkles"}
                  secondaryActionLabel={deepDiveLoadingKey === candidateKey ? t("competitors.stopDeepDive") : t("competitors.runDeepDive")}
                  onSecondaryAction={() => (
                    deepDiveLoadingKey === candidateKey
                      ? cancelDeepDive(t("competitors.deepDiveStopped"))
                      : runDeepDive(candidate)
                  )}
                  t={t}
                  tiktokActionLabel={candidate.tiktok_validation ? t("competitors.revalidateTikTok") : t("competitors.validateTikTok")}
                  tiktokActionLoading={tiktokVerificationLoadingKey === candidateKey}
                  variant="monitoring"
                />
              );
            })}
          </div>
        </section>
      ) : null}

      {deepDiveError ? <div className="alert danger">{deepDiveError}</div> : null}
      {deepDiveMessage ? <div className="alert subtle">{deepDiveMessage}</div> : null}
      {tiktokVerificationMessage ? <div className="alert subtle">{tiktokVerificationMessage}</div> : null}
      {deepDiveLoadingKey ? (
        <section className="panel wide competitor-stop-panel">
          <LoadingPanel text={t("competitors.deepDiveLoading")} />
          <button type="button" onClick={() => cancelDeepDive(t("competitors.deepDiveStopped"))}>
            <Square size={15} />
            {t("competitors.stopDeepDive")}
          </button>
        </section>
      ) : null}
      {!deepDiveLoadingKey && selectedDeepDiveReport ? (
        <CompetitorDeepDiveView report={selectedDeepDiveReport} t={t} />
      ) : null}

      {activeCompetitorTab === "monitoring" && monitoringCandidates.length ? (
        <section className="panel wide competitor-next-panel">
        <PanelTitle title={t("competitors.nextTitle")} subtitle={t("competitors.nextSubtitle")} />
        <div className="competitor-next-grid">
          <article className="list-card">
            <h4>{t("competitors.seedTitle")}</h4>
            <p>{t("competitors.seedBody")}</p>
          </article>
          <article className="list-card">
            <h4>{t("competitors.schemaTitle")}</h4>
            <p>{t("competitors.schemaBody")}</p>
          </article>
          <article className="list-card">
            <h4>{t("competitors.reviewTitle")}</h4>
            <p>{t("competitors.reviewBody")}</p>
          </article>
        </div>
      </section>
      ) : null}
    </div>
  );
}

function competitorCandidateKey(candidate: CompetitorCandidate): string {
  return candidate.id || candidate.asin || candidate.product_url || candidate.title;
}

function createRunId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function competitorScoreBreakdownLabel(key: string, t: Translator): string {
  if (key === "base") return t("competitors.weight.base");
  return t(`competitors.weight.${key}`, key);
}

function CompetitorCandidateCard({
  actionDisabled = false,
  actionLabel,
  candidate,
  onAction,
  onSecondaryAction,
  onTikTokAction,
  secondaryActionIcon = "sparkles",
  secondaryActionLabel,
  secondaryActionLoading = false,
  t,
  tiktokActionLabel,
  tiktokActionLoading = false,
  variant = "discovery",
}: {
  actionDisabled?: boolean;
  actionLabel: string;
  candidate: CompetitorCandidate;
  onAction: () => void;
  onSecondaryAction?: () => void;
  onTikTokAction?: () => void;
  secondaryActionIcon?: "sparkles" | "stop";
  secondaryActionLabel?: string;
  secondaryActionLoading?: boolean;
  t: Translator;
  tiktokActionLabel?: string;
  tiktokActionLoading?: boolean;
  variant?: "discovery" | "monitoring";
}) {
  const tiktokValidation = candidate.tiktok_validation;
  return (
    <article className="competitor-result-card">
      {candidate.image_url ? (
        <img src={candidate.image_url} alt="" loading="lazy" />
      ) : (
        <div className="competitor-image-placeholder"><ShoppingBag size={22} /></div>
      )}
      <div className="competitor-result-body">
        <div className="competitor-result-head">
          <div>
            <span className={`priority-pill priority-${candidate.priority.toLowerCase()}`}>
              {candidate.priority} · {candidate.score}
            </span>
            {candidate.breakout_label ? (
              <span className={`breakout-pill breakout-${(candidate.breakout_tier || "low_evidence").replace(/_/g, "-")}`}>
                {candidate.breakout_label}
              </span>
            ) : null}
            <h4><a href={candidate.product_url} target="_blank" rel="noreferrer">{candidate.title}</a></h4>
            <p>{candidate.brand || t("amazon.unknownBrand")} · {candidate.platform} · {candidate.asin || "-"}</p>
          </div>
          <div className="competitor-commerce-signal">
            <strong>{candidate.price_text || formatCurrency(candidate.price_value)}</strong>
            <span>{candidate.rating_value || "-"} / {formatInteger(candidate.review_count)}</span>
            <button
              className={variant === "monitoring" ? "secondary" : ""}
              disabled={actionDisabled}
              onClick={onAction}
              type="button"
            >
              {variant === "monitoring" ? <Trash2 size={14} /> : <Radar size={14} />}
              {actionLabel}
            </button>
            {onTikTokAction && tiktokActionLabel ? (
              <button
                className="tiktok"
                disabled={tiktokActionLoading}
                onClick={onTikTokAction}
                type="button"
              >
                {tiktokActionLoading ? <Loader2 className="spin" size={14} /> : <Megaphone size={14} />}
                {tiktokActionLabel}
              </button>
            ) : null}
            {onSecondaryAction && secondaryActionLabel ? (
              <button
                className="primary"
                disabled={secondaryActionLoading}
                onClick={onSecondaryAction}
                type="button"
              >
                {secondaryActionLoading ? (
                  <Loader2 className="spin" size={14} />
                ) : secondaryActionIcon === "stop" ? (
                  <Square size={14} />
                ) : (
                  <Sparkles size={14} />
                )}
                {secondaryActionLabel}
              </button>
            ) : null}
          </div>
        </div>
        <div className="chips competitor-source-chips">
          {candidate.is_sponsored ? <span>{t("amazon.sponsored")}</span> : null}
          {candidate.badges.slice(0, 3).map((badge) => <span key={badge}>{badge}</span>)}
          {candidate.matched_queries.slice(0, 2).map((query) => <span key={query}>{query}</span>)}
        </div>
        {candidate.score_breakdown?.length ? (
          <div className="competitor-score-breakdown" aria-label={t("competitors.scoreBreakdown")}>
            {candidate.score_breakdown.map((item) => (
              <span className={item.points < 0 ? "negative" : ""} key={item.key}>
                <b>{competitorScoreBreakdownLabel(item.key, t)}</b>
                {item.points > 0 ? "+" : ""}{item.points}
                {item.key !== "base" ? <em>{item.weight.toFixed(2)}x</em> : null}
              </span>
            ))} 
          </div>
        ) : null}
        {tiktokValidation ? (
          <div className={`tiktok-validation-card tiktok-${tiktokValidation.status}`}>
            <div className="tiktok-validation-head">
              <div>
                <strong>{tiktokValidation.label} · {tiktokValidation.score}</strong>
                <p>{formatMessage(t("competitors.tiktokValidationSummary"), {
                  videos: tiktokValidation.video_count,
                  views: formatCompactNumber(tiktokValidation.total_views),
                  comments: tiktokValidation.comment_samples,
                })}</p>
              </div>
              <span>{t("competitors.tiktokQuery")}: {tiktokValidation.query}</span>
            </div>
            {tiktokValidation.matched_terms?.length ? (
              <div className="chips competitor-source-chips">
                {tiktokValidation.matched_terms.slice(0, 6).map((term) => <span key={term}>{term}</span>)}
              </div>
            ) : null}
            {tiktokValidation.video_evidence?.length ? (
              <div className="tiktok-evidence-list">
                {tiktokValidation.video_evidence.slice(0, 3).map((video, index) => (
                  <article className="tiktok-evidence-item" key={video.url || `${candidate.id}-tiktok-${index}`}>
                    <div>
                      <a href={video.url} target="_blank" rel="noreferrer">{video.title || t("tiktok.evidenceTitle")}</a>
                      <p>
                        {video.author || t("tiktok.unknownAuthor")} · {formatCompactNumber(video.view_count)} {t("tiktok.views")} · {formatCompactNumber(video.like_count)} {t("tiktok.likes")} · {formatCompactNumber(video.comment_count)} {t("tiktok.comments")}
                      </p>
                    </div>
                    {video.snippet ? <p className="summary-text">{video.snippet}</p> : null}
                    {video.comment_samples?.length ? (
                      <div className="tiktok-comment-preview">
                        {video.comment_samples.slice(0, 2).map((comment, commentIndex) => (
                          <p key={`${video.url}-comment-${commentIndex}`}>
                            <b>{comment.author || "TikTok"}</b>: {comment.text}
                          </p>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <p className="tiktok-no-evidence">{t("competitors.tiktokNoVideoEvidence")}</p>
            )}
            {tiktokValidation.warnings?.length ? (
              <p className="tiktok-warning-text">{tiktokValidation.warnings.slice(0, 2).join(" ")}</p>
            ) : null}
          </div>
        ) : null}
        <div className="competitor-reason-grid">
          <div>
            <h5>{t("competitors.whyTrack")}</h5>
            <ul>
              {candidate.why_worth_tracking.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
          <div>
            <h5>{t("competitors.risks")}</h5>
            <ul>
              {(candidate.risks.length ? candidate.risks : [t("competitors.noRisks")]).map((risk) => <li key={risk}>{risk}</li>)}
            </ul>
          </div>
        </div>
        {candidate.claim_evidence.length ? (
          <p className="competitor-claim">{candidate.claim_evidence[0]}</p>
        ) : null}
      </div>
    </article>
  );
}

function CompetitorDeepDiveView({ report, t }: { report: CompetitorDeepDiveReport; t: Translator }) {
  const product = report.product;
  return (
    <section className="panel wide competitor-deep-dive">
      <PanelTitle
        title={t("competitors.deepDiveTitle")}
        subtitle={`${product.brand || t("amazon.unknownBrand")} · ${product.asin || product.product_url || ""}`}
      />

      <div className="deep-dive-hero">
        {product.image_url ? <img src={product.image_url} alt="" loading="lazy" /> : <div className="competitor-image-placeholder"><ShoppingBag size={24} /></div>}
        <div>
          <p className="eyebrow">{t("competitors.deepDiveVerdict")}</p>
          <h3>{report.verdict.text}</h3>
          <CompetitorCitationLinks citations={report.verdict.citations} t={t} />
          <div className="chips competitor-source-chips">
            <span>Amazon · {report.source_status.amazon}</span>
            <span>Reddit · {report.source_status.reddit}</span>
            <span>Web · {report.source_status.web}</span>
            <span>{report.sales_proxy.confidence} {t("report.confidence")}</span>
          </div>
        </div>
      </div>

      <div className="data-volume-grid deep-dive-volume">
        <div className="volume-stat">
          <span>{t("competitors.amazonReviewVolume")}</span>
          <strong>{formatInteger(report.data_volume.amazon_reviews_collected)}</strong>
          <p>{formatMessage(t("competitors.amazonReviewVolumeNote"), {
            requested: report.data_volume.amazon_reviews_requested,
            ai: report.data_volume.ai_reviews,
          })}</p>
        </div>
        <div className="volume-stat">
          <span>{t("competitors.redditVolume")}</span>
          <strong>{formatInteger(report.data_volume.reddit_posts_collected)}</strong>
          <p>{formatMessage(t("competitors.redditVolumeNote"), {
            requested: report.data_volume.reddit_posts_requested,
            detail: report.data_volume.reddit_detail_posts_requested ?? report.reddit.data_volume.comment_enrichment_post_limit,
            perPost: report.data_volume.reddit_comments_per_post_requested ?? report.reddit.data_volume.comments_per_enriched_post_limit,
            comments: report.data_volume.reddit_comments_collected,
            ai: report.data_volume.ai_reddit_posts,
          })}</p>
        </div>
        <div className="volume-stat">
          <span>{t("competitors.webVolume")}</span>
          <strong>{formatInteger(report.data_volume.web_sources_read)}</strong>
          <p>{formatMessage(t("competitors.webVolumeNote"), {
            candidates: report.data_volume.web_candidates,
          })}</p>
        </div>
        <div className="volume-stat">
          <span>{t("competitors.aiEvidenceVolume")}</span>
          <strong>{formatInteger(report.data_volume.ai_evidence_items)}</strong>
          <p>{formatMessage(t("competitors.aiEvidenceVolumeNote"), {
            reviews: report.data_volume.ai_reviews,
            posts: report.data_volume.ai_reddit_posts,
          })}</p>
        </div>
      </div>

      {report.llm_analysis.status !== "ok" && report.llm_analysis.enabled ? (
        <div className="alert warning">{report.llm_analysis.message || t("llm.unavailableMessage")}</div>
      ) : null}
      {report.warnings.length ? <div className="alert subtle">{report.warnings.join(" ")}</div> : null}

      <div className="deep-dive-section-grid">
        <CompetitorInsightSection title={t("competitors.breakoutAssessment")} items={report.breakout_assessment} t={t} />
        <CompetitorInsightSection title={t("competitors.whyItSells")} items={report.why_it_sells} t={t} />
        <CompetitorInsightSection title={t("competitors.userLove")} items={report.user_love} t={t} />
        <CompetitorInsightSection title={t("competitors.userComplaints")} items={report.user_complaints} t={t} />
        <CompetitorInsightSection title={t("competitors.rdTeardown")} items={report.rd_teardown} t={t} />
        <CompetitorInsightSection title={t("competitors.brandCommunication")} items={report.brand_communication} t={t} />
        <CompetitorInsightSection title={t("competitors.salesProxyInterpretation")} items={report.sales_proxy_interpretation} t={t} />
        <CompetitorInsightSection title={t("competitors.deepDiveRisks")} items={report.risks} t={t} />
      </div>

      <div className="deep-dive-sales-proxy">
        <h4>{t("competitors.salesProxySignals")}</h4>
        <div className="stack">
          {report.sales_proxy.signals.map((signal) => (
            <article className="list-card" key={`${signal.name}-${signal.value}`}>
              <h4>{signal.name} · {signal.value}</h4>
              <p>{signal.interpretation}</p>
            </article>
          ))}
        </div>
        <ul>
          {report.sales_proxy.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
        </ul>
      </div>

      <div className="two-col deep-dive-evidence-preview">
        <div>
          <h4>{t("competitors.amazonReviewEvidence")}</h4>
          <div className="comment-list">
            {report.amazon.review_samples.slice(0, 12).map((review, index) => (
              <div className="comment-item" key={review.id || `${product.asin}-deep-review-${index}`}>
                <p>{review.title ? `${review.title}: ` : ""}{review.body}</p>
                <span>{review.rating_value || "-"} ★ · {review.date_text || (review.verified_purchase ? t("amazon.verified") : t("amazon.unverified"))}</span>
              </div>
            ))}
            {!report.amazon.review_samples.length ? <p className="no-comments">{t("amazon.noReviewSamples")}</p> : null}
          </div>
        </div>
        <div>
          <h4>{t("competitors.redditEvidence")}</h4>
          <div className="comment-list">
            {report.reddit.posts.slice(0, 8).map((post, index) => (
              <div className="comment-item" key={post.id || `${post.url}-${index}`}>
                <p><a href={post.url} target="_blank" rel="noreferrer">{post.title}</a></p>
                <span>r/{post.subreddit || "unknown"} · {formatInteger(post.comments || 0)} {t("report.postComments")}</span>
              </div>
            ))}
            {!report.reddit.posts.length ? <p className="no-comments">{t("report.noCommentBodies")}</p> : null}
          </div>
        </div>
      </div>

      {report.web.articles.length ? (
        <div className="deep-dive-web-sources">
          <h4>{t("competitors.webEvidence")}</h4>
          <div className="article-list">
            {report.web.articles.slice(0, 6).map((article, index) => (
              <article className="article-card" key={`${article.url}-${index}`}>
                <div className="article-card-head">
                  <div>
                    <span className="evidence-index">W{index + 1}</span>
                    <a href={article.url} target="_blank" rel="noreferrer">{article.title}</a>
                    <p>{article.domain} · {article.source_type} · {formatInteger(article.readable_chars)} {t("articles.readableChars")}</p>
                  </div>
                  <span className={`authority-badge ${article.authority_level.toLowerCase()}`}>
                    {article.authority_level} · {article.authority_score}
                  </span>
                </div>
                <div className="article-snippets">
                  {article.evidence_snippets.slice(0, 3).map((snippet, snippetIndex) => (
                    <p key={`${article.url}-snippet-${snippetIndex}`}>{snippet}</p>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      <div className="deep-dive-section-grid">
        <CompetitorEvidenceChain title={t("competitors.deepDiveEvidenceChain")} items={report.evidence_chain} t={t} />
        <CompetitorInsightSection title={t("competitors.deepDiveDataGaps")} items={report.data_gaps} t={t} />
      </div>

      <div className="method-grid">
        <div>
          <h4>{t("report.query")}</h4>
          <p>{report.method.query}</p>
        </div>
        <div>
          <h4>{t("report.notes")}</h4>
          <ul>
            {report.method.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </div>
      </div>
    </section>
  );
}

function CompetitorInsightSection({ items, t, title }: { title: string; items: CompetitorDeepDiveItem[]; t: Translator }) {
  return (
    <div className="deep-dive-section">
      <h4>{title}</h4>
      <div className="stack">
        {items.map((item, index) => (
          <article className="list-card" key={`${title}-${item.title}-${index}`}>
            <h4>{item.title}</h4>
            <p>{item.detail}</p>
            <CompetitorCitationLinks citations={item.citations} t={t} />
          </article>
        ))}
      </div>
    </div>
  );
}

function CompetitorEvidenceChain({
  items,
  t,
  title,
}: {
  title: string;
  items: CompetitorDeepDiveReport["evidence_chain"];
  t: Translator;
}) {
  return (
    <div className="deep-dive-section">
      <h4>{title}</h4>
      <div className="stack">
        {items.map((item, index) => (
          <article className="list-card" key={`${item.claim}-${index}`}>
            <h4>{item.claim}</h4>
            <p>{item.detail}</p>
            <CompetitorCitationLinks citations={item.citations} t={t} />
          </article>
        ))}
      </div>
    </div>
  );
}

function CompetitorCitationLinks({ citations, t }: { citations: CompetitorDeepDiveItem["citations"]; t: Translator }) {
  if (!citations.length) return <p className="muted">{t("competitors.noCitations")}</p>;
  return (
    <div className="source-links competitor-citations">
      {citations.map((citation) => (
        <a href={citation.url} key={`${citation.id}-${citation.url}`} target="_blank" rel="noreferrer" title={citation.excerpt}>
          {citation.id} · {citation.source}/{citation.kind}
        </a>
      ))}
    </div>
  );
}

function ResearchPage({
  launchIntent,
  locale,
  onResearchSettingsChange,
  researchSettings,
  t,
}: {
  launchIntent?: ResearchLaunchIntent | null;
  onResearchSettingsChange: (settings: Partial<ResearchSettings>) => void;
  researchSettings: ResearchSettings;
} & LocalizedProps) {
  const [initialSession] = useState<ResearchSession>(() => loadResearchSession());
  const [category, setCategory] = useState(initialSession.category);
  const [activeSource, setActiveSource] = useState<ResearchSource>(initialSession.activeSource);
  const [articleUrls, setArticleUrls] = useState(initialSession.articleUrls);
  const [bypassCache, setBypassCache] = useState(false);
  const [redditReport, setRedditReport] = useState<AnalysisReport | null>(initialSession.redditReport);
  const [amazonReport, setAmazonReport] = useState<AmazonReport | null>(initialSession.amazonReport);
  const [youtubeReport, setYoutubeReport] = useState<YouTubeReport | null>(initialSession.youtubeReport);
  const [tiktokReport, setTikTokReport] = useState<TikTokReport | null>(initialSession.tiktokReport);
  const [articleDiscoveryReport, setArticleDiscoveryReport] = useState<ArticleDiscoveryReport | null>(
    initialSession.articleDiscoveryReport,
  );
  const [articleReport, setArticleReport] = useState<ArticleReport | null>(initialSession.articleReport);
  const [combinedReport, setCombinedReport] = useState<CombinedInsightReport | null>(initialSession.combinedReport);
  const [runningSources, setRunningSources] = useState<ResearchSource[]>([]);
  const runningSourcesRef = useRef<Set<ResearchSource>>(new Set());
  const [articleDiscoveryLoading, setArticleDiscoveryLoading] = useState(false);
  const [errorsBySource, setErrorsBySource] = useState<Partial<Record<ResearchSource, string>>>({});
  const [articleDiscoveryError, setArticleDiscoveryError] = useState<string | null>(null);
  const [historyItems, setHistoryItems] = useState<ResearchHistorySummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<ResearchHistoryItem | null>(null);
  const [historyStoragePath, setHistoryStoragePath] = useState(".cache/research-history.json");
  const [historyMessage, setHistoryMessage] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [sourceSettingsSource, setSourceSettingsSource] = useState<SourceSettingsSource | null>(null);
  const [tiktokLoginLoading, setTikTokLoginLoading] = useState(false);
  const [tiktokLoginMessage, setTikTokLoginMessage] = useState<string | null>(null);

  useEffect(() => {
    saveResearchSession({
      category,
      activeSource,
      articleUrls,
      redditReport,
      amazonReport,
      youtubeReport,
      tiktokReport,
      articleDiscoveryReport,
      articleReport,
      combinedReport,
    });
  }, [category, activeSource, articleUrls, redditReport, amazonReport, youtubeReport, tiktokReport, articleDiscoveryReport, articleReport, combinedReport]);

  useEffect(() => {
    refreshHistory();
  }, []);

  useEffect(() => {
    if (!launchIntent) return;
    if (launchIntent.category) {
      setCategory(launchIntent.category);
    }
    setActiveSource(launchIntent.source);
    setSourceSettingsSource(null);
    setHistoryMessage(null);
    setHistoryOpen(Boolean(launchIntent.openHistory));
    if (launchIntent.openHistory) {
      void refreshHistory();
    }
  }, [launchIntent?.nonce, launchIntent?.source, launchIntent?.category, launchIntent?.openHistory]);

  async function refreshHistory(): Promise<ResearchHistorySummary[]> {
    try {
      const result = await api.getHistory();
      setHistoryItems(result.items);
      setHistoryStoragePath(result.storage_path);
      return result.items;
    } catch {
      // History is a convenience layer; analysis remains usable if history cannot load.
      return [];
    }
  }

  function hasCurrentReports(): boolean {
    return Boolean(redditReport || amazonReport || youtubeReport || tiktokReport || articleReport || combinedReport);
  }

  async function saveCurrentHistory() {
    if (!hasCurrentReports()) {
      setHistoryMessage(t("history.noReport"));
      return;
    }
    setHistoryBusy(true);
    setHistoryMessage(null);
    try {
      const result = await api.saveHistory({
        category,
        reddit_report: redditReport,
        amazon_report: amazonReport,
        youtube_report: youtubeReport,
        tiktok_report: tiktokReport,
        article_report: articleReport,
        combined_report: combinedReport,
      });
      setHistoryItems((items) => [result.item, ...items.filter((item) => item.id !== result.item.id)]);
      setHistoryStoragePath(result.storage_path);
      setHistoryMessage(t("history.saved"));
    } catch (err) {
      setHistoryMessage(err instanceof Error ? err.message : t("history.saveError"));
    } finally {
      setHistoryBusy(false);
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryMessage(null);
    await refreshHistory();
  }

  function closeHistory() {
    setHistoryOpen(false);
    setHistoryMessage(null);
  }

  async function selectHistoryItem(id: string) {
    setHistoryBusy(true);
    setHistoryMessage(null);
    try {
      const result = await api.getHistoryItem(id);
      setSelectedHistoryItem(result.item);
      setHistoryStoragePath(result.storage_path);
    } catch (err) {
      setHistoryMessage(err instanceof Error ? err.message : t("history.loadError"));
    } finally {
      setHistoryBusy(false);
    }
  }

  function restoreHistoryItem(item: ResearchHistoryItem) {
    setCategory(item.category);
    setRedditReport(item.reddit_report || null);
    setAmazonReport(item.amazon_report || null);
    setYoutubeReport(item.youtube_report || null);
    setTikTokReport(item.tiktok_report || null);
    setArticleDiscoveryReport(null);
    setArticleReport(item.article_report || null);
    setCombinedReport(item.combined_report || null);
    setActiveSource(item.combined_report ? "combined" : item.article_report ? "articles" : item.tiktok_report ? "tiktok" : item.youtube_report ? "youtube" : item.amazon_report ? "amazon" : "reddit");
    setHistoryOpen(false);
    setHistoryMessage(t("history.loaded"));
  }

  async function deleteHistoryItem(id: string) {
    setHistoryBusy(true);
    setHistoryMessage(null);
    try {
      const result = await api.deleteHistoryItem(id);
      setHistoryItems(result.items);
      setHistoryStoragePath(result.storage_path);
      if (selectedHistoryItem?.id === id) {
        setSelectedHistoryItem(null);
      }
      setHistoryMessage(t("history.deleted"));
    } catch (err) {
      setHistoryMessage(err instanceof Error ? err.message : t("history.deleteError"));
    } finally {
      setHistoryBusy(false);
    }
  }

  function reportMatchesCurrentCategory(report: { category?: string } | null): boolean {
    return Boolean(report?.category && report.category.trim().toLowerCase() === category.trim().toLowerCase());
  }

  async function ensureCombinedInputs(request: AnalyzeRequest) {
    const shouldFetchReddit = bypassCache || !reportMatchesCurrentCategory(redditReport);
    const shouldFetchAmazon = bypassCache || !reportMatchesCurrentCategory(amazonReport);
    const redditPromise: Promise<AnalysisReport | null> = shouldFetchReddit
      ? api.analyze(request)
      : Promise.resolve(redditReport);
    const amazonPromise: Promise<AmazonReport | null> = shouldFetchAmazon
      ? api.analyzeAmazon({
        ...request,
        limit: researchSettings.amazonProductLimit,
        amazonKeywordLimit: researchSettings.amazonKeywordLimit,
      })
      : Promise.resolve(amazonReport);
    const [redditResult, amazonResult] = await Promise.allSettled([redditPromise, amazonPromise]);
    const partialErrors: string[] = [];
    let nextReddit: AnalysisReport | null = redditReport;
    let nextAmazon: AmazonReport | null = amazonReport;

    if (redditResult.status === "fulfilled") {
      nextReddit = redditResult.value;
      if (nextReddit) setRedditReport(nextReddit);
    } else {
      partialErrors.push(`${t("source.reddit")}: ${redditResult.reason instanceof Error ? redditResult.reason.message : t("research.errorFallback")}`);
      if (shouldFetchReddit) nextReddit = null;
    }

    if (amazonResult.status === "fulfilled") {
      nextAmazon = amazonResult.value;
      if (nextAmazon) setAmazonReport(nextAmazon);
    } else {
      partialErrors.push(`${t("source.amazon")}: ${amazonResult.reason instanceof Error ? amazonResult.reason.message : t("research.errorFallback")}`);
      if (shouldFetchAmazon) nextAmazon = null;
    }

    if (!nextReddit && !nextAmazon) {
      throw new Error(partialErrors.join("；") || t("combined.needSourceData"));
    }
    return { nextReddit, nextAmazon, partialMessage: partialErrors.join("；") };
  }

  function discoveredUrls(report: ArticleDiscoveryReport | null = articleDiscoveryReport): string[] {
    return report ? report.candidates.map((candidate) => candidate.url) : [];
  }

  function useDiscoveredArticleUrls(report: ArticleDiscoveryReport | null = articleDiscoveryReport) {
    const urls = discoveredUrls(report);
    if (!urls.length) return;
    setArticleUrls(urls.join("\n"));
  }

  function appendArticleUrl(url: string) {
    const existing = parseArticleUrls(articleUrls);
    if (existing.includes(url)) return;
    setArticleUrls([...existing, url].join("\n"));
  }

  async function discoverArticles() {
    setArticleDiscoveryLoading(true);
    setArticleDiscoveryError(null);
    try {
      const report = await api.discoverArticles({
        category,
        queryLimit: researchSettings.articleQueryLimit,
        resultsPerQuery: researchSettings.articleResultsPerQuery,
        candidateLimit: researchSettings.articleCandidateLimit,
        includeIndustryReports: true,
        bypassCache,
      });
      setArticleDiscoveryReport(report);
      useDiscoveredArticleUrls(report);
    } catch (err) {
      setArticleDiscoveryError(err instanceof Error ? err.message : t("articles.discoveryError"));
    } finally {
      setArticleDiscoveryLoading(false);
    }
  }

  async function openTikTokLoginBrowser() {
    setTikTokLoginLoading(true);
    setTikTokLoginMessage(null);
    clearSourceError("tiktok");
    try {
      const result = await api.openTikTokLoginBrowser();
      if (!result.ok) {
        throw new Error(result.message || t("tiktok.loginBrowserError"));
      }
      setTikTokLoginMessage(formatMessage(t("tiktok.loginBrowserOpened"), { path: result.profile_dir }));
    } catch (err) {
      setSourceError("tiktok", err instanceof Error ? err.message : t("tiktok.loginBrowserError"));
    } finally {
      setTikTokLoginLoading(false);
    }
  }

  function runTargetsFor(source: ResearchSource): ResearchSource[] {
    return source === "combined" ? ["combined", "reddit", "amazon"] : [source];
  }

  function isRunBlocked(source: ResearchSource): boolean {
    return runTargetsFor(source).some((target) => runningSourcesRef.current.has(target));
  }

  function startSourceRun(source: ResearchSource): boolean {
    const targets = runTargetsFor(source);
    if (targets.some((target) => runningSourcesRef.current.has(target))) return false;
    const next = new Set(runningSourcesRef.current);
    targets.forEach((target) => next.add(target));
    runningSourcesRef.current = next;
    setRunningSources(Array.from(next));
    return true;
  }

  function finishSourceRun(source: ResearchSource): void {
    const next = new Set(runningSourcesRef.current);
    runTargetsFor(source).forEach((target) => next.delete(target));
    runningSourcesRef.current = next;
    setRunningSources(Array.from(next));
  }

  function clearSourceError(source: ResearchSource): void {
    setErrorsBySource((current) => {
      if (!current[source]) return current;
      const next = { ...current };
      delete next[source];
      return next;
    });
  }

  function setSourceError(source: ResearchSource, message: string): void {
    setErrorsBySource((current) => ({ ...current, [source]: message }));
  }

  async function run(event?: FormEvent) {
    event?.preventDefault();
    const source = activeSource;
    if (!startSourceRun(source)) return;
    clearSourceError(source);
    try {
      const request: AnalyzeRequest = {
        category,
        ...researchSettings,
        redditDetailLimit: researchSettings.redditDetailLimit,
        redditCommentsPerPost: researchSettings.redditCommentsPerPost,
        useLlm: true,
        bypassCache,
      };
      if (source === "combined") {
        const { nextReddit, nextAmazon, partialMessage } = await ensureCombinedInputs(request);
        setCombinedReport(await api.analyzeCombined({
          category,
          reddit_report: nextReddit,
          amazon_report: nextAmazon,
          useLlm: true,
          locale,
        }));
        if (partialMessage) {
          setSourceError(source, partialMessage);
        }
      } else if (source === "amazon") {
        setAmazonReport(await api.analyzeAmazon({
          ...request,
          limit: researchSettings.amazonProductLimit,
          amazonKeywordLimit: researchSettings.amazonKeywordLimit,
        }));
      } else if (source === "youtube") {
        setYoutubeReport(await api.analyzeYoutube({
          ...request,
          limit: researchSettings.youtubeVideoLimit,
          youtubeTranscriptVideoLimit: researchSettings.youtubeTranscriptVideoLimit,
          youtubeCommentVideoLimit: researchSettings.youtubeCommentVideoLimit,
          youtubeCommentsPerVideo: researchSettings.youtubeCommentsPerVideo,
        }));
      } else if (source === "tiktok") {
        setTikTokReport(await api.analyzeTikTok({
          ...request,
          limit: researchSettings.tiktokVideoLimit,
          tiktokCommentsPerVideo: researchSettings.tiktokCommentsPerVideo,
        }));
      } else if (source === "articles") {
        const urls = parseArticleUrls(articleUrls);
        if (!urls.length) {
          throw new Error(t("articles.urlRequired"));
        }
        setArticleReport(await api.analyzeArticles({
          category,
          urls,
          limit: Math.min(researchSettings.articleReadLimit, urls.length),
          bypassCache,
        }));
      } else {
        setRedditReport(await api.analyze(request));
      }
    } catch (err) {
      setSourceError(source, err instanceof Error ? err.message : t("research.errorFallback"));
    } finally {
      finishSourceRun(source);
    }
  }

  const activeSourceLoading = runningSources.includes(activeSource);
  const activeRunBlocked = isRunBlocked(activeSource);
  const activeLoadingSource: ResearchSource = activeSourceLoading && runningSources.includes("combined") && activeSource !== "combined"
    ? "combined"
    : activeSource;
  const loadingText = activeLoadingSource === "amazon"
    ? t("research.amazonLoading")
    : activeLoadingSource === "youtube"
      ? t("youtube.loading")
    : activeLoadingSource === "tiktok"
      ? t("tiktok.loading")
    : activeLoadingSource === "articles"
      ? t("articles.loading")
    : activeLoadingSource === "combined"
      ? t("combined.loading")
      : t("research.loading");
  const backgroundSources = runningSources.includes("combined")
    ? runningSources.filter((source) => source === "combined" || !["reddit", "amazon"].includes(source))
    : runningSources;
  const visibleBackgroundSources = backgroundSources.filter((source) => source !== activeSource);
  const backgroundRunMessage = visibleBackgroundSources.length && !activeSourceLoading
    ? formatMessage(t(activeRunBlocked ? "research.blockedByRun" : "research.backgroundRun"), {
      source: visibleBackgroundSources.map((source) => t(`source.${source}`)).join(" / "),
    })
    : "";
  const activeError = errorsBySource[activeSource];

  const status = activeSource === "amazon" && amazonReport
    ? `${sourceLabel(amazonReport.source_mode, locale)} · ${confidenceLabel(amazonReport.confidence, locale)}`
    : activeSource === "youtube" && youtubeReport
      ? `${sourceLabel(youtubeReport.source_mode, locale)} · ${confidenceLabel(youtubeReport.confidence, locale)}`
    : activeSource === "tiktok" && tiktokReport
      ? `${sourceLabel(tiktokReport.source_mode, locale)} · ${confidenceLabel(tiktokReport.confidence, locale)}`
    : activeSource === "articles" && articleReport
      ? `${sourceLabel(articleReport.source_mode, locale)} · ${articleReport.data_volume.collected_articles} ${t("articles.items")}`
    : activeSource === "combined" && combinedReport
      ? `${t("source.combined")} · ${combinedReport.data_summary.evidence_items} ${t("combined.evidenceItems")}`
    : activeSource === "reddit" && redditReport
      ? `${sourceLabel(redditReport.source_mode, locale)} · ${confidenceLabel(redditReport.coverage.confidence, locale)}`
      : t("research.ready");
  const collectionSummary = activeSource === "amazon"
    ? describeAmazonResearchSettings(researchSettings, locale)
    : activeSource === "youtube"
      ? describeYoutubeResearchSettings(researchSettings, locale)
    : activeSource === "tiktok"
      ? describeTikTokResearchSettings(researchSettings, locale)
    : activeSource === "articles"
      ? describeArticleResearchSettings(researchSettings, locale)
    : activeSource === "combined"
      ? formatMessage(t("combined.summary"), {
        reddit: redditReport?.coverage.posts ?? 0,
        amazon: amazonReport?.metrics.products ?? 0,
      })
    : describeResearchSettings(researchSettings, locale);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">{t("research.eyebrow")}</p>
          <h2>{t("research.title")}</h2>
          <p>{t("research.description")}</p>
        </div>
        <div className="research-header-actions">
          <button type="button" disabled={historyBusy || !hasCurrentReports()} onClick={saveCurrentHistory}>
            {historyBusy ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
            {t("history.saveCurrent")}
          </button>
          <button type="button" className={historyOpen ? "active" : ""} onClick={historyOpen ? closeHistory : openHistory}>
            <FolderOpen size={16} />
            {historyOpen ? t("history.backToResearch") : t("history.open")}
          </button>
          <div className="status-pill">{status}</div>
        </div>
      </header>

      {historyMessage ? <div className="alert subtle history-message">{historyMessage}</div> : null}

      {sourceSettingsSource ? (
        <SourceCollectionSettingsView
          onClose={() => setSourceSettingsSource(null)}
          onResearchSettingsChange={onResearchSettingsChange}
          researchSettings={researchSettings}
          source={sourceSettingsSource}
          t={t}
        />
      ) : historyOpen ? (
        <HistoryResearchView
          busy={historyBusy}
          items={historyItems}
          locale={locale}
          onDelete={deleteHistoryItem}
          onRestore={restoreHistoryItem}
          onSelect={selectHistoryItem}
          selectedItem={selectedHistoryItem}
          storagePath={historyStoragePath}
          t={t}
        />
      ) : (
        <>

      <div className="source-tabs" role="tablist" aria-label="Research source">
        <button
          className={activeSource === "combined" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("combined")}
        >
          <Sparkles size={16} />
          {t("source.combined")}
        </button>
        <button
          className={activeSource === "reddit" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("reddit")}
        >
          <MessageSquare size={16} />
          {t("source.reddit")}
        </button>
        <button
          className={activeSource === "amazon" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("amazon")}
        >
          <ShoppingBag size={16} />
          {t("source.amazon")}
        </button>
        <button
          className={activeSource === "youtube" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("youtube")}
        >
          <Youtube size={16} />
          {t("source.youtube")}
        </button>
        <button
          className={activeSource === "tiktok" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("tiktok")}
        >
          <Megaphone size={16} />
          {t("source.tiktok")}
        </button>
        <button
          className={activeSource === "articles" ? "active" : ""}
          type="button"
          onClick={() => setActiveSource("articles")}
        >
          <FileText size={16} />
          {t("source.articles")}
        </button>
      </div>

      <form className={`query-panel${activeSource === "articles" ? " article-query-panel" : ""}`} onSubmit={run}>
        <label className="search-field">
          <Search size={17} />
          <input
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            placeholder={t("research.placeholder")}
            required
          />
        </label>
        <div className="collection-summary">
          <CalendarRange size={16} />
          <span>{collectionSummary}</span>
        </div>
        <label className="cache-toggle" title={t("research.bypassCacheNote")}>
          <input
            type="checkbox"
            checked={bypassCache}
            onChange={(event) => setBypassCache(event.target.checked)}
          />
          <span>{t("research.bypassCache")}</span>
        </label>
        {activeSource !== "combined" ? (
          <button
            type="button"
            className="secondary-action"
            disabled={activeSourceLoading || articleDiscoveryLoading}
            onClick={() => setSourceSettingsSource(activeSource)}
          >
            <Settings size={17} />
            {t("sourceSettings.open")}
          </button>
        ) : null}
        {activeSource === "articles" ? (
          <button type="button" className="secondary-action" disabled={articleDiscoveryLoading || activeSourceLoading} onClick={discoverArticles}>
            {articleDiscoveryLoading ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
            {articleDiscoveryLoading ? t("articles.discovering") : t("articles.discover")}
          </button>
        ) : null}
        {activeSource === "tiktok" ? (
          <button
            type="button"
            className="secondary-action"
            disabled={activeSourceLoading || tiktokLoginLoading}
            onClick={openTikTokLoginBrowser}
          >
            {tiktokLoginLoading ? <Loader2 className="spin" size={17} /> : <KeyRound size={17} />}
            {tiktokLoginLoading ? t("tiktok.loginBrowserOpening") : t("tiktok.loginBrowserOpen")}
          </button>
        ) : null}
        <button type="submit" disabled={activeRunBlocked || (activeSource === "articles" && articleDiscoveryLoading)}>
          {activeSourceLoading ? <Loader2 className="spin" size={17} /> : activeSource === "combined" ? <Sparkles size={17} /> : activeSource === "articles" ? <FileText size={17} /> : activeSource === "youtube" ? <Youtube size={17} /> : activeSource === "tiktok" ? <Megaphone size={17} /> : <RefreshCw size={17} />}
          {activeSource === "combined"
            ? t("combined.generate")
            : activeSource === "articles"
              ? bypassCache ? t("articles.refresh") : t("articles.collect")
              : activeSource === "youtube"
                ? bypassCache ? t("youtube.refresh") : t("youtube.collect")
              : activeSource === "tiktok"
                ? bypassCache ? t("tiktok.refresh") : t("tiktok.collect")
              : bypassCache ? t("research.refresh") : t("research.analyze")}
        </button>
        {activeSource === "articles" ? (
          <label className="article-url-field">
            <span><FileText size={16} /> {t("articles.urlsLabel")}</span>
            <textarea
              value={articleUrls}
              onChange={(event) => setArticleUrls(event.target.value)}
              placeholder={t("articles.urlsPlaceholder")}
              rows={5}
              required
            />
          </label>
        ) : null}
      </form>

      {backgroundRunMessage ? <div className="alert subtle">{backgroundRunMessage}</div> : null}
      {activeSource === "tiktok" && tiktokLoginMessage ? <div className="alert subtle">{tiktokLoginMessage}</div> : null}
      {activeError ? <div className="alert danger">{activeError}</div> : null}
      {articleDiscoveryError && activeSource === "articles" ? <div className="alert danger">{articleDiscoveryError}</div> : null}
      {activeSourceLoading ? (
        <LoadingPanel text={loadingText} />
      ) : null}
      {articleDiscoveryLoading && activeSource === "articles" ? <LoadingPanel text={t("articles.discoveryLoading")} /> : null}
      {!activeSourceLoading && activeSource === "reddit" && !redditReport ? <EmptyState t={t} /> : null}
      {!activeSourceLoading && activeSource === "amazon" && !amazonReport ? <EmptyState t={t} /> : null}
      {!activeSourceLoading && activeSource === "youtube" && !youtubeReport ? <YouTubeEmptyState t={t} /> : null}
      {!activeSourceLoading && activeSource === "tiktok" && !tiktokReport ? <TikTokEmptyState t={t} /> : null}
      {!activeSourceLoading && activeSource === "articles" && !articleReport ? <ArticleEmptyState t={t} /> : null}
      {!activeSourceLoading && activeSource === "combined" && !combinedReport ? (
        <CombinedEmptyState redditReady={Boolean(redditReport)} amazonReady={Boolean(amazonReport)} t={t} />
      ) : null}
      {activeSource === "reddit" && redditReport ? <ReportView locale={locale} report={redditReport} t={t} /> : null}
      {activeSource === "amazon" && amazonReport ? <AmazonReportView locale={locale} report={amazonReport} t={t} /> : null}
      {activeSource === "youtube" && youtubeReport ? <YouTubeReportView locale={locale} report={youtubeReport} t={t} /> : null}
      {activeSource === "tiktok" && tiktokReport ? <TikTokReportView locale={locale} report={tiktokReport} t={t} /> : null}
      {activeSource === "articles" && articleDiscoveryReport ? (
        <ArticleDiscoveryView
          onAppendUrl={appendArticleUrl}
          onUseUrls={() => useDiscoveredArticleUrls()}
          report={articleDiscoveryReport}
          selectedUrls={parseArticleUrls(articleUrls)}
          t={t}
        />
      ) : null}
      {activeSource === "articles" && articleReport ? <ArticleReportView locale={locale} report={articleReport} t={t} /> : null}
      {activeSource === "combined" && combinedReport ? (
        <CombinedInsightView locale={locale} report={combinedReport} t={t} />
      ) : null}
        </>
      )}
    </div>
  );
}

function SourceCollectionSettingsView({
  onClose,
  onResearchSettingsChange,
  researchSettings,
  source,
  t,
}: {
  onClose: () => void;
  onResearchSettingsChange: (settings: Partial<ResearchSettings>) => void;
  researchSettings: ResearchSettings;
  source: SourceSettingsSource;
  t: Translator;
}) {
  const [draft, setDraft] = useState<ResearchSettings>(researchSettings);
  const [researchDefaults, setResearchDefaults] = useState<ResearchDefaults | null>(null);
  const [agentReachSettings, setAgentReachSettings] = useState<AgentReachSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.getResearchSettings(), api.getAgentReachSettings()])
      .then(([defaults, agentReach]) => {
        if (cancelled) return;
        setResearchDefaults(defaults);
        setAgentReachSettings(agentReach);
        setDraft((current) => ({
          ...current,
          mode: defaults.mode,
          timeRange: defaults.timeRange,
          limit: defaults.limit,
          llmEvidencePosts: defaults.llmEvidencePosts,
          llmCommentSamplesPerPost: defaults.llmCommentSamplesPerPost,
          redditDetailLimit: agentReach.detail_limit,
          redditCommentsPerPost: agentReach.comments_per_post,
          amazonProductLimit: defaults.amazonProductLimit,
          amazonKeywordLimit: defaults.amazonKeywordLimit,
          amazonDetailLimit: defaults.amazonDetailLimit,
          amazonDiscussionLimit: defaults.amazonDiscussionLimit,
          amazonReviewsPerProduct: defaults.amazonReviewsPerProduct,
          amazonLlmProductLimit: defaults.amazonLlmProductLimit,
          amazonLlmReviewSamplesPerProduct: defaults.amazonLlmReviewSamplesPerProduct,
        }));
      })
      .catch((err) => {
        if (!cancelled) setMessage(err instanceof Error ? err.message : t("sourceSettings.loadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function updateDraft<K extends keyof ResearchSettings>(key: K, value: ResearchSettings[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function buildResearchUpdatePayload(settings: ResearchSettings): ResearchDefaults {
    const fallback = researchDefaults;
    return {
      mode: settings.mode,
      timeRange: settings.timeRange,
      limit: settings.limit,
      maxPostLimit: fallback?.maxPostLimit ?? 500,
      llmEvidencePosts: settings.llmEvidencePosts,
      llmCommentSamplesPerPost: settings.llmCommentSamplesPerPost,
      amazonProductLimit: settings.amazonProductLimit,
      maxAmazonProductLimit: fallback?.maxAmazonProductLimit ?? 100,
      amazonKeywordLimit: settings.amazonKeywordLimit,
      maxAmazonKeywordLimit: fallback?.maxAmazonKeywordLimit ?? 20,
      amazonDetailLimit: settings.amazonDetailLimit,
      amazonDiscussionLimit: settings.amazonDiscussionLimit,
      amazonReviewsPerProduct: settings.amazonReviewsPerProduct,
      amazonLlmProductLimit: settings.amazonLlmProductLimit,
      amazonLlmReviewSamplesPerProduct: settings.amazonLlmReviewSamplesPerProduct,
      env_path: fallback?.env_path ?? ".env",
    };
  }

  async function saveSourceSettings() {
    setSaving(true);
    setMessage(null);
    try {
      let nextSettings: Partial<ResearchSettings> = { ...draft };
      if (source === "reddit" || source === "amazon") {
        const updated = await api.updateResearchSettings(buildResearchUpdatePayload(draft));
        nextSettings = {
          ...nextSettings,
          mode: updated.mode,
          timeRange: updated.timeRange,
          limit: updated.limit,
          llmEvidencePosts: updated.llmEvidencePosts,
          llmCommentSamplesPerPost: updated.llmCommentSamplesPerPost,
          amazonProductLimit: updated.amazonProductLimit,
          amazonKeywordLimit: updated.amazonKeywordLimit,
          amazonDetailLimit: updated.amazonDetailLimit,
          amazonDiscussionLimit: updated.amazonDiscussionLimit,
          amazonReviewsPerProduct: updated.amazonReviewsPerProduct,
          amazonLlmProductLimit: updated.amazonLlmProductLimit,
          amazonLlmReviewSamplesPerProduct: updated.amazonLlmReviewSamplesPerProduct,
        };
        setResearchDefaults(updated);
      }
      if (source === "reddit" && agentReachSettings) {
        const updatedAgentReach = await api.updateAgentReachSettings({
          enabled: agentReachSettings.enabled,
          backend: agentReachSettings.backend,
          timeout_seconds: agentReachSettings.timeout_seconds,
          detail_limit: draft.redditDetailLimit,
          comments_per_post: draft.redditCommentsPerPost,
        });
        setAgentReachSettings(updatedAgentReach);
        nextSettings = {
          ...nextSettings,
          redditDetailLimit: updatedAgentReach.detail_limit,
          redditCommentsPerPost: updatedAgentReach.comments_per_post,
        };
      }
      onResearchSettingsChange(nextSettings);
      setMessage(t("sourceSettings.saved"));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t("sourceSettings.saveError"));
    } finally {
      setSaving(false);
    }
  }

  const sourceIcon = source === "reddit"
    ? <MessageSquare size={18} />
    : source === "amazon"
      ? <ShoppingBag size={18} />
      : source === "youtube"
        ? <Youtube size={18} />
        : <FileText size={18} />;

  if (loading) {
    return <LoadingPanel text={t("sourceSettings.loading")} />;
  }

  return (
    <section className="panel wide source-settings-page">
      <div className="source-settings-head">
        <button type="button" className="secondary-action" onClick={onClose}>
          <ArrowLeft size={16} />
          {t("sourceSettings.back")}
        </button>
        <div>
          <p className="eyebrow">{t("sourceSettings.eyebrow")}</p>
          <h3>{sourceIcon}{t(`sourceSettings.${source}.title`)}</h3>
          <p>{t(`sourceSettings.${source}.subtitle`)}</p>
        </div>
      </div>

      <div className="field-stack source-settings-grid">
        {source === "reddit" ? (
          <>
            <label>
              {t("settings.sourceMode")}
              <select value={draft.mode} onChange={(event) => updateDraft("mode", event.target.value as ResearchSettings["mode"])}>
                <option value="auto">{t("settings.modeAuto")}</option>
                <option value="agent_reach">{t("settings.modeAgentReach")}</option>
                <option value="oauth">{t("settings.modeOauth")}</option>
                <option value="rss">{t("settings.modeRss")}</option>
                <option value="sample">{t("settings.modeSample")}</option>
              </select>
            </label>
            <label>
              {t("settings.timeRange")}
              <select value={draft.timeRange} onChange={(event) => updateDraft("timeRange", event.target.value as ResearchSettings["timeRange"])}>
                <option value="day">{t("settings.day")}</option>
                <option value="week">{t("settings.week")}</option>
                <option value="month">{t("settings.month")}</option>
                <option value="year">{t("settings.year")}</option>
                <option value="all">{t("settings.all")}</option>
              </select>
            </label>
            <SourceNumberField label={t("settings.totalPostLimit")} max={researchDefaults?.maxPostLimit ?? 500} min={5} value={draft.limit} onChange={(value) => updateDraft("limit", value)} />
            <SourceNumberField label={t("settings.detailLimit")} max={100} min={0} value={draft.redditDetailLimit} onChange={(value) => updateDraft("redditDetailLimit", value)} />
            <SourceNumberField label={t("settings.commentsPerPost")} max={200} min={0} value={draft.redditCommentsPerPost} onChange={(value) => updateDraft("redditCommentsPerPost", value)} />
            <SourceNumberField label={t("settings.aiEvidencePosts")} max={100} min={1} value={draft.llmEvidencePosts} onChange={(value) => updateDraft("llmEvidencePosts", value)} />
            <SourceNumberField label={t("settings.aiCommentSamples")} max={50} min={0} value={draft.llmCommentSamplesPerPost} onChange={(value) => updateDraft("llmCommentSamplesPerPost", value)} />
            <div className="settings-path wide-field">
              <Database size={16} />
              <span>{formatMessage(t("settings.volumeSummary"), {
                posts: draft.limit,
                details: draft.redditDetailLimit,
                comments: draft.redditCommentsPerPost,
                aiPosts: draft.llmEvidencePosts,
                aiComments: draft.llmCommentSamplesPerPost,
              })}</span>
            </div>
          </>
        ) : null}

        {source === "amazon" ? (
          <>
            <SourceNumberField label={t("settings.amazonKeywordLimit")} max={researchDefaults?.maxAmazonKeywordLimit ?? 20} min={1} value={draft.amazonKeywordLimit} onChange={(value) => updateDraft("amazonKeywordLimit", value)} />
            <SourceNumberField label={t("settings.amazonProductLimit")} max={researchDefaults?.maxAmazonProductLimit ?? 100} min={1} value={draft.amazonProductLimit} onChange={(value) => updateDraft("amazonProductLimit", value)} />
            <SourceNumberField label={t("settings.amazonDetailLimit")} max={100} min={0} value={draft.amazonDetailLimit} onChange={(value) => updateDraft("amazonDetailLimit", value)} />
            <SourceNumberField label={t("settings.amazonDiscussionLimit")} max={100} min={0} value={draft.amazonDiscussionLimit} onChange={(value) => updateDraft("amazonDiscussionLimit", value)} />
            <SourceNumberField label={t("settings.amazonReviewsPerProduct")} max={100} min={0} value={draft.amazonReviewsPerProduct} onChange={(value) => updateDraft("amazonReviewsPerProduct", value)} />
            <SourceNumberField label={t("settings.amazonAiProducts")} max={100} min={1} value={draft.amazonLlmProductLimit} onChange={(value) => updateDraft("amazonLlmProductLimit", value)} />
            <SourceNumberField label={t("settings.amazonAiReviews")} max={50} min={0} value={draft.amazonLlmReviewSamplesPerProduct} onChange={(value) => updateDraft("amazonLlmReviewSamplesPerProduct", value)} />
            <div className="settings-path wide-field">
              <ShoppingBag size={16} />
              <span>{formatMessage(t("settings.amazonVolumeSummary"), {
                keywords: draft.amazonKeywordLimit,
                products: draft.amazonProductLimit,
                total: draft.amazonKeywordLimit * draft.amazonProductLimit,
                details: draft.amazonDetailLimit,
                discussions: draft.amazonDiscussionLimit,
                reviews: draft.amazonReviewsPerProduct,
                aiProducts: draft.amazonLlmProductLimit,
                aiReviews: draft.amazonLlmReviewSamplesPerProduct,
              })}</span>
            </div>
          </>
        ) : null}

        {source === "articles" ? (
          <>
            <SourceNumberField label={t("sourceSettings.articleQueryLimit")} max={30} min={1} value={draft.articleQueryLimit} onChange={(value) => updateDraft("articleQueryLimit", value)} />
            <SourceNumberField label={t("sourceSettings.articleResultsPerQuery")} max={20} min={1} value={draft.articleResultsPerQuery} onChange={(value) => updateDraft("articleResultsPerQuery", value)} />
            <SourceNumberField label={t("sourceSettings.articleCandidateLimit")} max={80} min={1} value={draft.articleCandidateLimit} onChange={(value) => updateDraft("articleCandidateLimit", value)} />
            <SourceNumberField label={t("sourceSettings.articleReadLimit")} max={80} min={1} value={draft.articleReadLimit} onChange={(value) => updateDraft("articleReadLimit", value)} />
            <div className="settings-path wide-field">
              <FileText size={16} />
              <span>{formatMessage(t("sourceSettings.articleSummary"), {
                queries: draft.articleQueryLimit,
                results: draft.articleResultsPerQuery,
                candidates: draft.articleCandidateLimit,
                read: draft.articleReadLimit,
              })}</span>
            </div>
          </>
        ) : null}

        {source === "youtube" ? (
          <>
            <SourceNumberField label={t("sourceSettings.youtubeVideoLimit")} max={50} min={1} value={draft.youtubeVideoLimit} onChange={(value) => updateDraft("youtubeVideoLimit", value)} />
            <SourceNumberField label={t("sourceSettings.youtubeTranscriptVideoLimit")} max={20} min={0} value={draft.youtubeTranscriptVideoLimit} onChange={(value) => updateDraft("youtubeTranscriptVideoLimit", value)} />
            <SourceNumberField label={t("sourceSettings.youtubeCommentVideoLimit")} max={20} min={0} value={draft.youtubeCommentVideoLimit} onChange={(value) => updateDraft("youtubeCommentVideoLimit", value)} />
            <SourceNumberField label={t("sourceSettings.youtubeCommentsPerVideo")} max={50} min={0} value={draft.youtubeCommentsPerVideo} onChange={(value) => updateDraft("youtubeCommentsPerVideo", value)} />
            <div className="settings-path wide-field">
              <Youtube size={16} />
              <span>{formatMessage(t("sourceSettings.youtubeSummary"), {
                videos: draft.youtubeVideoLimit,
                transcripts: draft.youtubeTranscriptVideoLimit,
                commentVideos: draft.youtubeCommentVideoLimit,
                comments: draft.youtubeCommentsPerVideo,
              })}</span>
            </div>
          </>
        ) : null}

        {source === "tiktok" ? (
          <>
            <SourceNumberField label={t("sourceSettings.tiktokVideoLimit")} max={30} min={1} value={draft.tiktokVideoLimit} onChange={(value) => updateDraft("tiktokVideoLimit", value)} />
            <SourceNumberField label={t("sourceSettings.tiktokCommentsPerVideo")} max={50} min={1} value={draft.tiktokCommentsPerVideo} onChange={(value) => updateDraft("tiktokCommentsPerVideo", value)} />
            <div className="settings-path wide-field">
              <Megaphone size={16} />
              <span>{formatMessage(t("sourceSettings.tiktokSummary"), {
                videos: draft.tiktokVideoLimit,
                comments: draft.tiktokCommentsPerVideo,
              })}</span>
            </div>
          </>
        ) : null}

        <div className="source-settings-actions wide-field">
          <button type="button" className="secondary-action" onClick={onClose}>{t("sourceSettings.back")}</button>
          <button type="button" disabled={saving} onClick={saveSourceSettings}>
            {saving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
            {t("sourceSettings.save")}
          </button>
        </div>
        {message ? <div className="alert subtle wide-field">{message}</div> : null}
      </div>
    </section>
  );
}

function SourceNumberField({
  label,
  max,
  min,
  onChange,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  value: number;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function HistoryResearchView({
  busy,
  items,
  locale,
  onDelete,
  onRestore,
  onSelect,
  selectedItem,
  storagePath,
  t,
}: {
  busy: boolean;
  items: ResearchHistorySummary[];
  locale: Locale;
  onDelete: (id: string) => void;
  onRestore: (item: ResearchHistoryItem) => void;
  onSelect: (id: string) => void;
  selectedItem: ResearchHistoryItem | null;
  storagePath: string;
  t: Translator;
}) {
  const [activeReportTab, setActiveReportTab] = useState<HistoryReportTab>("combined");
  const reportTabs = selectedItem ? historyReportTabs(selectedItem, t) : [];

  useEffect(() => {
    if (selectedItem && reportTabs.length) {
      setActiveReportTab(reportTabs[0].key);
    }
  }, [selectedItem?.id]);

  return (
    <section className="history-workspace">
      <div className="history-workspace-head">
        <div>
          <h3>{t("history.title")}</h3>
          <p>{formatMessage(t("history.storage"), { path: storagePath })}</p>
        </div>
        <span>{formatMessage(t("history.recordCount"), { count: items.length })}</span>
      </div>

      <div className="history-browser-grid">
        <section className="history-record-panel">
          <PanelTitle title={t("history.records")} subtitle={t("history.recordsSubtitle")} />
          {items.length ? (
            <div className="history-record-list">
              {items.map((item) => (
                <article className={`history-record${selectedItem?.id === item.id ? " active" : ""}`} key={item.id}>
                  <button type="button" className="history-record-main" disabled={busy} onClick={() => onSelect(item.id)}>
                    <span>{shortDate(item.saved_at, locale)}</span>
                    <strong>{item.category}</strong>
                    <p>{item.summary || t("history.noSummary")}</p>
                    <HistoryChips item={item} t={t} />
                  </button>
                  <button type="button" className="history-record-delete" disabled={busy} onClick={() => onDelete(item.id)} title={t("history.delete")}>
                    <Trash2 size={15} />
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <p className="history-empty">{t("history.empty")}</p>
          )}
        </section>

        <section className="history-detail-panel">
          {busy && !selectedItem ? <LoadingPanel text={t("history.loading")} /> : null}
          {!busy && !selectedItem ? (
            <div className="empty-state history-detail-empty">
              <FolderOpen size={36} />
              <h3>{t("history.selectTitle")}</h3>
              <p>{t("history.selectBody")}</p>
            </div>
          ) : null}
          {selectedItem ? (
            <div className="history-detail">
              <div className="history-detail-head">
                <div>
                  <p className="eyebrow">{t("history.fullResults")}</p>
                  <h3>{selectedItem.category}</h3>
                  <p>{shortDate(selectedItem.saved_at, locale)} · {selectedItem.summary || t("history.noSummary")}</p>
                  <HistoryChips item={selectedItem} t={t} />
                </div>
                <div className="history-detail-actions">
                  <button type="button" disabled={busy} onClick={() => onRestore(selectedItem)}>
                    <FolderOpen size={15} />
                    {t("history.restore")}
                  </button>
                  <button type="button" className="danger-action" disabled={busy} onClick={() => onDelete(selectedItem.id)}>
                    <Trash2 size={15} />
                    {t("history.delete")}
                  </button>
                </div>
              </div>

              <div className="history-report-tabs" role="tablist" aria-label={t("history.reportTabs")}>
                {reportTabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    className={activeReportTab === tab.key ? "active" : ""}
                    onClick={() => setActiveReportTab(tab.key)}
                  >
                    {tab.icon}
                    {tab.label}
                    <span>{tab.count}</span>
                  </button>
                ))}
              </div>

              <section className="history-report-page">
                {activeReportTab === "combined" && selectedItem.combined_report ? (
                  <CombinedInsightView locale={locale} report={selectedItem.combined_report} t={t} />
                ) : null}
                {activeReportTab === "reddit" && selectedItem.reddit_report ? (
                  <ReportView locale={locale} report={selectedItem.reddit_report} t={t} />
                ) : null}
                {activeReportTab === "amazon" && selectedItem.amazon_report ? (
                  <AmazonReportView locale={locale} report={selectedItem.amazon_report} t={t} />
                ) : null}
                {activeReportTab === "youtube" && selectedItem.youtube_report ? (
                  <YouTubeReportView locale={locale} report={selectedItem.youtube_report} t={t} />
                ) : null}
                {activeReportTab === "tiktok" && selectedItem.tiktok_report ? (
                  <TikTokReportView locale={locale} report={selectedItem.tiktok_report} t={t} />
                ) : null}
                {activeReportTab === "articles" && selectedItem.article_report ? (
                  <ArticleReportView locale={locale} report={selectedItem.article_report} t={t} />
                ) : null}
              </section>
            </div>
          ) : null}
        </section>
      </div>
    </section>
  );
}

function historyReportTabs(item: ResearchHistoryItem, t: Translator): Array<{
  key: HistoryReportTab;
  label: string;
  count: number;
  icon: ReactNode;
}> {
  const tabs: Array<{
    key: HistoryReportTab;
    label: string;
    count: number;
    icon: ReactNode;
  }> = [];
  if (item.combined_report) {
    tabs.push({
      key: "combined",
      label: t("source.combined"),
      count: item.evidence_items,
      icon: <Sparkles size={15} />,
    });
  }
  if (item.reddit_report) {
    tabs.push({
      key: "reddit",
      label: t("source.reddit"),
      count: item.reddit_posts,
      icon: <MessageSquare size={15} />,
    });
  }
  if (item.amazon_report) {
    tabs.push({
      key: "amazon",
      label: t("source.amazon"),
      count: item.amazon_products,
      icon: <ShoppingBag size={15} />,
    });
  }
  if (item.youtube_report) {
    tabs.push({
      key: "youtube",
      label: t("source.youtube"),
      count: item.youtube_videos,
      icon: <Youtube size={15} />,
    });
  }
  if (item.tiktok_report) {
    tabs.push({
      key: "tiktok",
      label: t("source.tiktok"),
      count: item.tiktok_videos,
      icon: <Megaphone size={15} />,
    });
  }
  if (item.article_report) {
    tabs.push({
      key: "articles",
      label: t("source.articles"),
      count: item.article_count,
      icon: <FileText size={15} />,
    });
  }
  return tabs;
}

function HistoryChips({ item, t }: { item: ResearchHistorySummary; t: Translator }) {
  return (
    <div className="history-chips">
      {item.has_combined ? <span>{t("source.combined")} · {item.evidence_items}</span> : null}
      {item.has_reddit ? <span>{t("source.reddit")} · {item.reddit_posts}</span> : null}
      {item.has_amazon ? <span>{t("source.amazon")} · {item.amazon_products}</span> : null}
      {item.has_youtube ? <span>{t("source.youtube")} · {item.youtube_videos}</span> : null}
      {item.has_tiktok ? <span>{t("source.tiktok")} · {item.tiktok_videos}</span> : null}
      {item.has_articles ? <span>{t("source.articles")} · {item.article_count}</span> : null}
    </div>
  );
}

function EmptyState({ t }: { t: Translator }) {
  return (
    <section className="empty-state">
      <MessageSquare size={36} />
      <h3>{t("research.emptyTitle")}</h3>
      <p>{t("research.emptyBody")}</p>
    </section>
  );
}

function ArticleEmptyState({ t }: { t: Translator }) {
  return (
    <section className="empty-state">
      <FileText size={36} />
      <h3>{t("articles.emptyTitle")}</h3>
      <p>{t("articles.emptyBody")}</p>
    </section>
  );
}

function YouTubeEmptyState({ t }: { t: Translator }) {
  return (
    <section className="empty-state">
      <Youtube size={36} />
      <h3>{t("youtube.emptyTitle")}</h3>
      <p>{t("youtube.emptyBody")}</p>
    </section>
  );
}

function TikTokEmptyState({ t }: { t: Translator }) {
  return (
    <section className="empty-state">
      <Megaphone size={36} />
      <h3>{t("tiktok.emptyTitle")}</h3>
      <p>{t("tiktok.emptyBody")}</p>
    </section>
  );
}

function LoadingPanel({ text }: { text: string }) {
  return (
    <section className="loading-panel">
      <Loader2 className="spin" size={22} />
      <span>{text}</span>
    </section>
  );
}

function CombinedEmptyState({
  redditReady,
  amazonReady,
  t,
}: {
  redditReady: boolean;
  amazonReady: boolean;
  t: Translator;
}) {
  return (
    <section className="empty-state">
      <Sparkles size={36} />
      <h3>{t("combined.emptyTitle")}</h3>
      <p>
        {formatMessage(t("combined.emptyBody"), {
          reddit: redditReady ? t("combined.ready") : t("combined.missing"),
          amazon: amazonReady ? t("combined.ready") : t("combined.missing"),
        })}
      </p>
    </section>
  );
}

function CombinedInsightView({ report, t }: { report: CombinedInsightReport } & LocalizedProps) {
  const exportBaseName = `insight-${slugify(report.category)}-${report.generated_at.slice(0, 10)}`;
  return (
    <div className="report-grid combined-grid">
      <section className="panel wide verdict-panel">
        <div className="combined-head">
          <PanelTitle title={t("combined.title")} subtitle={t("combined.subtitle")} />
          <div className="combined-actions">
            <button
              type="button"
              className="secondary-action"
              onClick={() => downloadText(`${exportBaseName}.md`, combinedReportToMarkdown(report, t), "text/markdown")}
            >
              <FileText size={16} />
              {t("combined.exportMarkdown")}
            </button>
            <button
              type="button"
              onClick={() => downloadText(`${exportBaseName}.html`, combinedReportToHtml(report, t), "text/html")}
            >
              <Download size={16} />
              {t("combined.exportHtml")}
            </button>
          </div>
        </div>
        {report.llm_analysis.status !== "ok" ? (
          <div className="alert warning">{report.llm_analysis.message || t("combined.localFallback")}</div>
        ) : null}
        <div className="verdict-copy">
          <span>{t("combined.verdict")}</span>
          <strong>{report.verdict.text}</strong>
          <CitationLinks citations={report.verdict.citations} t={t} />
        </div>
        <div className="combined-summary-grid">
          <div><span>{t("combined.redditPosts")}</span><b>{report.data_summary.reddit_posts}</b></div>
          <div><span>{t("combined.redditComments")}</span><b>{report.data_summary.reddit_comments}</b></div>
          <div><span>{t("combined.amazonProducts")}</span><b>{report.data_summary.amazon_products}</b></div>
          <div><span>{t("combined.amazonReviews")}</span><b>{report.data_summary.amazon_review_samples}</b></div>
        </div>
      </section>

      <InsightSection
        icon={<Lightbulb size={18} />}
        title={t("combined.opportunities")}
        subtitle={t("combined.opportunitiesSubtitle")}
        items={report.opportunities}
        t={t}
      />
      <InsightSection
        icon={<ShieldAlert size={18} />}
        title={t("combined.risks")}
        subtitle={t("combined.risksSubtitle")}
        items={report.risks}
        t={t}
      />
      <InsightSection
        icon={<FlaskConical size={18} />}
        title={t("combined.rdRecommendations")}
        subtitle={t("combined.rdSubtitle")}
        items={report.rd_recommendations}
        t={t}
      />
      <InsightSection
        icon={<Megaphone size={18} />}
        title={t("combined.brandCommunication")}
        subtitle={t("combined.brandSubtitle")}
        items={report.brand_communication}
        t={t}
      />

      <section className="panel wide evidence-chain-panel">
        <PanelTitle title={t("combined.evidenceChain")} subtitle={t("combined.evidenceChainSubtitle")} />
        <div className="evidence-chain-list">
          {report.evidence_chain.map((item, index) => (
            <article className="insight-item" key={`${item.claim}-${index}`}>
              <span className="evidence-index">#{index + 1}</span>
              <h4>{item.claim}</h4>
              <p>{item.detail}</p>
              <CitationLinks citations={item.citations} t={t} />
            </article>
          ))}
        </div>
      </section>

      <InsightSection
        icon={<Database size={18} />}
        title={t("combined.dataGaps")}
        subtitle={t("combined.dataGapsSubtitle")}
        items={report.data_gaps}
        t={t}
        wide
      />
    </div>
  );
}

function InsightSection({
  icon,
  title,
  subtitle,
  items,
  t,
  wide = false,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  items: CombinedInsightItem[];
  t: Translator;
  wide?: boolean;
}) {
  return (
    <section className={`panel insight-section${wide ? " wide" : ""}`}>
      <div className="insight-section-title">
        {icon}
        <PanelTitle title={title} subtitle={subtitle} />
      </div>
      <div className="stack">
        {items.map((item, index) => (
          <article className="insight-item" key={`${item.title}-${index}`}>
            <h4>{item.title}</h4>
            <p>{item.detail}</p>
            <CitationLinks citations={item.citations} t={t} />
          </article>
        ))}
      </div>
    </section>
  );
}

function CitationLinks({ citations, t }: { citations: InsightCitation[]; t: Translator }) {
  return (
    <div className="citation-links">
      {citations.map((citation) => (
        <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer" className="citation-link">
          <Link2 size={13} />
          {citation.source === "reddit" ? t("source.reddit") : t("source.amazon")} · {citation.kind} · {citation.id}
          <span className="citation-preview" role="tooltip">
            <strong>{citation.title}</strong>
            <small>{citation.reference}</small>
            <span>{citation.excerpt}</span>
          </span>
        </a>
      ))}
    </div>
  );
}

function ArticleDiscoveryView({
  onAppendUrl,
  onUseUrls,
  report,
  selectedUrls,
  t,
}: {
  onAppendUrl: (url: string) => void;
  onUseUrls: () => void;
  report: ArticleDiscoveryReport;
  selectedUrls: string[];
  t: Translator;
}) {
  return (
    <div className="report-grid article-discovery-grid">
      <section className="panel wide article-discovery-panel">
        <div className="combined-head">
          <PanelTitle
            title={t("articles.discoveryTitle")}
            subtitle={formatMessage(t("articles.discoverySubtitle"), {
              provider: report.source.source_name,
              count: report.data_volume.candidate_count,
            })}
          />
          <div className="combined-actions">
            <button type="button" onClick={onUseUrls}>
              <FileText size={16} />
              {t("articles.useDiscovered")}
            </button>
          </div>
        </div>
        <div className="competitor-audit-grid article-discovery-audit">
          <div>
            <span>{t("articles.discoveryQueries")}</span>
            <strong>{formatInteger(report.data_volume.query_count)}</strong>
            <p>{formatMessage(t("articles.discoveryResultsPerQuery"), { count: report.data_volume.results_per_query })}</p>
          </div>
          <div>
            <span>{t("articles.discoveryRawResults")}</span>
            <strong>{formatInteger(report.data_volume.raw_results)}</strong>
            <p>{formatMessage(t("articles.discoveryUniqueResults"), { count: report.data_volume.unique_results })}</p>
          </div>
          <div>
            <span>{t("articles.discoveryCandidates")}</span>
            <strong>{formatInteger(report.data_volume.candidate_count)}</strong>
            <p>{report.source.next_action}</p>
          </div>
        </div>
        {report.warnings.length ? (
          <div className="alert subtle">{report.warnings.slice(0, 4).join(" ")}</div>
        ) : null}
        <div className="query-chip-list">
          <span>{t("articles.generatedQueries")}</span>
          {report.queries.slice(0, 12).map((query) => <b key={query}>{query}</b>)}
        </div>
        <div className="article-discovery-list">
          {report.candidates.map((candidate) => (
            <ArticleDiscoveryCandidateCard
              candidate={candidate}
              key={candidate.url}
              onAppendUrl={onAppendUrl}
              selected={selectedUrls.includes(candidate.url)}
              t={t}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function ArticleDiscoveryCandidateCard({
  candidate,
  onAppendUrl,
  selected,
  t,
}: {
  candidate: ArticleDiscoveryCandidate;
  onAppendUrl: (url: string) => void;
  selected: boolean;
  t: Translator;
}) {
  return (
    <article className="article-discovery-card">
      <div className="article-card-head">
        <div>
          <a href={candidate.url} target="_blank" rel="noreferrer">{candidate.title || candidate.url}</a>
          <p>
            {candidate.domain} · {articleSourceTypeLabel(candidate.source_type, t)} · {t("articles.score")} {candidate.score}
          </p>
        </div>
        <button type="button" disabled={selected} onClick={() => onAppendUrl(candidate.url)}>
          {selected ? t("articles.urlAdded") : t("articles.addUrl")}
        </button>
      </div>
      {candidate.snippet ? <p className="summary-text">{candidate.snippet}</p> : null}
      <div className="article-discovery-meta">
        <span>{t("articles.fromQuery")}: {candidate.query}</span>
        <span>{t("articles.rank")}: {candidate.rank}</span>
      </div>
      {candidate.reasons.length ? (
        <div className="chips article-chip-row">
          {candidate.reasons.map((reason) => <span key={`${candidate.url}-${reason}`}>{reason}</span>)}
        </div>
      ) : null}
    </article>
  );
}

function YouTubeReportView({ locale, report, t }: { report: YouTubeReport } & LocalizedProps) {
  return (
    <div className="report-grid youtube-grid">
      <section className="metric-card hero-metric">
        <span>{t("youtube.videos")}</span>
        <strong>{formatInteger(report.metrics.videos)}</strong>
        <p>{confidenceLabel(report.confidence, locale)} · {sourceLabel(report.source_mode, locale)}</p>
      </section>
      <section className="metric-card">
        <span>{t("youtube.totalViews")}</span>
        <strong>{formatCompactNumber(report.metrics.total_views)}</strong>
        <p>{formatMessage(t("youtube.avgViews"), { count: formatCompactNumber(report.metrics.average_views) })}</p>
      </section>
      <section className="metric-card">
        <span>{t("youtube.comments")}</span>
        <strong>{formatInteger(report.data_volume.comment_samples)}</strong>
        <p>{formatMessage(t("youtube.publicCommentCount"), { count: formatCompactNumber(report.metrics.total_comment_count) })}</p>
      </section>

      <section className="panel wide data-volume-panel">
        <PanelTitle title={t("youtube.auditTitle")} subtitle={t("youtube.auditSubtitle")} />
        <div className="data-volume-grid">
          <div className="volume-stat">
            <span>{t("youtube.requestedVideos")}</span>
            <strong>{formatInteger(report.data_volume.collected_videos)}</strong>
            <p>{formatMessage(t("youtube.requestedVideosNote"), {
              requested: report.data_volume.requested_videos,
              collected: report.data_volume.collected_videos,
            })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("youtube.transcripts")}</span>
            <strong>{formatInteger(report.data_volume.videos_with_transcripts)}</strong>
            <p>{formatMessage(t("youtube.transcriptsNote"), {
              limit: report.data_volume.transcript_video_limit,
              chars: formatInteger(report.data_volume.transcript_chars),
            })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("youtube.commentSamples")}</span>
            <strong>{formatInteger(report.data_volume.comment_samples)}</strong>
            <p>{formatMessage(t("youtube.commentSamplesNote"), {
              videos: report.data_volume.comment_video_limit,
              comments: report.data_volume.comments_per_video_limit,
            })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("youtube.channels")}</span>
            <strong>{formatInteger(report.metrics.channels)}</strong>
            <p>{report.source.next_action}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("youtube.channelTitle")} subtitle={t("youtube.channelSubtitle")} />
        <div className="chips">
          {report.channels.length ? report.channels.map((channel) => (
            <span key={channel.name}>{channel.name} <b>{channel.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>
      <section className="panel">
        <PanelTitle title={t("youtube.signalTitle")} subtitle={t("youtube.signalSubtitle")} />
        <div className="chips">
          {report.product_signals.length ? report.product_signals.map((signal) => (
            <span key={signal.name}>{signal.name} <b>{signal.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>

      {report.warnings.length ? (
        <section className="panel wide">
          <PanelTitle title={t("youtube.warningTitle")} subtitle={t("youtube.warningSubtitle")} />
          <ul className="article-note-list">
            {report.warnings.slice(0, 12).map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </section>
      ) : null}

      <section className="panel wide">
        <PanelTitle title={t("youtube.evidenceTitle")} subtitle={formatMessage(t("youtube.evidenceSubtitle"), { count: report.videos.length })} />
        <div className="article-list youtube-video-list">
          {report.videos.map((video, index) => (
            <article className="article-card youtube-video-card" key={video.id || `${video.url}-${index}`}>
              <div className="article-card-head">
                <div>
                  <span className="evidence-index">#{index + 1}</span>
                  <a href={video.url} target="_blank" rel="noreferrer">{video.title}</a>
                  <p>
                    {video.channel || t("youtube.unknownChannel")} · {shortDate(video.upload_date || video.fetched_at, locale)} · {formatDuration(video.duration_seconds)} · {formatCompactNumber(video.view_count)} {t("youtube.views")}
                  </p>
                </div>
                {video.thumbnail ? <img className="youtube-thumb" src={video.thumbnail} alt="" loading="lazy" /> : null}
              </div>
              {video.description ? <p className="summary-text">{video.description}</p> : null}
              {video.tags.length ? (
                <div className="chips article-chip-row">
                  {video.tags.slice(0, 8).map((tag) => <span key={`${video.id}-${tag}`}>{tag}</span>)}
                </div>
              ) : null}
              {video.transcript ? (
                <div className="youtube-transcript-preview">
                  <h5>{t("youtube.transcriptPreview")}</h5>
                  <p>{video.transcript}</p>
                </div>
              ) : null}
              {video.comment_samples.length ? (
                <div className="comment-list">
                  {video.comment_samples.slice(0, 10).map((comment, commentIndex) => (
                    <div className="comment-item" key={comment.id || `${video.id}-comment-${commentIndex}`}>
                      <p>{comment.text}</p>
                      <span>{comment.author || "YouTube"} · {comment.like_count ?? 0}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.methodTitle")} subtitle={t("report.methodSubtitle")} />
        <div className="method-grid">
          <div>
            <h4>{t("report.query")}</h4>
            <p>{report.method.query}</p>
          </div>
          <div>
            <h4>{t("report.notes")}</h4>
            <ul>
              {report.method.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function TikTokReportView({ locale, report, t }: { report: TikTokReport } & LocalizedProps) {
  return (
    <div className="report-grid youtube-grid">
      <section className="metric-card hero-metric">
        <span>{t("tiktok.videos")}</span>
        <strong>{formatInteger(report.metrics.videos)}</strong>
        <p>{confidenceLabel(report.confidence, locale)} · {sourceLabel(report.source_mode, locale)}</p>
      </section>
      <section className="metric-card">
        <span>{t("tiktok.totalViews")}</span>
        <strong>{formatCompactNumber(report.metrics.total_views)}</strong>
        <p>{formatMessage(t("tiktok.avgViews"), { count: formatCompactNumber(report.metrics.average_views) })}</p>
      </section>
      <section className="metric-card">
        <span>{t("tiktok.detailComments")}</span>
        <strong>{formatInteger(report.data_volume.comment_samples)}</strong>
        <p>{formatMessage(t("tiktok.publicCommentCount"), { count: formatCompactNumber(report.metrics.total_comment_count) })}</p>
      </section>

      <section className="panel wide data-volume-panel">
        <PanelTitle title={t("tiktok.auditTitle")} subtitle={t("tiktok.auditSubtitle")} />
        <div className="data-volume-grid">
          <div className="volume-stat">
            <span>{t("tiktok.requestedVideos")}</span>
            <strong>{formatInteger(report.data_volume.collected_videos)}</strong>
            <p>{formatMessage(t("tiktok.requestedVideosNote"), {
              requested: report.data_volume.requested_videos,
              collected: report.data_volume.collected_videos,
            })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("tiktok.detailPages")}</span>
            <strong>{formatInteger(report.data_volume.detail_pages_visited)}</strong>
            <p>{t("tiktok.detailPagesNote")}</p>
          </div>
          <div className="volume-stat">
            <span>{t("tiktok.commentSamples")}</span>
            <strong>{formatInteger(report.data_volume.comment_samples)}</strong>
            <p>{formatMessage(t("tiktok.commentSamplesNote"), {
              videos: report.data_volume.videos_with_comment_samples,
              comments: report.data_volume.comments_per_video_limit,
            })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("tiktok.authors")}</span>
            <strong>{formatInteger(report.metrics.authors)}</strong>
            <p>{report.source.next_action}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("tiktok.authorTitle")} subtitle={t("tiktok.authorSubtitle")} />
        <div className="chips">
          {report.authors.length ? report.authors.map((author) => (
            <span key={author.name}>{author.name} <b>{author.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>
      <section className="panel">
        <PanelTitle title={t("tiktok.hashtagTitle")} subtitle={t("tiktok.hashtagSubtitle")} />
        <div className="chips">
          {report.hashtags.length ? report.hashtags.map((hashtag) => (
            <span key={hashtag.name}>#{hashtag.name} <b>{hashtag.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>
      <section className="panel">
        <PanelTitle title={t("tiktok.signalTitle")} subtitle={t("tiktok.signalSubtitle")} />
        <div className="chips">
          {report.product_signals.length ? report.product_signals.map((signal) => (
            <span key={signal.name}>{signal.name} <b>{signal.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>

      {report.warnings.length ? (
        <section className="panel wide">
          <PanelTitle title={t("tiktok.warningTitle")} subtitle={t("tiktok.warningSubtitle")} />
          <ul className="article-note-list">
            {report.warnings.slice(0, 12).map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </section>
      ) : null}

      <section className="panel wide">
        <PanelTitle title={t("tiktok.evidenceTitle")} subtitle={formatMessage(t("tiktok.evidenceSubtitle"), { count: report.videos.length })} />
        <div className="article-list youtube-video-list">
          {report.videos.map((video, index) => (
            <article className="article-card youtube-video-card" key={video.id || `${video.url}-${index}`}>
              <div className="article-card-head">
                <div>
                  <span className="evidence-index">#{index + 1}</span>
                  <a href={video.url} target="_blank" rel="noreferrer">{video.title || video.caption || video.url}</a>
                  <p>
                    {video.author || t("tiktok.unknownAuthor")} · {shortDate(video.published_at || video.fetched_at, locale)} · {formatCompactNumber(video.view_count)} {t("tiktok.views")} · {formatCompactNumber(video.like_count)} {t("tiktok.likes")}
                  </p>
                </div>
                {video.cover_url ? <img className="youtube-thumb" src={video.cover_url} alt="" loading="lazy" /> : null}
              </div>
              {video.caption ? <p className="summary-text">{video.caption}</p> : null}
              {video.hashtags.length ? (
                <div className="chips article-chip-row">
                  {video.hashtags.slice(0, 10).map((tag) => <span key={`${video.id}-${tag}`}>#{tag}</span>)}
                </div>
              ) : null}
              <div className="chips article-chip-row">
                <span>{formatCompactNumber(video.comment_count)} {t("tiktok.comments")}</span>
                <span>{formatCompactNumber(video.share_count)} {t("tiktok.shares")}</span>
                <span>{formatCompactNumber(video.save_count)} {t("tiktok.saves")}</span>
              </div>
              {video.comment_samples.length ? (
                <div className="comment-list">
                  {video.comment_samples.slice(0, 12).map((comment, commentIndex) => (
                    <div className="comment-item" key={comment.id || `${video.id}-tiktok-comment-${commentIndex}`}>
                      <p>{comment.text}</p>
                      <span>{comment.author || "TikTok"} · {comment.like_count ?? 0}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="no-comments">{t("tiktok.noCommentSamples")}</p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.methodTitle")} subtitle={t("report.methodSubtitle")} />
        <div className="method-grid">
          <div>
            <h4>{t("report.query")}</h4>
            <p>{report.method.query}</p>
          </div>
          <div>
            <h4>{t("report.notes")}</h4>
            <ul>
              {report.method.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function ArticleReportView({ locale, report, t }: { report: ArticleReport } & LocalizedProps) {
  return (
    <div className="report-grid article-grid">
      <section className="metric-card hero-metric">
        <span>{t("articles.collected")}</span>
        <strong>{report.data_volume.collected_articles}</strong>
        <p>{report.source.source_name} · {report.source.status}</p>
      </section>
      <section className="metric-card">
        <span>{t("articles.highAuthority")}</span>
        <strong>{report.data_volume.high_authority_articles}</strong>
        <p>{formatMessage(t("articles.mediumLowAuthority"), {
          medium: report.data_volume.medium_authority_articles,
          low: report.data_volume.low_authority_articles,
        })}</p>
      </section>
      <section className="metric-card">
        <span>{t("articles.evidenceSnippets")}</span>
        <strong>{report.data_volume.evidence_snippets}</strong>
        <p>{formatMessage(t("articles.failedArticles"), { count: report.data_volume.failed_articles })}</p>
      </section>

      <section className="panel wide data-volume-panel">
        <PanelTitle title={t("articles.auditTitle")} subtitle={t("articles.auditSubtitle")} />
        <div className="data-volume-grid">
          <div className="volume-stat">
            <span>{t("articles.requestedArticles")}</span>
            <strong>{report.data_volume.requested_articles}</strong>
            <p>{formatMessage(t("articles.requestedArticlesNote"), { collected: report.data_volume.collected_articles })}</p>
          </div>
          <div className="volume-stat">
            <span>{t("articles.sourceStatus")}</span>
            <strong>{report.source.status}</strong>
            <p>{report.source.next_action}</p>
          </div>
          <div className="volume-stat">
            <span>{t("articles.sourceTypes")}</span>
            <strong>{report.summary.source_types.length}</strong>
            <p>{report.summary.source_types.map((item) => `${articleSourceTypeLabel(item.name, t)} ${item.count}`).join(" / ") || t("articles.noSummary")}</p>
          </div>
          <div className="volume-stat">
            <span>{t("articles.domains")}</span>
            <strong>{report.summary.top_domains.length}</strong>
            <p>{report.summary.top_domains.slice(0, 3).map((item) => item.name).join(" / ") || t("articles.noSummary")}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("articles.brandMentions")} subtitle={t("articles.brandMentionsSubtitle")} />
        <div className="chips">
          {report.summary.top_brands.length ? report.summary.top_brands.map((brand) => (
            <span key={brand.name}>{brand.name} <b>{brand.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>
      <section className="panel">
        <PanelTitle title={t("articles.productSignals")} subtitle={t("articles.productSignalsSubtitle")} />
        <div className="chips">
          {report.summary.top_signals.length ? report.summary.top_signals.map((signal) => (
            <span key={signal.name}>{signal.name} <b>{signal.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>

      {report.warnings.length ? (
        <section className="panel wide">
          <PanelTitle title={t("articles.warningTitle")} subtitle={t("articles.warningSubtitle")} />
          <ul className="article-note-list">
            {report.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </section>
      ) : null}

      <section className="panel wide">
        <PanelTitle title={t("articles.articleEvidenceTitle")} subtitle={formatMessage(t("articles.articleEvidenceSubtitle"), { count: report.articles.length })} />
        <div className="article-list">
          {report.articles.map((article, index) => (
            <article className="article-card" key={`${article.url}-${index}`}>
              <div className="article-card-head">
                <div>
                  <span className="evidence-index">#{index + 1}</span>
                  <a href={article.url} target="_blank" rel="noreferrer">{article.title}</a>
                  <p>
                    {article.domain} · {articleSourceTypeLabel(article.source_type, t)} · {formatInteger(article.readable_chars)} {t("articles.readableChars")} · {shortDate(article.fetched_at, locale)}
                  </p>
                </div>
                <span className={`authority-badge ${article.authority_level.toLowerCase()}`}>
                  {confidenceLabel(article.authority_level, locale)} · {article.authority_score}
                </span>
              </div>
              {article.brand_mentions.length || article.product_signals.length ? (
                <div className="chips article-chip-row">
                  {article.brand_mentions.slice(0, 8).map((brand) => <span key={`${article.url}-${brand}`}>{brand}</span>)}
                  {article.product_signals.slice(0, 8).map((signal) => <span key={`${article.url}-${signal}`}>{signal}</span>)}
                </div>
              ) : null}
              <div className="article-reason-grid">
                <div>
                  <h5>{t("articles.authorityEvidence")}</h5>
                  <ul>
                    {(article.authority_evidence.length ? article.authority_evidence : [t("articles.noAuthorityEvidence")]).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div>
                  <h5>{t("articles.cautions")}</h5>
                  <ul>
                    {(article.cautions.length ? article.cautions : [t("articles.noCautions")]).map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              </div>
              <div className="article-snippets">
                {article.evidence_snippets.map((snippet, snippetIndex) => (
                  <p key={`${article.url}-snippet-${snippetIndex}`}>{snippet}</p>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.methodTitle")} subtitle={t("report.methodSubtitle")} />
        <div className="method-grid">
          <div>
            <h4>{t("report.query")}</h4>
            <p>{report.method.query}</p>
          </div>
          <div>
            <h4>{t("report.notes")}</h4>
            <ul>
              {report.method.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function articleSourceTypeLabel(value: string, t: Translator): string {
  return t(`articles.sourceType.${value}`, value.replace(/_/g, " "));
}

function ReportView({ locale, report, t }: { report: AnalysisReport } & LocalizedProps) {
  const volume = report.data_volume;
  const brandSizeMentions = useMemo(
    () => [
      ...report.brands.map((item) => ({ ...item, type: t("report.brand") })),
      ...report.sizes.map((item) => ({ ...item, type: t("report.size") })),
    ].slice(0, 10),
    [report.brands, report.sizes, t],
  );

  return (
    <div className="report-grid">
      <section className="metric-card hero-metric">
        <span>{t("report.marketSignal")}</span>
        <strong>{report.market_signal.score}/100</strong>
        <p>{report.market_signal.summary}</p>
      </section>
      <section className="metric-card">
        <span>{t("report.coverage")}</span>
        <strong>{report.coverage.posts}</strong>
        <p>
          {report.coverage.subreddits} {t("report.subreddits")} · {confidenceLabel(report.coverage.confidence, locale)}
        </p>
      </section>
      <section className="metric-card">
        <span>{t("report.sentiment")}</span>
        <strong>{pct(report.sentiment.negative_share)}</strong>
        <p>{t("report.sentimentNote")}</p>
      </section>

      <section className="panel wide data-volume-panel">
        <PanelTitle title={t("report.volumeTitle")} subtitle={t("report.volumeSubtitle")} />
        <div className="data-volume-grid">
          <div className="volume-stat">
            <span>{t("report.collectedPosts")}</span>
            <strong>{volume.collected_posts}</strong>
            <p>
              {formatMessage(t("report.collectedPostsNote"), {
                requested: volume.requested_posts,
                actual: volume.collected_posts,
              })}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("report.collectedComments")}</span>
            <strong>{volume.collected_comments}</strong>
            <p>
              {formatMessage(t("report.collectedCommentsNote"), {
                posts: volume.posts_with_collected_comments,
                detailLimit: volume.comment_enrichment_post_limit,
                commentLimit: volume.comments_per_enriched_post_limit,
              })}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("report.aiEvidencePosts")}</span>
            <strong>{volume.llm_requested ? volume.ai_evidence_posts : 0}</strong>
            <p>
              {volume.llm_requested
                ? formatMessage(t("report.aiEvidencePostsNote"), {
                  limit: volume.ai_evidence_post_limit,
                  actual: volume.ai_evidence_posts,
                })
                : t("report.noAiRequested")}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("report.aiCommentSamples")}</span>
            <strong>{volume.llm_requested ? volume.ai_comment_samples : 0}</strong>
            <p>
              {volume.llm_requested
                ? formatMessage(t("report.aiCommentSamplesNote"), {
                  limit: volume.ai_comment_samples_per_post_limit,
                  actual: volume.ai_comment_samples,
                })
                : t("report.noAiRequested")}
            </p>
          </div>
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.painTitle")} subtitle={t("report.painSubtitle")} />
        <TopicBarChart points={report.pain_points} />
      </section>
      <section className="panel">
        <PanelTitle title={t("report.trendTitle")} subtitle={t("report.trendSubtitle")} />
        {report.trend.length ? <TrendChart trend={report.trend} /> : <div className="chart-empty">{t("report.noTrend")}</div>}
      </section>
      <section className="panel">
        <PanelTitle title={t("report.sentimentMixTitle")} subtitle={t("report.sentimentMixSubtitle")} />
        <SentimentChart
          labels={{
            positive: t("chart.positive"),
            neutral: t("chart.neutral"),
            negative: t("chart.negative"),
          }}
          sentiment={report.sentiment}
        />
      </section>
      <section className="panel">
        <PanelTitle title={t("report.sourceCoverageTitle")} subtitle={t("report.sourceCoverageSubtitle")} />
        <CoverageChart subreddits={report.coverage.top_subreddits} />
      </section>

      <section className="panel">
        <PanelTitle title={t("report.opportunityTitle")} subtitle={t("report.opportunitySubtitle")} />
        <div className="stack">
          {report.opportunities.map((item) => (
            <article className="list-card" key={item.title}>
              <h4>{item.title}</h4>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("report.brandSizeTitle")} subtitle={t("report.brandSizeSubtitle")} />
        <div className="chips">
          {brandSizeMentions.length ? (
            brandSizeMentions.map((item) => (
              <span key={`${item.type}-${item.name}`}>
                {item.name} <b>{item.type} · {item.count}</b>
              </span>
            ))
          ) : (
            <p className="muted">{t("report.noMentions")}</p>
          )}
        </div>
      </section>

      {report.llm_analysis.enabled ? <LlmPanel report={report} t={t} /> : null}

      <section className="panel wide">
        <PanelTitle
          title={t("report.evidenceTitle")}
          subtitle={formatMessage(t("report.evidenceSubtitle"), { count: report.posts.length })}
        />
        <div className="evidence-list">
          {report.posts.map((post, index) => {
            const commentItems = (post.comment_items || []).filter((comment) => String(comment.text || "").trim());
            return (
              <article className="evidence-card" key={`${post.url}-${index}`}>
                <div className="evidence-card-head">
                  <div>
                    <span className="evidence-index">#{index + 1}</span>
                    <a href={post.url} target="_blank" rel="noreferrer">{post.title}</a>
                    <p>
                      r/{post.subreddit || "unknown"} · {shortDate(post.created_utc, locale)} · {t("report.postComments")}{" "}
                      {post.comments ?? 0}
                    </p>
                  </div>
                  <span>{post.source}</span>
                </div>
                <p className="evidence-excerpt">{post.excerpt || t("report.noSnippet")}</p>
                <div className="comment-audit">
                  <MessageSquare size={15} />
                  <span>
                    {t("report.commentBodies")} {commentItems.length}
                  </span>
                </div>
                {commentItems.length ? (
                  <div className="comment-list">
                    {commentItems.slice(0, 20).map((comment, commentIndex) => (
                      <div className="comment-item" key={comment.id || `${post.url}-comment-${commentIndex}`}>
                        <p>{comment.text}</p>
                        <span>
                          {comment.author ? `u/${comment.author}` : "Reddit"} · {comment.score ?? 0}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="no-comments">{t("report.noCommentBodies")}</p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.methodTitle")} subtitle={t("report.methodSubtitle")} />
        <div className="method-grid">
          <div>
            <h4>{t("report.query")}</h4>
            <p>{report.method.query}</p>
          </div>
          <div>
            <h4>{t("report.notes")}</h4>
            <ul>
              {report.method.notes.map((note) => <li key={note}>{note}</li>)}
              {report.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function AmazonReportView({ locale, report, t }: { report: AmazonReport } & LocalizedProps) {
  const priceRange = report.metrics.price_min !== null && report.metrics.price_max !== null
    ? `${formatCurrency(report.metrics.price_min)}-${formatCurrency(report.metrics.price_max)}`
    : t("amazon.noPrice");

  return (
    <div className="report-grid">
      <section className="metric-card hero-metric">
        <span>{t("amazon.products")}</span>
        <strong>{report.metrics.products}</strong>
        <p>{confidenceLabel(report.confidence, locale)} · {sourceLabel(report.source_mode, locale)}</p>
      </section>
      <section className="metric-card">
        <span>{t("amazon.priceRange")}</span>
        <strong>{priceRange}</strong>
        <p>{formatMessage(t("amazon.priceAvg"), { price: formatCurrency(report.metrics.price_avg) })}</p>
      </section>
      <section className="metric-card">
        <span>{t("amazon.ratingReviews")}</span>
        <strong>{report.metrics.rating_avg?.toFixed(1) || "-"}</strong>
        <p>{formatMessage(t("amazon.totalReviews"), { count: formatInteger(report.metrics.total_review_count) })}</p>
      </section>

      <section className="panel wide data-volume-panel">
        <PanelTitle title={t("amazon.volumeTitle")} subtitle={t("amazon.volumeSubtitle")} />
        <div className="data-volume-grid">
          <div className="volume-stat">
            <span>{t("amazon.keywordCoverage")}</span>
            <strong>{report.data_volume.query_count}</strong>
            <p>
              {formatMessage(t("amazon.keywordCoverageNote"), {
                perQuery: report.data_volume.requested_products_per_query,
                raw: report.data_volume.raw_collected_products,
                unique: report.data_volume.unique_products,
              })}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("amazon.collectedProducts")}</span>
            <strong>{report.data_volume.collected_products}</strong>
            <p>
              {formatMessage(t("amazon.collectedProductsNote"), {
                requested: report.data_volume.requested_products,
                actual: report.data_volume.collected_products,
              })}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("amazon.reviewSamples")}</span>
            <strong>{report.data_volume.collected_review_samples}</strong>
            <p>
              {formatMessage(t("amazon.reviewSamplesNote"), {
                products: report.data_volume.products_with_review_samples,
                limit: report.data_volume.discussion_product_limit,
              })}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("amazon.aiProducts")}</span>
            <strong>{report.data_volume.llm_requested ? report.data_volume.ai_products : 0}</strong>
            <p>
              {report.data_volume.llm_requested
                ? formatMessage(t("amazon.aiProductsNote"), {
                  limit: report.data_volume.ai_product_limit,
                  actual: report.data_volume.ai_products,
                })
                : t("report.noAiRequested")}
            </p>
          </div>
          <div className="volume-stat">
            <span>{t("amazon.aiReviews")}</span>
            <strong>{report.data_volume.llm_requested ? report.data_volume.ai_review_samples : 0}</strong>
            <p>
              {report.data_volume.llm_requested
                ? formatMessage(t("amazon.aiReviewsNote"), {
                  limit: report.data_volume.ai_review_samples_per_product_limit,
                  actual: report.data_volume.ai_review_samples,
                })
                : t("report.noAiRequested")}
            </p>
          </div>
        </div>
        {report.data_volume.per_query_counts.length ? (
          <div className="query-chip-list" aria-label={t("amazon.queriesUsed")}>
            <span>{t("amazon.queriesUsed")}</span>
            {report.data_volume.per_query_counts.map((item) => (
              <b key={item.query}>{item.query} · {item.count}</b>
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel">
        <PanelTitle title={t("amazon.brandTitle")} subtitle={t("amazon.brandSubtitle")} />
        <div className="chips">
          {report.brands.length ? report.brands.map((brand) => (
            <span key={brand.name}>{brand.name} <b>{brand.count}</b></span>
          )) : <p className="muted">{t("report.noMentions")}</p>}
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("amazon.priceBandsTitle")} subtitle={t("amazon.priceBandsSubtitle")} />
        <div className="chips">
          {report.price_bands.map((band) => (
            <span key={band.name}>{band.name} <b>{band.count}</b></span>
          ))}
        </div>
      </section>

      <section className="panel">
        <PanelTitle title={t("amazon.salesSignalsTitle")} subtitle={t("amazon.salesSignalsSubtitle")} />
        <div className="stack">
          <article className="list-card">
            <h4>{t("amazon.reviewCountSignal")}</h4>
            <p>{formatMessage(t("amazon.reviewCountSignalBody"), { count: formatInteger(report.metrics.total_review_count) })}</p>
          </article>
          <article className="list-card">
            <h4>{t("amazon.sponsoredSignal")}</h4>
            <p>{formatMessage(t("amazon.sponsoredSignalBody"), { count: report.metrics.sponsored_count })}</p>
          </article>
        </div>
      </section>

      {report.llm_analysis.enabled ? <LlmPanel report={report} t={t} /> : null}

      <section className="panel wide">
        <PanelTitle title={t("amazon.productsTitle")} subtitle={formatMessage(t("amazon.productsSubtitle"), { count: report.products.length })} />
        <div className="amazon-products">
          {report.products.map((product, index) => (
            <article className="amazon-product-card" key={product.asin || `${product.product_url}-${index}`}>
              <div className="amazon-product-head">
                <div>
                  <span className="evidence-index">#{product.rank || index + 1}</span>
                  <a href={product.product_url} target="_blank" rel="noreferrer">{product.title || product.asin}</a>
                  <p>
                    {product.brand || t("amazon.unknownBrand")} · {product.asin} · {product.price_text || t("amazon.noPrice")}
                  </p>
                </div>
                <span>{product.rating_value || "-"} / {formatInteger(product.review_count || 0)}</span>
              </div>
              {product.badges.length || product.is_sponsored ? (
                <div className="chips product-badges">
                  {product.is_sponsored ? <span>{t("amazon.sponsored")}</span> : null}
                  {product.badges.map((badge) => <span key={badge}>{badge}</span>)}
                </div>
              ) : null}
              {product.bullet_points.length ? (
                <ul className="product-bullets">
                  {product.bullet_points.slice(0, 5).map((point) => <li key={point}>{point}</li>)}
                </ul>
              ) : null}
              {product.review_samples.length ? (
                <div className="comment-list">
                  {product.review_samples.slice(0, 5).map((review, reviewIndex) => (
                    <div className="comment-item" key={`${product.asin}-review-${reviewIndex}`}>
                      <p>{review.title ? `${review.title}: ` : ""}{review.body}</p>
                      <span>
                        {review.rating_value || "-"} ★ · {review.verified_purchase ? t("amazon.verified") : t("amazon.unverified")}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="no-comments">{t("amazon.noReviewSamples")}</p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="panel wide">
        <PanelTitle title={t("report.methodTitle")} subtitle={t("report.methodSubtitle")} />
        <div className="method-grid">
          <div>
            <h4>{t("report.query")}</h4>
            <p>{report.method.query}</p>
          </div>
          <div>
            <h4>{t("report.notes")}</h4>
            <ul>
              {report.method.notes.map((note) => <li key={note}>{note}</li>)}
              {report.warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function combinedReportToMarkdown(report: CombinedInsightReport, t: Translator): string {
  const lines = [
    `# ${t("combined.title")} - ${report.category}`,
    "",
    `> ${report.verdict.text}`,
    "",
    citationMarkdown(report.verdict.citations),
    "",
    summaryMarkdown(report, t),
    "",
    itemSectionMarkdown(t("combined.opportunities"), report.opportunities),
    itemSectionMarkdown(t("combined.risks"), report.risks),
    itemSectionMarkdown(t("combined.rdRecommendations"), report.rd_recommendations),
    itemSectionMarkdown(t("combined.brandCommunication"), report.brand_communication),
    chainSectionMarkdown(t("combined.evidenceChain"), report.evidence_chain),
    itemSectionMarkdown(t("combined.dataGaps"), report.data_gaps),
  ];
  return lines.filter((line) => line !== null).join("\n");
}

function combinedReportToHtml(report: CombinedInsightReport, t: Translator): string {
  const sectionHtml = (title: string, items: CombinedInsightItem[]) => `
    <section>
      <h2>${escapeHtml(title)}</h2>
      ${items.map((item) => `
        <article>
          <h3>${escapeHtml(item.title)}</h3>
          <p>${escapeHtml(item.detail)}</p>
          ${citationsHtml(item.citations)}
        </article>
      `).join("")}
    </section>`;
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(t("combined.title"))} - ${escapeHtml(report.category)}</title>
  <style>
    body{font-family:Inter,Arial,sans-serif;margin:40px;color:#172033;line-height:1.6;background:#f7f8fb}
    main{max-width:960px;margin:auto;background:white;border:1px solid #e2e8f0;border-radius:12px;padding:32px}
    h1{margin-top:0} h2{margin-top:32px;border-top:1px solid #e2e8f0;padding-top:24px}
    article{margin:16px 0;padding:14px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc}
    .verdict{font-size:20px;font-weight:800}
    .meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}
    .meta div{background:#eef2f7;border-radius:8px;padding:10px}
    a{color:#0f766e;text-decoration:none}
    .citations{display:flex;flex-wrap:wrap;gap:8px}
    .citations a{border:1px solid #cbd5e1;border-radius:999px;padding:4px 8px;background:white;font-size:12px}
  </style>
</head>
<body>
  <main>
    <h1>${escapeHtml(t("combined.title"))} - ${escapeHtml(report.category)}</h1>
    <p class="verdict">${escapeHtml(report.verdict.text)}</p>
    ${citationsHtml(report.verdict.citations)}
    ${summaryHtml(report, t)}
    ${sectionHtml(t("combined.opportunities"), report.opportunities)}
    ${sectionHtml(t("combined.risks"), report.risks)}
    ${sectionHtml(t("combined.rdRecommendations"), report.rd_recommendations)}
    ${sectionHtml(t("combined.brandCommunication"), report.brand_communication)}
    <section>
      <h2>${escapeHtml(t("combined.evidenceChain"))}</h2>
      ${report.evidence_chain.map((item) => `
        <article>
          <h3>${escapeHtml(item.claim)}</h3>
          <p>${escapeHtml(item.detail)}</p>
          ${citationsHtml(item.citations)}
        </article>
      `).join("")}
    </section>
    ${sectionHtml(t("combined.dataGaps"), report.data_gaps)}
  </main>
</body>
</html>`;
}

function summaryMarkdown(report: CombinedInsightReport, t: Translator): string {
  return [
    `## ${t("combined.dataSummary")}`,
    "",
    `- ${t("combined.redditPosts")}: ${report.data_summary.reddit_posts}`,
    `- ${t("combined.redditComments")}: ${report.data_summary.reddit_comments}`,
    `- ${t("combined.amazonProducts")}: ${report.data_summary.amazon_products}`,
    `- ${t("combined.amazonReviews")}: ${report.data_summary.amazon_review_samples}`,
    `- ${t("combined.evidenceItems")}: ${report.data_summary.evidence_items}`,
  ].join("\n");
}

function summaryHtml(report: CombinedInsightReport, t: Translator): string {
  return `<div class="meta">
    <div><strong>${escapeHtml(t("combined.redditPosts"))}</strong><br>${report.data_summary.reddit_posts}</div>
    <div><strong>${escapeHtml(t("combined.redditComments"))}</strong><br>${report.data_summary.reddit_comments}</div>
    <div><strong>${escapeHtml(t("combined.amazonProducts"))}</strong><br>${report.data_summary.amazon_products}</div>
    <div><strong>${escapeHtml(t("combined.amazonReviews"))}</strong><br>${report.data_summary.amazon_review_samples}</div>
  </div>`;
}

function itemSectionMarkdown(title: string, items: CombinedInsightItem[]): string {
  return [
    `## ${title}`,
    "",
    ...items.flatMap((item, index) => [
      `### ${index + 1}. ${item.title}`,
      item.detail,
      "",
      citationMarkdown(item.citations),
      "",
    ]),
  ].join("\n");
}

function chainSectionMarkdown(title: string, items: CombinedEvidenceChainItem[]): string {
  return [
    `## ${title}`,
    "",
    ...items.flatMap((item, index) => [
      `### ${index + 1}. ${item.claim}`,
      item.detail,
      "",
      citationMarkdown(item.citations),
      "",
    ]),
  ].join("\n");
}

function citationMarkdown(citations: InsightCitation[]): string {
  if (!citations.length) return "_No citation available._";
  return citations.map((citation) => `- [${citation.id} ${citation.source}/${citation.kind}: ${citation.title}](${citation.url})`).join("\n");
}

function citationsHtml(citations: InsightCitation[]): string {
  return `<div class="citations">${citations.map((citation) => (
    `<a href="${escapeHtml(citation.url)}">${escapeHtml(`${citation.id} ${citation.source}/${citation.kind}`)}</a>`
  )).join("")}</div>`;
}

function downloadText(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "report";
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatCurrency(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function formatInteger(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "0";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatCompactNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "0";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return "-";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  if (minutes < 60) return `${minutes}:${remainder}`;
  const hours = Math.floor(minutes / 60);
  const hourMinutes = (minutes % 60).toString().padStart(2, "0");
  return `${hours}:${hourMinutes}:${remainder}`;
}

function LlmPanel({ report, t }: { report: { llm_analysis: AnalysisReport["llm_analysis"] }; t: Translator }) {
  const llm = report.llm_analysis;
  if (llm.status !== "ok") {
    return (
      <section className="panel wide">
        <PanelTitle title={t("llm.title")} subtitle={t("llm.unavailableSubtitle")} />
        <div className="alert warning">{llm.message || t("llm.unavailableMessage")}</div>
      </section>
    );
  }

  const result = llm.result || {};
  return (
    <section className="panel wide">
      <PanelTitle title={t("llm.title")} subtitle={`${llm.provider} · ${llm.model}`} />
      <p className="summary-text">{result.executive_summary}</p>
      <div className="two-col">
        <div>
          <h4>{t("llm.takeaways")}</h4>
          <ul>
            {(result.strategic_takeaways || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
        <div>
          <h4>{t("llm.dataGaps")}</h4>
          <ul>
            {(result.data_gaps || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </div>
      <div className="stack">
        {(result.opportunity_areas || []).map((item) => (
          <article className="list-card" key={item.title}>
            <h4>{item.title}</h4>
            <p>{item.rationale}</p>
            <div className="source-links">
              <span>{item.confidence} {t("report.confidence")}</span>
              {item.evidence_urls?.map((url) => (
                <a key={url} href={url} target="_blank" rel="noreferrer">{t("report.source")}</a>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function PanelTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="panel-title">
      <h3>{title}</h3>
      <p>{subtitle}</p>
    </div>
  );
}

function SettingsPage({
  locale,
  t,
  onResearchSettingsChange,
}: {
  onResearchSettingsChange: (settings: Partial<ResearchSettings>) => void;
} & LocalizedProps) {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [redditSettings, setRedditSettings] = useState<RedditSettings | null>(null);
  const [researchDefaults, setResearchDefaults] = useState<ResearchDefaults | null>(null);
  const [agentReachSettings, setAgentReachSettings] = useState<AgentReachSettings | null>(null);
  const [webSearchSettings, setWebSearchSettings] = useState<WebSearchSettings | null>(null);
  const [redditClientId, setRedditClientId] = useState("");
  const [redditClientSecret, setRedditClientSecret] = useState("");
  const [redditUserAgent, setRedditUserAgent] = useState("");
  const [clearRedditClientId, setClearRedditClientId] = useState(false);
  const [clearRedditClientSecret, setClearRedditClientSecret] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [webSearchApiKey, setWebSearchApiKey] = useState("");
  const [webSearchEngineId, setWebSearchEngineId] = useState("");
  const [clearWebSearchApiKey, setClearWebSearchApiKey] = useState(false);
  const [clearWebSearchEngineId, setClearWebSearchEngineId] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [redditSaving, setRedditSaving] = useState(false);
  const [researchSaving, setResearchSaving] = useState(false);
  const [agentReachSaving, setAgentReachSaving] = useState(false);
  const [webSearchSaving, setWebSearchSaving] = useState(false);
  const [agentReachReconnecting, setAgentReachReconnecting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [redditMessage, setRedditMessage] = useState<string | null>(null);
  const [researchMessage, setResearchMessage] = useState<string | null>(null);
  const [agentReachMessage, setAgentReachMessage] = useState<string | null>(null);
  const [webSearchMessage, setWebSearchMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.getLLMSettings(),
      api.getRedditSettings(),
      api.getResearchSettings(),
      api.getAgentReachSettings(),
      api.getWebSearchSettings(),
    ])
      .then(([llmData, redditData, researchData, agentReachData, webSearchData]) => {
        setSettings(llmData);
        setRedditSettings(redditData);
        setResearchDefaults(researchData);
        setAgentReachSettings(agentReachData);
        setWebSearchSettings(webSearchData);
        onResearchSettingsChange({
          mode: researchData.mode,
          timeRange: researchData.timeRange,
          limit: researchData.limit,
          amazonProductLimit: researchData.amazonProductLimit,
          amazonKeywordLimit: researchData.amazonKeywordLimit,
        });
        setRedditClientId(redditData.client_id);
        setRedditUserAgent(redditData.user_agent);
        setWebSearchEngineId(webSearchData.search_engine_id || "");
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : t("settings.loadError")))
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof LLMSettings>(key: K, value: LLMSettings[K]) {
    if (!settings) return;
    setSettings({ ...settings, [key]: value });
  }

  function updateAgentReach<K extends keyof AgentReachSettings>(key: K, value: AgentReachSettings[K]) {
    if (!agentReachSettings) return;
    setAgentReachSettings({ ...agentReachSettings, [key]: value });
  }

  function updateWebSearch<K extends keyof WebSearchSettings>(key: K, value: WebSearchSettings[K]) {
    if (!webSearchSettings) return;
    setWebSearchSettings({ ...webSearchSettings, [key]: value });
  }

  function updateResearchDefault<K extends keyof ResearchDefaults>(key: K, value: ResearchDefaults[K]) {
    if (!researchDefaults) return;
    const next = { ...researchDefaults, [key]: value };
    setResearchDefaults(next);
    if (key === "mode" || key === "timeRange" || key === "limit" || key === "amazonProductLimit" || key === "amazonKeywordLimit") {
      onResearchSettingsChange({
        mode: next.mode,
        timeRange: next.timeRange,
        limit: next.limit,
        amazonProductLimit: next.amazonProductLimit,
        amazonKeywordLimit: next.amazonKeywordLimit,
      });
    }
  }

  function applyProvider(name: string) {
    if (!settings) return;
    const provider = settings.providers.find((item) => item.name === name);
    if (!provider) return;
    setSettings({
      ...settings,
      provider: provider.name,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
      api_key_env: provider.api_key_env,
      api_key_required: provider.api_key_required,
      api_key_configured: false,
    });
    setApiKey("");
    setClearApiKey(false);
  }

  function applyWebSearchProvider(name: string) {
    if (!webSearchSettings) return;
    const provider = webSearchSettings.providers.find((item) => item.name === name);
    if (!provider) return;
    setWebSearchSettings({
      ...webSearchSettings,
      provider: provider.name,
      api_key_env: provider.api_key_env,
      api_key_configured: false,
      requires_search_engine_id: provider.requires_search_engine_id,
      search_engine_id_env: provider.search_engine_id_env,
      search_engine_id: "",
      search_engine_id_configured: !provider.requires_search_engine_id,
    });
    setWebSearchApiKey("");
    setWebSearchEngineId("");
    setClearWebSearchApiKey(false);
    setClearWebSearchEngineId(false);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await api.updateLLMSettings({
        provider: settings.provider,
        model_name: settings.model_name,
        base_url: settings.base_url,
        api_key: apiKey.trim() || undefined,
        clear_api_key: clearApiKey,
        temperature: settings.temperature,
        timeout_seconds: settings.timeout_seconds,
      });
      setSettings(updated);
      setApiKey("");
      setClearApiKey(false);
      setMessage(updated.api_key_configured ? t("settings.savedKey") : t("settings.savedNoKey"));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t("settings.saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function saveReddit() {
    if (!redditSettings) return;
    setRedditSaving(true);
    setRedditMessage(null);
    try {
      const updated = await api.updateRedditSettings({
        client_id: redditClientId.trim() || undefined,
        client_secret: redditClientSecret.trim() || undefined,
        clear_client_id: clearRedditClientId,
        clear_client_secret: clearRedditClientSecret,
        user_agent: redditUserAgent.trim(),
      });
      setRedditSettings(updated);
      setRedditClientId(updated.client_id);
      setRedditClientSecret("");
      setClearRedditClientId(false);
      setClearRedditClientSecret(false);
      setRedditMessage(updated.oauth_ready ? t("settings.redditSavedReady") : t("settings.redditSavedIncomplete"));
    } catch (err) {
      setRedditMessage(err instanceof Error ? err.message : t("settings.redditSaveError"));
    } finally {
      setRedditSaving(false);
    }
  }

  async function saveResearchDefaults() {
    if (!researchDefaults) return;
    setResearchSaving(true);
    setResearchMessage(null);
    try {
      const [updated, updatedAgentReach] = await Promise.all([
        api.updateResearchSettings({
          mode: researchDefaults.mode,
          timeRange: researchDefaults.timeRange,
          limit: researchDefaults.limit,
          llmEvidencePosts: researchDefaults.llmEvidencePosts,
          llmCommentSamplesPerPost: researchDefaults.llmCommentSamplesPerPost,
          amazonProductLimit: researchDefaults.amazonProductLimit,
          amazonKeywordLimit: researchDefaults.amazonKeywordLimit,
          amazonDetailLimit: researchDefaults.amazonDetailLimit,
          amazonDiscussionLimit: researchDefaults.amazonDiscussionLimit,
          amazonReviewsPerProduct: researchDefaults.amazonReviewsPerProduct,
          amazonLlmProductLimit: researchDefaults.amazonLlmProductLimit,
          amazonLlmReviewSamplesPerProduct: researchDefaults.amazonLlmReviewSamplesPerProduct,
        }),
        agentReachSettings
          ? api.updateAgentReachSettings({
            enabled: agentReachSettings.enabled,
            backend: agentReachSettings.backend,
            timeout_seconds: agentReachSettings.timeout_seconds,
            detail_limit: agentReachSettings.detail_limit,
            comments_per_post: agentReachSettings.comments_per_post,
          })
          : Promise.resolve(null),
      ]);
      setResearchDefaults(updated);
      if (updatedAgentReach) {
        setAgentReachSettings(updatedAgentReach);
      }
      onResearchSettingsChange({
        mode: updated.mode,
        timeRange: updated.timeRange,
        limit: updated.limit,
        amazonProductLimit: updated.amazonProductLimit,
        amazonKeywordLimit: updated.amazonKeywordLimit,
      });
      setResearchMessage(t("settings.researchSaved"));
    } catch (err) {
      setResearchMessage(err instanceof Error ? err.message : t("settings.researchSaveError"));
    } finally {
      setResearchSaving(false);
    }
  }

  async function saveAgentReach() {
    if (!agentReachSettings) return;
    setAgentReachSaving(true);
    setAgentReachMessage(null);
    try {
      const updated = await api.updateAgentReachSettings({
        enabled: agentReachSettings.enabled,
        backend: agentReachSettings.backend,
        timeout_seconds: agentReachSettings.timeout_seconds,
        detail_limit: agentReachSettings.detail_limit,
        comments_per_post: agentReachSettings.comments_per_post,
      });
      setAgentReachSettings(updated);
      setAgentReachMessage(updated.health.ready ? t("settings.agentReachSavedReady") : t("settings.agentReachSavedInstall"));
    } catch (err) {
      setAgentReachMessage(err instanceof Error ? err.message : t("settings.agentReachSaveError"));
    } finally {
      setAgentReachSaving(false);
    }
  }

  async function saveWebSearch() {
    if (!webSearchSettings) return;
    setWebSearchSaving(true);
    setWebSearchMessage(null);
    try {
      const updated = await api.updateWebSearchSettings({
        provider: webSearchSettings.provider,
        api_key: webSearchApiKey.trim() || undefined,
        clear_api_key: clearWebSearchApiKey,
        search_engine_id: webSearchEngineId.trim() || undefined,
        clear_search_engine_id: clearWebSearchEngineId,
      });
      setWebSearchSettings(updated);
      setWebSearchApiKey("");
      setWebSearchEngineId(updated.search_engine_id || "");
      setClearWebSearchApiKey(false);
      setClearWebSearchEngineId(false);
      setWebSearchMessage(updated.api_key_configured ? t("settings.webSearchSavedReady") : t("settings.webSearchSavedMissing"));
    } catch (err) {
      setWebSearchMessage(err instanceof Error ? err.message : t("settings.webSearchSaveError"));
    } finally {
      setWebSearchSaving(false);
    }
  }

  async function reconnectAgentReach() {
    if (!agentReachSettings) return;
    setAgentReachReconnecting(true);
    setAgentReachMessage(null);
    try {
      const result = await api.reconnectAgentReach();
      setAgentReachSettings({ ...agentReachSettings, health: result.health });
      if (result.ok) {
        setAgentReachMessage(t("settings.agentReachReconnectReady"));
      } else if (!result.health.opencli_installed) {
        setAgentReachMessage(t("settings.agentReachReconnectMissing"));
      } else {
        setAgentReachMessage(t("settings.agentReachReconnectDisconnected"));
      }
    } catch (err) {
      setAgentReachMessage(err instanceof Error ? err.message : t("settings.agentReachReconnectError"));
    } finally {
      setAgentReachReconnecting(false);
    }
  }

  if (loading || !settings || !researchDefaults || !webSearchSettings) {
    return <LoadingPanel text={t("settings.loading")} />;
  }

  return (
    <div className="page settings-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">{t("settings.eyebrow")}</p>
          <h2>{t("settings.title")}</h2>
          <p>{t("settings.description")}</p>
        </div>
        <div className="status-pill">
          {redditSettings?.oauth_ready ? t("settings.statusOauthReady") : t("settings.statusRssFallback")}
        </div>
      </header>

      <form className="settings-form" onSubmit={save}>
        {agentReachSettings ? (
          <section className="panel agent-reach-panel">
            <PanelTitle title={t("settings.agentReachTitle")} subtitle={t("settings.agentReachSubtitle")} />
            <div className="field-stack agent-grid">
              <label className="switch left toggle-row">
                <input
                  type="checkbox"
                  checked={agentReachSettings.enabled}
                  onChange={(event) => updateAgentReach("enabled", event.target.checked)}
                />
                <span>{t("settings.agentReachEnable")}</span>
              </label>
              <label>
                {t("settings.backend")}
                <select
                  value={agentReachSettings.backend}
                  onChange={(event) => updateAgentReach("backend", event.target.value as AgentReachSettings["backend"])}
                >
                  <option value="auto">{t("settings.backendAuto")}</option>
                  <option value="opencli">{t("settings.backendOpencli")}</option>
                  <option value="rdt">{t("settings.backendRdt")}</option>
                </select>
              </label>
              <label>
                {t("settings.timeoutSeconds")}
                <input
                  type="number"
                  min={10}
                  max={600}
                  step={1}
                  value={agentReachSettings.timeout_seconds}
                  onChange={(event) => updateAgentReach("timeout_seconds", Number(event.target.value))}
                />
              </label>
              <div className="settings-path wide-field">
                <Database size={16} />
                <span>
                  {agentReachSettings.health.ready
                    ? `${t("settings.agentReachHealthReady")} ${agentReachSettings.health.recommended_backend}`
                    : agentReachSettings.health.opencli_installed && !agentReachSettings.health.opencli_connected
                      ? t("settings.agentReachOpencliDisconnected")
                      : t("settings.agentReachNotReady")}
                </span>
              </div>
              <div className="health-grid wide-field">
                <span className={agentReachSettings.health.agent_reach_installed ? "ok" : "missing"}>agent-reach</span>
                <span className={agentReachSettings.health.mcporter_installed ? "ok" : "missing"}>mcporter</span>
                <span className={agentReachSettings.health.mcporter_exa_configured ? "ok" : "missing"}>Exa MCP</span>
                <span className={agentReachSettings.health.opencli_connected ? "ok" : "missing"}>
                  {agentReachSettings.health.opencli_installed ? t("settings.opencliExtension") : t("settings.opencli")}
                </span>
                <span className={agentReachSettings.health.rdt_installed ? "ok" : "missing"}>rdt-cli</span>
              </div>
              <div className="agent-health-panels wide-field">
                <div className="settings-path">
                  <MessageSquare size={16} />
                  <span>
                    {agentReachSettings.health.ready
                      ? `${t("settings.agentReachRedditReady")} ${agentReachSettings.health.recommended_backend}`
                      : t("settings.agentReachRedditMissing")}
                  </span>
                </div>
                <div className="settings-path">
                  <Search size={16} />
                  <span>
                    {agentReachSettings.health.web_search_ready
                      ? t("settings.agentReachSearchReady")
                      : t("settings.agentReachSearchMissing")}
                  </span>
                </div>
              </div>
              <div className="settings-path wide-field">
                <Database size={16} />
                <span>
                  {formatMessage(t("settings.agentReachSearchConfig"), {
                    config: agentReachSettings.health.mcporter_config_path || "-",
                    url: agentReachSettings.health.exa_mcp_url || "-",
                  })}
                </span>
              </div>
              <div className="agent-actions wide-field">
                <button
                  type="button"
                  className="secondary-action"
                  disabled={agentReachReconnecting || agentReachSaving}
                  onClick={reconnectAgentReach}
                >
                  {agentReachReconnecting ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
                  {agentReachReconnecting ? t("settings.reconnectingOpencli") : t("settings.reconnectOpencli")}
                </button>
                <button type="button" disabled={agentReachSaving || agentReachReconnecting} onClick={saveAgentReach}>
                  {agentReachSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
                  {t("settings.saveAgentReach")}
                </button>
              </div>
              {agentReachMessage ? <div className="alert subtle wide-field">{agentReachMessage}</div> : null}
            </div>
          </section>
        ) : null}

        <section className="panel web-search-panel">
          <PanelTitle title={t("settings.webSearchTitle")} subtitle={t("settings.webSearchSubtitle")} />
          <div className="field-stack credential-grid">
            <label>
              {t("settings.webSearchProvider")}
              <select value={webSearchSettings.provider} onChange={(event) => applyWebSearchProvider(event.target.value)}>
                {webSearchSettings.providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
            </label>
            {webSearchSettings.api_key_required ? (
              <label>
                {t("settings.apiKey")}
                <input
                  type="password"
                  value={webSearchApiKey}
                  disabled={clearWebSearchApiKey}
                  placeholder={webSearchSettings.api_key_configured ? t("settings.apiKeyKeep") : t("settings.webSearchApiKeyPaste")}
                  onChange={(event) => setWebSearchApiKey(event.target.value)}
                />
              </label>
            ) : (
              <div className="settings-path">
                <Search size={16} />
                <span>{t("settings.webSearchAgentReachRoute")}</span>
              </div>
            )}
            {webSearchSettings.requires_search_engine_id ? (
              <label className="wide-field">
                {t("settings.webSearchEngineId")}
                <input
                  value={webSearchEngineId}
                  disabled={clearWebSearchEngineId}
                  placeholder={webSearchSettings.search_engine_id_configured ? t("settings.webSearchEngineIdKeep") : t("settings.webSearchEngineIdPaste")}
                  onChange={(event) => setWebSearchEngineId(event.target.value)}
                />
              </label>
            ) : null}
            <div className="credential-actions">
              <div className="settings-path">
                <Search size={16} />
                <span>
                  {webSearchSettings.provider === "agent_reach"
                    ? t("settings.webSearchAgentReach")
                    : webSearchSettings.api_key_configured
                      ? t("settings.webSearchReady")
                      : t("settings.webSearchMissing")}
                </span>
              </div>
              <button type="button" disabled={webSearchSaving} onClick={saveWebSearch}>
                {webSearchSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
                {t("settings.saveWebSearch")}
              </button>
            </div>
            <div className="settings-checks">
              {webSearchSettings.api_key_required ? (
                <label className="switch left">
                  <input
                    type="checkbox"
                    checked={clearWebSearchApiKey}
                    onChange={(event) => {
                      setClearWebSearchApiKey(event.target.checked);
                      if (event.target.checked) setWebSearchApiKey("");
                    }}
                  />
                  <span>{t("settings.clearWebSearchApiKey")}</span>
                </label>
              ) : null}
              {webSearchSettings.requires_search_engine_id ? (
                <label className="switch left">
                  <input
                    type="checkbox"
                    checked={clearWebSearchEngineId}
                    onChange={(event) => {
                      setClearWebSearchEngineId(event.target.checked);
                      if (event.target.checked) {
                        setWebSearchEngineId("");
                        updateWebSearch("search_engine_id", "");
                      }
                    }}
                  />
                  <span>{t("settings.clearWebSearchEngineId")}</span>
                </label>
              ) : null}
            </div>
            <div className="settings-path wide-field">
              <Database size={16} />
              <span>
                {webSearchSettings.api_key_required
                  ? formatMessage(t("settings.webSearchEnvSummary"), {
                    key: webSearchSettings.api_key_env,
                    cx: webSearchSettings.search_engine_id_env || "-",
                  })
                  : t("settings.webSearchAgentReachEnvSummary")}
              </span>
            </div>
            {webSearchMessage ? <div className="alert subtle wide-field">{webSearchMessage}</div> : null}
          </div>
        </section>

        {redditSettings ? (
          <section className="panel reddit-panel">
            <PanelTitle title={t("settings.redditTitle")} subtitle={t("settings.redditSubtitle")} />
            <div className="field-stack credential-grid">
              <label>
                {t("settings.clientId")}
                <input
                  value={redditClientId}
                  disabled={clearRedditClientId}
                  placeholder={redditSettings.client_id_configured ? t("settings.clientIdSaved") : t("settings.clientIdPaste")}
                  onChange={(event) => setRedditClientId(event.target.value)}
                />
              </label>
              <label>
                {t("settings.clientSecret")}
                <input
                  type="password"
                  value={redditClientSecret}
                  disabled={clearRedditClientSecret}
                  placeholder={redditSettings.client_secret_configured ? t("settings.clientSecretKeep") : t("settings.clientSecretPaste")}
                  onChange={(event) => setRedditClientSecret(event.target.value)}
                />
              </label>
              <label className="wide-field">
                {t("settings.userAgent")}
                <input
                  value={redditUserAgent}
                  placeholder="InsightAgentRedditDemo/0.1 by yourname"
                  onChange={(event) => setRedditUserAgent(event.target.value)}
                />
              </label>
              <div className="credential-actions">
                <div className="settings-path">
                  <KeyRound size={16} />
                  <span>{redditSettings.oauth_ready ? t("settings.oauthReady") : t("settings.oauthIncomplete")}</span>
                </div>
                <button type="button" disabled={redditSaving} onClick={saveReddit}>
                  {redditSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
                  {t("settings.saveRedditApi")}
                </button>
              </div>
              <div className="settings-checks">
                <label className="switch left">
                  <input
                    type="checkbox"
                    checked={clearRedditClientId}
                    onChange={(event) => {
                      setClearRedditClientId(event.target.checked);
                      if (event.target.checked) setRedditClientId("");
                    }}
                  />
                  <span>{t("settings.clearClientId")}</span>
                </label>
                <label className="switch left">
                  <input
                    type="checkbox"
                    checked={clearRedditClientSecret}
                    onChange={(event) => {
                      setClearRedditClientSecret(event.target.checked);
                      if (event.target.checked) setRedditClientSecret("");
                    }}
                  />
                  <span>{t("settings.clearClientSecret")}</span>
                </label>
              </div>
              {redditMessage ? <div className="alert subtle wide-field">{redditMessage}</div> : null}
            </div>
          </section>
        ) : null}

        <section className="panel">
          <PanelTitle title={t("settings.connectionTitle")} subtitle={t("settings.connectionSubtitle")} />
          <div className="field-stack">
            <label>
              {t("settings.provider")}
              <select value={settings.provider} onChange={(event) => applyProvider(event.target.value)}>
                {settings.providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
            </label>
            <label>
              {t("settings.model")}
              <input value={settings.model_name} onChange={(event) => update("model_name", event.target.value)} />
            </label>
            <label>
              {t("settings.baseUrl")}
              <input value={settings.base_url} onChange={(event) => update("base_url", event.target.value)} />
            </label>
            <label>
              {t("settings.apiKey")}
              <input
                type="password"
                value={apiKey}
                disabled={clearApiKey || !settings.api_key_required}
                placeholder={settings.api_key_configured ? t("settings.apiKeyKeep") : t("settings.apiKeyPaste")}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
            {settings.api_key_required ? (
              <label className="switch left">
                <input type="checkbox" checked={clearApiKey} onChange={(event) => setClearApiKey(event.target.checked)} />
                <span>{t("settings.clearApiKey")}</span>
              </label>
            ) : null}
          </div>
        </section>

        <section className="panel">
          <PanelTitle title={t("settings.generationTitle")} subtitle={t("settings.generationSubtitle")} />
          <div className="field-stack">
            <label>
              {t("settings.temperature")}
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={settings.temperature}
                onChange={(event) => update("temperature", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.timeoutSeconds")}
              <input
                type="number"
                min={1}
                max={600}
                step={1}
                value={settings.timeout_seconds}
                onChange={(event) => update("timeout_seconds", Number(event.target.value))}
              />
            </label>
            <div className="settings-path">
              <Database size={16} />
              <span>{settings.env_path}</span>
            </div>
            <button type="submit" disabled={saving}>
              {saving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
              {t("settings.saveSettings")}
            </button>
            {message ? <div className="alert subtle">{message}</div> : null}
          </div>
        </section>
      </form>
    </div>
  );
}
