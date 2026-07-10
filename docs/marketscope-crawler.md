# MarketScope Chrome-session crawler

This collector captures data that the TikTok MarketScope UI loads in a Chrome profile that is already signed in. It uses the existing OpenCLI Browser Bridge and does not read Chrome cookies, Local Storage, passwords, or profile files.

## Security boundary

- Only `https://marketscope.tiktok.com` URLs are accepted.
- Only JSON responses whose path starts with `/wormhole/` are saved.
- By default, the collector also calls three audited, GET-only endpoints in the page context: account info, brand info, and the homepage task list. It does not replay unknown POST requests.
- Request and response headers are not collected.
- Full query strings are not saved. Only ordinary paging, date, metric, region, and `accountId` parameters are retained.
- Common authentication fields such as access tokens, session keys, CSRF tokens, cookies, and passwords are recursively redacted from JSON bodies.
- Output is local and defaults to `.cache/marketscope/`, which is ignored by Git.
- OpenCLI's temporary per-session network cache is deleted in the collector's cleanup path after response details are copied and sanitized.
- The collector opens its own background tab and closes only that tab. It never closes the user's original MarketScope tab.
- HTTP 401, 403, 429, login pages, and CAPTCHAs are treated as failures. The collector does not bypass or repeatedly retry them.

Use it only with MarketScope accounts and data you are authorized to access.

## Prerequisites

1. Chrome is open in the profile that can access MarketScope.
2. The OpenCLI Browser Bridge extension is enabled in that profile.
3. OpenCLI reports a connected extension:

```powershell
opencli daemon status
```

The output should contain `Extension: connected`.

## Check connectivity

From the repository root:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m insight_agent.ingestion.marketscope doctor
```

## Capture the supplied homepage

```powershell
.\scripts\crawl-marketscope.ps1 `
  -Url "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559"
```

The command prints a small summary. The data itself is written to a timestamped JSON file under:

```text
.cache/marketscope/
```

Choose an explicit output path when needed:

```powershell
.\scripts\crawl-marketscope.ps1 `
  -Url "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559" `
  -Output ".cache\marketscope\brand-homepage.json"
```

If several Chrome profiles are connected, pass the alias shown by `opencli profile list`:

```powershell
.\scripts\crawl-marketscope.ps1 `
  -Profile "gq3ccqgw" `
  -Url "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559"
```

## Capture multiple pages

The Python entry point accepts more than one URL and processes them sequentially:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m insight_agent.ingestion.marketscope capture `
  "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559" `
  "https://marketscope.tiktok.com/brand/perception?accountId=7433364033920663559"
```

Only use page URLs confirmed by the MarketScope navigation UI. Do not guess account IDs or attempt to access accounts that are not assigned to the connected user.

## Output format

The JSON bundle contains:

- `schema_version` and `source_mode`
- capture start and finish timestamps
- coverage and truncation limits
- each page's source URL, resolved URL, account ID, title, and visible text excerpt
- deduplicated `/wormhole/` responses with method, status, sanitized endpoint, body hash, and JSON body
- explicit warnings for missing, non-JSON, truncated, or unauthorized responses

The collector records only what those pages load during the run. Lazy-loaded tabs, unvisited pagination, alternate date ranges, and modules unavailable to the account are not included automatically.

Use passive capture only when you do not want the three allowlisted GET requests:

```powershell
.\scripts\crawl-marketscope.ps1 `
  -PassiveOnly `
  -Url "https://marketscope.tiktok.com/brand/homepage?accountId=7433364033920663559"
```

## Troubleshooting

`AUTH_REQUIRED`

: Sign in to MarketScope in the same Chrome profile connected to OpenCLI, verify that the account is assigned in Business Center, and run the command again.

`OpenCLI Browser Bridge is not connected`

: Enable the OpenCLI extension, run `opencli daemon restart`, then check `opencli daemon status`.

No `/wormhole/` JSON responses

: Increase `-SettleSeconds` up to 15, confirm that the page displays real dashboard data, and verify that the connected profile is the one you used to sign in.

Large or missing API bodies

: OpenCLI currently caps an individual captured response. The output marks truncation; narrow the MarketScope date range or page before capturing again.
