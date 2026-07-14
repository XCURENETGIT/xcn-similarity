const state = {
  view: "dashboard",
  health: null,
  stats: null,
  documents: [],
  logs: [],
  logOffset: 0,
  logLimit: 100,
  logNextOffset: null,
  logSourceType: "",
  logSvc: "",
  logUserId: "",
  selectedDocument: null,
  selectedLog: null,
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.hidden = true; }, 3600);
}

async function api(path, options = {}) {
  const headers = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : text || response.statusText;
    throw new Error(detail);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function compactMeta(metadata) {
  const meta = metadata || {};
  const priority = [
    "source_type",
    "attach_name",
    "attachment_name",
    "file_name",
    "fileName",
    "svc",
    "user_id",
    "ctime",
    "msg_id",
  ];
  const seen = new Set();
  const pairs = [];
  for (const key of priority) {
    const value = meta[key];
    if (value !== null && value !== undefined && value !== "") {
      pairs.push([key, value]);
      seen.add(key);
    }
  }
  for (const [key, value] of Object.entries(meta)) {
    if (!seen.has(key) && value !== null && value !== undefined && value !== "") {
      pairs.push([key, value]);
    }
  }
  pairs.splice(8);
  return pairs.map(([key, value]) => `${key}=${value}`).join(" · ") || "-";
}

function displayName(metadata, fallback) {
  const meta = metadata || {};
  return meta.attach_name || meta.attachment_name || meta.file_name || meta.fileName || meta.title || fallback || "-";
}

function score(value) {
  const n = Number(value || 0);
  return n.toFixed(4);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((el) => { el.hidden = true; });
  $(`${view}View`).hidden = false;
  $("pageTitle").textContent = {
    dashboard: "현황",
    documents: "문서 관리",
    search: "유사도 검색",
    logs: "로그 확인",
  }[view];
}

async function loadHealth() {
  state.health = await api("/health");
  $("healthText").textContent = `${state.health.status} / ${state.health.vector_backend}`;
  $("healthDetail").innerHTML = [
    ["상태", state.health.status],
    ["버전", state.health.version],
    ["벡터 백엔드", state.health.vector_backend],
    ["임베딩 백엔드", state.health.embedder_backend],
    ["임베딩 모델", state.health.embedding_model],
    ["임베딩 차원", state.health.embedding_dim],
    ["카탈로그 백엔드", state.health.catalog_backend],
    ["카탈로그 DB", state.health.catalog_database],
  ].map(([k, v]) => `<div class="kv"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("");
}

async function loadStats() {
  const response = await api("/similarity/stats");
  state.stats = response.data;
  $("metricDocuments").textContent = state.stats.documents.toLocaleString();
  $("metricDocumentChunks").textContent = state.stats.document_chunks.toLocaleString();
  $("metricLogs").textContent = state.stats.logs.toLocaleString();
  $("metricLogChunks").textContent = state.stats.log_chunks.toLocaleString();
}

async function loadDocuments() {
  const response = await api("/similarity/documents");
  state.documents = response.data || [];
  renderDocuments();
}

function renderDocuments() {
  const filter = $("documentFilter").value.trim().toLowerCase();
  const items = state.documents.filter((doc) => {
    const haystack = `${doc.document_id} ${doc.title} ${doc.department || ""} ${doc.owner || ""}`.toLowerCase();
    return !filter || haystack.includes(filter);
  });
  $("documentList").innerHTML = items.map((doc) => `
    <button class="item ${state.selectedDocument?.document_id === doc.document_id ? "active" : ""}" data-doc-id="${escapeHtml(doc.document_id)}">
      <strong>${escapeHtml(doc.title)}</strong>
      <small>${escapeHtml(doc.document_id)} · chunks=${doc.chunk_count} · ${escapeHtml(doc.department || "-")}</small>
    </button>
  `).join("") || `<div class="empty-state"><span>등록 문서가 없습니다.</span></div>`;
}

async function selectDocument(documentId) {
  state.selectedDocument = state.documents.find((doc) => doc.document_id === documentId);
  renderDocuments();
  $("documentEmpty").hidden = true;
  $("documentDetail").hidden = false;
  $("documentStatus").textContent = `${state.selectedDocument.status} · chunks=${state.selectedDocument.chunk_count}`;
  $("documentTitle").textContent = state.selectedDocument.title;
  $("documentMeta").textContent = compactMeta({
    id: state.selectedDocument.document_id,
    owner: state.selectedDocument.owner,
    department: state.selectedDocument.department,
    security_level: state.selectedDocument.security_level,
  });
  const chunks = await api(`/similarity/documents/${encodeURIComponent(documentId)}/chunks?limit=80`);
  $("documentChunks").innerHTML = renderChunks(chunks.data);
}

function renderChunks(chunks) {
  return (chunks || []).map((chunk) => `
    <article class="chunk">
      <strong>${escapeHtml(chunk.chunk_id)}</strong>
      <small>${escapeHtml(compactMeta(chunk.metadata))}</small>
      <p>${escapeHtml(chunk.text)}</p>
    </article>
  `).join("") || `<div class="empty-state"><span>chunk가 없습니다.</span></div>`;
}

async function deleteSelectedDocument() {
  if (!state.selectedDocument) return;
  if (!confirm(`문서를 삭제할까요?\n${state.selectedDocument.title}`)) return;
  await api(`/similarity/documents/${encodeURIComponent(state.selectedDocument.document_id)}`, { method: "DELETE" });
  state.selectedDocument = null;
  $("documentDetail").hidden = true;
  $("documentEmpty").hidden = false;
  await refreshAll();
  toast("문서를 삭제했습니다.");
}

async function submitDocument(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.file.files[0];
  if (!file) {
    toast("등록할 문서 파일을 선택하세요.");
    return;
  }
  try {
    JSON.parse(form.metadata_json.value || "{}");
  } catch {
    toast("Metadata JSON 형식이 올바르지 않습니다.");
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", form.title.value.trim() || file.name);
  formData.append("owner", form.owner.value.trim());
  formData.append("department", form.department.value.trim());
  formData.append("security_level", form.security_level.value.trim());
  formData.append("metadata_json", form.metadata_json.value || "{}");
  await api("/similarity/documents/upload", {
    method: "POST",
    body: formData,
  });
  $("documentDialog").close();
  form.reset();
  form.metadata_json.value = "{}";
  await refreshAll();
  toast("문서를 등록했습니다.");
}

function fillDocumentTitleFromFile() {
  const form = $("documentForm");
  const file = form.file.files[0];
  if (!file || form.title.value.trim()) return;
  const dot = file.name.lastIndexOf(".");
  form.title.value = dot > 0 ? file.name.slice(0, dot) : file.name;
}

function renderResults(hits) {
  return (hits || []).map((hit) => `
    <article class="result">
      <strong>${escapeHtml(displayName(hit.metadata, hit.target_id))} <span class="muted">score=${score(hit.score)}</span></strong>
      <small>${escapeHtml(hit.target_id)}</small>
      <small>${escapeHtml(hit.chunk_id)} · ${escapeHtml(compactMeta(hit.metadata))}</small>
      <p>${escapeHtml(hit.text_preview || hit.text || "")}</p>
    </article>
  `).join("") || `<div class="empty-state"><span>검색 결과가 없습니다.</span></div>`;
}

async function searchDocuments() {
  const text = $("queryText").value.trim();
  if (!text) {
    toast("검색할 본문을 입력하세요.");
    return;
  }
  const response = await api("/similarity/search/documents", {
    method: "POST",
    body: JSON.stringify({
      text,
      top_k: Number($("queryTopK").value || 10),
      min_score: Number($("queryMinScore").value || 0),
      metadata_filter: {},
    }),
  });
  $("documentSearchResults").innerHTML = renderResults(response.data);
}

function selectedQueryFile() {
  const file = $("queryFile").files[0];
  if (!file) {
    toast("검색할 파일을 선택하세요.");
    return null;
  }
  return file;
}

async function searchDocumentsByFile() {
  const file = selectedQueryFile();
  if (!file) return;
  $("documentSearchResults").innerHTML = `<div class="empty-state"><span>파일 텍스트 추출 및 검색 중입니다.</span></div>`;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("top_k", String(Number($("queryTopK").value || 10)));
  formData.append("min_score", String(Number($("queryMinScore").value || 0)));
  const response = await api("/similarity/search/documents/upload", {
    method: "POST",
    body: formData,
  });
  $("documentSearchResults").innerHTML = renderResults(response.data);
}

async function searchLogsByText() {
  const text = $("queryText").value.trim();
  if (!text) {
    toast("검색할 본문을 입력하세요.");
    return;
  }
  const metadataFilter = {};
  const sourceType = $("queryLogSourceType").value;
  const svc = $("queryLogSvc").value.trim();
  const userId = $("queryLogUserId").value.trim();
  if (sourceType) metadataFilter.source_type = sourceType;
  if (svc) metadataFilter.svc = svc;
  if (userId) metadataFilter.user_id = userId;
  const response = await api("/similarity/search/logs/text", {
    method: "POST",
    body: JSON.stringify({
      text,
      top_k: Number($("queryTopK").value || 20),
      min_score: Number($("queryMinScore").value || 0),
      metadata_filter: metadataFilter,
    }),
  });
  $("documentSearchResults").innerHTML = renderResults(response.data);
}

async function searchLogsByFile() {
  const file = selectedQueryFile();
  if (!file) return;
  $("documentSearchResults").innerHTML = `<div class="empty-state"><span>파일 텍스트 추출 및 검색 중입니다.</span></div>`;
  const sourceType = $("queryLogSourceType").value;
  const svc = $("queryLogSvc").value.trim();
  const userId = $("queryLogUserId").value.trim();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("top_k", String(Number($("queryTopK").value || 20)));
  formData.append("min_score", String(Number($("queryMinScore").value || 0)));
  if (sourceType) formData.append("source_type", sourceType);
  if (svc) formData.append("svc", svc);
  if (userId) formData.append("user_id", userId);
  const response = await api("/similarity/search/logs/upload", {
    method: "POST",
    body: formData,
  });
  $("documentSearchResults").innerHTML = renderResults(response.data);
}

async function searchLogsByDocument() {
  if (!state.selectedDocument) return;
  const sourceType = $("docSearchSourceType").value;
  $("similarLogsTitle").textContent = state.selectedDocument.title;
  $("similarLogsMeta").textContent = [
    `document_id=${state.selectedDocument.document_id}`,
    `top_k=${Number($("docSearchTopK").value || 20)}`,
    `min_score=${Number($("docSearchMinScore").value || 0)}`,
    `target=${sourceType || "all"}`,
  ].join(" · ");
  $("similarLogsResults").innerHTML = `<div class="empty-state"><span>검색 중입니다.</span></div>`;
  $("similarLogsDialog").showModal();
  const response = await api("/similarity/search/logs", {
    method: "POST",
    body: JSON.stringify({
      document_id: state.selectedDocument.document_id,
      top_k: Number($("docSearchTopK").value || 20),
      min_score: Number($("docSearchMinScore").value || 0),
      metadata_filter: sourceType ? { source_type: sourceType } : {},
    }),
  });
  $("similarLogsResults").innerHTML = renderResults(response.data);
}

async function loadLogs() {
  const params = new URLSearchParams({
    limit: String(state.logLimit),
    offset: String(state.logOffset),
  });
  if (state.logSourceType) params.set("source_type", state.logSourceType);
  if (state.logSvc) params.set("svc", state.logSvc);
  if (state.logUserId) params.set("user_id", state.logUserId);
  const response = await api(`/similarity/logs?${params.toString()}`);
  state.logs = response.data || [];
  state.logNextOffset = response.next_offset;
  renderLogs();
}

function renderLogs() {
  const page = Math.floor(state.logOffset / state.logLimit) + 1;
  $("logsPageText").textContent = `${page.toLocaleString()} 페이지 · ${state.logs.length.toLocaleString()}건`;
  $("prevLogsButton").disabled = state.logOffset <= 0;
  $("nextLogsButton").disabled = !state.logNextOffset;
  $("logList").innerHTML = state.logs.map((log) => `
    <button class="item ${state.selectedLog?.log_id === log.log_id ? "active" : ""}" data-log-id="${escapeHtml(log.log_id)}">
      <strong>${escapeHtml(displayName(log.metadata, log.log_id))}</strong>
      <small>${escapeHtml(log.log_id)} · chunks=${log.chunk_count} · ${escapeHtml(compactMeta(log.metadata))}</small>
      <p>${escapeHtml(log.sample_text)}</p>
    </button>
  `).join("") || `<div class="empty-state"><span>적재 로그가 없습니다.</span></div>`;
}

async function selectLog(logId) {
  state.selectedLog = state.logs.find((log) => log.log_id === logId);
  renderLogs();
  $("logEmpty").hidden = true;
  $("logDetail").hidden = false;
  $("logTitle").textContent = displayName(state.selectedLog.metadata, state.selectedLog.log_id);
  $("logMeta").textContent = compactMeta(state.selectedLog.metadata);
  const chunks = await api(`/similarity/logs/${encodeURIComponent(logId)}/chunks?limit=80`);
  $("logChunks").innerHTML = renderChunks(chunks.data);
}

async function refreshAll() {
  try {
    await Promise.all([loadHealth(), loadStats(), loadDocuments(), loadLogs()]);
  } catch (error) {
    toast(`조회 실패: ${error.message}`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  $("refreshButton").addEventListener("click", refreshAll);
  $("documentFilter").addEventListener("input", renderDocuments);
  $("documentList").addEventListener("click", (event) => {
    const item = event.target.closest("[data-doc-id]");
    if (item) selectDocument(item.dataset.docId).catch((error) => toast(error.message));
  });
  $("logList").addEventListener("click", (event) => {
    const item = event.target.closest("[data-log-id]");
    if (item) selectLog(item.dataset.logId).catch((error) => toast(error.message));
  });
  $("newDocumentButton").addEventListener("click", () => $("documentDialog").showModal());
  $("cancelDocumentButton").addEventListener("click", () => $("documentDialog").close());
  $("closeSimilarLogsButton").addEventListener("click", () => $("similarLogsDialog").close());
  $("documentForm").file.addEventListener("change", fillDocumentTitleFromFile);
  $("documentForm").addEventListener("submit", submitDocument);
  $("deleteDocumentButton").addEventListener("click", deleteSelectedDocument);
  $("searchDocumentsButton").addEventListener("click", () => searchDocuments().catch((error) => toast(error.message)));
  $("searchDocumentsByFileButton").addEventListener("click", () => searchDocumentsByFile().catch((error) => toast(error.message)));
  $("searchLogsByTextButton").addEventListener("click", () => searchLogsByText().catch((error) => toast(error.message)));
  $("searchLogsByFileButton").addEventListener("click", () => searchLogsByFile().catch((error) => toast(error.message)));
  $("searchLogsButton").addEventListener("click", () => searchLogsByDocument().catch((error) => toast(error.message)));
  $("applyLogFiltersButton").addEventListener("click", () => {
    state.logSourceType = $("logSourceTypeFilter").value;
    state.logSvc = $("logSvcFilter").value.trim();
    state.logUserId = $("logUserIdFilter").value.trim();
    state.logOffset = 0;
    state.selectedLog = null;
    $("logDetail").hidden = true;
    $("logEmpty").hidden = false;
    loadLogs().catch((error) => toast(error.message));
  });
  $("clearLogFiltersButton").addEventListener("click", () => {
    $("logSourceTypeFilter").value = "";
    $("logSvcFilter").value = "";
    $("logUserIdFilter").value = "";
    state.logSourceType = "";
    state.logSvc = "";
    state.logUserId = "";
    state.logOffset = 0;
    state.selectedLog = null;
    $("logDetail").hidden = true;
    $("logEmpty").hidden = false;
    loadLogs().catch((error) => toast(error.message));
  });
  ["logSvcFilter", "logUserIdFilter"].forEach((id) => {
    $(id).addEventListener("keydown", (event) => {
      if (event.key === "Enter") $("applyLogFiltersButton").click();
    });
  });
  $("prevLogsButton").addEventListener("click", () => {
    state.logOffset = Math.max(0, state.logOffset - state.logLimit);
    loadLogs().catch((error) => toast(error.message));
  });
  $("nextLogsButton").addEventListener("click", () => {
    if (!state.logNextOffset) return;
    state.logOffset = Number(state.logNextOffset);
    loadLogs().catch((error) => toast(error.message));
  });
  setView("dashboard");
  refreshAll();
});
