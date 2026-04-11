const state = {
  selectedId: null,
  memories: [],
  provider: null,
  runtime: {},
};

const SCOPE_FIELDS = ["user_id", "agent_id", "run_id"];

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Accept": "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function qs(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderStats(payload) {
  const stats = qs("stats-grid");
  const totals = payload.totals || {};
  const runtime = payload.runtime || {};
  state.provider = payload.provider;
  state.runtime = runtime;
  qs("runtime-pill").textContent = `${payload.provider} | ${runtime.api_host}:${runtime.api_port}`;
  stats.innerHTML = [
    ["Active provider", payload.provider],
    ["Memories", totals.memories ?? 0],
    ["Pinned", totals.pinned ?? 0],
    ["Archived", totals.archived ?? 0],
    ["Connected clients", totals.connected_clients ?? 0],
    ["Configured clients", totals.configured_clients ?? 0],
    ["Stale integrations", totals.stale_clients ?? 0],
  ].map(([label, value]) => `
    <article class="stat-card">
      <div class="stat-label">${escapeHtml(label)}</div>
      <div class="stat-value">${escapeHtml(value)}</div>
    </article>
  `).join("");

  const warning = qs("overview-callout");
  if (payload.warning) {
    warning.className = "notice notice-warning";
    warning.textContent = payload.warning.includes("At least one of")
      ? "Mem0 can only browse records inside a known scope. Use user_id, agent_id, or run_id in Memory Explorer."
      : payload.warning;
    warning.classList.remove("hidden");
  } else {
    warning.className = "notice notice-info hidden";
    warning.classList.add("hidden");
    warning.textContent = "";
  }

  renderScopeSummary();
}

function currentScope() {
  return {
    user_id: qs("user_id").value.trim(),
    agent_id: qs("agent_id").value.trim(),
    run_id: qs("run_id").value.trim(),
  };
}

function hasScope() {
  const scope = currentScope();
  return Boolean(scope.user_id || scope.agent_id || scope.run_id);
}

function scopeSummary() {
  const scope = currentScope();
  if (scope.user_id) return `user_id: ${scope.user_id}`;
  if (scope.agent_id) return `agent_id: ${scope.agent_id}`;
  if (scope.run_id) return `run_id: ${scope.run_id}`;
  return "No scope selected";
}

function activeScopeItems() {
  const scope = currentScope();
  return SCOPE_FIELDS
    .filter((field) => scope[field])
    .map((field) => ({ field, value: scope[field] }));
}

function renderScopeSummary() {
  const summary = qs("scope-summary");
  const active = activeScopeItems();
  if (!active.length) {
    summary.classList.add("hidden");
    summary.innerHTML = "";
    return;
  }
  summary.innerHTML = `
    <div class="scope-summary-copy">
      <strong>Current explorer scope</strong>
      <span>This view is narrowed to one memory context.</span>
    </div>
    <div class="scope-pills">
      ${active.map((item) => `<span class="scope-pill"><span class="scope-pill-label">${escapeHtml(item.field)}</span><span class="scope-pill-value">${escapeHtml(item.value)}</span></span>`).join("")}
    </div>
  `;
  summary.classList.remove("hidden");
}

function renderActiveScopeBar() {
  const bar = qs("active-scope");
  const active = activeScopeItems();
  if (!active.length) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML = `
    <div class="active-scope-copy">
      <strong>Browsing scoped records</strong>
      <span>${escapeHtml(scopeSummary())}</span>
    </div>
    <div class="scope-pills">
      ${active.map((item) => `<button class="scope-pill scope-pill-action" type="button" data-clear-field="${escapeHtml(item.field)}"><span class="scope-pill-label">${escapeHtml(item.field)}</span><span class="scope-pill-value">${escapeHtml(item.value)}</span><span class="scope-pill-close">×</span></button>`).join("")}
    </div>
  `;
  bar.classList.remove("hidden");
  bar.querySelectorAll("[data-clear-field]").forEach((button) => {
    button.addEventListener("click", () => {
      const field = button.dataset.clearField;
      if (field) {
        qs(field).value = "";
        loadMemories();
      }
    });
  });
}

function renderClients(payload) {
  const list = qs("client-list");
  const items = payload.results || [];
  function stateLabel(item) {
    if (item.health === "connected") return "Connected";
    if (item.health === "configured") return "Configured";
    if (item.health === "stale_config") return "Stale config";
    if (item.health === "timeout") return "Check timed out";
    if (item.health === "not_configured") return "Not configured";
    if (item.health === "not_detected") return "Not detected";
    return item.connected ? "Connected" : "Unknown";
  }

  function stateClass(item) {
    if (item.health === "connected") return "badge-ok";
    if (item.health === "configured") return "badge-info";
    if (item.health === "stale_config") return "badge-warn";
    if (item.health === "timeout") return "badge-warn";
    if (item.health === "not_configured" || item.health === "not_detected") return "badge-muted";
    return "badge-muted";
  }

  list.innerHTML = items.map((item) => `
    <article class="client-card">
      <div class="memory-topline">
        <strong>${escapeHtml(item.target)}</strong>
        <span class="badge ${stateClass(item)}">${escapeHtml(stateLabel(item))}</span>
      </div>
      <div class="memory-meta">
        <span>${escapeHtml(item.kind || "config")}</span>
        ${item.path ? `<span>${escapeHtml(item.path)}</span>` : ""}
      </div>
      <div class="client-details">
        ${item.launcher ? `<div><span class="client-label">Launcher</span><code>${escapeHtml(item.launcher)}</code></div>` : ""}
        ${item.command ? `<div><span class="client-label">Command</span><code>${escapeHtml(item.command)}</code></div>` : ""}
        ${item.expected_launcher && item.stale_launcher ? `<div><span class="client-label">Expected launcher</span><code>${escapeHtml(item.expected_launcher)}</code></div>` : ""}
        ${item.stale_launcher ? `<div class="client-warning">Configured, but still pointing to an old launcher. Reconnect this client.</div>` : ""}
        ${item.health === "timeout" ? `<div class="client-warning">The live status check timed out. The integration may still work, but this console could not verify it quickly.</div>` : ""}
        ${!item.launcher && item.details ? `<pre class="client-raw">${escapeHtml(item.details)}</pre>` : ""}
      </div>
    </article>
  `).join("");
}

function memoryCard(item) {
  const score = item.score ? `score ${Number(item.score).toFixed(2)}` : item.updated_at || item.created_at || "no timestamp";
  return `
    <article class="memory-card ${state.selectedId === item.id ? "active" : ""}" data-memory-id="${escapeHtml(item.id)}">
      <div class="memory-topline">
        <strong>${escapeHtml(item.user_id || item.agent_id || item.run_id || item.id)}</strong>
        <div>
          ${item.pinned ? '<span class="badge badge-pinned">Pinned</span>' : ""}
        </div>
      </div>
      <p class="memory-snippet">${escapeHtml(item.display_text || "(empty)")}</p>
      <div class="memory-meta">
        <span>${escapeHtml(score)}</span>
        <span>${escapeHtml(item.provider || "")}</span>
        ${item.metadata ? `<span>metadata</span>` : ""}
      </div>
    </article>
  `;
}

function renderExplorerCallout(message, type = "info") {
  const callout = qs("explorer-callout");
  if (!message) {
    callout.className = "notice notice-info hidden";
    callout.classList.add("hidden");
    callout.textContent = "";
    return;
  }
  callout.className = type === "warning" ? "notice notice-warning" : "notice notice-info";
  callout.textContent = message;
  callout.classList.remove("hidden");
}

function renderExplorerEmpty(message) {
  const empty = qs("explorer-empty");
  if (!message) {
    empty.classList.add("hidden");
    empty.textContent = "";
    return;
  }
  empty.textContent = message;
  empty.classList.remove("hidden");
}

function mem0NeedsScope() {
  return state.provider === "mem0" && !hasScope();
}

function renderScopeAwareEmpty(payload) {
  if (mem0NeedsScope()) {
    renderExplorerEmpty("Pick a scope to browse Mem0 records. Start with a user, agent, or run that should own the memories you want to inspect.");
    renderExplorerCallout("Tip: use a stable user_id for personal preferences, an agent_id for long-lived tools, or a run_id for one session.", "info");
    return;
  }

  if (payload.warning) {
    renderExplorerEmpty(`No records were returned for ${scopeSummary()}. Try a different scope or search term.`);
    return;
  }

  renderExplorerEmpty(`No memories match the current filters for ${scopeSummary()}.`);
}

function renderMemories(payload) {
  state.memories = payload.items || [];
  const list = qs("memory-list");
  renderActiveScopeBar();
  renderExplorerCallout(null);
  renderExplorerEmpty(null);

  if (payload.warning) {
    const message = payload.warning.includes("At least one of")
      ? "Mem0 only returns records inside a known scope. Add a user_id, agent_id, or run_id, then search again."
      : payload.warning;
    renderExplorerCallout(message, "warning");
  }

  if (!state.memories.length) {
    list.innerHTML = "";
    renderScopeAwareEmpty(payload);
    selectMemory(null);
    return;
  }
  if (!state.selectedId || !state.memories.some((item) => item.id === state.selectedId)) {
    state.selectedId = state.memories[0].id;
  }
  list.innerHTML = state.memories.map(memoryCard).join("");
  list.querySelectorAll(".memory-card").forEach((card) => {
    card.addEventListener("click", () => selectMemory(card.dataset.memoryId));
  });
  selectMemory(state.selectedId);
}

async function loadOverview() {
  const [stats, clients] = await Promise.all([
    request("/admin/stats"),
    request("/admin/clients"),
  ]);
  renderStats(stats);
  renderClients(clients);
}

function currentFilters() {
  const params = new URLSearchParams();
  const query = qs("query").value.trim();
  const scope = currentScope();
  if (query) params.set("query", query);
  if (scope.user_id) params.set("user_id", scope.user_id);
  if (scope.agent_id) params.set("agent_id", scope.agent_id);
  if (scope.run_id) params.set("run_id", scope.run_id);
  if (qs("pinned_only").checked) params.set("pinned", "true");
  params.set("limit", "100");
  return params;
}

function applyFiltersFromUrl() {
  const params = new URLSearchParams(window.location.search);
  qs("query").value = params.get("query") || "";
  qs("user_id").value = params.get("user_id") || "";
  qs("agent_id").value = params.get("agent_id") || "";
  qs("run_id").value = params.get("run_id") || "";
  qs("pinned_only").checked = (params.get("pinned") || "").toLowerCase() === "true";
}

function syncUrlFromFilters() {
  const params = currentFilters();
  params.delete("limit");
  const next = params.toString();
  const nextUrl = `${window.location.pathname}${next ? `?${next}` : ""}`;
  const current = `${window.location.pathname}${window.location.search}`;
  if (nextUrl !== current) {
    window.history.replaceState({}, "", nextUrl);
  }
}

async function copyCurrentViewLink() {
  const url = `${window.location.origin}${window.location.pathname}${window.location.search}`;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      renderExplorerCallout("Link copied. You can reopen or share this exact explorer view.", "info");
      return;
    }
  } catch (error) {
    // Fall back to legacy copy path below.
  }

  const input = document.createElement("input");
  input.value = url;
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  input.remove();
  renderExplorerCallout("Link copied. You can reopen or share this exact explorer view.", "info");
}

