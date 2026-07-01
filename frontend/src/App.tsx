import {
  BarChart3,
  Bot,
  CalendarRange,
  Database,
  KeyRound,
  Languages,
  Loader2,
  MessageSquare,
  RefreshCw,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
  api,
  type AgentReachSettings,
  type AnalysisReport,
  type AnalyzeRequest,
  type LLMSettings,
  type RedditSettings,
  type ResearchDefaults,
} from "./lib/api";
import { confidenceLabel, pct, shortDate, sourceLabel } from "./lib/format";
import { formatMessage, loadLocale, makeTranslator, saveLocale, type Locale, type Translator } from "./lib/i18n";
import {
  describeResearchSettings,
  loadResearchSettings,
  saveResearchSettings,
  type ResearchSettings,
} from "./lib/researchSettings";
import { CoverageChart, SentimentChart, TopicBarChart, TrendChart } from "./components/charts";

type Page = "research" | "settings";
type LocalizedProps = {
  locale: Locale;
  t: Translator;
};

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
        {page === "research" ? (
          <ResearchPage locale={locale} researchSettings={researchSettings} t={t} />
        ) : (
          <SettingsPage
            locale={locale}
            t={t}
            onResearchSettingsChange={updateResearchSettings}
          />
        )}
      </main>
    </div>
  );
}

function ResearchPage({ locale, researchSettings, t }: { researchSettings: ResearchSettings } & LocalizedProps) {
  const [category, setCategory] = useState("wireless bras for large bust");
  const [bypassCache, setBypassCache] = useState(false);
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(event?: FormEvent) {
    event?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const request: AnalyzeRequest = {
        category,
        ...researchSettings,
        useLlm: false,
        bypassCache,
      };
      setReport(await api.analyze(request));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("research.errorFallback"));
    } finally {
      setLoading(false);
    }
  }

  const status = report
    ? `${sourceLabel(report.source_mode, locale)} · ${confidenceLabel(report.coverage.confidence, locale)}`
    : t("research.ready");
  const collectionSummary = describeResearchSettings(researchSettings, locale);

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
          {loading ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
          {bypassCache ? t("research.refresh") : t("research.analyze")}
        </button>
      </form>

      {error ? <div className="alert danger">{error}</div> : null}
      {loading ? <LoadingPanel text={t("research.loading")} /> : null}
      {!loading && !report ? <EmptyState t={t} /> : null}
      {report ? <ReportView locale={locale} report={report} t={t} /> : null}
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
        <TrendChart trend={report.trend} />
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

function LlmPanel({ report, t }: { report: AnalysisReport; t: Translator }) {
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
    if (key === "mode" || key === "timeRange" || key === "limit") {
      onResearchSettingsChange({
        mode: next.mode,
        timeRange: next.timeRange,
        limit: next.limit,
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
