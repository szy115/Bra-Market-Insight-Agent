# Insight Agent Reddit MVP

Reddit-first market insight MVP for bra subcategory research. The demo accepts a category, fetches Reddit-visible posts when possible, and renders a report-style Web UI with signal strength, pain-point clusters, sentiment, evidence links, and data caveats.

## Project Layout

```text
.
├── frontend/                 # React + Vite + ECharts Web UI
├── src/insight_agent/        # Python package
│   ├── server.py             # HTTP server, Reddit connector, analysis logic
│   ├── static/               # Legacy backend-served Web UI
│   └── data/                 # Sample fallback data
├── tests/                    # Automated tests
├── scripts/                  # Windows dev scripts
├── pyproject.toml            # Package metadata and dev dependencies
├── .env.example              # Local environment template
└── app.py                    # Compatibility entrypoint
```

## Setup

From PowerShell:

```powershell
.\scripts\setup.ps1
```

The setup script creates `.venv`, installs the Python package in editable mode with dev tools, installs frontend dependencies, and creates `.env` from `.env.example` if needed.

Traditional requirements files are also provided for tooling that expects them:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Run

Recommended full-stack dev mode:

```powershell
.\scripts\dev-all.ps1
```

Open:

```text
http://127.0.0.1:5173
```

Stop both services:

```powershell
.\scripts\stop-dev.ps1
```

Separate terminals also work:

```powershell
.\scripts\dev.ps1
.\scripts\dev-frontend.ps1
```

Backend API:

```text
http://127.0.0.1:8000
```

The compatibility entrypoint also works:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Test

```powershell
.\scripts\test.ps1
```

Full local check:

```powershell
.\scripts\check.ps1
```

## Reddit Access Modes

- `auto`: tries Agent Reach, Reddit OAuth, RSS, then built-in sample data.
- `agent_reach`: uses Agent Reach upstream tools such as OpenCLI or rdt-cli. This is the preferred internal MVP path for larger read-only Reddit collection with post-detail/comment enrichment.
- `oauth`: requires `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.
- `rss`: uses Reddit search RSS. This can still be rate-limited.
- `sample`: uses local sample data so the UI/report can be reviewed without live access.

## Agent Reach

Agent Reach is treated as a loose, multi-platform collection provider. It is not part of the analysis logic. The backend calls upstream command-line tools, normalizes their output into evidence items, and then converts those evidence items into the existing report pipeline.

For Reddit, install Agent Reach outside this workspace, then install the Reddit/OpenCLI channel:

```powershell
.\scripts\install-agent-reach.ps1
```

Desktop setup should use OpenCLI with a dedicated Reddit account logged in through Chrome. Server setup can use rdt-cli with Cookie, but protect Cookie values like passwords.

Check status any time:

```powershell
.\scripts\doctor-agent-reach.ps1
```

If the doctor output says `Extension: disconnected`, finish the one manual browser step:

```text
1. Install/connect the OpenCLI Chrome extension.
2. Keep Chrome open.
3. Log in to Reddit in Chrome with a dedicated Reddit account.
4. Run .\scripts\doctor-agent-reach.ps1 again.
```

When the extension is connected, Settings should show Agent Reach as ready and `auto` mode will stop falling back to RSS.

In the Web UI:

```text
Settings -> Agent Reach
```

Configure backend, timeout, how many posts to enrich with details, and how many comments to attach per enriched post. Keep volume conservative and rely on cache/rate limits for internal use.

You can configure OAuth from the Web UI:

```text
Settings -> Reddit API Credentials
```

The UI writes these values to `.env` and syncs the running backend process. Manual `.env` setup also works:

```text
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=InsightAgentRedditDemo/0.1 by yourname
```

## LLM Analysis

The Web UI has an `LLM Settings` panel inspired by the reference project's settings surface. It stores provider, model, base URL, and API key in the local `.env` file. Research runs request AI synthesis by default; if no model key is configured, the report still runs and shows a clear LLM unavailable warning.

Supported provider metadata is data-driven from:

```text
src/insight_agent/data/llm_providers.json
```

## Reference Repo

`Vibe-Trading/` is treated as a local reference project for architecture, UI patterns, charts, and LLM settings. It is ignored by Git for this project.

See:

```text
docs/vibe_trading_adaptation.md
```

## MVP Limits

This demo analyzes Reddit post titles and snippets, not complete comment threads. The market score is directional and should not be treated as market size or sales volume.