async function loadMemories() {
  try {
    const params = currentFilters();
    syncUrlFromFilters();
    renderScopeSummary();
    const payload = await request(`/admin/memories?${params.toString()}`);
    renderMemories(payload);
  } catch (error) {
    renderMemories({ items: [] });
    qs("memory-list").innerHTML = "";
    renderExplorerCallout(error.message, "warning");
    renderExplorerEmpty("The explorer could not load records for the current filters.");
  }
}

function setExclusiveScope(field, value) {
  SCOPE_FIELDS.forEach((id) => {
    qs(id).value = id === field ? value : "";
  });
}

function clearScope() {
  SCOPE_FIELDS.forEach((id) => {
    qs(id).value = "";
  });
}

function selectMemory(memoryId) {
  state.selectedId = memoryId;
  const selected = state.memories.find((item) => item.id === memoryId);
  document.querySelectorAll(".memory-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.memoryId === memoryId);
  });
  if (!selected) {
    qs("detail-empty").classList.remove("hidden");
    qs("detail-form").classList.add("hidden");
    return;
  }
  qs("detail-empty").classList.add("hidden");
  qs("detail-form").classList.remove("hidden");
  qs("detail-memory").value = selected.display_text || "";
  qs("detail-metadata").value = JSON.stringify(selected.metadata || {}, null, 2);
  qs("detail-pinned").checked = Boolean(selected.pinned);
  qs("detail-meta").textContent = JSON.stringify({
    record_id: selected.id,
    provider: selected.provider,
    scope: {
      user_id: selected.user_id,
      agent_id: selected.agent_id,
      run_id: selected.run_id,
    },
    timestamps: {
      created_at: selected.created_at,
      updated_at: selected.updated_at,
      admin_updated_at: selected.admin_updated_at,
    },
    score: selected.score,
  }, null, 2);
}

