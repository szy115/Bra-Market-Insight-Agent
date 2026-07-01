import {
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
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldAlert,
  ShoppingBag,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  api,
  type AgentReachSettings,
  type AnalysisReport,
  type AnalyzeRequest,
  type AmazonReport,
  type CombinedInsightItem,
  type CombinedInsightReport,
  type CombinedEvidenceChainItem,
  type InsightCitation,
  type LLMSettings,
  type RedditSettings,
  type ResearchDefaults,
  type ResearchHistorySummary,
} from "./lib/api";
import { confidenceLabel, pct, shortDate, sourceLabel } from "./lib/format";
import { formatMessage, loadLocale, makeTranslator, saveLocale, type Locale, type Translator } from "./lib/i18n";
import {
  describeAmazonResearchSettings,
  describeResearchSettings,
  loadResearchSettings,
  saveResearchSettings,
  type ResearchSettings,
} from "./lib/researchSettings";
import { CoverageChart, SentimentChart, TopicBarChart, TrendChart } from "./components/charts";

type Page = "research" | "settings";
type ResearchSource = "reddit" | "amazon" | "combined";
type LocalizedProps = {
  locale: Locale;
  t: Translator;
};
type ResearchSession = {
  category: string;
  activeSource: ResearchSource;
  redditReport: AnalysisReport | null;
  amazonReport: AmazonReport | null;
  combinedReport: CombinedInsightReport | null;
};

const RESEARCH_SESSION_KEY = "insight-agent.research-session";

