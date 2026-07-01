# Insight Agent Reddit MVP

Reddit-first market insight MVP for bra subcategory research. The app collects Reddit posts, enriches selected posts with comment bodies when Agent Reach/OpenCLI is connected, and renders a report-style Web UI with signal strength, pain-point clusters, sentiment, evidence links, data-volume audit, and AI synthesis.

## Can Someone Clone And Run It?

Yes, on Windows with PowerShell, Python 3.11+, and Node.js installed. The setup script creates the Python virtual environment, installs the Python package, installs frontend dependencies, and creates `.env` from `.env.example`.

Live Reddit comments require one extra browser setup step: OpenCLI plus its Chrome extension must be connected to a Chrome profile that is logged in to Reddit. Without that, the app still runs, but Agent Reach will show a clear disconnected status instead of silently falling back to RSS.

AI synthesis is requested by default. Without an LLM API key, the report still runs and shows an LLM unavailable warning.

## Prerequisites

- Windows + PowerShell
- Python 3.11 or newer
- Node.js LTS with `npm`
- Optional: `pnpm`; the scripts prefer `pnpm` when available and fall back to `npm`
- Optional for live Reddit comments: Chrome, OpenCLI, and the OpenCLI Chrome extension
- Optional for AI synthesis: an API key for one configured OpenAI-compatible provider

The PowerShell scripts are the supported path. The Python and frontend projects can be run manually on other platforms, but the checked-in automation is Windows-first.

## Quick Start

From PowerShell:

```powershell
git clone <your-repo-url>
cd <repo-folder>
.\scripts\setup.ps1
.\scripts\dev-all.ps1
```

Open:

```text
http://127.0.0.1:5173
```

Stop both dev services:

```powershell
.\scripts\stop-dev.ps1
```

## What Setup Does

`.\scripts\setup.ps1` does the following:

- Creates `.venv`
- Installs the Python package in editable mode with dev tools: `pip install -e ".[dev]"`
- Copies `.env.example` to `.env` if `.env` does not exist
- Installs frontend dependencies in `frontend/` using `pnpm install` or `npm install`

Useful override variables:

```powershell
$env:INSIGHT_PYTHON="C:\Path\To\python.exe"
$env:INSIGHT_PNPM="C:\Path\To\pnpm.cmd"
```

## Manual Setup

If you do not want to use the setup script:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
cd frontend
npm install
cd ..
```

Then run backend and frontend separately:

```powershell
.\scripts\dev.ps1
.\scripts\dev-frontend.ps1
```

Backend API:

```text
http://127.0.0.1:8000
```

Frontend:

```text
http://127.0.0.1:5173
```

The compatibility entrypoint also works:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Test And Build

Run tests:

```powershell
.\scripts\test.ps1
```

Run the full local check:

```powershell
.\scripts\check.ps1
```

`check.ps1` runs Ruff, pytest, and the frontend production build.

## Project Layout

```text
.
├── frontend/                 # React + Vite + ECharts Web UI
├── src/insight_agent/        # Python package
│   ├── server.py             # HTTP server, Reddit connectors, analysis logic
│   ├── ingestion/            # Agent Reach/OpenCLI normalization
│   ├── llm.py                # OpenAI-compatible LLM synthesis client
│   ├── static/               # Legacy backend-served Web UI
│   └── data/                 # Sample data and LLM provider metadata
├── tests/                    # Automated tests
├── scripts/                  # Windows dev scripts
├── pyproject.toml            # Python package metadata and dev dependencies
├── .env.example              # Local environment template
└── app.py                    # Compatibility entrypoint
```

## Environment File

The first setup run creates `.env` from `.env.example`. `.env` is intentionally ignored by Git because it can contain API keys and local tool paths.

Current default research behavior in `.env.example`:

```text
INSIGHT_RESEARCH_MODE=agent_reach
INSIGHT_RESEARCH_POST_LIMIT=100
AGENT_REACH_BACKEND=opencli
AGENT_REACH_DETAIL_LIMIT=20
AGENT_REACH_COMMENTS_PER_POST=20
INSIGHT_LLM_PROVIDER=deepseek
INSIGHT_LLM_MODEL=deepseek-v4-pro
```

With these defaults, live Reddit collection expects OpenCLI to be ready. For a no-network smoke test, switch the Web UI setting to `sample`, or edit:

```text
INSIGHT_RESEARCH_MODE=sample
```

## Reddit Access Modes

- `agent_reach`: uses Agent Reach upstream tools such as OpenCLI or rdt-cli. This is the preferred path for larger read-only Reddit collection with post detail and comment enrichment. It fails closed when the selected backend is unavailable.
- `auto`: tries Agent Reach, Reddit OAuth, RSS, then built-in sample data.
- `oauth`: requires `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.
- `rss`: uses Reddit search RSS. RSS does not provide comment bodies and can be rate-limited.
- `sample`: uses local sample data so the UI/report can be reviewed without live access.

