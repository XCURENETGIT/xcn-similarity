/* XCN Similarity admin data layer - live API only */
(function () {
  const emptyHealth = {
    status: "unknown",
    version: "-",
    vector_backend: "-",
    vector_node: "-",
    embedder_backend: "-",
    embedding_model: "-",
    embedding_dim: 0,
    catalog_backend: "-",
    catalog_database: "-",
    object_store: "Milvus internal MinIO",
    gpu: "-",
  };

  const state = {
    health: emptyHealth,
    settings: { recent_match_min_score: 0.82, recent_match_log_limit: 50, recent_match_limit: 20, recent_match_days: 30, recent_match_cache_ttl_sec: 300, grey_zone_low_score: 0.62, grey_zone_high_score: 0.82, manual_review_enabled: true },
    stats: { documents: 0, document_chunks: 0, logs: 0, log_chunks: 0, documents_today: 0, logs_today: 0, document_index_bytes: 0, log_index_bytes: 0, total_index_bytes: 0, storage_paths: [], monitor_alerts: [], retention_policy: {}, recent_match_policy: {} },
    pipeline: { PENDING: 0, PROCESSING: 0, INDEXED: 0, FAILED: 0 },
    documents: [],
    documentPaging: { offset: 0, next_offset: null, limit: 30, query: "" },
    logs: [],
    docChunkText: {},
    docChunks: {},
    logChunkText: {},
    logChunks: {},
    matches: [],
    recentMatches: [],
    kafkaResults: [],
    kafkaResultPaging: { offset: 0, next_offset: null, limit: 50, delivery_status: "" },
    reviews: {},
    securityInsight: null,
    securityInsightHistory: [],
    logPaging: { offset: 0, next_offset: null, limit: 50, order: "desc" },
    lastError: "",
  };

  async function api(path, options) {
    const response = await fetch(path, options || {});
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

  function matchKey(match) {
    const m = match || {};
    return [
      m.document_id || "",
      m.log_id || m.target_id || "",
      m.doc_chunk_id || "",
      m.log_chunk_id || "",
      m.target_type || "",
    ].join("|");
  }

  function reviewScopeOf(score) {
    const value = Number(score || 0);
    const low = Number(state.settings.grey_zone_low_score ?? 0.62);
    const high = Number(state.settings.grey_zone_high_score ?? state.settings.recent_match_min_score ?? 0.82);
    if (value >= high) return "high_risk";
    if (value >= low) return "grey_zone";
    return "low_risk";
  }

  function reviewScopeLabel(scope) {
    if (scope === "high_risk") return "고위험";
    if (scope === "grey_zone") return "Grey Zone";
    if (scope === "low_risk") return "저위험";
    return "수동";
  }

  function reviewDecisionLabel(decision) {
    if (decision === "true_positive") return "정탐 확정";
    if (decision === "false_positive") return "오탐 확정";
    if (decision === "pending") return "보류";
    return "미분류";
  }

  function applyReviewState(item) {
    if (!item) return item;
    item.match_key = item.match_key || matchKey(item);
    item.review_scope = item.review_scope || reviewScopeOf(item.score);
    item.review_scope_label = reviewScopeLabel(item.review_scope);
    item.review = state.reviews[item.match_key] || null;
    item.review_status = item.review ? item.review.decision : "unreviewed";
    item.review_status_label = item.review ? reviewDecisionLabel(item.review.decision) : "미분류";
    return item;
  }

  function mergeReviewState(items) {
    return (items || []).map(applyReviewState);
  }

  async function loadReviews() {
    const result = await api("/similarity/reviews?limit=2000").catch(() => ({ data: [] }));
    state.reviews = {};
    for (const item of (result.data || [])) {
      if (item && item.match_key) state.reviews[item.match_key] = item;
    }
    mergeReviewState(state.matches);
    mergeReviewState(state.recentMatches);
    return state.reviews;
  }

  async function saveMatchReview(match, payload) {
    const key = matchKey(match);
    const scope = reviewScopeOf(match && match.score);
    const body = {
      match_key: key,
      decision: payload.decision,
      reason_code: payload.reason_code,
      comment: payload.comment || "",
      reviewer: payload.reviewer || "",
      review_scope: scope,
      match: {
        id: match.id,
        document_id: match.document_id,
        log_id: match.log_id,
        doc_chunk_id: match.doc_chunk_id,
        log_chunk_id: match.log_chunk_id,
        score: match.score,
        raw_score: match.raw_score,
        coverage_score: match.coverage_score,
        weighted_coverage_score: match.weighted_coverage_score,
        phrase_match_score: match.phrase_match_score,
        context_bonus: match.context_bonus,
        doc_title: match.doc_title,
        doc_security: match.doc_security,
        metadata: match.metadata || {},
      },
    };
    const result = await api("/similarity/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const review = result.data || result;
    state.reviews[key] = review;
    applyReviewState(match);
    mergeReviewState(state.matches);
    mergeReviewState(state.recentMatches);
    return review;
  }

  function metadataName(metadata, fallback) {
    const m = metadata || {};
    return m.title || m.subject || m.mail_subject || m.msg_subject || m.email_subject ||
      m.attach_name || m.attachment_name || m.name || m.file_name || m.fileName || m.attachName || fallback || "-";
  }

  function displayLogId(logId) {
    const raw = String(logId || "");
    return raw.replace(/:attach:\d+$/i, "");
  }

  function logTitleKind(metadata) {
    const m = metadata || {};
    if (m.source_type === "attachment" || m.attach_name || m.attachment_name || m.attachName) return "첨부파일";
    if (m.title || m.subject || m.mail_subject || m.msg_subject || m.email_subject) return "로깅제목";
    if (m.file_name || m.fileName) return "파일명";
    return "본문";
  }

  function normalizeDocument(doc) {
    const metadata = doc.metadata || {};
    return {
      ...doc,
      owner: doc.owner || "-",
      department: doc.department || "-",
      security_level: doc.security_level || metadata.security_level || "대외비",
      metadata: {
        ...metadata,
        ext: metadata.ext || metadata.file_ext || metadata.extension || "",
        size: metadata.size || metadata.file_size || "",
        file_name: metadata.file_name || metadata.fileName || metadata.original_name || "",
        file_size: metadata.file_size || metadata.size || "",
        file_checksum_sha256: metadata.file_checksum_sha256 || metadata.checksum_sha256 || metadata.sha256 || metadata.checksum || "",
        pages: metadata.pages || metadata.page_count || "",
      },
    };
  }

  function upsertDocumentInState(doc) {
    const normalized = normalizeDocument(doc);
    const idx = state.documents.findIndex((item) => item.document_id === normalized.document_id);
    if (idx >= 0) state.documents[idx] = normalized;
    else state.documents.unshift(normalized);
    return normalized;
  }

  function normalizeLog(log) {
    const metadata = log.metadata || {};
    return {
      ...log,
      status: log.status || "INDEXED",
      sample_text: log.sample_text || "",
      metadata: {
        ...metadata,
        channel: metadata.channel || metadata.svc || "-",
        source_type: metadata.source_type || "body",
        user_id: metadata.user_id || metadata.user || "-",
        ctime: metadata.ctime || log.created_at || "",
        attach_name: metadataName(metadata, metadata.source_type === "attachment" ? "첨부" : "본문"),
      },
    };
  }

  function updatePipeline() {
    const counts = { PENDING: 0, PROCESSING: 0, INDEXED: 0, FAILED: 0 };
    for (const doc of state.documents) counts[doc.status] = (counts[doc.status] || 0) + 1;
    counts.INDEXED = state.stats.log_chunks + state.stats.document_chunks;
    state.pipeline = counts;
  }

  async function loadInitial() {
    const settingsResult = await api("/similarity/settings").catch(() => ({}));
    state.settings = {
      ...state.settings,
      ...(settingsResult.data || settingsResult || {}),
    };
    const minScore = Number(state.settings.recent_match_min_score || 0.82);
    const logLimit = Math.max(Number(state.settings.recent_match_log_limit || 50), 1000);
    const limit = Math.max(Number(state.settings.recent_match_limit || 20), logLimit);
    const days = Math.max(1, Number(state.settings.recent_match_days || 30));
    const [health, stats, documentPage, logs, recentMatches, reviews] = await Promise.all([
      api("/health"),
      api("/similarity/stats"),
      api("/similarity/documents/search?limit=30&offset=0"),
      api("/similarity/logs?limit=50"),
      api(`/similarity/results/recent-matches?limit=${encodeURIComponent(limit)}&min_score=${encodeURIComponent(minScore)}&risk_level=high`).catch(() => ({ data: [] })),
      api("/similarity/reviews?limit=2000").catch(() => ({ data: [] })),
    ]);
    state.reviews = {};
    for (const item of (reviews.data || [])) {
      if (item && item.match_key) state.reviews[item.match_key] = item;
    }
    state.health = {
      ...emptyHealth,
      ...health,
      vector_node: health.vector_backend || "-",
      object_store: "Milvus internal MinIO",
      gpu: health.embedder_backend === "hf_transformer" ? "enabled if available" : "-",
    };
    state.stats = { documents_today: 0, logs_today: 0, ...(stats.data || stats) };
    for (const doc of (documentPage.data || [])) upsertDocumentInState(doc);
    state.documentPaging = {
      offset: 0,
      next_offset: documentPage.next_offset ?? null,
      limit: 30,
      query: "",
    };
    state.logs = (logs.data || []).map(normalizeLog);
    state.recentMatches = mergeReviewState(await groupDocumentHitsByLog((recentMatches.data || []).map(recentDocumentHitToResult)))
      .filter((item) => item.score >= minScore);
    updatePipeline();
    return state;
  }

  async function loadSecurityInsight(force = false) {
    const qs = force ? "?force=true" : "";
    const result = await api("/similarity/insights/security" + qs);
    state.securityInsight = result.data || result || null;
    return state.securityInsight;
  }

  async function loadSecurityInsightHistory(days = 7) {
    const result = await api(`/similarity/insights/security/history?days=${encodeURIComponent(days)}&limit=168`);
    state.securityInsightHistory = result.data || [];
    return state.securityInsightHistory;
  }

  async function refreshRecentMatches(logLimit) {
    const minScore = Number(state.settings.recent_match_min_score || 0.82);
    const effectiveLogLimit = Math.max(Number(logLimit || state.settings.recent_match_log_limit || 50), 1000);
    const limit = Math.max(Number(state.settings.recent_match_limit || 20), effectiveLogLimit);
    const days = Math.max(1, Number(state.settings.recent_match_days || 30));
    const result = await api(`/similarity/results/recent-matches?limit=${encodeURIComponent(limit)}&min_score=${encodeURIComponent(minScore)}&risk_level=high`).catch(() => ({ data: [] }));
    state.recentMatches = mergeReviewState(await groupDocumentHitsByLog((result.data || []).map(recentDocumentHitToResult)))
      .filter((item) => item.score >= minScore);
    return state.recentMatches;
  }

  async function loadLogs({ sourceType, svc, userId, limit = 50, offset, order = "desc" } = {}) {
    const qs = new URLSearchParams();
    qs.set("limit", String(limit));
    qs.set("order", order);
    if (offset !== undefined && offset !== null && String(offset) !== "") qs.set("offset", String(offset));
    if (sourceType) qs.set("source_type", sourceType);
    if (svc) qs.set("svc", svc);
    if (userId) qs.set("user_id", userId);
    const result = await api("/similarity/logs?" + qs.toString());
    state.logs = (result.data || []).map(normalizeLog);
    state.logPaging = {
      offset: Number(offset || 0),
      next_offset: result.next_offset || null,
      limit: Number(limit || 50),
      order,
    };
    await refreshRecentMatches(Number(offset || 0) + Number(limit || 50));
    return result;
  }

  async function loadHighRiskLogs({ sourceType, svc, userId, limit = 50, offset = 0 } = {}) {
    await refreshRecentMatches(Math.max(1000, Number(offset || 0) + Number(limit || 50)));
    const grouped = new Map();
    (state.recentMatches || [])
      .filter((match) => {
        const md = match.metadata || {};
        if (sourceType && md.source_type !== sourceType) return false;
        if (svc && !String(md.svc || "").toLowerCase().includes(String(svc).toLowerCase())) return false;
        if (userId && !String(md.user_id || "").toLowerCase().includes(String(userId).toLowerCase())) return false;
        return true;
      })
      .forEach((match) => {
        const key = displayLogId(match.log_id) || match.log_id;
        const current = grouped.get(key);
        if (!current) {
          grouped.set(key, {
            ...match,
            log_group_id: key,
            matched_documents: 1,
            matched_document_ids: [match.document_id].filter(Boolean),
          });
          return;
        }
        current.matched_documents = (current.matched_documents || 1) + 1;
        current.matched_document_ids = Array.from(new Set([...(current.matched_document_ids || []), match.document_id].filter(Boolean)));
        current.matched_chunks = Math.max(Number(current.matched_chunks || 1), Number(match.matched_chunks || 1));
        if (Number(match.score || 0) > Number(current.score || 0)) {
          grouped.set(key, {
            ...current,
            ...match,
            log_group_id: key,
            matched_documents: current.matched_documents,
            matched_document_ids: current.matched_document_ids,
          });
        }
      });
    const filtered = Array.from(grouped.values()).sort((a, b) => {
      const at = parseTime((a.metadata || {}).ctime);
      const bt = parseTime((b.metadata || {}).ctime);
      return bt - at || Number(b.score || 0) - Number(a.score || 0);
    });
    const start = Number(offset || 0);
    const end = start + Number(limit || 50);
    const page = filtered.slice(start, end).map((match) => normalizeLog({
      log_id: match.log_id,
      status: "INDEXED",
      chunk_count: match.matched_chunks || 1,
      sample_text: match.log_text || match.text_preview || "",
      metadata: { ...(match.metadata || {}), log_id: match.log_id, log_group_id: match.log_group_id, matched_documents: match.matched_documents || 1 },
    }));
    state.logs = page;
    state.logPaging = {
      offset: start,
      next_offset: end < filtered.length ? end : null,
      limit: Number(limit || 50),
      order: "desc",
      high_risk_only: true,
      total: filtered.length,
    };
    return { success: true, data: page, next_offset: end < filtered.length ? end : null, total: filtered.length };
  }

  async function fetchDocumentChunks(documentId) {
    if (!documentId) return [];
    if (state.docChunks[documentId]) return state.docChunks[documentId];
    const doc = state.documents.find((item) => item.document_id === documentId);
    if (doc && doc.metadata && doc.metadata.file_retained === false) {
      state.docChunks[documentId] = [];
      state.docChunkText[documentId] = [];
      return [];
    }
    const result = await api(`/similarity/documents/${encodeURIComponent(documentId)}/chunks?limit=100`);
    const chunks = result.data || [];
    state.docChunks[documentId] = chunks;
    state.docChunkText[documentId] = chunks.map((x) => x.text || "");
    return chunks;
  }

  function normalizeKafkaResult(row) {
    const similarity = row && row.data && row.data.similarity ? row.data.similarity : {};
    const summary = row.summary || similarity.summary || {};
    const delivery = row.delivery || {};
    const results = row.results || similarity.results || [];
    return {
      ...row,
      summary,
      results,
      detected: row.detected ?? Boolean(summary.detected),
      max_score: Number(row.max_score ?? summary.max_score ?? 0),
      match_count: Number(row.match_count ?? summary.match_count ?? 0),
      risk_level: row.risk_level || summary.risk_level || "none",
      delivery_status: row.delivery_status || "pending",
      delivery_topic: delivery.topic || "",
      delivery_partition: delivery.partition,
      delivery_offset: delivery.offset,
      delivery_updated_at: row.delivery_updated_at || row.updated_at || row.generated_at || "",
      generated_at: row.generated_at || similarity.generated_at || "",
      kafka_payload: {
        type: row.type || "similarity",
        msgid: row.msgid || "",
        data: row.data || {},
      },
    };
  }

  async function loadKafkaResults({ limit = 50, offset = 0, deliveryStatus = "" } = {}) {
    const qs = new URLSearchParams();
    qs.set("limit", String(limit));
    qs.set("offset", String(offset));
    if (deliveryStatus) qs.set("delivery_status", deliveryStatus);
    const result = await api("/similarity/results?" + qs.toString());
    const rows = (result.data || []).map(normalizeKafkaResult);
    state.kafkaResults = rows;
    state.kafkaResultPaging = {
      offset: Number(offset || 0),
      next_offset: result.next_offset ?? null,
      limit: Number(limit || 50),
      delivery_status: deliveryStatus || "",
    };
    return { data: rows, next_offset: result.next_offset ?? null };
  }

  async function fetchLogChunks(logId) {
    if (!logId) return [];
    const result = await api(`/similarity/logs/${encodeURIComponent(logId)}/chunks?limit=100`);
    const chunks = result.data || [];
    state.logChunks[logId] = chunks;
    state.logChunkText[logId] = chunks.map((x) => x.text || "");
    return chunks;
  }

  function hitToResult(hit, mode, context) {
    const metadata = hit.metadata || {};
    const targetId = hit.target_id || "";
    const isDoc = hit.target_type === "document";
    const doc = isDoc
      ? state.documents.find((x) => x.document_id === targetId)
      : (context && context.document) || {};
    const log = !isDoc
      ? state.logs.find((x) => x.log_id === targetId) || { log_id: targetId, metadata }
      : {};
    const docTitle = doc.title || metadata.title || metadata.file_name || targetId;
    const logTitle = metadataName(metadata, targetId);
    const docHidden = !!(doc && doc.metadata && doc.metadata.file_retained === false) || metadata.file_retained === false;
    const docText = isDoc
      ? (docHidden ? "" : (hit.text_preview || ""))
      : ((context && context.documentText) || (context && context.text) || "");
    const logText = isDoc ? "" : (hit.text_preview || "");
    const terms = extractSharedTerms(docText, logText);
    return {
      id: `${targetId}:${hit.chunk_id}`,
      score: Number(hit.score || 0),
      raw_score: Number(hit.score || 0),
      coverage_score: null,
      target_type: hit.target_type,
      target_id: targetId,
      document_id: isDoc ? targetId : (doc.document_id || ""),
      doc_title: isDoc ? docTitle : (docTitle || "선택 문서"),
      doc_security: doc.security_level || "대외비",
      doc_dept: doc.department || "-",
      doc_chunk_id: isDoc ? hit.chunk_id : "",
      log_id: isDoc ? "" : targetId,
      log_chunk_id: isDoc ? "" : hit.chunk_id,
      log_title: logTitle,
      doc_text: docHidden ? "" : docText,
      log_text: logText,
      text_preview: hit.text_preview || "",
      terms,
      breakdown: [["코사인 유사도", Number(hit.score || 0)]],
      metadata,
      mode,
      matched_chunks: 1,
      matched_chunk_ids: isDoc ? [hit.chunk_id].filter(Boolean) : [hit.chunk_id].filter(Boolean),
    };
  }

  function extractTerms(text) {
    return tokenizeTerms(text).slice(0, 8);
  }

  const TERM_STOPWORDS = new Set([
    "안녕하세요", "감사합니다", "드립니다", "부탁드립니다", "차장님", "부장님", "과장님", "대리님",
    "이승영입니다", "가능한", "그리고", "하지만", "위하여", "통하여", "있습니다", "없습니다",
  ]);

  function tokenizeTerms(text) {
    const raw = String(text || "").match(/[A-Za-z0-9가-힣_.:%/-]{3,}/g) || [];
    const terms = [];
    const seen = new Set();
    for (const item of raw) {
      const term = item.replace(/^[_.:%/-]+|[_.:%/-]+$/g, "");
      const key = term.toLowerCase();
      if (term.length < 3 || TERM_STOPWORDS.has(term) || /입니다$|드립니다$|합니다$/.test(term)) continue;
      if (!seen.has(key)) {
        seen.add(key);
        terms.push(term);
      }
    }
    return terms;
  }

  function extractSharedTerms(leftText, rightText) {
    const left = new Set(tokenizeTerms(leftText).map((x) => x.toLowerCase()));
    if (!left.size) return [];
    const shared = [];
    const seen = new Set();
    for (const term of tokenizeTerms(rightText)) {
      const key = term.toLowerCase();
      if (!seen.has(key) && left.has(key)) {
        seen.add(key);
        shared.push(term);
      }
      if (shared.length >= 8) break;
    }
    return shared;
  }

  function termCoverage(leftText, rightText) {
    const left = new Set(tokenizeTerms(leftText).map((x) => x.toLowerCase()));
    const right = new Set(tokenizeTerms(rightText).map((x) => x.toLowerCase()));
    if (!left.size || !right.size) return 0;
    let shared = 0;
    for (const key of right) {
      if (left.has(key)) shared += 1;
    }
    return shared / right.size;
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, Number(value || 0)));
  }

  function termWeight(term) {
    const value = String(term || "");
    if (!value) return 0;
    if (/^\d{4,}$/.test(value) || /[0-9][0-9,._:%/-]{2,}/.test(value)) return 2.0;
    if (/[A-Za-z]/.test(value) && /\d/.test(value)) return 1.8;
    if (value.length >= 8) return 1.5;
    if (value.length >= 5) return 1.25;
    return 1.0;
  }

  function weightedTermCoverage(leftText, rightText) {
    const left = new Set(tokenizeTerms(leftText).map((x) => x.toLowerCase()));
    const rightTerms = tokenizeTerms(rightText).map((x) => x.toLowerCase());
    if (!left.size || !rightTerms.length) return 0;
    const seen = new Set();
    let total = 0;
    let shared = 0;
    for (const key of rightTerms) {
      if (seen.has(key)) continue;
      seen.add(key);
      const weight = termWeight(key);
      total += weight;
      if (left.has(key)) shared += weight;
    }
    return total ? shared / total : 0;
  }

  function phraseMatchScore(leftText, rightText) {
    const leftTerms = tokenizeTerms(leftText).map((x) => x.toLowerCase());
    const rightTerms = tokenizeTerms(rightText).map((x) => x.toLowerCase());
    if (leftTerms.length < 2 || rightTerms.length < 2) return 0;
    const leftPhrases = new Set();
    for (let n = 2; n <= 4; n += 1) {
      for (let i = 0; i <= leftTerms.length - n; i += 1) {
        leftPhrases.add(leftTerms.slice(i, i + n).join(" "));
      }
    }
    let total = 0;
    let matched = 0;
    for (let n = 2; n <= 4; n += 1) {
      for (let i = 0; i <= rightTerms.length - n; i += 1) {
        total += 1;
        if (leftPhrases.has(rightTerms.slice(i, i + n).join(" "))) matched += n;
      }
    }
    return total ? Math.min(1, matched / Math.max(total, 1)) : 0;
  }

  function buildEvidenceBreakdown(raw, weightedCoverage, phraseScore) {
    return [
      ["최고 청크 벡터 유사도", raw],
      ["가중 공통어구 커버리지", weightedCoverage],
      ["구문 일치 보강", phraseScore],
    ];
  }

  function applyEvidenceScore(item) {
    const raw = Number(item.raw_score ?? item.score ?? 0);
    if (!String(item.doc_text || "").trim() || !String(item.log_text || "").trim()) {
      item.raw_score = raw;
      item.coverage_score = null;
      item.weighted_coverage_score = null;
      item.phrase_match_score = null;
      item.context_bonus = 0;
      item.score = clamp01(raw);
      item.breakdown = [["최고 청크 벡터 유사도", raw]];
      return item;
    }
    const coverage = termCoverage(item.doc_text, item.log_text);
    const weightedCoverage = weightedTermCoverage(item.doc_text, item.log_text);
    const phraseScore = phraseMatchScore(item.doc_text, item.log_text);
    const adjusted = raw * 0.85 + weightedCoverage * 0.10 + phraseScore * 0.05;
    item.raw_score = raw;
    item.coverage_score = coverage;
    item.weighted_coverage_score = weightedCoverage;
    item.phrase_match_score = phraseScore;
    item.context_bonus = 0;
    item.score = clamp01(adjusted);
    item.breakdown = buildEvidenceBreakdown(raw, weightedCoverage, phraseScore);
    return item;
  }

  function applyRecentMatchScore(item) {
    return applyEvidenceScore(item);
  }

  async function groupLogResults(results) {
    const grouped = new Map();
    for (const item of results) {
      if (!item.log_id) {
        grouped.set(item.id, item);
        continue;
      }
      const current = grouped.get(item.log_id);
      if (!current) {
        grouped.set(item.log_id, { ...item, id: item.log_id, matched_chunks: 1, matched_chunk_ids: [...(item.matched_chunk_ids || [])] });
        continue;
      }
      current.raw_score = Math.max(current.raw_score ?? current.score, item.raw_score ?? item.score);
      current.score = Math.max(current.score, item.score);
      current.log_chunk_id = current.log_chunk_id || item.log_chunk_id;
      current.text_preview = [current.text_preview, item.text_preview].filter(Boolean).join("\n\n");
      current.log_text = [current.log_text, item.log_text].filter(Boolean).join("\n\n");
      current.terms = Array.from(new Set([...(current.terms || []), ...(item.terms || [])])).slice(0, 8);
      current.matched_chunks = (current.matched_chunks || 1) + 1;
      current.matched_chunk_ids = Array.from(new Set([...(current.matched_chunk_ids || []), ...(item.matched_chunk_ids || [])]));
      current.breakdown = [["최고 청크 벡터 유사도", current.raw_score ?? current.score]];
    }

    const items = Array.from(grouped.values());
    await Promise.all(items.map(async (item) => {
      if (!item.log_id) return;
      const document = state.documents.find((doc) => doc.document_id === item.document_id) || {};
      const documentHidden = !!(document && document.metadata && document.metadata.file_retained === false);
      try {
        if (!String(item.doc_text || "").trim() && item.document_id && !documentHidden) {
          const docChunks = await fetchDocumentChunks(item.document_id);
          const docText = docChunks.map((chunk) => chunk.text || "").filter(Boolean).join("\n\n");
          if (docText) item.doc_text = docText;
        }
      } catch {
        // Keep stored previews when document chunks are unavailable.
      }
      try {
        const chunks = await fetchLogChunks(item.log_id);
        const fullText = chunks.map((chunk) => chunk.text || "").filter(Boolean).join("\n\n");
        if (fullText) {
          item.log_text = fullText;
        }
      } catch {
        // Keep matched previews when full log chunks are unavailable.
      }
      item.terms = extractSharedTerms(item.doc_text, item.log_text);
      applyEvidenceScore(item);
    }));
    return mergeReviewState(items.sort((a, b) => b.score - a.score));
  }

  function recentDocumentHitToResult(hit) {
    const metadata = hit.metadata || {};
    const logMeta = metadata._match_log_metadata || {};
    const docId = hit.target_id || metadata.document_id || "";
    const logId = metadata._match_log_id || "";
    const logChunkId = metadata._match_log_chunk_id || "";
    const doc = state.documents.find((x) => x.document_id === docId) || {};
    const docText = hit.text_preview || metadata._match_document_text_preview || "";
    const logText = metadata._match_log_text_preview || "";
    const storedBreakdown = Array.isArray(metadata.score_breakdown) ? metadata.score_breakdown : [];
    const compactBreakdown = [
      storedBreakdown.find((item) => item && item[0] === "최고 청크 벡터 유사도") || ["최고 청크 벡터 유사도", Number(metadata.raw_score ?? hit.score ?? 0)],
      storedBreakdown.find((item) => item && item[0] === "가중 공통어구 커버리지") || ["가중 공통어구 커버리지", Number(metadata.weighted_coverage_score ?? 0)],
      storedBreakdown.find((item) => item && item[0] === "구문 일치 보강") || ["구문 일치 보강", Number(metadata.phrase_match_score ?? 0)],
    ];
    const storedTerms = Array.isArray(metadata.matched_terms) ? metadata.matched_terms : [];
    const item = {
      id: `${logId}:${docId}`,
      score: Number(hit.score || 0),
      raw_score: Number(metadata.raw_score ?? hit.score ?? 0),
      coverage_score: metadata.weighted_coverage_score ?? metadata.coverage_score ?? null,
      weighted_coverage_score: metadata.weighted_coverage_score ?? null,
      phrase_match_score: metadata.phrase_match_score ?? null,
      context_bonus: 0,
      target_type: "log",
      target_id: logId,
      document_id: docId,
      doc_title: doc.title || metadata.title || docId,
      doc_security: doc.security_level || metadata.security_level || "대외비",
      doc_dept: doc.department || metadata.department || "-",
      doc_chunk_id: hit.chunk_id || "",
      log_id: logId,
      log_chunk_id: logChunkId,
      log_title: metadataName(logMeta, logId),
      doc_text: docText,
      log_text: logText,
      text_preview: logText,
      terms: storedTerms.length ? storedTerms : extractSharedTerms(docText, logText),
      breakdown: compactBreakdown,
      metadata: logMeta,
      mode: "recent",
      matched_chunks: 1,
      matched_chunk_ids: [logChunkId].filter(Boolean),
    };
    if (storedBreakdown.length || storedTerms.length) return item;
    return applyRecentMatchScore(item);
  }

  async function groupDocumentHitsByLog(results) {
    const grouped = new Map();
    for (const item of results) {
      const key = `${item.log_id}:${item.document_id}`;
      const current = grouped.get(key);
      if (!current) {
        grouped.set(key, item);
        continue;
      }
      if ((item.raw_score || item.score) > (current.raw_score || current.score)) {
        current.raw_score = item.raw_score;
        current.doc_chunk_id = item.doc_chunk_id;
        current.doc_text = item.doc_text;
      }
      current.log_text = [current.log_text, item.log_text].filter(Boolean).join("\n\n");
      current.terms = extractSharedTerms(current.doc_text, current.log_text);
      current.matched_chunks = (current.matched_chunks || 1) + 1;
      current.matched_chunk_ids = Array.from(new Set([...(current.matched_chunk_ids || []), ...(item.matched_chunk_ids || [])]));
      applyRecentMatchScore(current);
    }
    return Array.from(grouped.values()).sort((a, b) => b.score - a.score);
  }

  async function searchDocumentsByText(text, topK, minScore) {
    const result = await api("/similarity/search/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, top_k: topK, min_score: minScore, metadata_filter: {} }),
    });
    state.matches = mergeReviewState((result.data || []).map((hit) => hitToResult(hit, "docs", { text })));
    return state.matches;
  }

  async function searchLogsByText(text, topK, minScore, filter) {
    const metadata_filter = {};
    if (filter && filter.sourceType) metadata_filter.source_type = filter.sourceType;
    if (filter && filter.svc) metadata_filter.svc = filter.svc;
    if (filter && filter.userId) metadata_filter.user_id = filter.userId;
    const result = await api("/similarity/search/logs/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, top_k: topK, min_score: minScore, metadata_filter }),
    });
    state.matches = mergeReviewState(await groupLogResults((result.data || []).map((hit) => hitToResult(hit, "logs", { text }))));
    return state.matches;
  }

  async function searchLogsForDocument(document, topK = 20, minScore = 0.0, filter = {}) {
    const documentHidden = !!(document && document.metadata && document.metadata.file_retained === false);
    const chunks = documentHidden ? [] : await fetchDocumentChunks(document.document_id);
    const documentText = documentHidden ? "" : chunks.map((chunk) => chunk.text || "").filter(Boolean).join("\n\n").slice(0, 8000);
    const metadata_filter = {};
    if (filter && filter.sourceType) metadata_filter.source_type = filter.sourceType;
    if (filter && filter.svc) metadata_filter.svc = filter.svc;
    if (filter && filter.userId) metadata_filter.user_id = filter.userId;
    const result = await api("/similarity/search/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: document.document_id, top_k: Number(topK), min_score: Number(minScore), metadata_filter }),
    });
    state.matches = mergeReviewState(await groupLogResults((result.data || []).map((hit) => hitToResult(hit, "logs", { document, documentText }))));
    return state.matches;
  }

  async function searchDocumentCatalog(params) {
    const p = params || {};
    const limit = Number(p.limit || 30);
    const offset = Number(p.offset || 0);
    const query = new URLSearchParams();
    query.set("limit", String(limit));
    query.set("offset", String(offset));
    if (p.query) query.set("query", p.query);
    if (p.security_level) query.set("security_level", p.security_level);
    if (p.department) query.set("department", p.department);
    if (p.owner) query.set("owner", p.owner);
    const result = await api(`/similarity/documents/search?${query.toString()}`);
    const docs = (result.data || []).map(normalizeDocument);
    for (const doc of docs) upsertDocumentInState(doc);
    state.documentPaging = {
      offset,
      next_offset: result.next_offset ?? null,
      limit,
      query: p.query || "",
    };
    return { data: docs, next_offset: result.next_offset ?? null };
  }

  async function searchByFile(file, mode, topK, minScore, filter) {
    const form = new FormData();
    form.append("file", file);
    form.append("top_k", String(topK));
    form.append("min_score", String(minScore));
    let path = "/similarity/search/documents/upload";
    if (mode === "logs") {
      path = "/similarity/search/logs/upload";
      if (filter && filter.sourceType) form.append("source_type", filter.sourceType);
      if (filter && filter.svc) form.append("svc", filter.svc);
      if (filter && filter.userId) form.append("user_id", filter.userId);
    }
    const result = await api(path, { method: "POST", body: form });
    const matches = (result.data || []).map((hit) => hitToResult(hit, mode, { text: file.name }));
    state.matches = mergeReviewState(mode === "logs" ? await groupLogResults(matches) : matches);
    return state.matches;
  }

  async function uploadDocument(file, fields) {
    const meta = fields || {};
    const files = Array.isArray(file) ? file : [file];
    const first = files[0] || {};
    const form = new FormData();
    for (const item of files) form.append("file", item);
    form.append("title", (meta.title || first.name || "").trim());
    form.append("security_level", (meta.security_level || "").trim());
    form.append("retain_file", meta.retain_file === false ? "false" : "true");
    form.append("metadata_json", JSON.stringify({}));
    const result = await api("/similarity/documents/upload", { method: "POST", body: form });
    const docs = Array.isArray(result.data) ? result.data : [result.data].filter(Boolean);
    docs.forEach(upsertDocumentInState);
    return docs[0] || null;
  }

  async function deleteDocument(documentId) {
    await api(`/similarity/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
    state.documents = state.documents.filter((item) => item.document_id !== documentId);
    delete state.docChunks[documentId];
    delete state.docChunkText[documentId];
  }

  async function updateDocument(documentId, fields) {
    const meta = fields || {};
    const result = await api(`/similarity/documents/${encodeURIComponent(documentId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: (meta.title || "").trim(),
        owner: "",
        department: "",
        security_level: (meta.security_level || "").trim(),
        metadata: {}
      })
    });
    upsertDocumentInState(result.data);
    return result.data;
  }

  const SCORE_RISK_LEVELS = [
    { key: "hi", tone: "high", label: "높음", range: ">= 0.82", desc: "등록 문서와 매우 유사하여 즉시 검토가 필요합니다." },
    { key: "md", tone: "med", label: "주의", range: "0.62-0.82", desc: "0.62 이상 0.82 미만입니다. 유사 구간이 있어 추가 확인을 권장합니다." },
    { key: "lo", tone: "low", label: "낮음", range: "< 0.62", desc: "유사도가 낮아 참고 수준으로 봅니다." }
  ];

  function riskOf(score) {
    const value = Number(score || 0);
    if (value >= 0.82) return SCORE_RISK_LEVELS[0];
    if (value >= 0.62) return SCORE_RISK_LEVELS[1];
    return SCORE_RISK_LEVELS[2];
  }
  function statusClass(s) { return "badge-" + String(s || "indexed").toLowerCase(); }
  function secClass(level) {
    if (level === "기밀" || level === "대외비") return "sec-1";
    if (level === "일반") return "sec-2";
    return "sec-3";
  }
  function fmtTime(iso) {
    if (!iso) return "-";
    const d = parseDate(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const parts = Object.fromEntries(new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(d).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }
  function parseDate(value, defaultZone = "local") {
    if (value instanceof Date) return value;
    if (!value) return new Date(NaN);
    const text = String(value).trim();
    const hasExplicitZone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text);
    const normalized = !hasExplicitZone && defaultZone === "utc" && /^\d{4}-\d{2}-\d{2}T/.test(text) ? `${text}Z` : text;
    return new Date(normalized);
  }
  function parseTime(value, defaultZone = "local") {
    const time = parseDate(value, defaultZone).getTime();
    return Number.isNaN(time) ? 0 : time;
  }
  function num(n) { return Number(n || 0).toLocaleString("ko-KR"); }
  function highRiskMatchForLog(logId) {
    const id = String(logId || "");
    if (!id) return null;
    const groupId = displayLogId(id);
    return (state.recentMatches || []).find((item) => item.log_id === id || displayLogId(item.log_id) === groupId) || null;
  }

  function scoreBreakdownLabel(label) {
    const labels = {
      "근거 보정 점수": "최종 점수",
      "대표 유사도 점수": "대표 점수",
      "최고 청크 벡터 유사도": "AI 유사도",
      "가중 공통어구 커버리지": "핵심어 일치",
      "구문 일치 보강": "문장흐름",
      "운영 판정 반영 비중 - 벡터": "반영 비중: 벡터",
      "운영 판정 반영 비중 - 근거 보정": "반영 비중: 근거",
      "코사인 유사도": "AI 유사도",
      "유사도": "유사도",
    };
    return labels[label] || label;
  }

  function scoreBreakdownDescription(label, value) {
    const score = Number(value || 0);
    const pct = `${(score * 100).toFixed(1)}%`;
    const descriptions = {
      "근거 보정 점수": `AI 유사도에 핵심어·문장 흐름·전송 위험을 반영한 최종값 (${pct})`,
      "대표 유사도 점수": `운영 판정과 Kafka 결과에 사용하는 대표 점수입니다. 현재 벡터 유사도 100%를 반영합니다 (${pct}).`,
      "최고 청크 벡터 유사도": `문서와 로그를 AI 임베딩으로 비교한 원점수입니다. 원문이 있으면 운영 점수에 85% 반영합니다 (${pct}).`,
      "가중 공통어구 커버리지": `숫자·코드·식별자를 더 중요하게 본 핵심어 일치율입니다. 원문이 있으면 운영 점수에 10% 반영합니다 (${pct}).`,
      "구문 일치 보강": `핵심어가 같은 순서로 이어지는 정도입니다. 원문이 있으면 운영 점수에 5% 반영합니다 (${pct}).`,
      "운영 판정 반영 비중 - 벡터": `현재 운영 판정 점수에 반영되는 벡터 유사도 비중입니다 (${pct}).`,
      "운영 판정 반영 비중 - 근거 보정": `현재 공통어구·구문·상황 보정은 판정 점수에 직접 반영하지 않고 설명용으로만 사용합니다 (${pct}).`,
      "코사인 유사도": `문서와 질의를 AI 임베딩으로 비교한 유사도 (${pct})`,
      "유사도": `기본 유사도 점수 (${pct})`,
    };
    return descriptions[label] || `정규화 점수 (${pct})`;
  }

  window.XCN = Object.assign(state, {
    api, loadInitial, loadSecurityInsight, loadSecurityInsightHistory, loadLogs, loadHighRiskLogs, loadKafkaResults, fetchDocumentChunks, fetchLogChunks,
    searchDocumentsByText, searchLogsByText, searchLogsForDocument, searchDocumentCatalog, searchByFile,
    uploadDocument, updateDocument, deleteDocument,
    riskOf, scoreRiskLevels: SCORE_RISK_LEVELS, statusClass, secClass, fmtTime, parseTime, num, metadataName, displayLogId, logTitleKind, highRiskMatchForLog,
    matchKey, reviewScopeOf, reviewScopeLabel, reviewDecisionLabel, loadReviews, saveMatchReview,
    scoreBreakdownLabel, scoreBreakdownDescription,
  });
})();


