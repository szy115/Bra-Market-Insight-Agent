const form = document.querySelector("#analysisForm");
const runButton = document.querySelector("#runButton");
const emptyState = document.querySelector("#emptyState");
const loadingState = document.querySelector("#loadingState");
const errorState = document.querySelector("#errorState");
const report = document.querySelector("#report");
const reportTitle = document.querySelector("#reportTitle");
const sourceBadge = document.querySelector("#sourceBadge");
const settingsToggle = document.querySelector("#settingsToggle");
const llmForm = document.querySelector("#llmForm");
const saveLlmButton = document.querySelector("#saveLlmButton");
const llmStatus = document.querySelector("#llmStatus");

const els = {
  signalScore: document.querySelector("#signalScore"),
  signalSummary: document.querySelector("#signalSummary"),
  coveragePosts: document.querySelector("#coveragePosts"),
  coverageText: document.querySelector("#coverageText"),
  sentimentHeadline: document.querySelector("#sentimentHeadline"),
  sentimentText: document.querySelector("#sentimentText"),
  painPoints: document.querySelector("#painPoints"),
  subreddits: document.querySelector("#subreddits"),
  mentions: document.querySelector("#mentions"),
  trendChart: document.querySelector("#trendChart"),
  sentimentChart: document.querySelector("#sentimentChart"),
  opportunities: document.querySelector("#opportunities"),
  llmPanel: document.querySelector("#llmPanel"),
  llmAnalysis: document.querySelector("#llmAnalysis"),
  posts: document.querySelector("#posts"),
  methodNotes: document.querySelector("#methodNotes"),
  warnings: document.querySelector("#warnings"),
};

let llmSettings = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setState(state) {
  emptyState.classList.toggle("hidden", state !== "empty");
  loadingState.classList.toggle("hidden", state !== "loading");
  errorState.classList.toggle("hidden", state !== "error");
  report.classList.toggle("hidden", state !== "report");
}

function sourceLabel(mode) {
  const labels = {
    agent_reach: "Agent Reach",
    oauth: "Live Reddit OAuth",
    rss: "Live Reddit RSS",
    sample: "Sample fallback",
  };
  return labels[mode] || mode || "Unknown source";
}

function renderBars(container, items, nameKey = "name") {
  if (!items.length) {
    container.innerHTML = `<p class="post-meta">No strong signal detected.</p>`;
    return;
  }
  const max = Math.max(...items.map((item) => item.count), 1);
  container.innerHTML = items
    .map((item) => {
      const pct = Math.max(6, Math.round((item.count / max) * 100));
      return `
        <div class="bar-row">
          <strong>${escapeHtml(item[nameKey])}</strong>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
          <span>${item.count}</span>
        </div>
      `;
    })
    .join("");
}

function renderPainPoints(points) {
  if (!points.length) {
    els.painPoints.innerHTML = `<p class="post-meta">No repeated pain-point clusters were detected.</p>`;
    return;
  }
  els.painPoints.innerHTML = points
    .map((point) => {
      const examples = point.examples
        .map(
          (example) => `
          <div class="example">
            <a href="${escapeHtml(example.url)}" target="_blank" rel="noreferrer">
              ${escapeHtml(example.title)}
            </a>
            <p>${escapeHtml(example.snippet)}</p>
          </div>
        `,
        )
        .join("");
      return `
        <article class="cluster">
          <div class="cluster-head">
            <h4>${escapeHtml(point.topic)}</h4>
            <span class="cluster-count">${point.count} mentions</span>
          </div>
          <div class="examples">${examples}</div>
        </article>
      `;
    })
    .join("");
}

function renderMentions(brands, sizes) {
  const rows = [
    ...brands.map((item) => ({ label: item.name, count: item.count, type: "Brand" })),
    ...sizes.map((item) => ({ label: item.name, count: item.count, type: "Size" })),
  ].slice(0, 10);
  if (!rows.length) {
    els.mentions.innerHTML = `<p class="post-meta">No brand or size mentions detected.</p>`;
    return;
  }
  els.mentions.innerHTML = rows
    .map(
      (row) => `
      <div class="mention-chip">
        <span>${escapeHtml(row.label)}</span>
        <strong>${row.type} · ${row.count}</strong>
      </div>
    `,
    )
    .join("");
}