## Agent Reach And OpenCLI

Agent Reach is the local collection layer. For Reddit, the desktop path uses OpenCLI and a Chrome profile that is logged in to Reddit.

Install Agent Reach and OpenCLI helpers:

```powershell
.\scripts\install-agent-reach.ps1
```

Check status:

```powershell
.\scripts\doctor-agent-reach.ps1
```

In the Web UI:

```text
Settings -> Agent Reach
```

Use **Reconnect OpenCLI extension** before starting research. The button restarts the OpenCLI daemon and refreshes the health check. If it still says disconnected:

```text
1. Open Chrome.
2. Enable/install the OpenCLI Browser Bridge extension.
3. Log in to reddit.com in that Chrome profile.
4. Click Reconnect OpenCLI extension again.
```

When OpenCLI is connected, Agent Reach can collect posts and then call `opencli reddit read` to fetch comment bodies for the configured number of posts.

## Reddit OAuth

OAuth is optional and separate from Agent Reach. Configure it in:

```text
Settings -> Reddit API Credentials
```

Manual `.env` setup also works:

```text
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=InsightAgentRedditDemo/0.1 by yourname
```

OAuth is useful for stable post metadata, but it is not the current preferred path for comment enrichment.

## LLM Analysis

Research runs request AI synthesis by default. The app uses OpenAI-compatible chat completions and stores provider settings in `.env`.

Default provider metadata lives in:

```text
src/insight_agent/data/llm_providers.json
```

Configure from the Web UI:

```text
Settings -> LLM Connection
```

Or edit `.env`, for example:

```text
INSIGHT_LLM_PROVIDER=deepseek
INSIGHT_LLM_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=your_key
```

If the key is missing or invalid, collection and local analysis still run. The report will include an LLM warning instead of failing the whole request.

## Troubleshooting

**Frontend cannot start**

- Install Node.js LTS.
- Run `npm install` inside `frontend/`, or rerun `.\scripts\setup.ps1`.

**Backend cannot import `insight_agent`**

- Run `.\scripts\setup.ps1`.
- Or set `PYTHONPATH` to `src` and use `.venv\Scripts\python.exe`.

**Agent Reach says OpenCLI disconnected**

- Open Chrome with the OpenCLI extension enabled.
- Log in to Reddit in that same Chrome profile.
- Click `Settings -> Agent Reach -> Reconnect OpenCLI extension`.
- Run `.\scripts\doctor-agent-reach.ps1` for command-line diagnostics.

**No Reddit comments are collected**

- RSS and OAuth modes do not provide comment bodies in this app.
- Use `agent_reach` with OpenCLI connected.
- Make sure `AGENT_REACH_DETAIL_LIMIT` and `AGENT_REACH_COMMENTS_PER_POST` are greater than `0`.
- Use “Bypass cache” on the research page after fixing OpenCLI, otherwise an older cached run can hide the change.

**AI synthesis is unavailable**

- Add the selected provider API key in Settings or `.env`.
- Restart the backend if you edited `.env` manually.

## Git Hygiene

Do not commit:

- `.env`
- `.venv/`
- `.cache/`
- `.dev/`
- `frontend/node_modules/`
- `frontend/dist/`

The frontend lockfile `frontend/pnpm-lock.yaml` is committed so dependency versions are reproducible for pnpm users. npm users can still run `npm install`.

## Reference Repo

`Vibe-Trading/` is treated as a local reference project for architecture, UI patterns, charts, and LLM settings. It is ignored by Git for this project.

See:

```text
docs/vibe_trading_adaptation.md
```

## MVP Limits

The market score is directional and should not be treated as market size or sales volume. Reddit availability depends on platform access, login state, browser extension connectivity, and rate limits. Comment-body coverage is only available through Agent Reach detail enrichment and is limited by the configured post/comment caps.
