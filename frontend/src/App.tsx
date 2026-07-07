import {
  BarChart3,
  Bot,
  Database,
  Download,
  ExternalLink,
  FileText,
  History,
  Languages,
  Link2,
  Loader2,
  MessageSquare,
  Newspaper,
  PackageSearch,
  Plus,
  Save,
  Settings,
  Sparkles,
  Star,
  Trash2,
  Video,
} from "lucide-react";
import { Fragment, type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import {
  api,
  type AgentOutputFileMeta,
  type AgentOutputFileResponse,
  type AgentRunEvent,
  type AgentRunRequest,
  type AgentRunResponse,
  type LLMSettings,
} from "./lib/api";
import { formatMessage, loadLocale, makeTranslator, saveLocale, type Locale, type Translator } from "./lib/i18n";

type Page = "agent" | "settings";
type AgentArtifactTab = "market" | "draft" | "output";
type AgentPromptTemplateId = "market_insight_weekly" | "breakout_competitor_tiktok";
type AgentPromptTemplate = {
  id: AgentPromptTemplateId;
  mode: "market" | "competitor";
  title: string;
  description: string;
  prompt: string;
  sources: string[];
};
type LocalizedProps = {
  locale: Locale;
  t: Translator;
};
type AgentSessionSnapshot = {
  version: 1;
  selectedTemplateId: AgentPromptTemplateId;
  agentMode: "market" | "competitor";
  prompt: string;
  artifactTab: AgentArtifactTab;
  result: AgentRunResponse | null;
  streamEvents: AgentRunEvent[];
  selectedOutputPath: string;
  savedAt: string;
};
type AgentRunHistoryItem = AgentSessionSnapshot & {
  id: string;
  title: string;
  status: string;
  skillName: string;
  fileCount: number;
  toolNames: string[];
  createdAt: string;
  updatedAt: string;
};
type AgentChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  runId?: string;
  createdAt: string;
};
type AgentConversationSession = AgentSessionSnapshot & {
  id: string;
  title: string;
  messages: AgentChatMessage[];
  runs: AgentRunHistoryItem[];
  createdAt: string;
  updatedAt: string;
};

const AGENT_SESSION_STORAGE_KEY = "insight-agent.agent-session";
const AGENT_RUN_HISTORY_STORAGE_KEY = "insight-agent.agent-run-history";
const AGENT_RUN_HISTORY_LIMIT = 20;
const AGENT_CONVERSATION_STORAGE_KEY = "insight-agent.agent-sessions";
const AGENT_CONVERSATION_LIMIT = 20;

export function App() {
  const [page, setPage] = useState<Page>("agent");
  const [locale, setLocale] = useState<Locale>(() => loadLocale());
  const t = useMemo(() => makeTranslator(locale), [locale]);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

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
          <button className={page === "agent" ? "active" : ""} onClick={() => setPage("agent")}>
            <Sparkles size={17} /> <span>{t("nav.agent")}</span>
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
        {page === "agent" ? <SimpleAgentPage locale={locale} t={t} /> : null}
        {page === "settings" ? <SettingsPage locale={locale} t={t} /> : null}
      </main>
    </div>
  );
}

function isAgentPromptTemplateId(value: unknown): value is AgentPromptTemplateId {
  return value === "market_insight_weekly" || value === "breakout_competitor_tiktok";
}

function isAgentMode(value: unknown): value is "market" | "competitor" {
  return value === "market" || value === "competitor";
}

function isAgentArtifactTab(value: unknown): value is AgentArtifactTab {
  return value === "market" || value === "draft" || value === "output";
}