function renderTrendChart(points) {
  if (!points.length) {
    els.trendChart.innerHTML = `<p class="post-meta">No dated live posts available for a trend line.</p>`;
    return;
  }
  const width = 560;
  const height = 180;
  const padding = 26;
  const max = Math.max(...points.map((p) => p.count), 1);
  const xStep = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;
  const coords = points.map((point, index) => {
    const x = padding + index * xStep;
    const y = height - padding - (point.count / max) * (height - padding * 2);
    return { ...point, x, y };
  });
  const path = coords
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const labels = coords
    .filter((_, index) => index === 0 || index === coords.length - 1 || coords.length <= 6)
    .map(
      (point) =>
        `<text x="${point.x}" y="${height - 4}" text-anchor="middle">${escapeHtml(point.month.slice(5) || point.month)}</text>`,
    )
    .join("");
  const dots = coords
    .map(
      (point) =>
        `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(point.month)}: ${point.count}</title></circle>`,
    )
    .join("");
  els.trendChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Discussion trend line">
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" class="axis" />
      <path d="${path}" class="trend-line" />
      <g class="trend-dots">${dots}</g>
      <g class="chart-labels">${labels}</g>
    </svg>
  `;
}

function renderSentimentChart(sentiment) {
  const total = Math.max(sentiment.positive + sentiment.neutral + sentiment.negative, 1);
  const rows = [
    { label: "Positive", count: sentiment.positive, cls: "positive" },
    { label: "Neutral", count: sentiment.neutral, cls: "neutral" },
    { label: "Negative", count: sentiment.negative, cls: "negative" },
  ];
  els.sentimentChart.innerHTML = `
    <div class="sentiment-stack">
      ${rows
        .map((row) => {
          const pct = Math.round((row.count / total) * 100);
          return `<div class="${row.cls}" style="width:${pct}%"><span>${pct}%</span></div>`;
        })
        .join("")}
    </div>
    <div class="sentiment-legend">
      ${rows.map((row) => `<span><i class="${row.cls}"></i>${row.label}: ${row.count}</span>`).join("")}
    </div>
  `;
}

function renderOpportunities(items) {
  els.opportunities.innerHTML = items
    .map(
      (item) => `
      <article class="opportunity">
        <div class="opportunity-head">
          <h4>${escapeHtml(item.title)}</h4>
        </div>
        <p>${escapeHtml(item.detail)}</p>
      </article>
    `,
    )
    .join("");
}

function renderLlmAnalysis(llm) {
  if (!llm || !llm.enabled) {
    els.llmPanel.classList.add("hidden");
    els.llmAnalysis.innerHTML = "";
    return;
  }
  els.llmPanel.classList.remove("hidden");
  if (llm.status !== "ok") {
    els.llmAnalysis.innerHTML = `<div class="warning">${escapeHtml(llm.message || "LLM analysis is unavailable.")}</div>`;
    return;
  }
  const result = llm.result || {};
  const takeaways = (result.strategic_takeaways || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const opportunities = (result.opportunity_areas || [])
    .map((item) => {
      const links = (item.evidence_urls || [])
        .map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">source</a>`)
        .join(" ");
      return `
        <article class="opportunity">
          <h4>${escapeHtml(item.title)}</h4>
          <p>${escapeHtml(item.rationale)}</p>
          <div class="post-meta">${escapeHtml(item.confidence || "Low")} confidence · ${links}</div>
        </article>
      `;
    })
    .join("");
  const gaps = (result.data_gaps || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  els.llmAnalysis.innerHTML = `
    <p class="llm-summary">${escapeHtml(result.executive_summary || "")}</p>
    <div class="llm-grid">
      <div><h4>Strategic takeaways</h4><ul>${takeaways}</ul></div>
      <div><h4>Data gaps</h4><ul>${gaps}</ul></div>
    </div>
    <div class="opportunity-list">${opportunities}</div>
    <p class="post-meta">Provider: ${escapeHtml(llm.provider)} · Model: ${escapeHtml(llm.model)}</p>
  `;
}

function renderPosts(posts) {
  els.posts.innerHTML = posts
    .map(
      (post, index) => {
        const comments = (post.comment_items || []).filter((comment) => String(comment.text || "").trim());
        const commentMarkup = comments.length
          ? `<div class="comment-list">${comments
              .slice(0, 20)
              .map(
                (comment) => `
                  <div class="comment-item">
                    <p>${escapeHtml(comment.text)}</p>
                    <span>${escapeHtml(comment.author ? `u/${comment.author}` : "Reddit")} · ${escapeHtml(comment.score ?? 0)}</span>
                  </div>
                `,
              )
              .join("")}</div>`
          : `<p class="no-comments">No comment text was collected; this run only has Reddit's comment counts.</p>`;
        return `
      <article class="post">
        <div class="post-head">
          <h4><span class="post-index">#${index + 1}</span><a href="${escapeHtml(post.url)}" target="_blank" rel="noreferrer">${escapeHtml(post.title)}</a></h4>
          <span>${escapeHtml(post.source || "reddit")}</span>
        </div>
        <div class="post-meta">r/${escapeHtml(post.subreddit || "unknown")} · ${escapeHtml(post.created_utc || "unknown date")} · Reddit comments ${escapeHtml(post.comments ?? 0)}</div>
        <p>${escapeHtml(post.excerpt || "No snippet available.")}</p>
        <div class="comment-audit">Comment text ${comments.length}</div>
        ${commentMarkup}
      </article>
    `;
      },
    )
    .join("");
}