async function saveSelected(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const metadataText = qs("detail-metadata").value.trim();
  let metadata = {};
  if (metadataText) {
    metadata = JSON.parse(metadataText);
  }
  await request(`/admin/memories/${encodeURIComponent(state.selectedId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      memory: qs("detail-memory").value,
      metadata,
      pinned: qs("detail-pinned").checked,
    }),
  });
  await Promise.all([loadOverview(), loadMemories()]);
}

async function deleteSelected() {
  if (!state.selectedId) return;
  if (!confirm("Delete this memory?")) return;
  await request(`/admin/memories/${encodeURIComponent(state.selectedId)}`, {
    method: "DELETE",
  });
  state.selectedId = null;
  await Promise.all([loadOverview(), loadMemories()]);
}

async function bootstrap() {
  applyFiltersFromUrl();
  qs("refresh-overview").addEventListener("click", () => Promise.all([loadOverview(), loadMemories()]));
  qs("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loadMemories();
  });
  qs("reset-search").addEventListener("click", () => {
    qs("query").value = "";
    clearScope();
    qs("pinned_only").checked = false;
    loadMemories();
  });
  qs("clear-scope").addEventListener("click", () => {
    clearScope();
    loadMemories();
  });
  qs("copy-link").addEventListener("click", () => {
    syncUrlFromFilters();
    copyCurrentViewLink();
  });
  document.querySelectorAll("[data-scope-field]").forEach((button) => {
    button.addEventListener("click", () => {
      setExclusiveScope(button.dataset.scopeField, button.dataset.scopeValue || "");
      loadMemories();
    });
  });
  window.addEventListener("popstate", () => {
    applyFiltersFromUrl();
    loadMemories();
  });
  qs("detail-form").addEventListener("submit", saveSelected);
  qs("delete-memory").addEventListener("click", deleteSelected);

  await Promise.all([loadOverview(), loadMemories()]);
}

bootstrap().catch((error) => {
  document.body.innerHTML = `<pre class="empty-state">${escapeHtml(error.message)}</pre>`;
});