function loadAgentSession(): AgentSessionSnapshot | null {
  try {
    const raw = localStorage.getItem(AGENT_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AgentSessionSnapshot>;
    if (
      parsed.version !== 1 ||
      !isAgentPromptTemplateId(parsed.selectedTemplateId) ||
      !isAgentMode(parsed.agentMode) ||
      !isAgentArtifactTab(parsed.artifactTab)
    ) {
      localStorage.removeItem(AGENT_SESSION_STORAGE_KEY);
      return null;
    }
    return {
      version: 1,
      selectedTemplateId: parsed.selectedTemplateId,
      agentMode: parsed.agentMode,
      prompt: typeof parsed.prompt === "string" ? parsed.prompt : "",
      artifactTab: parsed.artifactTab,
      result: parsed.result && typeof parsed.result === "object" ? parsed.result as AgentRunResponse : null,
      streamEvents: Array.isArray(parsed.streamEvents) ? parsed.streamEvents as AgentRunEvent[] : [],
      selectedOutputPath: typeof parsed.selectedOutputPath === "string" ? parsed.selectedOutputPath : "",
      savedAt: typeof parsed.savedAt === "string" ? parsed.savedAt : new Date().toISOString(),
    };
  } catch {
    try {
      localStorage.removeItem(AGENT_SESSION_STORAGE_KEY);
    } catch {
      // Ignore storage failures; the Agent can still run without persistence.
    }
    return null;
  }
}

function saveAgentSession(snapshot: AgentSessionSnapshot): void {
  try {
    localStorage.setItem(AGENT_SESSION_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // Local storage can fail in private mode or when the quota is full.
  }
}

function normalizeAgentRunHistoryItem(value: unknown): AgentRunHistoryItem | null {
  if (!isRecord(value)) return null;
  if (
    value.version !== 1 ||
    typeof value.id !== "string" ||
    !isAgentPromptTemplateId(value.selectedTemplateId) ||
    !isAgentMode(value.agentMode) ||
    !isAgentArtifactTab(value.artifactTab)
  ) {
    return null;
  }
  return {
    version: 1,
    id: value.id,
    selectedTemplateId: value.selectedTemplateId,
    agentMode: value.agentMode,
    prompt: typeof value.prompt === "string" ? value.prompt : "",
    artifactTab: value.artifactTab,
    result: value.result && typeof value.result === "object" ? value.result as AgentRunResponse : null,
    streamEvents: Array.isArray(value.streamEvents) ? value.streamEvents as AgentRunEvent[] : [],
    selectedOutputPath: typeof value.selectedOutputPath === "string" ? value.selectedOutputPath : "",
    savedAt: typeof value.savedAt === "string" ? value.savedAt : new Date().toISOString(),
    title: typeof value.title === "string" && value.title.trim() ? value.title : "Untitled run",
    status: typeof value.status === "string" ? value.status : "ok",
    skillName: typeof value.skillName === "string" ? value.skillName : "",
    fileCount: typeof value.fileCount === "number" ? value.fileCount : 0,
    toolNames: Array.isArray(value.toolNames) ? value.toolNames.filter((item): item is string => typeof item === "string") : [],
    createdAt: typeof value.createdAt === "string" ? value.createdAt : new Date().toISOString(),
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : new Date().toISOString(),
  };
}

function loadAgentRunHistory(): AgentRunHistoryItem[] {
  try {
    const raw = localStorage.getItem(AGENT_RUN_HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(normalizeAgentRunHistoryItem)
      .filter((item): item is AgentRunHistoryItem => Boolean(item))
      .slice(0, AGENT_RUN_HISTORY_LIMIT);
  } catch {
    try {
      localStorage.removeItem(AGENT_RUN_HISTORY_STORAGE_KEY);
    } catch {
      // Ignore storage failures.
    }
    return [];
  }
}

function saveAgentRunHistory(history: AgentRunHistoryItem[]): AgentRunHistoryItem[] {
  let next = history.slice(0, AGENT_RUN_HISTORY_LIMIT);
  while (next.length) {
    try {
      localStorage.setItem(AGENT_RUN_HISTORY_STORAGE_KEY, JSON.stringify(next));
      return next;
    } catch {
      next = next.slice(0, -1);
    }
  }
  try {
    localStorage.removeItem(AGENT_RUN_HISTORY_STORAGE_KEY);
  } catch {
    // Ignore storage failures.
  }
  return [];
}

function buildAgentSessionSnapshot(args: {
  selectedTemplateId: AgentPromptTemplateId;
  agentMode: "market" | "competitor";
  prompt: string;
  artifactTab: AgentArtifactTab;
  result: AgentRunResponse | null;
  streamEvents: AgentRunEvent[];
  selectedOutputPath: string;
}): AgentSessionSnapshot {
  return {
    version: 1,
    selectedTemplateId: args.selectedTemplateId,
    agentMode: args.agentMode,
    prompt: args.prompt,
    artifactTab: args.artifactTab,
    result: args.result,
    streamEvents: args.streamEvents,
    selectedOutputPath: args.selectedOutputPath,
    savedAt: new Date().toISOString(),
  };
}

function shortHistoryTitle(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > 52 ? `${compact.slice(0, 52)}...` : compact;
}

function buildAgentRunHistoryItem(snapshot: AgentSessionSnapshot, existing?: AgentRunHistoryItem): AgentRunHistoryItem | null {
  if (!snapshot.result) return null;
  const result = snapshot.result;
  const id = result.run_id || existing?.id || `${Date.now()}`;
  const title = result.artifact?.title
    || result.message?.content
    || result.prompt
    || snapshot.prompt
    || existing?.title
    || "Untitled run";
  const generatedAt = result.generated_at || snapshot.savedAt;
  return {
    ...snapshot,
    id,
    title: shortHistoryTitle(title),
    status: result.status || "ok",
    skillName: result.skill?.name || result.skill?.skill_id || "",
    fileCount: buildAgentOutputFiles(result).length,
    toolNames: result.tools.map((tool) => tool.label || tool.name),
    createdAt: existing?.createdAt || generatedAt,
    updatedAt: generatedAt,
  };
}

function upsertAgentRunHistory(history: AgentRunHistoryItem[], snapshot: AgentSessionSnapshot): AgentRunHistoryItem[] {
  const existing = snapshot.result ? history.find((item) => item.id === snapshot.result?.run_id) : undefined;
  const item = buildAgentRunHistoryItem(snapshot, existing);
  if (!item) return history;
  return [item, ...history.filter((entry) => entry.id !== item.id)].slice(0, AGENT_RUN_HISTORY_LIMIT);
}

function newClientId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function assistantContentFromResult(result: AgentRunResponse): string {
  if (result.response_type === "message") return result.message?.content || "";
  if (result.status === "needs_input") {
    const questions = result.pending?.questions?.map((question) => `- ${question.question}`).join("\n") || "";
    return [result.pending?.message || "需要补齐参数后继续执行。", questions].filter(Boolean).join("\n");
  }
  if (result.artifact) {
    return `${result.artifact.title}\n\n${result.artifact.executive_summary}`;
  }
  return "任务已完成。";
}

function messagesFromRunSnapshot(snapshot: AgentSessionSnapshot): AgentChatMessage[] {
  if (!snapshot.result) return [];
  const createdAt = snapshot.result.generated_at || snapshot.savedAt;
  return [
    {
      id: `${snapshot.result.run_id}-user`,
      role: "user",
      content: snapshot.result.prompt || snapshot.prompt,
      runId: snapshot.result.run_id,
      createdAt,
    },
    {
      id: `${snapshot.result.run_id}-assistant`,
      role: "assistant",
      content: assistantContentFromResult(snapshot.result),
      runId: snapshot.result.run_id,
      createdAt,
    },
  ];
}

function snapshotFromConversation(session: AgentConversationSession): AgentSessionSnapshot {
  return {
    version: 1,
    selectedTemplateId: session.selectedTemplateId,
    agentMode: session.agentMode,
    prompt: session.prompt,
    artifactTab: session.artifactTab,
    result: session.result,
    streamEvents: session.streamEvents,
    selectedOutputPath: session.selectedOutputPath,
    savedAt: session.savedAt,
  };
}

function buildConversationTitle(value: string): string {
  const title = shortHistoryTitle(value);
  return title || "New conversation";
}

function normalizeAgentConversationSession(value: unknown): AgentConversationSession | null {
  if (!isRecord(value)) return null;
  if (
    value.version !== 1 ||
    typeof value.id !== "string" ||
    !isAgentPromptTemplateId(value.selectedTemplateId) ||
    !isAgentMode(value.agentMode) ||
    !isAgentArtifactTab(value.artifactTab)
  ) {
    return null;
  }
  return {
    version: 1,
    id: value.id,
    selectedTemplateId: value.selectedTemplateId,
    agentMode: value.agentMode,
    prompt: typeof value.prompt === "string" ? value.prompt : "",
    artifactTab: value.artifactTab,
    result: value.result && typeof value.result === "object" ? value.result as AgentRunResponse : null,
    streamEvents: Array.isArray(value.streamEvents) ? value.streamEvents as AgentRunEvent[] : [],
    selectedOutputPath: typeof value.selectedOutputPath === "string" ? value.selectedOutputPath : "",
    savedAt: typeof value.savedAt === "string" ? value.savedAt : new Date().toISOString(),
    title: typeof value.title === "string" && value.title.trim() ? value.title : "New conversation",
    messages: Array.isArray(value.messages)
      ? value.messages.filter(isRecord).map((message) => ({
          id: typeof message.id === "string" ? message.id : newClientId("msg"),
          role: message.role === "assistant" ? "assistant" : "user",
          content: typeof message.content === "string" ? message.content : "",
          runId: typeof message.runId === "string" ? message.runId : undefined,
          createdAt: typeof message.createdAt === "string" ? message.createdAt : new Date().toISOString(),
        }))
      : [],
    runs: Array.isArray(value.runs)
      ? value.runs.map(normalizeAgentRunHistoryItem).filter((item): item is AgentRunHistoryItem => Boolean(item))
      : [],
    createdAt: typeof value.createdAt === "string" ? value.createdAt : new Date().toISOString(),
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : new Date().toISOString(),
  };
}

function saveAgentConversationSessions(sessions: AgentConversationSession[]): AgentConversationSession[] {
  let next = sessions.slice(0, AGENT_CONVERSATION_LIMIT).map((session) => ({
    ...session,
    messages: session.messages.slice(-200),
    runs: session.runs.slice(0, AGENT_RUN_HISTORY_LIMIT),
  }));
  while (next.length) {
    try {
      localStorage.setItem(AGENT_CONVERSATION_STORAGE_KEY, JSON.stringify(next));
      return next;
    } catch {
      next = next.slice(0, -1);
    }
  }
  try {
    localStorage.removeItem(AGENT_CONVERSATION_STORAGE_KEY);
  } catch {
    // Ignore storage failures.
  }
  return [];
}

function loadAgentConversationSessions(): AgentConversationSession[] {
  try {
    const raw = localStorage.getItem(AGENT_CONVERSATION_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const sessions = parsed
          .map(normalizeAgentConversationSession)
          .filter((item): item is AgentConversationSession => Boolean(item));
        if (sessions.length) return sessions.slice(0, AGENT_CONVERSATION_LIMIT);
      }
    }
  } catch {
    try {
      localStorage.removeItem(AGENT_CONVERSATION_STORAGE_KEY);
    } catch {
      // Ignore storage failures.
    }
  }

  const legacySession = loadAgentSession();
  const legacyRuns = loadAgentRunHistory();
  if (!legacySession?.result && !legacyRuns.length) return [];
  const runSnapshots = legacyRuns.length ? legacyRuns : legacySession ? [buildAgentRunHistoryItem(legacySession)].filter(Boolean) as AgentRunHistoryItem[] : [];
  const baseSnapshot = legacySession || runSnapshots[0] || null;
  if (!baseSnapshot) return [];
  const messages = runSnapshots.flatMap((run) => messagesFromRunSnapshot(run));
  const sessionId = newClientId("session");
  const title = buildConversationTitle(baseSnapshot.result?.artifact?.title || baseSnapshot.result?.prompt || baseSnapshot.prompt);
  const createdAt = runSnapshots[runSnapshots.length - 1]?.createdAt || baseSnapshot.savedAt;
  const updatedAt = runSnapshots[0]?.updatedAt || baseSnapshot.savedAt;
  const session: AgentConversationSession = {
    version: 1,
    selectedTemplateId: baseSnapshot.selectedTemplateId,
    agentMode: baseSnapshot.agentMode,
    prompt: baseSnapshot.prompt,
    artifactTab: baseSnapshot.artifactTab,
    result: baseSnapshot.result,
    streamEvents: baseSnapshot.streamEvents,
    selectedOutputPath: baseSnapshot.selectedOutputPath,
    savedAt: baseSnapshot.savedAt,
    id: sessionId,
    title,
    messages,
    runs: runSnapshots,
    createdAt,
    updatedAt,
  };
  return saveAgentConversationSessions([session]);
}

function upsertAgentConversationSession(
  sessions: AgentConversationSession[],
  session: AgentConversationSession,
): AgentConversationSession[] {
  return [session, ...sessions.filter((item) => item.id !== session.id)].slice(0, AGENT_CONVERSATION_LIMIT);
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

function SimpleAgentPage({ locale, t }: LocalizedProps) {
  const promptTemplates = useMemo(() => buildAgentPromptTemplates(t), [t]);
  const [initialConversations] = useState<AgentConversationSession[]>(() => loadAgentConversationSessions());
  const [initialConversation] = useState<AgentConversationSession | null>(() => initialConversations[0] || null);
  const [initialSession] = useState<AgentSessionSnapshot | null>(() => initialConversation ? snapshotFromConversation(initialConversation) : loadAgentSession());
  const [selectedTemplateId, setSelectedTemplateId] = useState<AgentPromptTemplateId>(
    initialSession?.selectedTemplateId || "market_insight_weekly",
  );
  const selectedTemplate = promptTemplates.find((template) => template.id === selectedTemplateId) || promptTemplates[0]!;
  const [agentMode, setAgentMode] = useState<"market" | "competitor">(initialSession?.agentMode || selectedTemplate.mode);
  const [prompt, setPrompt] = useState(initialSession?.prompt ?? selectedTemplate.prompt);
  const [artifactTab, setArtifactTab] = useState<AgentArtifactTab>(initialSession?.artifactTab || "market");
  const [result, setResult] = useState<AgentRunResponse | null>(initialSession?.result || null);
  const [streamEvents, setStreamEvents] = useState<AgentRunEvent[]>(initialSession?.streamEvents || []);
  const [selectedOutputPath, setSelectedOutputPath] = useState(initialSession?.selectedOutputPath || "");
  const [messages, setMessages] = useState<AgentChatMessage[]>(initialConversation?.messages || (initialSession ? messagesFromRunSnapshot(initialSession) : []));
  const [sessionRuns, setSessionRuns] = useState<AgentRunHistoryItem[]>(initialConversation?.runs || []);
  const [conversationSessions, setConversationSessions] = useState<AgentConversationSession[]>(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState(initialConversation?.id || newClientId("session"));
  const [showHistory, setShowHistory] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const artifactJson = result ? JSON.stringify(result, null, 2) : "";
  const hasFinalArtifact = Boolean(
    result?.artifact && result.status === "ok" && result.response_type !== "message",
  );
  const artifactTitle = hasFinalArtifact && result?.artifact ? result.artifact.title : t("agent.simpleTitle");
  const artifactTabs: Array<{ id: AgentArtifactTab; label: string }> = [
    { id: "market", label: t("agent.tab.market") },
    { id: "draft", label: t("agent.tab.draft") },
    { id: "output", label: t("agent.tab.output") },
  ];
  const executionEvents = result?.events?.length
    ? result.events
    : streamEvents.length
      ? streamEvents
      : loading
        ? buildLoadingAgentEvents(t)
        : [];
  const awaitingInput = result?.status === "needs_input";

  useEffect(() => {
    const snapshot = buildAgentSessionSnapshot({
      selectedTemplateId,
      agentMode,
      prompt,
      artifactTab,
      result,
      streamEvents,
      selectedOutputPath,
    });
    saveAgentSession(snapshot);
    const now = new Date().toISOString();
    const currentSession: AgentConversationSession = {
      ...snapshot,
      id: activeConversationId,
      title: buildConversationTitle(
        result?.artifact?.title || messages.find((message) => message.role === "user")?.content || t("agent.newConversation"),
      ),
      messages,
      runs: sessionRuns,
      createdAt: conversationSessions.find((session) => session.id === activeConversationId)?.createdAt || now,
      updatedAt: now,
    };
    setConversationSessions((current) => saveAgentConversationSessions(upsertAgentConversationSession(current, currentSession)));
  }, [
    activeConversationId,
    agentMode,
    artifactTab,
    messages,
    prompt,
    result,
    selectedOutputPath,
    selectedTemplateId,
    sessionRuns,
    streamEvents,
    t,
  ]);

  function applyPromptTemplate(template: AgentPromptTemplate) {
    setSelectedTemplateId(template.id);
    setAgentMode(template.mode);
    setPrompt(template.prompt);
    setArtifactTab("draft");
  }

  function applyAgentRunResponse(nextResult: AgentRunResponse): AgentSessionSnapshot {
    const nextPrompt = "";
    const nextSelectedOutputPath = nextResult.status === "needs_input" || nextResult.response_type === "message"
      ? ""
      : preferredAgentOutputPath(nextResult);
    const nextArtifactTab = nextResult.status === "needs_input" || nextResult.response_type === "message"
      ? "draft"
      : "output";
    const nextEvents = nextResult.events || [];
    setResult(nextResult);
    setStreamEvents(nextEvents);
    setSelectedOutputPath(nextSelectedOutputPath);
    setArtifactTab(nextArtifactTab);
    setPrompt(nextPrompt);
    setAgentMode(nextResult.mode || agentMode);
    const snapshot = buildAgentSessionSnapshot({
      selectedTemplateId,
      agentMode: nextResult.mode || agentMode,
      prompt: nextPrompt,
      artifactTab: nextArtifactTab,
      result: nextResult,
      streamEvents: nextEvents,
      selectedOutputPath: nextSelectedOutputPath,
    });
    saveAgentSession(snapshot);
    const runItem = buildAgentRunHistoryItem(snapshot, sessionRuns.find((item) => item.id === nextResult.run_id));
    if (runItem) {
      setSessionRuns((current) => [runItem, ...current.filter((item) => item.id !== runItem.id)].slice(0, AGENT_RUN_HISTORY_LIMIT));
    }
    setMessages((current) => {
      if (current.some((message) => message.role === "assistant" && message.runId === nextResult.run_id)) return current;
      return [
        ...current,
        {
          id: `${nextResult.run_id}-assistant`,
          role: "assistant",
          content: assistantContentFromResult(nextResult),
          runId: nextResult.run_id,
          createdAt: nextResult.generated_at || new Date().toISOString(),
        },
      ];
    });
    return snapshot;
  }

  function restoreSessionRun(item: AgentRunHistoryItem) {
    setSelectedTemplateId(item.selectedTemplateId);
    setAgentMode(item.agentMode);
    setPrompt("");
    setArtifactTab(item.artifactTab);
    setResult(item.result);
    setStreamEvents(item.streamEvents);
    setSelectedOutputPath(item.selectedOutputPath || (item.result ? preferredAgentOutputPath(item.result) : ""));
    setError(null);
    setLoading(false);
    saveAgentSession(item);
  }

  function openSessionRunFile(item: AgentRunHistoryItem, path: string) {
    setSelectedTemplateId(item.selectedTemplateId);
    setAgentMode(item.agentMode);
    setPrompt("");
    setArtifactTab("output");
    setResult(item.result);
    setStreamEvents(item.streamEvents);
    setSelectedOutputPath(path);
    setError(null);
    setLoading(false);
    saveAgentSession({
      ...item,
      artifactTab: "output",
      selectedOutputPath: path,
    });
  }

  function restoreConversationSession(session: AgentConversationSession) {
    setSelectedTemplateId(session.selectedTemplateId);
    setAgentMode(session.agentMode);
    setPrompt(session.prompt);
    setArtifactTab(session.artifactTab);
    setResult(session.result);
    setStreamEvents(session.streamEvents);
    setSelectedOutputPath(session.selectedOutputPath || (session.result ? preferredAgentOutputPath(session.result) : ""));
    setMessages(session.messages);
    setSessionRuns(session.runs);
    setActiveConversationId(session.id);
    setError(null);
    setLoading(false);
    setShowHistory(false);
    saveAgentSession(snapshotFromConversation(session));
  }

  function startNewConversation() {
    const template = promptTemplates.find((item) => item.id === selectedTemplateId) || promptTemplates[0]!;
    setActiveConversationId(newClientId("session"));
    setSelectedTemplateId(template.id);
    setAgentMode(template.mode);
    setPrompt(template.prompt);
    setArtifactTab("draft");
    setResult(null);
    setStreamEvents([]);
    setSelectedOutputPath("");
    setMessages([]);
    setSessionRuns([]);
    setError(null);
    setLoading(false);
    setShowHistory(false);
  }

  function deleteConversationSession(id: string) {
    setConversationSessions((current) => {
      const next = saveAgentConversationSessions(current.filter((item) => item.id !== id));
      if (activeConversationId === id) {
        const fallback = next[0];
        if (fallback) {
          restoreConversationSession(fallback);
        } else {
          startNewConversation();
        }
      }
      return next;
    });
  }

  async function runAgent(event?: FormEvent) {
    event?.preventDefault();
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) return;
    const pendingResult = result?.status === "needs_input" ? result : null;
    setLoading(true);
    setError(null);
    setResult(null);
    setStreamEvents([]);
    setSelectedOutputPath("");
    setArtifactTab(pendingResult ? "draft" : "output");
    const userMessage: AgentChatMessage = {
      id: newClientId("msg"),
      role: "user",
      content: cleanPrompt,
      createdAt: new Date().toISOString(),
    };
    setMessages((current) => [...current, userMessage]);
    try {
      const request: AgentRunRequest = {
        prompt: cleanPrompt,
        agentMode: pendingResult?.mode || agentMode,
        locale,
        useLlm: true,
        agentToolTimeoutSeconds: 600,
      };
      if (pendingResult?.pending) {
        request.continueRunId = pendingResult.pending.continue_run_id || pendingResult.run_id;
        request.skillId = pendingResult.pending.skill_id || pendingResult.skill?.skill_id || undefined;
        request.params = pendingResult.pending.resolved_params || pendingResult.skill?.params;
      }
      const response = await api.runAgentStream(request, {
        onEvent: (nextEvent) => setStreamEvents((current) => upsertAgentRunEvent(current, nextEvent)),
        onResult: (nextResult) => {
          applyAgentRunResponse(nextResult);
        },
      });
      applyAgentRunResponse(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("agent.runError"));
    } finally {
      setLoading(false);
    }
  }

  function openAgentOutputFile(path: string) {
    setSelectedOutputPath(path);
    setArtifactTab("output");
  }

  const activeRunAssistantIndex = result?.run_id
    ? messages.findIndex((message) => message.role === "assistant" && message.runId === result.run_id)
    : -1;
  const latestUserMessageIndex = (() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index]?.role === "user") return index;
    }
    return -1;
  })();
  const shouldShowEventsBeforeMessages = executionEvents.length > 0 && messages.length === 0;
  const shouldInsertEventsBeforeMessage = (index: number) => (
    executionEvents.length > 0 && activeRunAssistantIndex === index
  );
  const shouldInsertEventsAfterMessage = (index: number) => (
    executionEvents.length > 0 && activeRunAssistantIndex < 0 && latestUserMessageIndex === index
  );
  const renderExecutionTimeline = (key: string) => (
    <Fragment key={key}>
      <div className="agent-tool-toggle">
        <Link2 size={15} />
        <span>{formatMessage(t("agent.eventCount"), { count: executionEvents.length })}</span>
      </div>
      <AgentExecutionTimeline
        events={executionEvents}
        onOpenOutputFile={openAgentOutputFile}
        selectedOutputPath={selectedOutputPath}
        t={t}
      />
    </Fragment>
  );

  return (
    <div className="agent-minimal-page">
      <header className="agent-minimal-head">
        <h2>{artifactTitle}</h2>
        <div className="agent-minimal-actions">
          <button
            type="button"
            className="agent-history-button"
            disabled={loading}
            onClick={startNewConversation}
          >
            <Plus size={16} />
            <span>{t("agent.newConversation")}</span>
          </button>
          <button
            type="button"
            className={`agent-history-button ${showHistory ? "active" : ""}`}
            onClick={() => setShowHistory((current) => !current)}
          >
            <History size={16} />
            <span>{t("agent.history.open")}</span>
            <b>{conversationSessions.length}</b>
          </button>
          <button
            type="button"
            className="icon-only-button"
            disabled={!hasFinalArtifact}
            onClick={() => {
              if (hasFinalArtifact && result?.artifact) {
                downloadText(`${slugify(result.artifact.title)}.json`, artifactJson, "application/json");
              }
            }}
            title={t("agent.downloadArtifact")}
          >
            <Download size={17} />
          </button>
        </div>
      </header>

      {showHistory ? (
        <AgentConversationHistoryPanel
          activeSessionId={activeConversationId}
          locale={locale}
          onDelete={deleteConversationSession}
          onRestore={restoreConversationSession}
          sessions={conversationSessions}
          t={t}
        />
      ) : null}

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
            {shouldShowEventsBeforeMessages ? renderExecutionTimeline("execution-empty") : null}
            {messages.map((message, index) => {
              const linkedRun = message.runId ? sessionRuns.find((item) => item.id === message.runId) : undefined;
              return (
                <Fragment key={message.id}>
                  {shouldInsertEventsBeforeMessage(index) ? renderExecutionTimeline(`execution-before-${message.id}`) : null}
                  <div className={`agent-message ${message.role}`}>
                    <p>{message.content}</p>
                    {message.role === "assistant" && linkedRun && isCompletedArtifactRun(linkedRun.result) ? (
                      <AgentRunOutputFileChips
                        activePath={selectedOutputPath}
                        files={buildAgentOutputFiles(linkedRun.result)}
                        onOpen={(path) => openSessionRunFile(linkedRun, path)}
                        t={t}
                      />
                    ) : null}
                  </div>
                  {shouldInsertEventsAfterMessage(index) ? renderExecutionTimeline(`execution-after-${message.id}`) : null}
                </Fragment>
              );
            })}
            {loading ? (
              <div className="agent-message assistant">
                <Loader2 className="spin" size={17} />
                <span>{t("agent.running")}</span>
              </div>
            ) : null}
            {error ? <div className="alert danger">{error}</div> : null}
            {!messages.length && !loading ? (
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
                placeholder={awaitingInput ? t("agent.clarificationPlaceholder") : t("agent.promptPlaceholder")}
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
              <AgentArtifactSummary result={hasFinalArtifact ? result : null} t={t} />
            ) : null}
            {artifactTab === "draft" ? (
              <AgentDraftView prompt={prompt} result={result} t={t} />
            ) : null}
            {artifactTab === "output" ? (
              hasFinalArtifact && result ? (
                <AgentOutputFilesView
                  onSelectedPathChange={setSelectedOutputPath}
                  result={result}
                  selectedPath={selectedOutputPath}
                  t={t}
                />
              ) : selectedOutputPath ? (
                <AgentSingleOutputFileView path={selectedOutputPath} t={t} />
              ) : <AgentArtifactPlaceholder loading={loading} t={t} />
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function formatAgentHistoryTime(value: string, locale: Locale): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AgentConversationHistoryPanel({
  activeSessionId,
  locale,
  onDelete,
  onRestore,
  sessions,
  t,
}: {
  activeSessionId: string;
  locale: Locale;
  onDelete: (id: string) => void;
  onRestore: (item: AgentConversationSession) => void;
  sessions: AgentConversationSession[];
  t: Translator;
}) {
  return (
    <section className="agent-run-history-panel">
      <header>
        <div>
          <h3>{t("agent.history.title")}</h3>
          <p>{formatMessage(t("agent.history.count"), { count: sessions.length })}</p>
        </div>
      </header>
      {sessions.length ? (
        <div className="agent-run-history-list">
          {sessions.map((item) => {
            const latestRun = item.runs[0];
            const statusLabel = latestRun?.status === "needs_input"
              ? t("agent.event.status.needsInput")
              : t("agent.event.status.ok");
            const fileCount = item.runs.reduce((total, run) => total + run.fileCount, 0);
            const sessionMeta = formatMessage(t("agent.history.sessionMeta"), {
              messages: item.messages.length,
              runs: item.runs.length,
            });
            return (
              <article className={`agent-run-history-item ${activeSessionId === item.id ? "active" : ""}`} key={item.id}>
                <button className="agent-run-history-main" type="button" onClick={() => onRestore(item)}>
                  <span className="agent-run-history-title">{item.title}</span>
                  <span className="agent-run-history-meta">
                    {formatAgentHistoryTime(item.updatedAt, locale)}
                    {" · "}
                    {statusLabel}
                    {activeSessionId === item.id ? ` · ${t("agent.history.current")}` : ""}
                  </span>
                  <span className="agent-run-history-detail">
                    {sessionMeta}
                  </span>
                  <span className="agent-run-history-detail">
                    {t("agent.history.latestSkill")}: {latestRun?.skillName || t("agent.history.noSkill")}
                  </span>
                  <span className="agent-run-history-detail">
                    {formatMessage(t("agent.history.files"), { count: fileCount })}
                  </span>
                </button>
                <button
                  className="agent-run-history-delete"
                  type="button"
                  onClick={() => onDelete(item.id)}
                  title={t("agent.history.delete")}
                >
                  <Trash2 size={15} />
                </button>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="agent-run-history-empty">{t("agent.history.empty")}</p>
      )}
    </section>
  );
}

function upsertAgentRunEvent(events: AgentRunEvent[], nextEvent: AgentRunEvent): AgentRunEvent[] {
  const existingIndex = events.findIndex((event) => event.id === nextEvent.id);
  if (existingIndex < 0) {
    return [...events, nextEvent].sort((left, right) => left.seq - right.seq);
  }
  const updated = [...events];
  updated[existingIndex] = { ...updated[existingIndex], ...nextEvent };
  return updated.sort((left, right) => left.seq - right.seq);
}

function buildLoadingAgentEvents(t: Translator): AgentRunEvent[] {
  const timestamp = new Date().toISOString();
  return [
    {
      id: "loading-input",
      seq: 1,
      type: "input",
      status: "ok",
      title: t("agent.event.input"),
      message: t("agent.event.inputBody"),
      timestamp,
    },
    {
      id: "loading-planner",
      seq: 2,
      type: "planner",
      status: "running",
      title: t("agent.event.planner"),
      message: t("agent.event.plannerBody"),
      timestamp,
    },
    {
      id: "loading-tools",
      seq: 3,
      type: "tool",
      status: "running",
      title: t("agent.event.tools"),
      message: t("agent.event.toolsBody"),
      timestamp,
    },
    {
      id: "loading-artifact",
      seq: 4,
      type: "artifact",
      status: "running",
      title: t("agent.event.artifact"),
      message: t("agent.event.artifactBody"),
      timestamp,
    },
  ];
}

function agentEventStatusLabel(status: AgentRunEvent["status"], t: Translator): string {
  if (status === "ok") return t("agent.event.status.ok");
  if (status === "error") return t("agent.event.status.error");
  if (status === "running") return t("agent.event.status.running");
  if (status === "needs_input") return t("agent.event.status.needsInput");
  return t("agent.event.status.skipped");
}

function formatEventDetail(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function displayAgentEvent(event: AgentRunEvent, t: Translator): { title: string; message: string } {
  if (event.type === "input") {
    return {
      title: t("agent.event.input"),
      message: t("agent.event.inputBody"),
    };
  }
  return {
    title: event.title,
    message: event.message || "",
  };
}

function AgentExecutionTimeline({
  events,
  onOpenOutputFile,
  selectedOutputPath,
  t,
}: {
  events: AgentRunEvent[];
  onOpenOutputFile: (path: string) => void;
  selectedOutputPath: string;
  t: Translator;
}) {
  return (
    <div className="agent-execution-timeline">
      {events.map((event) => {
        const displayEvent = displayAgentEvent(event, t);
        const hasDetails = Boolean(event.input || event.output || event.file_path || event.data || typeof event.duration_ms === "number");
        const canOpenOutputFile = (event.type === "tool" || event.type === "skill") && event.file_path && event.status !== "running";
        return (
          <article className={`agent-execution-event ${event.status}`} key={event.id}>
            <div className="agent-execution-dot" aria-hidden="true" />
            <div className="agent-execution-card">
              <div className="agent-execution-head">
                <span>{displayEvent.title}</span>
                <b>{agentEventStatusLabel(event.status, t)}</b>
              </div>
              {displayEvent.message ? <p>{displayEvent.message}</p> : null}
              <div className="agent-execution-meta">
                <span>{event.type}</span>
                {event.tool ? <span>{event.tool}</span> : null}
                {typeof event.duration_ms === "number" ? <span>{event.duration_ms}ms</span> : null}
                {event.file_path ? <span>{t("agent.event.fileSaved")}</span> : null}
              </div>
              {canOpenOutputFile ? (
                <button
                  className={`agent-execution-file-button ${selectedOutputPath === event.file_path ? "active" : ""}`}
                  type="button"
                  onClick={() => onOpenOutputFile(event.file_path!)}
                >
                  <FileText size={16} />
                  <span>
                    <strong>{lastPathPart(event.file_path!)}</strong>
                    <small>{event.type === "skill" ? t("agent.event.openSkillFile") : t("agent.event.openOutputFile")}</small>
                  </span>
                </button>
              ) : null}
              {hasDetails ? (
                <details className="agent-execution-details">
                  <summary>{t("agent.event.details")}</summary>
                  <dl className="agent-execution-detail-grid">
                    <div>
                      <dt>{t("agent.event.doing")}</dt>
                      <dd>{displayEvent.message || displayEvent.title}</dd>
                    </div>
                    <div>
                      <dt>{t("agent.event.success")}</dt>
                      <dd>{agentEventStatusLabel(event.status, t)}</dd>
                    </div>
                    {typeof event.duration_ms === "number" ? (
                      <div>
                        <dt>{t("agent.event.duration")}</dt>
                        <dd>{event.duration_ms}ms</dd>
                      </div>
                    ) : null}
                    {event.file_path ? (
                      <div className="wide">
                        <dt>{t("agent.event.filePath")}</dt>
                        <dd><code>{event.file_path}</code></dd>
                      </div>
                    ) : null}
                    {event.input ? (
                      <div className="wide">
                        <dt>{t("agent.event.inputParams")}</dt>
                        <dd><pre>{formatEventDetail(event.input)}</pre></dd>
                      </div>
                    ) : null}
                    {event.output ? (
                      <div className="wide">
                        <dt>{t("agent.event.outputSummary")}</dt>
                        <dd><pre>{formatEventDetail(event.output)}</pre></dd>
                      </div>
                    ) : null}
                    {event.data ? (
                      <div className="wide">
                        <dt>{t("agent.event.rawMeta")}</dt>
                        <dd><pre>{formatEventDetail(event.data)}</pre></dd>
                      </div>
                    ) : null}
                  </dl>
                </details>
              ) : null}
            </div>
          </article>
        );
      })}
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
  if (!result?.artifact) return <AgentArtifactPlaceholder loading={false} t={t} />;
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

function isCompletedArtifactRun(result: AgentRunResponse | null): result is AgentRunResponse {
  return Boolean(result && result.status !== "needs_input" && result.response_type !== "message" && result.artifact);
}

const HIDDEN_AGENT_OUTPUT_FILE_TYPES = new Set(["artifact", "events", "run"]);

function buildAgentOutputFiles(result: AgentRunResponse): AgentOutputFileMeta[] {
  const files = result.output_files?.length
    ? result.output_files.filter((file) => !HIDDEN_AGENT_OUTPUT_FILE_TYPES.has(String(file.type || "").toLowerCase()))
    : [];
  if (!files.length) {
    result.tools.forEach((tool) => {
      if (!tool.file_path) return;
      files.push({
        type: "tool",
        label: tool.label,
        name: lastPathPart(tool.file_path),
        path: tool.file_path,
        summary: tool.summary,
      });
    });
  }
  const seen = new Set<string>();
  return files.filter((file) => {
    if (!file.path || seen.has(file.path)) return false;
    seen.add(file.path);
    return true;
  });
}

function outputFileTypeLabel(file: AgentOutputFileMeta, t: Translator): string {
  const type = String(file.type || "").toLowerCase();
  if (type === "report") return t("agent.output.type.report");
  if (type === "tool") return t("agent.output.type.tool");
  if (type === "artifact") return t("agent.output.type.artifact");
  if (type === "events") return t("agent.output.type.events");
  if (type === "run") return t("agent.output.type.run");
  if (type === "skill") return t("agent.output.type.skill");
  return file.type || t("agent.output.type.file");
}

function outputFileShortLabel(file: AgentOutputFileMeta, t: Translator): string {
  const type = outputFileTypeLabel(file, t);
  const label = file.label || file.name || type;
  return label === type ? type : `${type} · ${label}`;
}

function preferredAgentOutputPath(result: AgentRunResponse): string {
  const files = buildAgentOutputFiles(result);
  return files.find((file) => file.type === "report" || file.name.toLowerCase().endsWith(".html"))?.path
    || files.find((file) => file.type === "tool")?.path
    || files[0]?.path
    || "";
}

function AgentRunOutputFileChips({
  activePath,
  files,
  onOpen,
  t,
}: {
  activePath: string;
  files: AgentOutputFileMeta[];
  onOpen: (path: string) => void;
  t: Translator;
}) {
  const visibleFiles = files.filter((file) => file.path);
  if (!visibleFiles.length) return null;
  return (
    <div className="agent-message-files" aria-label={t("agent.output.files")}>
      <span>{formatMessage(t("agent.output.filesCount"), { count: visibleFiles.length })}</span>
      <div>
        {visibleFiles.map((file) => (
          <button
            className={activePath === file.path ? "active" : ""}
            key={file.path}
            type="button"
            onClick={() => onOpen(file.path)}
            title={file.summary || file.name}
          >
            <FileText size={14} />
            <span>{outputFileShortLabel(file, t)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function lastPathPart(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function AgentSingleOutputFileView({ path, t }: { path: string; t: Translator }) {
  const [openedFile, setOpenedFile] = useState<AgentOutputFileResponse | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setOpenedFile(null);
      return;
    }
    let ignore = false;
    setLoadingFile(true);
    setFileError(null);
    api.readAgentOutputFile(path)
      .then((file) => {
        if (!ignore) setOpenedFile(file);
      })
      .catch((err) => {
        if (!ignore) {
          setOpenedFile(null);
          setFileError(err instanceof Error ? err.message : t("agent.output.fileError"));
        }
      })
      .finally(() => {
        if (!ignore) setLoadingFile(false);
      });
    return () => {
      ignore = true;
    };
  }, [path, t]);

  return (
    <section className="agent-output-single">
      <header className="agent-output-preview-head">
        <div>
          <span>{openedFile?.name || lastPathPart(path)}</span>
          <code>{openedFile?.path || path}</code>
        </div>
        {openedFile ? (
          <button
            type="button"
            className="icon-only-button"
            onClick={() => downloadText(openedFile.name, outputFileDownloadText(openedFile), outputFileMime(openedFile))}
            title={t("agent.output.download")}
          >
            <Download size={16} />
          </button>
        ) : null}
      </header>
      {loadingFile ? <AgentArtifactPlaceholder loading t={t} /> : null}
      {fileError ? <div className="alert danger">{fileError}</div> : null}
      {!loadingFile && !fileError && openedFile ? <AgentOutputFileContent file={openedFile} t={t} /> : null}
    </section>
  );
}

function AgentOutputFilesView({
  onSelectedPathChange,
  result,
  selectedPath,
  t,
}: {
  onSelectedPathChange: (path: string) => void;
  result: AgentRunResponse;
  selectedPath: string;
  t: Translator;
}) {
  const files = useMemo(() => buildAgentOutputFiles(result), [result]);
  const [openedFile, setOpenedFile] = useState<AgentOutputFileResponse | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const preferredPath = preferredAgentOutputPath(result);
  const effectiveSelectedPath = files.some((file) => file.path === selectedPath)
    ? selectedPath
    : preferredPath || files[0]?.path || "";

  useEffect(() => {
    if (!files.length) {
      if (selectedPath) onSelectedPathChange("");
      return;
    }
    if (!files.some((file) => file.path === selectedPath)) {
      onSelectedPathChange(effectiveSelectedPath);
    }
  }, [effectiveSelectedPath, files, onSelectedPathChange, selectedPath]);

  useEffect(() => {
    if (!effectiveSelectedPath) {
      setOpenedFile(null);
      return;
    }
    let ignore = false;
    setLoadingFile(true);
    setFileError(null);
    api.readAgentOutputFile(effectiveSelectedPath)
      .then((file) => {
        if (!ignore) setOpenedFile(file);
      })
      .catch((err) => {
        if (!ignore) {
          setOpenedFile(null);
          setFileError(err instanceof Error ? err.message : t("agent.output.fileError"));
        }
      })
      .finally(() => {
        if (!ignore) setLoadingFile(false);
      });
    return () => {
      ignore = true;
    };
  }, [effectiveSelectedPath, t]);

  const selectedMeta = files.find((file) => file.path === effectiveSelectedPath);

  if (!files.length) return <AgentArtifactPlaceholder loading={false} t={t} />;

  return (
    <section className="agent-output-preview">
      <header className="agent-output-preview-head">
        <div>
          <span>{selectedMeta?.label || openedFile?.name || t("agent.output.preview")}</span>
          <code>{openedFile?.path || effectiveSelectedPath}</code>
        </div>
        {openedFile ? (
          <button
            type="button"
            className="icon-only-button"
            onClick={() => downloadText(openedFile.name, outputFileDownloadText(openedFile), outputFileMime(openedFile))}
            title={t("agent.output.download")}
          >
            <Download size={16} />
          </button>
        ) : null}
      </header>
      {loadingFile ? <AgentArtifactPlaceholder loading t={t} /> : null}
      {fileError ? <div className="alert danger">{fileError}</div> : null}
      {!loadingFile && !fileError && openedFile ? <AgentOutputFileContent file={openedFile} t={t} /> : null}
    </section>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function renderTableValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return formatEventDetail(value);
  if (typeof value === "object") return formatEventDetail(value);
  return String(value);
}

type RenderableTable = {
  name: string;
  rows: Array<Record<string, unknown>>;
};

const renderableArrayPriority = [
  "products",
  "review_samples",
  "reviews",
  "articles",
  "videos",
  "posts",
  "events",
  "tools",
  "evidence",
  "steps",
];
const nestedEvidenceArrayKeys = ["review_samples", "comment_items", "comment_samples", "reviews", "comments"];

function isNestedEvidenceArrayKey(key: string): boolean {
  return nestedEvidenceArrayKeys.includes(key);
}

function extractRenderableTables(content: unknown): RenderableTable[] {
  if (Array.isArray(content)) return [{ name: "items", rows: content.filter(isRecord) }].filter((table) => table.rows.length);
  if (!isRecord(content)) return [];
  const data = isRecord(content.data) ? content.data : content;
  const tables: RenderableTable[] = [];
  const added = new Set<string>();
  const hasPrimaryArray = Object.entries(data).some(
    ([key, value]) => Array.isArray(value) && !isNestedEvidenceArrayKey(key) && value.some(isRecord),
  );

  function addTable(name: string, value: unknown) {
    if (!Array.isArray(value) || added.has(name)) return;
    if (hasPrimaryArray && isNestedEvidenceArrayKey(name)) return;
    const rows = value.filter(isRecord);
    if (!rows.length) return;
    tables.push({ name, rows });
    added.add(name);
  }

  renderableArrayPriority.forEach((key) => addTable(key, data[key]));
  Object.entries(data).forEach(([key, value]) => addTable(key, value));
  return tables;
}

function renderableColumns(rows: Array<Record<string, unknown>>): string[] {
  const preferred = [
    "id",
    "type",
    "tool",
    "instruction",
    "title",
    "name",
    "brand",
    "asin",
    "product_asin",
    "product_brand",
    "status",
    "summary",
    "price",
    "rating",
    "rating_value",
    "reviews",
    "body",
    "date_text",
    "url",
  ];
  const keys = new Set<string>();
  rows.forEach((row) => {
    Object.entries(row).forEach(([key, value]) => {
      if (isNestedEvidenceArrayKey(key) && Array.isArray(value)) return;
      if (value !== undefined) keys.add(key);
    });
  });
  const preferredKeys = preferred.filter((key) => keys.has(key));
  const rest = [...keys].filter((key) => !preferredKeys.includes(key));
  return [...preferredKeys, ...rest];
}

function nestedEvidenceRows(row: Record<string, unknown>): Array<{ key: string; label: string; rows: Array<Record<string, unknown>> }> {
  return nestedEvidenceArrayKeys
    .map((key) => {
      const value = row[key];
      const rows = Array.isArray(value) ? value.filter(isRecord) : [];
      return { key, label: key, rows };
    })
    .filter((item) => item.rows.length);
}

function nestedEvidenceCount(row: Record<string, unknown>): number {
  return nestedEvidenceRows(row).reduce((total, item) => total + item.rows.length, 0);
}

function summaryItems(content: unknown): Array<{ label: string; value: string }> {
  if (!isRecord(content)) return [];
  return ["name", "label", "status", "summary", "duration_ms", "generated_at", "run_id"]
    .filter((key) => content[key] !== undefined)
    .map((key) => ({ label: key, value: renderTableValue(content[key]) }));
}

function outputFileMime(file: AgentOutputFileResponse): string {
  if (file.format === "html") return "text/html";
  return file.format === "markdown" ? "text/markdown" : "application/json";
}

function outputFileDownloadText(file: AgentOutputFileResponse): string {
  return (file.format === "markdown" || file.format === "html") && typeof file.content === "string"
    ? file.content
    : formatEventDetail(file.content);
}

function AgentOutputFileContent({ file, t }: { file: AgentOutputFileResponse; t: Translator }) {
  if (file.format === "html" && typeof file.content === "string") {
    return <AgentHtmlPreview html={file.content} title={file.name} />;
  }
  if (file.format === "markdown" && typeof file.content === "string") {
    return <AgentMarkdownPreview markdown={file.content} />;
  }
  const renderer = findArtifactRenderer(file, file.content);
  if (renderer) {
    return <>{renderer.render({ content: file.content, file, t })}</>;
  }
  return <AgentJsonPreview content={file.content} t={t} />;
}

function AgentHtmlPreview({ html, title }: { html: string; title: string }) {
  return (
    <iframe
      className="agent-html-preview"
      sandbox=""
      srcDoc={html}
      title={title}
    />
  );
}

function AgentMarkdownPreview({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/);
  const elements: ReactNode[] = [];
  let index = 0;
  let key = 0;

  function readUntil(predicate: (line: string) => boolean): string[] {
    const collected: string[] = [];
    while (index < lines.length && !predicate(lines[index] || "")) {
      collected.push(lines[index] || "");
      index += 1;
    }
    return collected;
  }

  while (index < lines.length) {
    const line = lines[index] || "";
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }
    if (trimmed.startsWith("```")) {
      const fence = trimmed;
      index += 1;
      const code = readUntil((nextLine) => nextLine.trim().startsWith("```"));
      if (index < lines.length) index += 1;
      elements.push(
        <pre className="agent-md-code" key={key++}>
          <code>{fence.replace(/^```/, "") ? `${fence.replace(/^```/, "")}\n${code.join("\n")}` : code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (trimmed.startsWith("# ")) {
      elements.push(<h1 key={key++}>{trimmed.slice(2)}</h1>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      elements.push(<h2 key={key++}>{trimmed.slice(3)}</h2>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith("### ")) {
      elements.push(<h3 key={key++}>{trimmed.slice(4)}</h3>);
      index += 1;
      continue;
    }
    if (trimmed.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length && (lines[index] || "").trim().startsWith("- ")) {
        items.push((lines[index] || "").trim().slice(2));
        index += 1;
      }
      elements.push(<ul key={key++}>{items.map((item) => <li key={item}>{item}</li>)}</ul>);
      continue;
    }
    if (/^\d+\.\s/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s/.test((lines[index] || "").trim())) {
        items.push((lines[index] || "").trim().replace(/^\d+\.\s/, ""));
        index += 1;
      }
      elements.push(<ol key={key++}>{items.map((item) => <li key={item}>{item}</li>)}</ol>);
      continue;
    }
    if (trimmed.includes("|") && (lines[index + 1] || "").includes("---")) {
      const tableLines: string[] = [];
      while (index < lines.length && (lines[index] || "").includes("|")) {
        tableLines.push(lines[index] || "");
        index += 1;
      }
      const rows = tableLines
        .filter((row) => !/^\s*\|?\s*:?-{3,}/.test(row))
        .map((row) => row.split("|").map((cell) => cell.trim()).filter(Boolean));
      const [header, ...body] = rows;
      if (header) {
        elements.push(
          <table className="agent-md-table" key={key++}>
            <thead><tr>{header.map((cell) => <th key={cell}>{cell}</th>)}</tr></thead>
            <tbody>
              {body.map((row, rowIndex) => (
                <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>,
        );
      }
      continue;
    }
    const paragraph = readUntil((nextLine) => {
      const next = nextLine.trim();
      return !next || next.startsWith("#") || next.startsWith("- ") || /^\d+\.\s/.test(next) || next.startsWith("```");
    }).join(" ");
    elements.push(<p key={key++}>{paragraph}</p>);
  }

  return <article className="agent-markdown-preview">{elements}</article>;
}

type ArtifactRendererProps = {
  content: unknown;
  file: AgentOutputFileResponse;
  t: Translator;
};

type ArtifactRenderer = {
  id: string;
  match: (file: AgentOutputFileResponse, content: unknown, toolName: string) => boolean;
  render: (props: ArtifactRendererProps) => ReactNode;
};

function normalizeName(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function fileToolName(file: AgentOutputFileResponse): string {
  const match = file.name.match(/^tool-\d+-(.+)\.json$/i);
  if (match?.[1]) return match[1].toLowerCase();
  return file.name.replace(/\.(json|md|html)$/i, "").toLowerCase();
}

function outputToolName(file: AgentOutputFileResponse, content: unknown): string {
  if (isRecord(content) && typeof content.name === "string") return normalizeName(content.name);
  return fileToolName(file);
}

function toolPayload(content: unknown): Record<string, unknown> {
  if (isRecord(content) && isRecord(content.data)) return content.data;
  return isRecord(content) ? content : {};
}

function recordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
}

function textValue(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return renderTableValue(value);
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value.replace(/[^0-9.-]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatMetric(value: unknown, fallback = "—"): string {
  const numeric = numberValue(value);
  if (numeric === null) return textValue(value, fallback);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: numeric % 1 ? 1 : 0 }).format(numeric);
}

function formatPercentMetric(value: unknown): string {
  const numeric = numberValue(value);
  if (numeric === null) return textValue(value);
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(normalized)}%`;
}

function compactDisplayText(value: unknown, limit = 180): string {
  const normalized = " ".concat(String(value || "").split(/\s+/).join(" ")).trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit - 1).trim()}...`;
}

function firstField(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function nestedEvidenceForRecord(row: Record<string, unknown>): Array<{ key: string; rows: Array<Record<string, unknown>> }> {
  return nestedEvidenceArrayKeys
    .map((key) => ({ key, rows: recordArray(row[key]) }))
    .filter((item) => item.rows.length);
}

function ArtifactStatGrid({ items }: { items: Array<{ label: string; value: unknown; hint?: string }> }) {
  const visible = items.filter((item) => item.value !== undefined && item.value !== null && item.value !== "");
  if (!visible.length) return null;
  return (
    <div className="artifact-stat-grid">
      {visible.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <b>{formatMetric(item.value)}</b>
          {item.hint ? <small>{item.hint}</small> : null}
        </div>
      ))}
    </div>
  );
}

function ArtifactRendererShell({
  children,
  icon,
  stats,
  subtitle,
  summary,
  title,
}: {
  children: ReactNode;
  icon: ReactNode;
  stats?: Array<{ label: string; value: unknown; hint?: string }>;
  subtitle: string;
  summary?: string;
  title: string;
}) {
  return (
    <article className="artifact-renderer">
      <header className="artifact-renderer-hero">
        <div className="artifact-renderer-icon">{icon}</div>
        <div>
          <span>{subtitle}</span>
          <h3>{title}</h3>
          {summary ? <p>{summary}</p> : null}
        </div>
      </header>
      {stats ? <ArtifactStatGrid items={stats} /> : null}
      <div className="artifact-renderer-body">{children}</div>
    </article>
  );
}

function ArtifactSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="artifact-renderer-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function ArtifactPillList({ items }: { items: Array<Record<string, unknown>> | string[] }) {
  const normalized = items
    .map((item) => {
      if (typeof item === "string") return { label: item, value: "" };
      return {
        label: textValue(firstField(item, ["name", "topic", "keyword", "title", "query"]), ""),
        value: firstField(item, ["count", "share", "score", "value"]),
      };
    })
    .filter((item) => item.label);
  if (!normalized.length) return <p className="artifact-muted">暂无可展示数据。</p>;
  return (
    <div className="artifact-pill-list">
      {normalized.map((item) => (
        <span key={`${item.label}-${textValue(item.value, "")}`}>
          {item.label}
          {item.value !== undefined && item.value !== "" ? <b>{formatMetric(item.value)}</b> : null}
        </span>
      ))}
    </div>
  );
}

function ArtifactMiniBars({ items, labelKey = "name", valueKey = "count" }: { items: Array<Record<string, unknown>>; labelKey?: string; valueKey?: string }) {
  const max = Math.max(...items.map((item) => numberValue(item[valueKey]) || 0), 1);
  if (!items.length) return <p className="artifact-muted">暂无可展示数据。</p>;
  return (
    <div className="artifact-mini-bars">
      {items.map((item, index) => {
        const value = numberValue(item[valueKey]) || 0;
        const label = textValue(item[labelKey] ?? item.period ?? item.week ?? item.keyword, `#${index + 1}`);
        return (
          <div key={`${label}-${index}`}>
            <span>{label}</span>
            <div><i style={{ width: `${Math.max(4, (value / max) * 100)}%` }} /></div>
            <b>{formatMetric(value)}</b>
          </div>
        );
      })}
    </div>
  );
}

function ArtifactEvidenceDisclosure({ label, rows }: { label: string; rows: Array<Record<string, unknown>> }) {
  const [open, setOpen] = useState(false);
  if (!rows.length) return null;
  return (
    <div className="artifact-evidence-disclosure">
      <button type="button" onClick={() => setOpen((current) => !current)}>
        <MessageSquare size={13} />
        <span>{open ? "收起" : "展开"} {label} ({rows.length})</span>
      </button>
      {open ? (
        <div className="artifact-evidence-list">
          {rows.map((row, index) => (
            <blockquote key={index}>
              <p>{compactDisplayText(firstField(row, ["body", "text", "content", "snippet", "excerpt", "title"]), 320)}</p>
              <footer>
                {textValue(firstField(row, ["author", "user", "rating", "date_text", "subreddit"]), "")}
              </footer>
            </blockquote>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ArtifactExternalLink({ url }: { url: unknown }) {
  const href = typeof url === "string" ? url : "";
  if (!href) return null;
  return (
    <a className="artifact-link" href={href} rel="noreferrer" target="_blank">
      <ExternalLink size={13} />
      <span>打开来源</span>
    </a>
  );
}

function AmazonShelfArtifact({ content }: ArtifactRendererProps) {
  const wrapper = isRecord(content) ? content : {};
  const data = toolPayload(content);
  const metrics = isRecord(data.metrics) ? data.metrics : {};
  const products = recordArray(data.products);
  const brands = recordArray(data.brands);
  const priceBands = recordArray(data.price_bands);
  const queries = stringArray(data.queries);
  const reviewSampleCount = products.reduce((total, product) => total + recordArray(product.review_samples).length, 0);
  return (
    <ArtifactRendererShell
      icon={<PackageSearch size={22} />}
      subtitle="Amazon shelf"
      title="Amazon 商品货架"
      summary={textValue(wrapper.summary, "价格、评分、评论量、品牌和评论样本信号。")}
      stats={[
        { label: "商品数", value: metrics.products ?? products.length },
        { label: "品牌数", value: brands.length || undefined },
        { label: "平均价格", value: metrics.price_avg ? `$${formatMetric(metrics.price_avg)}` : undefined },
        { label: "平均评分", value: metrics.rating_avg },
        { label: "评论总量", value: metrics.total_review_count },
        { label: "评论样本", value: metrics.review_samples ?? reviewSampleCount },
      ]}
    >
      <div className="artifact-two-column">
        <ArtifactSection title="价格带">
          <ArtifactMiniBars items={priceBands} />
        </ArtifactSection>
        <ArtifactSection title="品牌信号">
          <ArtifactPillList items={brands} />
        </ArtifactSection>
      </div>
      {queries.length ? (
        <ArtifactSection title="检索关键词">
          <ArtifactPillList items={queries} />
        </ArtifactSection>
      ) : null}
      <ArtifactSection title={`商品列表 (${products.length})`}>
        <div className="artifact-product-list">
          {products.length ? products.map((product, index) => {
            const reviews = recordArray(product.review_samples);
            return (
              <article className="artifact-product-card" key={`${textValue(product.asin, String(index))}-${index}`}>
                <div>
                  <span>{textValue(product.brand, "Unknown brand")}</span>
                  <h5>{textValue(product.title, "Untitled product")}</h5>
                  <p>{textValue(product.asin, "")}</p>
                </div>
                <div className="artifact-product-metrics">
                  <span>{textValue(product.price)}</span>
                  <span><Star size={13} />{textValue(product.rating)}</span>
                  <span>{formatMetric(product.reviews)} reviews</span>
                </div>
                <ArtifactPillList items={stringArray(product.badges)} />
                <ArtifactExternalLink url={product.url} />
                <ArtifactEvidenceDisclosure label="review" rows={reviews} />
              </article>
            );
          }) : <p className="artifact-muted">本次工具结果没有返回商品明细。</p>}
        </div>
      </ArtifactSection>
    </ArtifactRendererShell>
  );
}

function RedditVocArtifact({ content }: ArtifactRendererProps) {
  const data = toolPayload(content);
  const coverage = isRecord(data.coverage) ? data.coverage : {};
  const signal = isRecord(data.market_signal) ? data.market_signal : {};
  const sentiment = isRecord(data.sentiment) ? data.sentiment : {};
  const painPoints = recordArray(data.pain_points);
  const brands = recordArray(data.brands);
  const sizes = recordArray(data.sizes);
  const posts = recordArray(data.posts);
  return (
    <ArtifactRendererShell
      icon={<MessageSquare size={22} />}
      subtitle="Reddit VOC"
      title="Reddit 用户声音"
      summary={textValue(signal.summary, "用户痛点、真实语言、品牌和尺码讨论。")}
      stats={[
        { label: "帖子数", value: coverage.posts ?? posts.length },
        { label: "Subreddit", value: coverage.subreddits },
        { label: "市场信号", value: signal.score },
        { label: "正向占比", value: sentiment.positive_share ? formatPercentMetric(sentiment.positive_share) : undefined },
        { label: "负向占比", value: sentiment.negative_share ? formatPercentMetric(sentiment.negative_share) : undefined },
      ]}
    >
      <div className="artifact-two-column">
        <ArtifactSection title="痛点主题">
          <ArtifactPillList items={painPoints} />
        </ArtifactSection>
        <ArtifactSection title="品牌与尺码">
          <ArtifactPillList items={[...brands, ...sizes]} />
        </ArtifactSection>
      </div>
      <ArtifactSection title={`帖子证据 (${posts.length})`}>
        <div className="artifact-feed-list">
          {posts.length ? posts.map((post, index) => {
            const comments = recordArray(post.comment_items);
            return (
              <article className="artifact-feed-card" key={`${textValue(post.id, String(index))}-${index}`}>
                <div className="artifact-feed-meta">
                  <span>{textValue(post.subreddit, "Reddit")}</span>
                  <span>{formatMetric(post.score)} score</span>
                  <span>{formatMetric(post.comments)} comments</span>
                </div>
                <h5>{textValue(post.title, "Untitled post")}</h5>
                <p>{compactDisplayText(post.excerpt, 260)}</p>
                <ArtifactExternalLink url={post.url} />
                <ArtifactEvidenceDisclosure label="comments" rows={comments} />
              </article>
            );
          }) : <p className="artifact-muted">本次工具结果没有返回帖子明细。</p>}
        </div>
      </ArtifactSection>
    </ArtifactRendererShell>
  );
}

function TiktokSocialArtifact({ content }: ArtifactRendererProps) {
  const data = toolPayload(content);
  const metrics = isRecord(data.metrics) ? data.metrics : {};
  const signal = isRecord(data.market_signal) ? data.market_signal : {};
  const hashtags = recordArray(data.hashtags);
  const painPoints = recordArray(data.pain_points);
  const videos = recordArray(data.videos);
  return (
    <ArtifactRendererShell
      icon={<Video size={22} />}
      subtitle="TikTok social"
      title="TikTok 社媒验证"
      summary={textValue(signal.summary, "视频、创作者语言和评论区样本。")}
      stats={[
        { label: "视频数", value: metrics.videos ?? videos.length },
        { label: "创作者", value: metrics.authors },
        { label: "点赞", value: metrics.total_likes },
        { label: "评论", value: metrics.total_comment_count },
        { label: "分享", value: metrics.total_shares },
        { label: "社媒信号", value: signal.score },
      ]}
    >
      <div className="artifact-two-column">
        <ArtifactSection title="Hashtag">
          <ArtifactPillList items={hashtags} />
        </ArtifactSection>
        <ArtifactSection title="评论痛点">
          <ArtifactPillList items={painPoints} />
        </ArtifactSection>
      </div>
      <ArtifactSection title={`视频证据 (${videos.length})`}>
        <div className="artifact-feed-list">
          {videos.length ? videos.map((video, index) => {
            const comments = recordArray(video.comment_samples);
            return (
              <article className="artifact-feed-card" key={`${textValue(video.url, String(index))}-${index}`}>
                <div className="artifact-feed-meta">
                  <span>{textValue(video.author, "Creator")}</span>
                  <span>{formatMetric(video.views)} views</span>
                  <span>{formatMetric(video.comments)} comments</span>
                </div>
                <h5>{textValue(video.title, "Untitled video")}</h5>
                <p>{compactDisplayText(video.snippet, 260)}</p>
                <ArtifactExternalLink url={video.url} />
                <ArtifactEvidenceDisclosure label="comments" rows={comments} />
              </article>
            );
          }) : <p className="artifact-muted">本次工具结果没有返回视频明细。</p>}
        </div>
      </ArtifactSection>
    </ArtifactRendererShell>
  );
}

function MediaRankingsArtifact({ content }: ArtifactRendererProps) {
  const data = toolPayload(content);
  const articles = recordArray(data.articles);
  return (
    <ArtifactRendererShell
      icon={<Newspaper size={22} />}
      subtitle="Media rankings"
      title="媒体测评与公开榜单"
      summary={textValue(data.summary, "美国媒体测评、公开排名和可访问报道页面。")}
      stats={[
        { label: "文章数", value: articles.length },
        { label: "高权威来源", value: articles.filter((article) => normalizeName(article.authority_level).includes("high")).length },
        { label: "含产品信号", value: articles.filter((article) => recordArray(article.product_signals).length).length },
      ]}
    >
      <ArtifactSection title={`文章来源 (${articles.length})`}>
        <div className="artifact-source-grid">
          {articles.length ? articles.map((article, index) => (
            <article key={`${textValue(article.url, String(index))}-${index}`}>
              <span>{textValue(article.domain, "Unknown source")}</span>
              <h5>{textValue(article.title, "Untitled article")}</h5>
              <p>{textValue(article.source_type)} · {textValue(article.authority_level)}</p>
              <ArtifactPillList items={recordArray(article.product_signals)} />
              <ArtifactExternalLink url={article.url} />
            </article>
          )) : <p className="artifact-muted">本次工具结果没有返回媒体文章。</p>}
        </div>
      </ArtifactSection>
    </ArtifactRendererShell>
  );
}

function SifMcpArtifact({ content, file, t }: ArtifactRendererProps) {
  const data = toolPayload(content);
  const tool = outputToolName(file, content).replace(/^sif_/, "");
  const profiles = recordArray(data.profiles);
  const timing = recordArray(data.timing_summary);
  const trends = recordArray(data.trend);
  const asins = recordArray(data.asins);
  const keywords = stringArray(data.keywords);
  const profile = profiles[0];
  const trend = profile && isRecord(profile.trend) ? profile.trend : {};
  const current = profile && isRecord(profile.current) ? profile.current : {};
  const seasonality = profile && isRecord(profile.seasonality) ? profile.seasonality : {};
  const recentWeeks = recordArray(trend.recent_weeks);
  return (
    <ArtifactRendererShell
      icon={<BarChart3 size={22} />}
      subtitle="Sif MCP"
      title={`Sif 数据工具：${tool}`}
      summary={textValue((isRecord(content) ? content.summary : "") || profile?.interpretation || data.render_footer, "关键词、竞争、ASIN 或销量趋势数据。")}
      stats={[
        { label: "国家", value: data.country },
        { label: "关键词", value: profile?.keyword ?? keywords.length },
        { label: "当前搜索量", value: current.search_volume },
        { label: "同比变化", value: trend.yoy_change ? formatPercentMetric(trend.yoy_change) : undefined },
        { label: "趋势", value: trend.direction },
        { label: "季节性", value: seasonality.strength },
      ]}
    >
      {profiles.length ? (
        <ArtifactSection title="关键词画像">
          <div className="artifact-profile-grid">
            {profiles.map((item, index) => {
              const itemTrend = isRecord(item.trend) ? item.trend : {};
              const itemCurrent = isRecord(item.current) ? item.current : {};
              const itemSeasonality = isRecord(item.seasonality) ? item.seasonality : {};
              return (
                <article key={`${textValue(item.keyword, String(index))}-${index}`}>
                  <span>{textValue(item.keyword, "keyword")}</span>
                  <h5>{textValue(item.diagnosis, "诊断")}</h5>
                  <p>{textValue(item.interpretation)}</p>
                  <div>
                    <b>{formatMetric(itemCurrent.search_volume)}</b>
                    <small>当前搜索量</small>
                  </div>
                  <div>
                    <b>{formatPercentMetric(itemTrend.yoy_change)}</b>
                    <small>同比变化</small>
                  </div>
                  <div>
                    <b>{textValue(itemSeasonality.strength)}</b>
                    <small>季节性</small>
                  </div>
                </article>
              );
            })}
          </div>
        </ArtifactSection>
      ) : null}
      {recentWeeks.length ? (
        <ArtifactSection title="近期周度趋势">
          <ArtifactMiniBars items={recentWeeks} labelKey="week" valueKey="volume" />
        </ArtifactSection>
      ) : null}
      {timing.length ? (
        <ArtifactSection title="行动时机">
          <div className="artifact-source-grid">
            {timing.map((item, index) => (
              <article key={`${textValue(item.keyword, String(index))}-${index}`}>
                <span>{textValue(item.keyword, "keyword")}</span>
                <h5>{formatMetric(item.weeks_to_peak)} weeks to peak</h5>
                <p>{textValue(item.action_hint)}</p>
              </article>
            ))}
          </div>
        </ArtifactSection>
      ) : null}
      {trends.length || asins.length ? (
        <ArtifactSection title="结构化明细">
          <AgentJsonPreview content={trends.length ? trends : asins} t={t} />
        </ArtifactSection>
      ) : null}
      {!profiles.length && !timing.length && !trends.length && !asins.length ? (
        <AgentJsonPreview content={content} t={t} />
      ) : null}
    </ArtifactRendererShell>
  );
}

function FinalArtifactJson({ content }: ArtifactRendererProps) {
  const artifact = isRecord(content) ? content : {};
  return (
    <ArtifactRendererShell
      icon={<Sparkles size={22} />}
      subtitle="Final artifact"
      title={textValue(artifact.title, "Artifact")}
      summary={textValue(artifact.executive_summary, "")}
      stats={[
        { label: "关键发现", value: Array.isArray(artifact.key_findings) ? artifact.key_findings.length : undefined },
        { label: "机会", value: Array.isArray(artifact.opportunities) ? artifact.opportunities.length : undefined },
        { label: "风险", value: Array.isArray(artifact.risks) ? artifact.risks.length : undefined },
        { label: "下一步", value: Array.isArray(artifact.next_steps) ? artifact.next_steps.length : undefined },
      ]}
    >
      <div className="artifact-two-column">
        <ArtifactSection title="关键发现">
          <ArtifactBulletList items={stringArray(artifact.key_findings)} />
        </ArtifactSection>
        <ArtifactSection title="机会">
          <ArtifactBulletList items={stringArray(artifact.opportunities)} />
        </ArtifactSection>
        <ArtifactSection title="风险">
          <ArtifactBulletList items={stringArray(artifact.risks)} />
        </ArtifactSection>
        <ArtifactSection title="下一步">
          <ArtifactBulletList items={stringArray(artifact.next_steps)} />
        </ArtifactSection>
      </div>
    </ArtifactRendererShell>
  );
}

function ArtifactBulletList({ items }: { items: string[] }) {
  if (!items.length) return <p className="artifact-muted">暂无。</p>;
  return (
    <ul className="artifact-bullet-list">
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}

const artifactRenderers: ArtifactRenderer[] = [
  {
    id: "amazon_shelf",
    match: (_file, _content, toolName) => toolName === "amazon_shelf",
    render: (props) => <AmazonShelfArtifact {...props} />,
  },
  {
    id: "reddit_voc",
    match: (_file, _content, toolName) => toolName === "reddit_voc",
    render: (props) => <RedditVocArtifact {...props} />,
  },
  {
    id: "tiktok_social",
    match: (_file, _content, toolName) => toolName === "tiktok_social",
    render: (props) => <TiktokSocialArtifact {...props} />,
  },
  {
    id: "media_rankings",
    match: (_file, _content, toolName) => toolName === "media_rankings",
    render: (props) => <MediaRankingsArtifact {...props} />,
  },
  {
    id: "sif_mcp",
    match: (_file, _content, toolName) => toolName.startsWith("sif_"),
    render: (props) => <SifMcpArtifact {...props} />,
  },
  {
    id: "final_artifact",
    match: (file, content) => file.name === "artifact.json" && isRecord(content) && typeof content.executive_summary === "string",
    render: (props) => <FinalArtifactJson {...props} />,
  },
];

function findArtifactRenderer(file: AgentOutputFileResponse, content: unknown): ArtifactRenderer | null {
  if (file.format && file.format !== "json") return null;
  const toolName = outputToolName(file, content);
  return artifactRenderers.find((renderer) => renderer.match(file, content, toolName)) || null;
}

function AgentJsonPreview({ content, t }: { content: unknown; t: Translator }) {
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const tables = extractRenderableTables(content)
    .map((table) => ({ ...table, columns: renderableColumns(table.rows) }))
    .filter((table) => table.columns.length);
  const items = summaryItems(content);
  return (
    <div className="agent-json-preview">
      {items.length ? (
        <div className="agent-json-summary">
          {items.map((item) => (
            <div key={item.label}>
              <span>{item.label}</span>
              <b>{item.value}</b>
            </div>
          ))}
        </div>
      ) : null}
      {tables.map((table) => {
        const caption = `${table.name} · ${formatMessage(t("agent.output.previewRows"), { count: table.rows.length })}`;
        const hasNestedEvidence = table.rows.some((row) => nestedEvidenceCount(row) > 0);
        const tableNode = (
          <table className="agent-json-table">
            <thead>
              <tr>
                {table.columns.map((column) => <th key={column}>{column}</th>)}
                {hasNestedEvidence ? <th>{t("agent.output.comments")}</th> : null}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, index) => {
                const rowNestedEvidence = nestedEvidenceRows(row);
                const rowNestedCount = rowNestedEvidence.reduce((total, item) => total + item.rows.length, 0);
                const expandedKey = `${table.name}-${index}`;
                const expanded = Boolean(expandedRows[expandedKey]);
                return (
                  <Fragment key={expandedKey}>
                    <tr key={`${expandedKey}-row`}>
                      {table.columns.map((column) => <td key={column}>{renderTableValue(row[column])}</td>)}
                      {hasNestedEvidence ? (
                        <td>
                          {rowNestedCount ? (
                            <button
                              className="agent-json-expand-button"
                              type="button"
                              onClick={() => setExpandedRows((current) => ({ ...current, [expandedKey]: !current[expandedKey] }))}
                            >
                              {expanded
                                ? t("agent.output.hideComments")
                                : formatMessage(t("agent.output.showCommentsWithCount"), { count: rowNestedCount })}
                            </button>
                          ) : (
                            <span className="agent-json-empty-comments">{t("agent.output.noComments")}</span>
                          )}
                        </td>
                      ) : null}
                    </tr>
                    {expanded && rowNestedCount ? (
                      <tr className="agent-json-child-row" key={`${expandedKey}-comments`}>
                        <td colSpan={table.columns.length + (hasNestedEvidence ? 1 : 0)}>
                          <div className="agent-json-child-panel">
                            {rowNestedEvidence.map((item) => {
                              const childColumns = renderableColumns(item.rows);
                              return (
                                <section key={item.key}>
                                  <h4>{item.label}</h4>
                                  <table className="agent-json-child-table">
                                    <thead>
                                      <tr>{childColumns.map((column) => <th key={column}>{column}</th>)}</tr>
                                    </thead>
                                    <tbody>
                                      {item.rows.map((childRow, childIndex) => (
                                        <tr key={childIndex}>
                                          {childColumns.map((column) => <td key={column}>{renderTableValue(childRow[column])}</td>)}
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </section>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        );
        return (
          <div className="agent-json-table-wrap" key={table.name}>
          <div className="agent-json-table-caption">
            <span>{caption}</span>
          </div>
          {tableNode}
        </div>
        );
      })}
      <details className="agent-json-raw" open={!tables.length}>
        <summary>{t("agent.output.rawJson")}</summary>
        <pre className="artifact-json minimal"><code>{formatEventDetail(content)}</code></pre>
      </details>
    </div>
  );
}

function AgentDraftView({
  prompt,
  result,
  t,
}: {
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
    </div>
  );
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

function LoadingPanel({ text }: { text: string }) {
  return (
    <div className="loading-panel">
      <Loader2 className="spin" />
      <span>{text}</span>
    </div>
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

function SettingsPage({ t }: LocalizedProps) {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.getLLMSettings()
      .then((llmData) => {
        setSettings(llmData);
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : t("settings.loadError")))
      .finally(() => setLoading(false));
  }, [t]);

  function update<K extends keyof LLMSettings>(key: K, value: LLMSettings[K]) {
    if (!settings) return;
    setSettings({ ...settings, [key]: value });
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

  if (loading || !settings) {
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
      </header>

      <form className="settings-form" onSubmit={save}>
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