function loadResearchSession(): ResearchSession {
  const fallback: ResearchSession = {
    category: "wireless bras for large bust",
    activeSource: "combined",
    redditReport: null,
    amazonReport: null,
    combinedReport: null,
  };
  try {
    const raw = localStorage.getItem(RESEARCH_SESSION_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ResearchSession>;
    const activeSource: ResearchSource = parsed.activeSource === "reddit" || parsed.activeSource === "amazon"
      ? parsed.activeSource
      : "combined";
    return {
      category: typeof parsed.category === "string" && parsed.category.trim() ? parsed.category : fallback.category,
      activeSource,
      redditReport: parsed.redditReport || null,
      amazonReport: parsed.amazonReport || null,
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

export function App() {
  const [page, setPage] = useState<Page>("research");
  const [locale, setLocale] = useState<Locale>(() => loadLocale());
  const [researchSettings, setResearchSettings] = useState<ResearchSettings>(() => loadResearchSettings());
  const t = useMemo(() => makeTranslator(locale), [locale]);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  useEffect(() => {
    api.getResearchSettings()
      .then((settings) => {
        updateResearchSettings({
          mode: settings.mode,
          timeRange: settings.timeRange,
          limit: settings.limit,
          amazonProductLimit: settings.amazonProductLimit,
          amazonKeywordLimit: settings.amazonKeywordLimit,
        });
      })
      .catch(() => {
        // Local storage defaults still keep the demo usable if the API is unavailable.
      });
  }, []);

  function updateResearchSettings(next: ResearchSettings) {
    setResearchSettings(next);
    saveResearchSettings(next);
  }

  function updateLocale(next: Locale) {
    setLocale(next);
    saveLocale(next);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">IA</div>
          <div>
            <h1>Insight Agent</h1>
            <p>{t("brand.subtitle")}</p>
          </div>
        </div>
        <nav className="nav">
          <button className={page === "research" ? "active" : ""} onClick={() => setPage("research")}>
            <BarChart3 size={17} /> {t("nav.research")}
          </button>
          <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}>
            <Settings size={17} /> {t("nav.settings")}
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
        <div className={page === "research" ? "" : "page-hidden"} aria-hidden={page !== "research"}>
          <ResearchPage locale={locale} researchSettings={researchSettings} t={t} />
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

function ResearchPage({ locale, researchSettings, t }: { researchSettings: ResearchSettings } & LocalizedProps) {
  const [initialSession] = useState<ResearchSession>(() => loadResearchSession());
  const [category, setCategory] = useState(initialSession.category);
  const [activeSource, setActiveSource] = useState<ResearchSource>(initialSession.activeSource);
  const [bypassCache, setBypassCache] = useState(false);
  const [redditReport, setRedditReport] = useState<AnalysisReport | null>(initialSession.redditReport);
  const [amazonReport, setAmazonReport] = useState<AmazonReport | null>(initialSession.amazonReport);
  const [combinedReport, setCombinedReport] = useState<CombinedInsightReport | null>(initialSession.combinedReport);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyItems, setHistoryItems] = useState<ResearchHistorySummary[]>([]);
  const [historyStoragePath, setHistoryStoragePath] = useState(".cache/research-history.json");
  const [historyMessage, setHistoryMessage] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);

  useEffect(() => {
    saveResearchSession({
      category,
      activeSource,
      redditReport,
      amazonReport,
      combinedReport,
    });
  }, [category, activeSource, redditReport, amazonReport, combinedReport]);

  useEffect(() => {
    refreshHistory();
  }, []);

  async function refreshHistory() {
    try {
      const result = await api.getHistory();
      setHistoryItems(result.items);
      setHistoryStoragePath(result.storage_path);
    } catch {
      // History is a convenience layer; analysis remains usable if history cannot load.
    }
  }

  function hasCurrentReports(): boolean {
    return Boolean(redditReport || amazonReport || combinedReport);
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

  async function loadHistoryItem(id: string) {
    setHistoryBusy(true);
    setHistoryMessage(null);
    try {
      const result = await api.getHistoryItem(id);
      setCategory(result.item.category);
      setRedditReport(result.item.reddit_report || null);
      setAmazonReport(result.item.amazon_report || null);
      setCombinedReport(result.item.combined_report || null);
      setActiveSource(result.item.combined_report ? "combined" : result.item.amazon_report ? "amazon" : "reddit");
      setHistoryMessage(t("history.loaded"));
    } catch (err) {
      setHistoryMessage(err instanceof Error ? err.message : t("history.loadError"));
    } finally {
      setHistoryBusy(false);
    }
  }

  async function deleteHistoryItem(id: string) {
    setHistoryBusy(true);
    setHistoryMessage(null);
    try {
      const result = await api.deleteHistoryItem(id);
      setHistoryItems(result.items);
      setHistoryStoragePath(result.storage_path);
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

  async function run(event?: FormEvent) {
    event?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const request: AnalyzeRequest = {
        category,
        ...researchSettings,
        useLlm: true,
        bypassCache,
      };
      if (activeSource === "combined") {
        const { nextReddit, nextAmazon, partialMessage } = await ensureCombinedInputs(request);
        setCombinedReport(await api.analyzeCombined({
          category,
          reddit_report: nextReddit,
          amazon_report: nextAmazon,
          useLlm: true,
          locale,
        }));
        if (partialMessage) {
          setError(partialMessage);
        }
      } else if (activeSource === "amazon") {
        setAmazonReport(await api.analyzeAmazon({
          ...request,
          limit: researchSettings.amazonProductLimit,
          amazonKeywordLimit: researchSettings.amazonKeywordLimit,
        }));
      } else {
        setRedditReport(await api.analyze(request));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("research.errorFallback"));
    } finally {
      setLoading(false);
    }
  }

  const status = activeSource === "amazon" && amazonReport
    ? `${sourceLabel(amazonReport.source_mode, locale)} · ${confidenceLabel(amazonReport.confidence, locale)}`
    : activeSource === "combined" && combinedReport
      ? `${t("source.combined")} · ${combinedReport.data_summary.evidence_items} ${t("combined.evidenceItems")}`
    : activeSource === "reddit" && redditReport
      ? `${sourceLabel(redditReport.source_mode, locale)} · ${confidenceLabel(redditReport.coverage.confidence, locale)}`
      : t("research.ready");
  const collectionSummary = activeSource === "amazon"
    ? describeAmazonResearchSettings(researchSettings, locale)
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
        <div className="status-pill">{status}</div>
      </header>

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
      </div>

      <form className="query-panel" onSubmit={run}>
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
        <button type="submit" disabled={loading}>
          {loading ? <Loader2 className="spin" size={17} /> : activeSource === "combined" ? <Sparkles size={17} /> : <RefreshCw size={17} />}
          {activeSource === "combined" ? t("combined.generate") : bypassCache ? t("research.refresh") : t("research.analyze")}
        </button>
      </form>

      <section className="history-panel">
        <div className="history-head">
          <div>
            <h3>{t("history.title")}</h3>
            <p>{formatMessage(t("history.storage"), { path: historyStoragePath })}</p>
          </div>
          <button type="button" disabled={historyBusy || !hasCurrentReports()} onClick={saveCurrentHistory}>
            {historyBusy ? <Loader2 className="spin" size={16} /> : <Save size={16} />}
            {t("history.saveCurrent")}
          </button>
        </div>
        {historyMessage ? <div className="alert subtle">{historyMessage}</div> : null}
        {historyItems.length ? (
          <div className="history-list">
            {historyItems.slice(0, 8).map((item) => (
              <article className="history-item" key={item.id}>
                <div>
                  <h4>{item.category}</h4>
                  <p>{shortDate(item.saved_at, locale)} · {item.summary || t("history.noSummary")}</p>
                  <div className="history-chips">
                    {item.has_combined ? <span>{t("source.combined")} · {item.evidence_items}</span> : null}
                    {item.has_reddit ? <span>{t("source.reddit")} · {item.reddit_posts}</span> : null}
                    {item.has_amazon ? <span>{t("source.amazon")} · {item.amazon_products}</span> : null}
                  </div>
                </div>
                <div className="history-actions">
                  <button type="button" disabled={historyBusy} onClick={() => loadHistoryItem(item.id)}>
                    <FolderOpen size={15} />
                    {t("history.load")}
                  </button>
                  <button type="button" className="danger-action" disabled={historyBusy} onClick={() => deleteHistoryItem(item.id)}>
                    <Trash2 size={15} />
                    {t("history.delete")}
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="history-empty">{t("history.empty")}</p>
        )}
      </section>

      {error ? <div className="alert danger">{error}</div> : null}
      {loading ? (
        <LoadingPanel
          text={
            activeSource === "amazon"
              ? t("research.amazonLoading")
              : activeSource === "combined"
                ? t("combined.loading")
                : t("research.loading")
          }
        />
      ) : null}
      {!loading && activeSource === "reddit" && !redditReport ? <EmptyState t={t} /> : null}
      {!loading && activeSource === "amazon" && !amazonReport ? <EmptyState t={t} /> : null}
      {!loading && activeSource === "combined" && !combinedReport ? (
        <CombinedEmptyState redditReady={Boolean(redditReport)} amazonReady={Boolean(amazonReport)} t={t} />
      ) : null}
      {activeSource === "reddit" && redditReport ? <ReportView locale={locale} report={redditReport} t={t} /> : null}
      {activeSource === "amazon" && amazonReport ? <AmazonReportView locale={locale} report={amazonReport} t={t} /> : null}
      {activeSource === "combined" && combinedReport ? (
        <CombinedInsightView locale={locale} report={combinedReport} t={t} />
      ) : null}
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
        <a key={citation.id} href={citation.url} target="_blank" rel="noreferrer" title={citation.excerpt}>
          <Link2 size={13} />
          {citation.source === "reddit" ? t("source.reddit") : t("source.amazon")} · {citation.kind} · {citation.id}
        </a>
      ))}
    </div>
  );
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
  onResearchSettingsChange: (settings: ResearchSettings) => void;
} & LocalizedProps) {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [redditSettings, setRedditSettings] = useState<RedditSettings | null>(null);
  const [researchDefaults, setResearchDefaults] = useState<ResearchDefaults | null>(null);
  const [agentReachSettings, setAgentReachSettings] = useState<AgentReachSettings | null>(null);
  const [redditClientId, setRedditClientId] = useState("");
  const [redditClientSecret, setRedditClientSecret] = useState("");
  const [redditUserAgent, setRedditUserAgent] = useState("");
  const [clearRedditClientId, setClearRedditClientId] = useState(false);
  const [clearRedditClientSecret, setClearRedditClientSecret] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [redditSaving, setRedditSaving] = useState(false);
  const [researchSaving, setResearchSaving] = useState(false);
  const [agentReachSaving, setAgentReachSaving] = useState(false);
  const [agentReachReconnecting, setAgentReachReconnecting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [redditMessage, setRedditMessage] = useState<string | null>(null);
  const [researchMessage, setResearchMessage] = useState<string | null>(null);
  const [agentReachMessage, setAgentReachMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getLLMSettings(), api.getRedditSettings(), api.getResearchSettings(), api.getAgentReachSettings()])
      .then(([llmData, redditData, researchData, agentReachData]) => {
        setSettings(llmData);
        setRedditSettings(redditData);
        setResearchDefaults(researchData);
        setAgentReachSettings(agentReachData);
        onResearchSettingsChange({
          mode: researchData.mode,
          timeRange: researchData.timeRange,
          limit: researchData.limit,
          amazonProductLimit: researchData.amazonProductLimit,
          amazonKeywordLimit: researchData.amazonKeywordLimit,
        });
        setRedditClientId(redditData.client_id);
        setRedditUserAgent(redditData.user_agent);
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

  if (loading || !settings || !researchDefaults) {
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
                <span className={agentReachSettings.health.opencli_connected ? "ok" : "missing"}>
                  {agentReachSettings.health.opencli_installed ? t("settings.opencliExtension") : t("settings.opencli")}
                </span>
                <span className={agentReachSettings.health.rdt_installed ? "ok" : "missing"}>rdt-cli</span>
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

        <section className="panel collection-panel">
          <PanelTitle title={t("settings.volumeTitle")} subtitle={t("settings.volumeSubtitle")} />
          <div className="field-stack">
            <div className="field-section-heading wide-field">
              <h4>{t("settings.redditVolumeTitle")}</h4>
              <p>{t("settings.redditVolumeSubtitle")}</p>
            </div>
            <label>
              {t("settings.sourceMode")}
              <select
                value={researchDefaults.mode}
                onChange={(event) => updateResearchDefault("mode", event.target.value as ResearchDefaults["mode"])}
              >
                <option value="auto">{t("settings.modeAuto")}</option>
                <option value="agent_reach">{t("settings.modeAgentReach")}</option>
                <option value="oauth">{t("settings.modeOauth")}</option>
                <option value="rss">{t("settings.modeRss")}</option>
                <option value="sample">{t("settings.modeSample")}</option>
              </select>
            </label>
            <label>
              {t("settings.timeRange")}
              <select
                value={researchDefaults.timeRange}
                onChange={(event) => updateResearchDefault("timeRange", event.target.value as ResearchDefaults["timeRange"])}
              >
                <option value="day">{t("settings.day")}</option>
                <option value="week">{t("settings.week")}</option>
                <option value="month">{t("settings.month")}</option>
                <option value="year">{t("settings.year")}</option>
                <option value="all">{t("settings.all")}</option>
              </select>
            </label>
            <label>
              {t("settings.totalPostLimit")}
              <input
                type="number"
                min={5}
                max={researchDefaults.maxPostLimit}
                step={1}
                value={researchDefaults.limit}
                onChange={(event) => updateResearchDefault("limit", Number(event.target.value))}
              />
            </label>
            {agentReachSettings ? (
              <>
                <label>
                  {t("settings.detailLimit")}
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={agentReachSettings.detail_limit}
                    onChange={(event) => updateAgentReach("detail_limit", Number(event.target.value))}
                  />
                </label>
                <label>
                  {t("settings.commentsPerPost")}
                  <input
                    type="number"
                    min={0}
                    max={200}
                    step={1}
                    value={agentReachSettings.comments_per_post}
                    onChange={(event) => updateAgentReach("comments_per_post", Number(event.target.value))}
                  />
                </label>
              </>
            ) : null}
            <label>
              {t("settings.aiEvidencePosts")}
              <input
                type="number"
                min={1}
                max={100}
                step={1}
                value={researchDefaults.llmEvidencePosts}
                onChange={(event) => updateResearchDefault("llmEvidencePosts", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.aiCommentSamples")}
              <input
                type="number"
                min={0}
                max={50}
                step={1}
                value={researchDefaults.llmCommentSamplesPerPost}
                onChange={(event) => updateResearchDefault("llmCommentSamplesPerPost", Number(event.target.value))}
              />
            </label>
            <div className="settings-path">
              <SlidersHorizontal size={16} />
              <span>{describeResearchSettings(researchDefaults, locale)}</span>
            </div>
            <div className="settings-path wide-field">
              <Database size={16} />
              <span>
                {formatMessage(t("settings.volumeSummary"), {
                  posts: researchDefaults.limit,
                  details: agentReachSettings?.detail_limit ?? 0,
                  comments: agentReachSettings?.comments_per_post ?? 0,
                  aiPosts: researchDefaults.llmEvidencePosts,
                  aiComments: researchDefaults.llmCommentSamplesPerPost,
                })}
              </span>
            </div>
            <div className="field-section-heading wide-field">
              <h4>{t("settings.amazonVolumeTitle")}</h4>
              <p>{t("settings.amazonVolumeSubtitle")}</p>
            </div>
            <label>
              {t("settings.amazonKeywordLimit")}
              <input
                type="number"
                min={1}
                max={researchDefaults.maxAmazonKeywordLimit}
                step={1}
                value={researchDefaults.amazonKeywordLimit}
                onChange={(event) => updateResearchDefault("amazonKeywordLimit", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonProductLimit")}
              <input
                type="number"
                min={1}
                max={researchDefaults.maxAmazonProductLimit}
                step={1}
                value={researchDefaults.amazonProductLimit}
                onChange={(event) => updateResearchDefault("amazonProductLimit", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonDetailLimit")}
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={researchDefaults.amazonDetailLimit}
                onChange={(event) => updateResearchDefault("amazonDetailLimit", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonDiscussionLimit")}
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={researchDefaults.amazonDiscussionLimit}
                onChange={(event) => updateResearchDefault("amazonDiscussionLimit", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonReviewsPerProduct")}
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={researchDefaults.amazonReviewsPerProduct}
                onChange={(event) => updateResearchDefault("amazonReviewsPerProduct", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonAiProducts")}
              <input
                type="number"
                min={1}
                max={100}
                step={1}
                value={researchDefaults.amazonLlmProductLimit}
                onChange={(event) => updateResearchDefault("amazonLlmProductLimit", Number(event.target.value))}
              />
            </label>
            <label>
              {t("settings.amazonAiReviews")}
              <input
                type="number"
                min={0}
                max={50}
                step={1}
                value={researchDefaults.amazonLlmReviewSamplesPerProduct}
                onChange={(event) => updateResearchDefault("amazonLlmReviewSamplesPerProduct", Number(event.target.value))}
              />
            </label>
            <div className="settings-path wide-field">
              <ShoppingBag size={16} />
              <span>
                {formatMessage(t("settings.amazonVolumeSummary"), {
                  keywords: researchDefaults.amazonKeywordLimit,
                  products: researchDefaults.amazonProductLimit,
                  total: researchDefaults.amazonKeywordLimit * researchDefaults.amazonProductLimit,
                  details: researchDefaults.amazonDetailLimit,
                  discussions: researchDefaults.amazonDiscussionLimit,
                  reviews: researchDefaults.amazonReviewsPerProduct,
                  aiProducts: researchDefaults.amazonLlmProductLimit,
                  aiReviews: researchDefaults.amazonLlmReviewSamplesPerProduct,
                })}
              </span>
            </div>
            <button type="button" disabled={researchSaving} onClick={saveResearchDefaults}>
              {researchSaving ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
              {t("settings.saveResearchDefaults")}
            </button>
            {researchMessage ? <div className="alert subtle wide-field">{researchMessage}</div> : null}
          </div>
        </section>

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