function renderMethod(method, warnings) {
  els.methodNotes.innerHTML = (method.notes || [])
    .map((note) => `<li>${escapeHtml(note)}</li>`)
    .join("");
  const methodWarning = `Query used: ${method.query}`;
  const allWarnings = [methodWarning, ...(warnings || [])];
  els.warnings.innerHTML = allWarnings
    .map((warning) => `<div class="warning">${escapeHtml(warning)}</div>`)
    .join("");
}

function renderReport(data) {
  reportTitle.textContent = data.category;
  sourceBadge.textContent = sourceLabel(data.source_mode);
  els.signalScore.textContent = `${data.market_signal.score}/100`;
  els.signalSummary.textContent = data.market_signal.summary;
  els.coveragePosts.textContent = `${data.coverage.posts} posts`;
  els.coverageText.textContent = `${data.coverage.subreddits} subreddits · confidence ${data.coverage.confidence}`;

  const negativePct = Math.round((data.sentiment.negative_share || 0) * 100);
  const positivePct = Math.round((data.sentiment.positive_share || 0) * 100);
  els.sentimentHeadline.textContent = `${negativePct}% negative`;
  els.sentimentText.textContent = `${data.sentiment.positive} positive · ${data.sentiment.neutral} neutral · ${data.sentiment.negative} negative`;

  renderPainPoints(data.pain_points || []);
  renderBars(els.subreddits, data.coverage.top_subreddits || []);
  renderMentions(data.brands || [], data.sizes || []);
  renderTrendChart(data.trend || []);
  renderSentimentChart(data.sentiment || { positive: 0, neutral: 0, negative: 0 });
  renderOpportunities(data.opportunities || []);
  renderLlmAnalysis(data.llm_analysis);
  renderPosts(data.posts || []);
  renderMethod(data.method || {}, data.warnings || []);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const payload = {
    category: formData.get("category"),
    timeRange: formData.get("timeRange"),
    limit: Number(formData.get("limit")),
    mode: formData.get("mode"),
    useLlm: formData.get("useLlm") === "on",
    bypassCache: formData.get("bypassCache") === "on",
  };

  runButton.disabled = true;
  setState("loading");
  errorState.textContent = "";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Analysis failed");
    }
    renderReport(data);
    setState("report");
  } catch (error) {
    errorState.textContent = error.message;
    setState("error");
  } finally {
    runButton.disabled = false;
  }
});

function applyProviderDefaults(providerName) {
  if (!llmSettings) return;
  const provider = llmSettings.providers.find((item) => item.name === providerName);
  if (!provider) return;
  llmForm.elements.model_name.value = provider.default_model;
  llmForm.elements.base_url.value = provider.default_base_url;
}

async function loadLlmSettings() {
  try {
    const response = await fetch("/api/settings/llm");
    llmSettings = await response.json();
    const providerSelect = llmForm.elements.provider;
    providerSelect.innerHTML = llmSettings.providers
      .map((provider) => `<option value="${escapeHtml(provider.name)}">${escapeHtml(provider.label)}</option>`)
      .join("");
    providerSelect.value = llmSettings.provider;
    llmForm.elements.model_name.value = llmSettings.model_name;
    llmForm.elements.base_url.value = llmSettings.base_url;
    llmForm.elements.temperature.value = llmSettings.temperature;
    llmForm.elements.timeout_seconds.value = llmSettings.timeout_seconds;
    llmStatus.textContent = llmSettings.api_key_configured
      ? `Key configured · saved in ${llmSettings.env_path}`
      : `No key configured · saved in ${llmSettings.env_path}`;
  } catch (error) {
    llmStatus.textContent = `Failed to load LLM settings: ${error.message}`;
  }
}

settingsToggle.addEventListener("click", () => {
  llmForm.classList.toggle("hidden");
});

llmForm.elements.provider.addEventListener("change", (event) => {
  applyProviderDefaults(event.target.value);
});

llmForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(llmForm);
  const payload = {
    provider: formData.get("provider"),
    model_name: formData.get("model_name"),
    base_url: formData.get("base_url"),
    api_key: formData.get("api_key"),
    clear_api_key: formData.get("clear_api_key") === "on",
    temperature: Number(formData.get("temperature")),
    timeout_seconds: Number(formData.get("timeout_seconds")),
  };
  saveLlmButton.disabled = true;
  llmStatus.textContent = "Saving...";
  try {
    const response = await fetch("/api/settings/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Failed to save settings");
    llmSettings = data;
    llmForm.elements.api_key.value = "";
    llmForm.elements.clear_api_key.checked = false;
    llmStatus.textContent = data.api_key_configured ? "Saved · key configured" : "Saved · no key configured";
  } catch (error) {
    llmStatus.textContent = error.message;
  } finally {
    saveLlmButton.disabled = false;
  }
});

loadLlmSettings();
