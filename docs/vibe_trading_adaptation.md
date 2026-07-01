# Vibe-Trading Reference Adaptation

This project uses `Vibe-Trading/` as a reference repo for application shape, not for trading logic.

## What To Adopt

- Backend/frontend separation: keep the market-insight API separate from the Web UI, with a clean API client boundary.
- Run/report model: every analysis should eventually be a saved report with input, source coverage, evidence, warnings, and generated artifacts.
- Settings surface: LLM credentials and model settings should be configurable from the UI and persisted locally in `.env`.
- Provider abstraction: LLM providers should be data-driven from JSON metadata rather than hardcoded in UI components.
- Evidence-first reports: conclusions should have source URLs, confidence, and data gaps.
- Chart vocabulary: use charts for signal strength, trend, sentiment mix, topic counts, source coverage, and brand/attribute maps.
- Development ergonomics: scripts should start/stop/status/log the app without manual process hunting.

## What Not To Adopt Yet

- Multi-agent orchestration and swarm execution.
- Trading-specific connectors, tools, run cards, and safety gates.
- Large LangGraph/ReAct loop machinery.
- Heavy live streaming protocol until reports become long-running jobs.

## Market-Insight Target Shape

```text
frontend/
  React/Vite app shell
  pages: Research, Reports, ReportDetail, Settings
  charts: TrendChart, SentimentChart, TopicBarChart, SourceCoverage

src/insight_agent/
  api.py
  connectors/
    reddit.py
  analysis/
    reddit_report.py
    llm_synthesis.py
  llm.py
  settings.py
  storage.py
  data/
    llm_providers.json
```

## Current MVP Delta

- Added data-driven LLM provider settings.
- Added local `.env` persistence through the Web UI.
- Added optional OpenAI-compatible LLM synthesis for Reddit reports.
- Added trend and sentiment chart panels to the current Web UI.
- Kept Reddit-only scope and avoided multi-agent orchestration.
