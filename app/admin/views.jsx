/* views.jsx — Dashboard, Documents, Search, Logs */

/* ============================== DASHBOARD ============================== */

function Metric({ icon, label, value, sub, trend }) {
  return h("article", { className: "metric" },
    h("div", { className: "m-top" }, h("div", { className: "m-ico" }, h(Icon, { name: icon, size: 16 })), label),
    h("div", { className: "m-val mono" }, value),
    h("div", { className: "m-sub" }, trend && h("span", { className: "trend up" }, "▲ " + trend), sub));
}
function MetricSet({ icon, title, primaryLabel, primaryValue, secondaryLabel, secondaryValue, todayLabel, todayValue, extraLabel, extraValue }) {
  return h("article", { className: "metric metric-set" },
    h("div", { className: "m-top" }, h("div", { className: "m-ico" }, h(Icon, { name: icon, size: 16 })), title),
    h("div", { className: "metric-set-body" },
      h("div", { className: "metric-main" },
        h("div", { className: "m-val mono" }, primaryValue),
        h("div", { className: "m-sub" }, primaryLabel)),
      h("div", { className: "metric-side" },
        h("div", { className: "side-chip" }, h("span", null, secondaryLabel), h("b", { className: "mono" }, secondaryValue)),
        h("div", { className: "side-chip today" }, h("span", null, todayLabel), h("b", { className: "mono" }, todayValue)),
        h("div", { className: "side-chip" }, h("span", null, extraLabel), h("b", { className: "mono" }, extraValue)))));
}
function dashboardRiskPageSize() {
  const width = window.innerWidth || 1200;
  if (width < 720) return 6;
  if (width < 1100) return 10;
  return 15;
}

function Dashboard({ onMatch, toast, dataVersion }) {
  const { stats, num } = XCN;
  const [securityInsight, setSecurityInsight] = React.useState(XCN.securityInsight || null);
  const [insightBusy, setInsightBusy] = React.useState(false);
  const feed = XCN.recentMatches || [];
  const [matchPage, setMatchPage] = React.useState(0);
  const [pageSize, setPageSize] = React.useState(() => dashboardRiskPageSize());
  const docs = XCN.documents || [];
  const logs = XCN.logs || [];
  const recentCfg = XCN.settings || {};
  const sortedFeed = [...feed].sort((a, b) => {
    const at = XCN.parseTime((a.metadata || {}).ctime);
    const bt = XCN.parseTime((b.metadata || {}).ctime);
    return bt - at || Number(b.score || 0) - Number(a.score || 0);
  });
  const totalPages = Math.max(1, Math.ceil(sortedFeed.length / pageSize));
  const safePage = Math.min(matchPage, totalPages - 1);
  const pageFeed = sortedFeed.slice(safePage * pageSize, safePage * pageSize + pageSize);
  React.useEffect(() => {
    const onResize = () => setPageSize(dashboardRiskPageSize());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  React.useEffect(() => {
    if (matchPage > totalPages - 1) setMatchPage(Math.max(0, totalPages - 1));
  }, [matchPage, totalPages]);
  React.useEffect(() => {
    let cancelled = false;
    setSecurityInsight(XCN.securityInsight || null);
    if (!XCN.securityInsight) {
      setInsightBusy(true);
      XCN.loadSecurityInsight(false)
        .then((next) => { if (!cancelled) setSecurityInsight(next); })
        .catch((error) => { if (!cancelled) toast && toast("AI 보안 인사이트 생성 실패 · " + error.message); })
        .finally(() => { if (!cancelled) setInsightBusy(false); });
    }
    return () => { cancelled = true; };
  }, [dataVersion]);
  const refreshInsight = async () => {
    setInsightBusy(true);
    try {
      const next = await XCN.loadSecurityInsight(true);
      setSecurityInsight(next);
      toast && toast("AI 보안 인사이트를 다시 생성했습니다.");
    } catch (error) {
      toast && toast("AI 보안 인사이트 생성 실패 · " + error.message);
    } finally {
      setInsightBusy(false);
    }
  };
  const attachmentMatches = feed.filter((m) => (m.metadata || {}).source_type === "attachment").length;
  const affectedUsers = new Set(feed.map((m) => (m.metadata || {}).user_id).filter(Boolean)).size;
  const highMatches = feed.length;
  const uniqueRiskLogs = new Set(feed.map((m) => XCN.displayLogId(m.log_id)).filter(Boolean)).size;
  const bytes = (value) => {
    const n = Number(value || 0);
    if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${n} B`;
  };
  const storagePaths = Array.isArray(stats.storage_paths) ? stats.storage_paths : [];
  const alerts = Array.isArray(stats.monitor_alerts) ? stats.monitor_alerts : [];
  const retention = stats.retention_policy || {};
  const recentPolicy = stats.recent_match_policy || {};
  const serviceTop = topCounts(feed.map((m) => (m.metadata || {}).svc || (m.metadata || {}).channel || "-"), 5);
  const securityTop = topCounts(docs.map((d) => d.security_level || (d.metadata || {}).security_level || "미분류"), 4);
  const recentLogTop = topCounts(logs.map((l) => (l.metadata || {}).svc || "-"), 5);
  return h("div", { className: "view" },
    h("div", { className: "metric-grid metric-pair-grid" },
      h(MetricSet, {
        icon: "doc",
        title: "문서 인덱스",
        primaryLabel: "등록문서",
        primaryValue: num(stats.documents),
        secondaryLabel: "문서청크",
        secondaryValue: num(stats.document_chunks),
        todayLabel: "오늘 신규",
        todayValue: "+" + num(stats.documents_today || 0),
        extraLabel: "인덱스 용량",
        extraValue: bytes(stats.document_index_bytes || 0)
      }),
      h(MetricSet, {
        icon: "logs",
        title: "로그 인덱스",
        primaryLabel: "로깅데이터",
        primaryValue: num(stats.logs),
        secondaryLabel: "로그청크",
        secondaryValue: num(stats.log_chunks),
        todayLabel: "오늘 신규",
        todayValue: "+" + num(stats.logs_today || 0),
        extraLabel: "인덱스 용량",
        extraValue: bytes(stats.log_index_bytes || 0)
      })
    ),
    h(StorageStatusPanel, { stats, storagePaths, alerts, retention, recentPolicy, bytes }),
    h(SecurityInsightPanel, { insight: securityInsight, busy: insightBusy, onRefresh: refreshInsight }),
    h("div", { className: "dash-grid" },
      /* recent high-risk matches */
      h("section", { className: "panel high-risk-panel" },
        h("div", { className: "panel-head" },
          h("div", { className: "ttl" },
            h("h2", null, h(Icon, { name: "alert", size: 16, style: { verticalAlign: "-3px", marginRight: 6, color: "var(--risk-high)" } }), "최근 고위험 매칭"),
            h("p", null, "최근 로깅 데이터가 벡터화될 때 등록 문서와 비교해 임계치를 초과한 항목")),
            h("div", { className: "actions" }, h("span", { className: "chip" },
              h("b", null, feed.length), `건 유사 매칭 · 확인 대상 로그 ${uniqueRiskLogs}건 · 유사도 ${Number(recentCfg.recent_match_min_score || 0.82).toFixed(2)} 이상`))),
        feed.length ? h("div", { className: "risk-feed-body" },
          h("div", { className: "risk-feed-list" }, pageFeed.map((mm) => {
          const r = XCN.riskOf(mm.score);
          const log = XCN.logs.find((l) => l.log_id === mm.log_id) || { metadata: {} };
          const md = { ...(mm.metadata || {}), ...(log.metadata || {}) };
          return h("div", { className: "feed-item", key: mm.id, onClick: () => onMatch(mm) },
            h("div", { className: "feed-rail " + r.key }),
            h("div", { className: "feed-main" },
              h("div", { className: "ttl" }, h(TitleKind, { kind: "등록문서" }), h("span", null, mm.doc_title), h(SecPill, { level: mm.doc_security })),
              h("div", { className: "sub" },
                h("span", { title: mm.log_id || "-", className: "feed-log-id" }, "로깅ID ", XCN.displayLogId(mm.log_id) || "-"),
                h("span", null, md.user_id || "-"),
                h("span", { className: "feed-flow" }, md.src_ip || "-", h(Icon, { name: "arrowRight", size: 12 }), md.host || "-"),
                h("span", null, md.channel || md.svc || "-"),
                h("span", null, XCN.fmtTime(md.ctime)))),
            h(ScorePill, { score: mm.score }));
          })),
          h("div", { className: "pager" },
            h("button", { className: "btn btn-ghost btn-sm", disabled: safePage <= 0, onClick: () => setMatchPage(Math.max(0, safePage - 1)) }, "이전"),
            h("span", { className: "chip" }, `${safePage + 1} / ${totalPages} 페이지 · ${safePage * pageSize + 1}-${Math.min((safePage + 1) * pageSize, sortedFeed.length)} / ${sortedFeed.length}`),
            h("button", { className: "btn btn-ghost btn-sm", disabled: safePage >= totalPages - 1, onClick: () => setMatchPage(Math.min(totalPages - 1, safePage + 1)) }, "다음")))
        : h("div", { className: "empty" },
            h("div", { className: "e-ico" }, h(Icon, { name: "shield", size: 24 })),
            h("strong", null, "임계치 초과 매칭 없음"),
            h("span", null, "최근 로깅 데이터와 등록 문서의 벡터 비교 결과가 임계치 미만입니다."))
      ),
      h("div", { className: "dashboard-side" },
        h("section", { className: "panel" },
          h("div", { className: "panel-head" }, h("div", { className: "ttl" },
            h("h2", null, "위험 요약"), h("p", null, "중복 매칭을 제거한 실제 확인 대상 기준"))),
          h("div", { className: "insight-grid" },
            h(InsightCard, { label: "유사 매칭 건수", value: highMatches, sub: "로그-등록문서 기준" }),
            h(InsightCard, { label: "확인 대상 로그", value: uniqueRiskLogs, sub: "중복 제거 기준" }),
            h(InsightCard, { label: "첨부 매칭", value: attachmentMatches, sub: "첨부파일 기반" }),
            h(InsightCard, { label: "영향 사용자", value: affectedUsers, sub: "고유 사용자" }))),
        h("section", { className: "panel" },
          h("div", { className: "panel-head" }, h("div", { className: "ttl" },
            h("h2", null, "서비스 타입 분포"), h("p", null, "고위험 매칭 기준 상위 서비스"))),
          h(MiniList, { items: serviceTop, empty: "표시할 서비스 없음" })),
        h("section", { className: "panel" },
          h("div", { className: "panel-head" }, h("div", { className: "ttl" },
            h("h2", null, "문서 보안등급"), h("p", null, "등록 문서 보안등급 분포"))),
          h(MiniList, { items: securityTop, empty: "등록 문서 없음" })),
        h("section", { className: "panel" },
          h("div", { className: "panel-head" }, h("div", { className: "ttl" },
            h("h2", null, "최근 로그 서비스"), h("p", null, "최근 로딩된 로그 기준"))),
          h(MiniList, { items: recentLogTop, empty: "최근 로그 없음" }))
      )
    )
  );
}

function StorageStatusPanel({ stats, storagePaths, alerts, retention, recentPolicy, bytes }) {
  const total = Number(stats.total_index_bytes || 0);
  return h("section", { className: "panel storage-status-panel" },
    h("div", { className: "panel-head" },
      h("div", { className: "ttl" },
        h("h2", null, "대용량 운영 상태"),
        h("p", null, "벡터 인덱스 사용량, 디스크 여유율, 임계치 상태"))),
    h("div", { className: "storage-status-grid" },
      h("div", { className: "storage-total" },
        h("span", null, "벡터 인덱스 사용량"),
        h("b", { className: "mono" }, bytes(total)),
        h("small", null, `Milvus 객체 기준 · 문서 ${bytes(stats.document_index_bytes || 0)} · 로그 ${bytes(stats.log_index_bytes || 0)}`)),
      h("div", { className: "storage-list" },
        storagePaths.length ? storagePaths.map((item) => h(StoragePathRow, { key: item.path, item, bytes })) :
          h("div", { className: "empty compact" }, "디스크 경로 정보 없음")),
      h("div", { className: "storage-policy" },
        h("div", null, h("span", null, "최근 매칭 문서"), h("b", null, recentPolicy.sampling_enabled ? "일부 대상" : "전체 대상")),
        h("small", null, recentPolicy.document_limit ? `대상 문서 ${XCN.num(recentPolicy.document_count || 0)} / 최대 ${XCN.num(recentPolicy.document_limit || 0)}` : `대상 문서 ${XCN.num(recentPolicy.document_count || 0)} / 제한 없음`),
        h("div", null, h("span", null, "보관 정책"), h("b", null, `${retention.hot_days || 90}일 hot · ${retention.warm_days || 365}일 warm`)),
        h("small", null, `archive 기준 ${retention.archive_days || 1095}일 · 자동 삭제 없음`)),
      h("div", { className: "storage-alerts" },
        alerts.length ? alerts.map((item, idx) => h("div", { key: idx, className: "storage-alert " + (item.level || "warning") },
          h(Icon, { name: item.level === "critical" ? "alert" : "shield", size: 14 }),
          h("span", null, item.message || item.type || "알림"))) :
          h("div", { className: "storage-alert ok" }, h(Icon, { name: "shield", size: 14 }), h("span", null, "임계치 초과 없음")))));
}

function StoragePathRow({ item, bytes }) {
  const used = Math.max(0, Math.min(Number(item.used_percent || 0), 100));
  const level = used >= 90 ? "critical" : used >= 80 ? "warning" : "ok";
  const paths = Array.isArray(item.paths) && item.paths.length ? item.paths.join(", ") : item.path;
  return h("div", { className: "storage-path-row " + level },
    h("div", { className: "storage-path-top" },
      h("b", null, item.label || item.path),
      h("span", { className: "mono" }, `${used.toFixed(1)}%`)),
    h("div", { className: "storage-bar" }, h("i", { style: { width: `${used}%` } })),
    h("small", null, `${bytes(item.free_bytes || 0)} 여유 / ${bytes(item.total_bytes || 0)} 전체 · ${paths}`));
}

function SecurityInsightPanel({ insight, busy, onRefresh }) {
  const item = insight || {};
  const facts = item.facts || {};
  const severity = item.severity || "medium";
  const severityLabel = severity === "high" ? "즉시 검토" : severity === "low" ? "안정" : "주의";
  const reasons = Array.isArray(item.reasons) ? item.reasons : [];
  const actions = Array.isArray(item.actions) ? item.actions : [];
  return h("section", { className: "panel ai-security-panel severity-" + severity },
    h("div", { className: "ai-sec-head" },
      h("div", { className: "ai-sec-title" },
        h("span", { className: "ai-badge" }, h(Icon, { name: "shieldCheck", size: 14 }), "AI 보안 인사이트"),
        h("h2", null, item.headline || (busy ? "AI 인사이트를 비동기로 생성 중입니다." : "최근 고위험 매칭을 분석 중입니다.")),
        h("p", null, item.summary || "현황 데이터는 먼저 표시하고, vLLM 분석 결과는 준비되는 즉시 이 영역에 표시됩니다.")),
      h("div", { className: "ai-sec-actions" },
        h("span", { className: "risk-chip" }, severityLabel),
        h("button", { className: "btn btn-ghost btn-sm", disabled: busy, onClick: onRefresh },
          h(Icon, { name: "refresh", size: 14 }), busy ? "생성 중" : "다시 생성"))),
    h("div", { className: "ai-sec-grid" },
      h("div", { className: "ai-fact" }, h("span", null, "유사 매칭 건수"), h("b", { className: "mono" }, XCN.num(facts.recent_match_count || 0))),
      h("div", { className: "ai-fact" }, h("span", null, "확인 대상 로그"), h("b", { className: "mono" }, XCN.num(facts.unique_high_risk_logs || 0))),
      h("div", { className: "ai-fact" }, h("span", null, "최고 유사도"), h("b", { className: "mono" }, Number(facts.max_score || 0).toFixed(3))),
      h("div", { className: "ai-fact" }, h("span", null, "첨부 비중"), h("b", { className: "mono" }, Number(facts.attachment_ratio || 0).toFixed(1) + "%"))),
    h("div", { className: "ai-sec-body" },
      h("div", { className: "ai-list" },
        h("div", { className: "section-label" }, "판단 근거"),
        reasons.length ? reasons.map((text, idx) => h("div", { className: "ai-line", key: "r" + idx }, h("span", null, idx + 1), h("p", null, text)))
          : h("div", { className: "ai-muted" }, "표시할 근거가 없습니다.")),
      h("div", { className: "ai-list" },
        h("div", { className: "section-label" }, "권장 조치"),
        actions.length ? actions.map((text, idx) => h("div", { className: "ai-line action", key: "a" + idx }, h("span", null, idx + 1), h("p", null, text)))
          : h("div", { className: "ai-muted" }, "권장 조치가 없습니다."))),
    h("div", { className: "ai-sec-foot" },
      h("span", null, "source ", h("b", null, item.source || "-")),
      h("span", null, "model ", h("b", null, item.model || "-")),
      item.generated_at && h("span", null, "generated ", h("b", null, XCN.fmtTime(item.generated_at))),
      item.reason && h("span", null, "reason ", h("b", null, item.reason)),
      item.llm_error && h("span", { className: "ai-error", title: item.llm_error }, "fallback 적용")));
}

/* ============================== AI INSIGHT HISTORY ============================== */
function SecurityInsights({ toast, dataVersion }) {
  const [rows, setRows] = React.useState(XCN.securityInsightHistory || []);
  const [sel, setSel] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const selected = rows.find((row) => insightKey(row) === sel) || rows[0] || null;

  const loadHistory = React.useCallback(async () => {
    setBusy(true);
    try {
      const next = await XCN.loadSecurityInsightHistory(7);
      setRows(next);
      if (next.length && !next.some((row) => insightKey(row) === sel)) setSel(insightKey(next[0]));
      if (!next.length) setSel("");
    } catch (error) {
      toast && toast("AI 인사이트 이력 조회 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  }, [sel, toast]);

  React.useEffect(() => { loadHistory(); }, [dataVersion]);

  return h("div", { className: "view split insight-history-view" },
    h("section", { className: "panel", style: { overflow: "hidden" } },
      h("div", { className: "list-toolbar" },
        h("div", { className: "panel-head", style: { padding: 0, border: 0 } }, h("div", { className: "ttl" },
          h("h2", null, "AI 인사이트 이력"),
          h("p", null, "최근 1주 동안 매시간 생성된 보안 인사이트 저장본"))),
        h("button", { className: "btn btn-ghost btn-sm", disabled: busy, onClick: loadHistory },
          h(Icon, { name: "refresh", size: 15 }), busy ? "조회 중" : "새로고침")),
      h("div", { className: "list-scroll insight-history-list" },
        rows.length ? rows.map((row) => {
          const facts = row.facts || {};
          const key = insightKey(row);
          const severity = row.severity || "medium";
          return h("button", { key, className: "row-item insight-history-item" + (key === insightKey(selected) ? " active" : ""), onClick: () => setSel(key) },
            h("div", { className: "ri-top" },
              h("span", { className: "ri-title" }, row.headline || "-"),
              h("span", { className: "risk-chip mini " + severity }, insightSeverityLabel(severity))),
            h("div", { className: "ri-meta" },
              h("span", null, XCN.fmtTime(row.generated_at)),
              h("span", null, row.source || "-"),
              h("span", null, row.model || "-"),
              h("span", null, row.reason || "-")),
            h("div", { className: "ri-preview" },
              "유사 매칭 ", XCN.num(facts.recent_match_count || 0),
              " · 확인 대상 로그 ", XCN.num(facts.unique_high_risk_logs || 0),
              " · 최고 유사도 ", Number(facts.max_score || 0).toFixed(3)));
        }) : h("div", { className: "empty compact" }, "최근 1주 저장된 AI 인사이트가 없습니다."))),

    selected ? h("section", { className: "panel", style: { overflow: "hidden" } },
      h("div", { className: "detail-head insight-detail-head" },
        h("div", { className: "dh-main" },
          h("h2", null, selected.headline || "-"),
          h("div", { className: "dh-sub" },
            XCN.fmtTime(selected.generated_at), " · ", selected.source || "-", " · ", selected.reason || "-")),
        h("span", { className: "risk-chip " + (selected.severity || "medium") }, insightSeverityLabel(selected.severity))),
      h("div", { className: "detail-body insight-history-detail" },
        h("div", { className: "prov insight-history-facts" },
          h(ProvCell, { icon: "spark", k: "유사 매칭 건수" }, XCN.num((selected.facts || {}).recent_match_count || 0)),
          h(ProvCell, { icon: "logs", k: "확인 대상 로그" }, XCN.num((selected.facts || {}).unique_high_risk_logs || 0)),
          h(ProvCell, { icon: "shield", k: "최고 유사도" }, Number((selected.facts || {}).max_score || 0).toFixed(3)),
          h(ProvCell, { icon: "file", k: "첨부 비중" }, Number((selected.facts || {}).attachment_ratio || 0).toFixed(1) + "%")),
        h("section", { className: "detail-block" },
          h("h3", null, "요약"),
          h("p", null, selected.summary || "-")),
        h("section", { className: "detail-block" },
          h("h3", null, "판단 근거"),
          insightLines(selected.reasons, "근거 없음")),
        h("section", { className: "detail-block" },
          h("h3", null, "권장 조치"),
          insightLines(selected.actions, "권장 조치 없음")),
        selected.llm_error && h("section", { className: "detail-block" },
          h("h3", null, "LLM 처리 정보"),
          h("p", { className: "ai-error" }, "fallback 적용 · ", selected.llm_error)))) :
      h("section", { className: "panel" }, h("div", { className: "empty" }, "선택된 인사이트가 없습니다.")));
}

function insightKey(row) {
  if (!row) return "";
  return String(row.generated_at || row.created_hour || row.headline || "");
}

function insightSeverityLabel(severity) {
  return severity === "high" ? "즉시 검토" : severity === "low" ? "안정" : "주의";
}

function insightLines(items, empty) {
  const lines = Array.isArray(items) ? items.filter(Boolean) : [];
  return lines.length ? h("div", { className: "ai-list standalone" },
    lines.map((text, idx) => h("div", { className: "ai-line", key: idx }, h("span", null, idx + 1), h("p", null, text))))
    : h("p", { className: "ai-muted" }, empty);
}
function topCounts(values, limit) {
  const counts = new Map();
  values.forEach((value) => {
    const key = String(value || "-").trim() || "-";
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, limit);
}
function InsightCard({ label, value, sub }) {
  return h("div", { className: "insight-card" },
    h("div", { className: "ic-label" }, label),
    h("div", { className: "ic-value mono" }, XCN.num(value)),
    h("div", { className: "ic-sub" }, sub));
}
function MiniList({ items, empty }) {
  const max = Math.max(1, ...items.map((x) => x.count));
  return items.length ? h("div", { className: "mini-list" }, items.map((item) =>
    h("div", { className: "mini-row", key: item.label },
      h("span", { className: "mini-label" }, item.label),
      h("span", { className: "mini-bar" }, h("i", { style: { width: Math.max(8, Math.round((item.count / max) * 100)) + "%" } })),
      h("b", { className: "mono" }, item.count)))) : h("div", { className: "empty compact" }, empty);
}
function TitleKind({ kind }) {
  return h("span", { className: "title-kind" }, kind || "-");
}
function Operations() {
  const { pipeline, health } = XCN;
  return h("div", { className: "view" },
    h("div", { className: "ops-grid" },
      h("section", { className: "panel" },
        h("div", { className: "panel-head" }, h("div", { className: "ttl" },
          h("h2", null, "임베딩 파이프라인"), h("p", null, "준실시간 비동기 처리 상태"))),
        h("div", { className: "pipe" },
          h(PipeStage, { cls: "s-pending", lab: "PENDING", n: pipeline.PENDING }),
          h(PipeStage, { cls: "s-processing", lab: "PROCESSING", n: pipeline.PROCESSING }),
          h(PipeStage, { cls: "s-indexed", lab: "INDEXED", n: pipeline.INDEXED }),
          h(PipeStage, { cls: "s-failed", lab: "FAILED", n: pipeline.FAILED }))),
      h("section", { className: "panel" },
        h("div", { className: "panel-head" }, h("div", { className: "ttl" },
          h("h2", null, "서비스 상태"), h("p", null, "벡터 DB · 임베딩 · 카탈로그"))),
        h("div", { className: "kv-list" },
          kv("벡터 백엔드", health.vector_backend + " · " + health.vector_node),
          kv("임베딩 모델", `${health.embedding_model} (${health.embedding_dim}d)`),
          kv("카탈로그", `${health.catalog_backend} · ${health.catalog_database}`),
          kv("객체 저장소", health.object_store),
          kv("GPU", health.gpu),
          kv("API 버전", "v" + health.version))),
      h("section", { className: "panel wide" },
        h("div", { className: "panel-head" }, h("div", { className: "ttl" },
          h("h2", null, "운영 기준"), h("p", null, "현황 화면에서 분리된 런타임 점검 항목"))),
        h("div", { className: "ops-note" },
          h(ProvCell, { icon: "database", k: "벡터 저장소" }, `${health.vector_backend || "-"} 백엔드에 문서/로그 청크를 분리 저장합니다.`),
          h(ProvCell, { icon: "cpu", k: "임베딩 모델" }, `${health.embedding_model || "-"} · ${health.embedding_dim || 0}차원 벡터를 사용합니다.`),
          h(ProvCell, { icon: "logs", k: "처리 상태" }, "PENDING/PROCESSING 증가가 지속되면 인덱서 또는 MongoDB/Milvus 연결 상태를 확인합니다."))))
  );
}
function PipeStage({ cls, lab, n }) {
  return h("div", { className: "pipe-stage " + cls },
    h("div", { className: "lab" }, lab), h("div", { className: "num mono" }, XCN.num(n)));
}
function kv(k, v) {
  return h("div", { className: "kv-row", key: k },
    h("span", { className: "k" }, k), h("span", { className: "v" }, v));
}

function logDisplayName(match, log) {
  const md = (log && log.metadata) || (match && match.metadata) || {};
  const channel = md.channel || md.svc || "로그";
  if (md.title) return md.title;
  if (md.subject) return md.subject;
  if (md.mail_subject) return md.mail_subject;
  if (md.msg_subject) return md.msg_subject;
  if (md.email_subject) return md.email_subject;
  if (md.attach_name && md.attach_name !== "-") return md.attach_name;
  if (md.file_name) return md.file_name;
  if (md.fileName) return md.fileName;
  if (md.source_type === "attachment") return "첨부 데이터";
  return `${channel} 본문`;
}

function logMetaLine(match, log) {
  const md = (log && log.metadata) || (match && match.metadata) || {};
  return `${XCN.displayLogId(match.log_id || match.target_id) || "-"} · ${md.user_id || "-"} · ${md.channel || md.svc || "-"}`;
}
function logDirectionLabel(md) {
  const direction = String((md && (md.direction || md.directionSvc)) || "").toUpperCase();
  if (direction === "O" || direction === "OUT") return "외부 발신";
  if (direction === "I" || direction === "IN") return "외부 수신";
  return direction || "-";
}
function formatBytes(value) {
  const n = Number(value || 0);
  if (!n) return "-";
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}
function shortChecksum(value) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.length > 16 ? text.slice(0, 12) + "..." + text.slice(-6) : text;
}
function firstMeta(md, keys) {
  for (const key of keys) {
    const value = md && md[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return "";
}
function extractMailHeader(text, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(?:^|\\n)\\s*${escaped}\\s*[:：]\\s*([^\\n\\r]+)`, "i");
  const m = String(text || "").match(re);
  return m ? m[1].trim() : "";
}
function mailInfo(log, chunks) {
  const md = (log && log.metadata) || {};
  const text = [log && log.sample_text, ...(chunks || []).slice(0, 2).map((chunk) => chunk.text || "")].filter(Boolean).join("\n");
  return {
    from: firstMeta(md, ["mail_from", "from", "sender", "sender_email", "src_email", "user_email"]) || extractMailHeader(text, "From"),
    to: firstMeta(md, ["mail_to", "to", "receiver", "recipients", "recipient", "dst_email"]) || extractMailHeader(text, "To"),
    cc: firstMeta(md, ["cc", "mail_cc"]) || extractMailHeader(text, "Cc"),
    bcc: firstMeta(md, ["bcc", "mail_bcc"]) || extractMailHeader(text, "Bcc"),
    subject: firstMeta(md, ["subject", "mail_subject", "msg_subject", "email_subject"]) || extractMailHeader(text, "Subject"),
  };
}

/* ============================== DOCUMENTS ============================== */
const UPLOAD_MAX_MB = 300;
const UPLOAD_FORMAT_HINTS = ["단일: PDF DOC DOCX HWP HWPX ODT RTF", "표/발표: XLS XLSX CSV TSV PPT PPTX", "텍스트/소스: TXT MD JSON XML HTML SQL PY JS TS JAVA SH", "압축: ZIP TAR TAR.GZ TGZ"];
const UPLOAD_ALLOWED_EXTS = [
  "pdf", "doc", "docx", "odt", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx",
  "txt", "text", "csv", "tsv", "md", "markdown", "rtf", "json", "jsonl", "xml", "html", "htm", "log",
  "java", "py", "js", "jsx", "ts", "tsx", "c", "cpp", "h", "cs", "go", "rs",
  "sql", "sh", "yaml", "yml", "properties", "ini", "conf",
  "zip", "tar", "tar.gz", "tgz"
];
const UPLOAD_ACCEPT_ATTR = UPLOAD_ALLOWED_EXTS.map((ext) => "." + ext).join(",");

function fileExt(name) {
  const value = String(name || "").toLowerCase();
  if (value.endsWith(".tar.gz")) return "tar.gz";
  const m = value.match(/\.([a-z0-9]+)$/);
  return m ? m[1] : "";
}
function fileExtLabel(name) {
  const ext = fileExt(name);
  return ext ? ext.toUpperCase() : "FILE";
}
function fileKindIcon(name) {
  const ext = fileExt(name);
  if (["zip", "tar", "tar.gz", "tgz"].includes(ext)) return "layers";
  if (["xls", "xlsx", "csv", "tsv"].includes(ext)) return "layers";
  if (["json", "xml", "html", "htm", "yaml", "yml", "java", "py", "js", "jsx", "ts", "tsx", "c", "cpp", "h", "cs", "go", "rs", "sql", "sh", "md", "properties", "ini", "conf", "log"].includes(ext)) return "file";
  return "doc";
}
function validateUploadFile(file) {
  if (!file) return "파일을 찾을 수 없습니다.";
  if (!file.size) return "빈 파일은 등록할 수 없습니다.";
  if (file.size > UPLOAD_MAX_MB * 1024 * 1024) {
    return `파일 크기가 ${UPLOAD_MAX_MB}MB를 초과합니다 · 현재 ${formatBytes(file.size)}`;
  }
  const ext = fileExt(file.name);
  if (ext && !UPLOAD_ALLOWED_EXTS.includes(ext)) {
    return `지원하지 않는 형식입니다 · .${ext}`;
  }
  return "";
}

function Documents({ onMatch, toast, refresh, dataVersion }) {
  const fileRef = React.useRef(null);
  const dropRef = React.useRef(null);
  const [sel, setSel] = React.useState("");
  const [q, setQ] = React.useState("");
  const [docs, setDocs] = React.useState([]);
  const [docOffset, setDocOffset] = React.useState(0);
  const [docNextOffset, setDocNextOffset] = React.useState(null);
  const [docListBusy, setDocListBusy] = React.useState(false);
  const [chunks, setChunks] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [draggingUpload, setDraggingUpload] = React.useState(false);
  const [uploadFiles, setUploadFiles] = React.useState([]);
  const [uploadError, setUploadError] = React.useState("");
  const [titleTouched, setTitleTouched] = React.useState(false);
  const [uploadMeta, setUploadMeta] = React.useState({
    title: "",
    security_level: "대외비",
    retain_file: true
  });
  const [editing, setEditing] = React.useState(false);
  const [editMeta, setEditMeta] = React.useState({
    title: "",
    security_level: "대외비"
  });
  const doc = XCN.documents.find((d) => d.document_id === sel);
  const docTextHidden = !!(doc && doc.metadata && doc.metadata.file_retained === false);
  const uploadFile = uploadFiles[0] || null;
  const uploadTotalSize = uploadFiles.reduce((sum, item) => sum + Number(item.size || 0), 0);

  const loadDocumentPage = React.useCallback(async (targetOffset = 0) => {
    setDocListBusy(true);
    try {
      const result = await XCN.searchDocumentCatalog({
        query: q.trim(),
        limit: 30,
        offset: targetOffset,
      });
      setDocs(result.data || []);
      setDocOffset(targetOffset);
      setDocNextOffset(result.next_offset ?? null);
      if (!sel && result.data && result.data[0]) setSel(result.data[0].document_id);
    } catch (error) {
      toast("문서 목록 조회 실패 · " + error.message);
    } finally {
      setDocListBusy(false);
    }
  }, [q, sel, toast]);

  React.useEffect(() => {
    const timer = setTimeout(() => loadDocumentPage(0), 250);
    return () => clearTimeout(timer);
  }, [dataVersion, q]);

  React.useEffect(() => {
    if (!sel) {
      setChunks([]);
      return;
    }
    XCN.fetchDocumentChunks(sel).then(setChunks).catch((error) => toast("문서 청크 조회 실패 · " + error.message));
  }, [sel, dataVersion]);

  React.useEffect(() => {
    setEditing(false);
  }, [sel]);

  const acceptUploadFiles = (files) => {
    const selected = Array.from(files || []).filter(Boolean);
    if (!selected.length) return;
    const invalid = selected.map(validateUploadFile).find(Boolean);
    const totalSize = selected.reduce((sum, item) => sum + Number(item.size || 0), 0);
    const err = invalid || (totalSize > UPLOAD_MAX_MB * 1024 * 1024 ? `파일 합계가 ${UPLOAD_MAX_MB}MB를 초과합니다 · 현재 ${formatBytes(totalSize)}` : "");
    if (err) {
      setUploadError(err);
      toast(err);
      return;
    }
    setUploadError("");
    setUploadFiles(selected);
    setUploadMeta((prev) => ({
      ...prev,
      title: selected.length === 1 && prev.title && prev.title.trim()
        ? prev.title
        : selected.length === 1
          ? selected[0].name.replace(/\.[^/.]+$/, "") || selected[0].name
          : ""
    }));
  };

  const chooseUploadFile = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    acceptUploadFiles(files);
  };

  const handleUploadDrop = (event) => {
    event.preventDefault();
    setDraggingUpload(false);
    const files = event.dataTransfer && event.dataTransfer.files;
    acceptUploadFiles(files);
  };

  const openFilePicker = () => {
    if (busy) return;
    fileRef.current && fileRef.current.click();
  };

  const clearUploadFile = (event) => {
    if (event) event.stopPropagation();
    setUploadFiles([]);
    setUploadError("");
  };

  const updateUploadMeta = (key, value) => {
    setUploadMeta((prev) => ({ ...prev, [key]: value }));
  };

  const cancelUpload = () => {
    setUploadFiles([]);
    setUploadError("");
    setTitleTouched(false);
    setUploadMeta({ title: "", security_level: "대외비", retain_file: true });
  };

  const beginEdit = () => {
    if (!doc) return;
    setEditMeta({
      title: doc.title || "",
      security_level: doc.security_level === "일반" ? "일반" : "대외비"
    });
    setEditing(true);
  };

  const updateEditMeta = (key, value) => {
    setEditMeta((prev) => ({ ...prev, [key]: value }));
  };

  const saveEdit = async () => {
    if (!doc) return;
    if (!editMeta.title.trim()) {
      toast("문서명을 입력하세요.");
      return;
    }
    setBusy(true);
    try {
      const info = await XCN.updateDocument(doc.document_id, editMeta);
      await loadDocumentPage(docOffset);
      await refresh();
      setSel(info.document_id);
      setEditing(false);
      toast("문서 정보 수정 완료 · " + info.title);
    } catch (error) {
      toast("문서 정보 수정 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };

  const submitUpload = async () => {
    if (!uploadFiles.length) {
      setUploadError("등록할 문서 파일을 선택하세요.");
      toast("등록할 문서 파일을 선택하세요.");
      return;
    }
    if (uploadFiles.length === 1 && !uploadMeta.title.trim()) {
      setTitleTouched(true);
      toast("문서명을 입력하세요.");
      return;
    }
    setBusy(true);
    try {
      const info = await XCN.uploadDocument(uploadFiles, uploadMeta);
      cancelUpload();
      await loadDocumentPage(0);
      await refresh();
      if (info && info.document_id) setSel(info.document_id);
      toast(`문서 등록 완료 · ${uploadFiles.length}개 파일 처리`);
    } catch (error) {
      toast("문서 등록 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };

  const removeDocument = async () => {
    if (!doc || !confirm(`문서를 삭제하시겠습니까?\n${doc.title}`)) return;
    setBusy(true);
    try {
      await XCN.deleteDocument(doc.document_id);
      setSel("");
      await loadDocumentPage(docOffset);
      await refresh();
      toast("문서 삭제 완료");
    } catch (error) {
      toast("문서 삭제 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };

  return h("div", { className: "view documents-view" },
    h("section", { className: "panel document-register-panel", style: { overflow: "hidden" } },
      h("div", { className: "document-register" },
        h("div", { className: "panel-head", style: { padding: 0, border: 0 } },
          h("div", { className: "ttl" },
            h("h2", null, "문서 등록"),
            h("p", null, "파일을 끌어 놓으면 텍스트 추출 후 벡터 인덱스에 등록됩니다."))),
        h("input", { ref: fileRef, type: "file", multiple: true, style: { display: "none" }, accept: UPLOAD_ACCEPT_ATTR, onChange: chooseUploadFile }),
        h("div", { className: "document-register-left" },
          h("div", {
            ref: dropRef,
            className: "document-drop" + (draggingUpload ? " dragging" : "") + (uploadFiles.length ? " has-file" : "") + (uploadError ? " has-error" : "") + (busy ? " uploading" : ""),
            role: "button",
            tabIndex: busy ? -1 : 0,
            "aria-label": uploadFiles.length ? `선택된 파일 ${uploadFiles.length}개. 클릭하면 변경합니다.` : "문서 파일을 드래그앤드롭하거나 클릭해 선택",
            "aria-disabled": busy ? "true" : "false",
            onClick: openFilePicker,
            onKeyDown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openFilePicker(); } },
            onDragOver: (event) => { if (busy) return; event.preventDefault(); setDraggingUpload(true); },
            onDragLeave: (event) => { if (event.currentTarget === event.target) setDraggingUpload(false); },
            onDrop: handleUploadDrop
          },
            h("span", { className: "drop-mark", "aria-hidden": "true" },
              busy ? h(Icon, { name: "refresh", size: 22 }) : h(Icon, { name: uploadFile ? fileKindIcon(uploadFile.name) : "upload", size: 22 })),
            h("span", { className: "drop-main" },
              uploadFiles.length
                ? h("b", null, uploadFiles.length === 1 ? uploadFile.name : `${uploadFiles.length}개 파일 개별 등록`)
                : h("b", null, busy ? "등록 처리 중…" : h(React.Fragment, null, h("u", null, "클릭"), "하거나 파일을 여기로 끌어 놓으세요")),
              uploadFiles.length
                ? h("small", { className: "drop-fileinfo" },
                    h("span", { className: "file-ext mono" }, uploadFiles.length === 1 ? fileExtLabel(uploadFile.name) : `${uploadFiles.length} FILES`),
                    h("span", null, formatBytes(uploadTotalSize)),
                    h("span", { className: "drop-hint" }, "클릭하면 다른 파일로 변경"))
                : h("small", null, `최대 ${UPLOAD_MAX_MB}MB · 단일 문서 또는 ZIP/TAR 압축 묶음`)),
            uploadFiles.length > 0 && !busy && h("button", {
              type: "button",
              className: "drop-clear",
              "aria-label": "선택한 파일 제거",
              onClick: clearUploadFile
            }, h(Icon, { name: "close", size: 15 })),
            !uploadFiles.length && !busy && h("span", { className: "drop-cta", "aria-hidden": "true" }, "파일 선택")),
          !uploadFiles.length && !uploadError && h("div", { className: "drop-formats" },
            UPLOAD_FORMAT_HINTS.map((fmt) => h("span", { className: "format-chip", key: fmt }, fmt))),
          uploadError && h("div", { className: "drop-error", role: "alert" },
            h(Icon, { name: "alert", size: 14 }), h("span", null, uploadError))),
        h("div", { className: "document-register-form" },
          h("div", { className: "upload-grid" },
            h("div", { className: "field" },
              h("label", null, "문서명 ", h("span", { className: "req" }, "*")),
              h("input", {
                className: "input" + (titleTouched && !uploadMeta.title.trim() ? " invalid" : ""),
                value: uploadMeta.title,
                onChange: (e) => updateUploadMeta("title", e.target.value),
                onBlur: () => setTitleTouched(true),
                "aria-invalid": titleTouched && !uploadMeta.title.trim() ? "true" : "false",
                placeholder: "문서명"
              }),
              titleTouched && !uploadMeta.title.trim() && h("small", { className: "field-error" }, "문서명을 입력하세요.")),
            h("div", { className: "field" },
              h("label", null, "보안등급"),
              h("select", { className: "input", value: uploadMeta.security_level, onChange: (e) => updateUploadMeta("security_level", e.target.value) },
                h("option", { value: "대외비" }, "대외비"),
                h("option", { value: "일반" }, "일반")))),
          h("div", { className: "register-actions" },
            h("label", { className: "check-row compact" },
              h("input", { type: "checkbox", checked: uploadMeta.retain_file, onChange: (e) => updateUploadMeta("retain_file", e.target.checked) }),
              h("span", null, "원본 저장"),
              h("small", null, uploadMeta.retain_file ? "원본 파일 보관" : "벡터만 유지")),
            h("div", { className: "upload-actions" },
              h("button", { className: "btn btn-ghost btn-sm", type: "button", disabled: busy || (!uploadFile && !uploadMeta.title.trim()), onClick: cancelUpload }, "초기화"),
              h("button", { className: "btn btn-primary btn-sm", type: "button", disabled: busy || !uploadFiles.length, onClick: submitUpload },
                busy ? h(Icon, { name: "refresh", size: 15 }) : h(Icon, { name: "plus", size: 15 }), busy ? "등록 중" : "등록 실행")))))),
    h("div", { className: "split document-workspace" },
      h("section", { className: "panel document-manage-panel", style: { overflow: "hidden" } },
      h("div", { className: "list-toolbar document-list-toolbar" },
        h("div", { className: "panel-head", style: { padding: 0, border: 0 } },
          h("div", { className: "ttl" }, h("h2", null, "등록 문서"), h("p", null, "문서 관리 전용 목록"))),
        h("div", { className: "global-search", style: { width: "100%", marginLeft: 0, height: 36 } },
          h(Icon, { name: "search", size: 15 }),
          h("input", { placeholder: "문서명 · ID · 파일명 · 크기 · 체크섬 검색", value: q, onChange: (e) => setQ(e.target.value) }))),
      h("div", { className: "list-scroll" },
        docListBusy && h("div", { className: "empty" }, h("strong", null, "문서 목록 조회 중"), h("span", null, "카탈로그에서 페이지 단위로 불러오고 있습니다.")),
        !docListBusy && !docs.length && h("div", { className: "empty" }, h("strong", null, "문서 없음"), h("span", null, q ? "검색 조건에 맞는 문서가 없습니다." : "등록된 문서가 없습니다.")),
        !docListBusy && docs.map((d) => h("button", { key: d.document_id, className: "row-item" + (d.document_id === sel ? " active" : ""), onClick: () => setSel(d.document_id) },
          h("div", { className: "ri-top" },
            h("span", { className: "ri-title" }, d.title),
            h(SecPill, { level: d.security_level })),
          h("div", { className: "ri-meta" }, `${d.document_id} · ${d.metadata && d.metadata.file_retained === false ? "벡터 전용" : "chunks " + d.chunk_count}`),
          h("div", { className: "ri-meta" }, `${(d.metadata && d.metadata.file_name) || "파일명 없음"} · ${formatBytes(d.metadata && d.metadata.file_size)} · SHA-256 ${shortChecksum(d.metadata && d.metadata.file_checksum_sha256)}`),
          h("div", { style: { display: "flex", gap: 6, alignItems: "center", marginTop: 2 } }, h(StatusBadge, { status: d.status })))),
        h("div", { className: "pager-row" },
          h("button", { className: "btn btn-ghost btn-sm", disabled: docListBusy || docOffset <= 0, onClick: () => loadDocumentPage(Math.max(0, docOffset - 30)) }, "이전"),
          h("span", { className: "muted mono" }, `${docOffset + 1} - ${docOffset + docs.length}`),
          h("button", { className: "btn btn-ghost btn-sm", disabled: docListBusy || docNextOffset === null, onClick: () => loadDocumentPage(Number(docNextOffset || 0)) }, "다음")))),

    /* detail */
    doc ? h("section", { className: "panel", style: { overflow: "hidden" } },
      h("div", { className: "detail-head" },
        h("div", { className: "dh-main" },
          h("div", { style: { display: "flex", gap: 8, alignItems: "center" } }, h(StatusBadge, { status: doc.status }), h(SecPill, { level: doc.security_level })),
          h("h2", null, doc.title),
          h("div", { className: "meta-chips" },
            h(Chip, null, "ID ", h("b", null, doc.document_id)),
            h(Chip, null, doc.metadata.file_retained === false ? "원본 미보관" : "원본 보관"),
            !docTextHidden && h(Chip, null, "chunks ", h("b", null, doc.chunk_count)),
            h(Chip, null, doc.metadata.ext || doc.metadata.file_ext || "-", doc.metadata.pages ? ` · ${doc.metadata.pages}p` : "", doc.metadata.file_size ? " · " + formatBytes(doc.metadata.file_size) : ""))),
        h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
          h("button", { className: "btn btn-ghost btn-sm", disabled: busy, onClick: beginEdit },
            h(Icon, { name: "edit", size: 15 }), "정보 수정"),
          h("button", { className: "btn btn-danger btn-sm", disabled: busy, onClick: removeDocument },
            h(Icon, { name: "trash", size: 15 }), "삭제"))),
      h("div", { className: "detail-body" },
        editing && h("div", { className: "upload-box" },
          h("div", { className: "section-label" }, "문서 정보 수정"),
          h("div", { className: "upload-grid" },
            h("div", { className: "field" },
              h("label", null, "문서명"),
              h("input", { className: "input", value: editMeta.title, onChange: (e) => updateEditMeta("title", e.target.value), placeholder: "문서명" })),
            h("div", { className: "field" },
              h("label", null, "보안등급"),
              h("select", { className: "input", value: editMeta.security_level, onChange: (e) => updateEditMeta("security_level", e.target.value) },
                h("option", { value: "대외비" }, "대외비"),
                h("option", { value: "일반" }, "일반")))),
          h("div", { className: "upload-actions" },
            h("button", { className: "btn btn-ghost btn-sm", disabled: busy, onClick: () => setEditing(false) }, "취소"),
            h("button", { className: "btn btn-primary btn-sm", disabled: busy, onClick: saveEdit },
              h(Icon, { name: "save", size: 15 }), busy ? "저장 중" : "저장"))),
        h("div", { className: "doc-content-card" },
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "원본 식별 정보"),
          h("div", { className: "document-identity-grid" },
            h(ProvCell, { icon: "file", k: "파일명" }, doc.metadata.file_name || "-"),
            h(ProvCell, { icon: "layers", k: "파일 크기" }, formatBytes(doc.metadata.file_size)),
            h(ProvCell, { icon: "database", k: "SHA-256 체크섬" }, doc.metadata.file_checksum_sha256 || "-"),
            h(ProvCell, { icon: "shield", k: "원본 보관 상태" }, doc.metadata.file_retained === false ? "원본 미보관 · 벡터/메타데이터로 식별" : "원본 보관"))),
        h("div", { className: "doc-content-card" },
          h("div", { className: "section-label", style: { marginBottom: 10 } }, docTextHidden ? "벡터 전용 문서" : "문서 청크", !docTextHidden && h("span", { className: "count" }, chunks.length || doc.chunk_count)),
          docTextHidden ? h("div", { className: "empty" },
            h("div", { className: "e-ico" }, h(Icon, { name: "shield", size: 24 })),
            h("strong", null, "원문 비공개"),
            h("span", null, "원본과 청크 본문은 저장하지 않으며 유사도 검색은 벡터로만 수행됩니다."))
          : chunks.length ? h("div", { style: { display: "flex", flexDirection: "column", gap: 10 } },
            chunks.map((chunk, i) => h("div", { className: "chunk", key: chunk.chunk_id || i },
              h("div", { className: "chunk-head" }, h("span", { className: "cid" }, chunk.chunk_id || `chunk-${i+1}`),
                h("span", { className: "cmeta" }, `${(chunk.text || "").length}자`)),
              h("div", { className: "chunk-text" }, chunk.text || "")))
          ) : h("div", { className: "empty" },
            h("div", { className: "e-ico" }, h(Icon, { name: doc.status === "FAILED" ? "alert" : "clock", size: 24 })),
            h("strong", null, doc.status === "FAILED" ? "인덱싱 실패" : "인덱싱 대기 중"),
            h("span", null, doc.status === "FAILED" ? (doc.metadata.error || "재처리가 필요합니다.") : "임베딩 처리가 완료되면 청크가 표시됩니다.")))
        )
    ) : null)
  );
}

/* ============================== SEARCH ============================== */
function Search({ onMatch, toast }) {
  const fileRef = React.useRef(null);
  const [mode, setMode] = React.useState("logs"); // docs = 로그 기준 문서 매칭, logs = 문서 기준 로그 추적
  const [documentId, setDocumentId] = React.useState("");
  const [selectedDocument, setSelectedDocument] = React.useState(null);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [docQuery, setDocQuery] = React.useState("");
  const [docSecurity, setDocSecurity] = React.useState("");
  const [docResults, setDocResults] = React.useState([]);
  const [docOffset, setDocOffset] = React.useState(0);
  const [docNextOffset, setDocNextOffset] = React.useState(null);
  const [docPickerBusy, setDocPickerBusy] = React.useState(false);
  const [text, setText] = React.useState("");
  const [ran, setRan] = React.useState(false);
  const [results, setResults] = React.useState([]);
  const [selectedIndex, setSelectedIndex] = React.useState(0);
  const [topK, setTopK] = React.useState(20);
  const [minScore, setMinScore] = React.useState(0.6);
  const [sourceType, setSourceType] = React.useState("");
  const [svc, setSvc] = React.useState("");
  const [userId, setUserId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [conditionsCollapsed, setConditionsCollapsed] = React.useState(false);

  const runSearch = async () => {
    const activeDocument = selectedDocument || XCN.documents.find((doc) => doc.document_id === documentId);
    if (mode === "logs" && !activeDocument && !text.trim()) {
      toast("등록 문서를 선택하거나 문서 본문 텍스트를 입력하세요.");
      return;
    }
    if (mode === "docs" && !text.trim()) {
      toast("검색 텍스트를 입력하세요.");
      return;
    }
    setBusy(true);
    try {
      const hits = mode === "docs"
        ? await XCN.searchDocumentsByText(text, Number(topK), Number(minScore))
        : activeDocument
          ? await XCN.searchLogsForDocument(activeDocument, Number(topK), Number(minScore), { sourceType, svc, userId })
          : await XCN.searchLogsByText(text, Number(topK), Number(minScore), { sourceType, svc, userId });
      setResults(hits);
      setSelectedIndex(0);
      setRan(true);
      setConditionsCollapsed(true);
      toast("검색 완료 · " + hits.length + "건");
    } catch (error) {
      toast("검색 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };

  const fileSearch = async (event) => {
    const files = Array.from(event.target.files || []);
    const file = files[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const hits = await XCN.searchByFile(file, mode, Number(topK), Number(minScore), { sourceType, svc, userId });
      setResults(hits);
      setSelectedIndex(0);
      setRan(true);
      setConditionsCollapsed(true);
      toast("파일 검색 완료 · " + hits.length + "건");
    } catch (error) {
      toast("파일 검색 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };

  const loadDocumentPicker = async (targetOffset = 0) => {
    setDocPickerBusy(true);
    try {
      const result = await XCN.searchDocumentCatalog({
        query: docQuery.trim(),
        security_level: docSecurity,
        limit: 20,
        offset: targetOffset
      });
      setDocResults(result.data || []);
      setDocOffset(targetOffset);
      setDocNextOffset(result.next_offset);
    } catch (error) {
      toast("등록 문서 검색 실패 · " + error.message);
    } finally {
      setDocPickerBusy(false);
    }
  };

  React.useEffect(() => {
    if (pickerOpen) loadDocumentPicker(0);
  }, [pickerOpen]);

  const chooseDocument = (doc) => {
    setSelectedDocument(doc);
    setDocumentId(doc.document_id);
    setText("");
    setPickerOpen(false);
  };

  const clearDocument = () => {
    setSelectedDocument(null);
    setDocumentId("");
  };

  const selectedMatch = results[Math.min(selectedIndex, Math.max(results.length - 1, 0))] || null;
  const selectedLog = selectedMatch ? (XCN.logs.find((l) => l.log_id === selectedMatch.log_id) || { metadata: selectedMatch.metadata || {} }) : null;
  const selectedMeta = (selectedLog && selectedLog.metadata) || (selectedMatch && selectedMatch.metadata) || {};
  const selectedDoc = selectedMatch && selectedMatch.document_id ? XCN.documents.find((d) => d.document_id === selectedMatch.document_id) : null;
  const selectedTitle = selectedMatch
    ? (mode === "docs" ? (selectedMatch.doc_title || selectedMatch.document_id || "-") : logDisplayName(selectedMatch, selectedLog))
    : "";
  const scoreAvg = results.length ? results.reduce((sum, item) => sum + Number(item.score || 0), 0) / results.length : 0;
  const scoreMax = results.length ? Math.max(...results.map((item) => Number(item.score || 0))) : 0;
  const conditionSummary = mode === "docs"
    ? `로그 기준 문서 매칭 · Top K ${topK} · Min ${minScore}`
    : `${documentId ? "선택 문서로 로그 추적" : "문서 기준 로그 추적"} · ${sourceType || "전체"} · ${svc || "svc 전체"} · ${userId || "사용자 전체"}`;

  return h("div", { className: "view split search-workspace" },
    h("section", { className: "panel", style: { overflow: "hidden" } },
      h("div", { className: "panel-head" }, h("div", { className: "ttl" },
        h("h2", null, "유사도 검색"), h("p", null, "기준 데이터를 선택해 문서 매칭 또는 로그 추적을 수행"))),
      h("div", { className: "search-left-body" + (conditionsCollapsed ? " is-collapsed" : "") },
        h("div", { className: "search-condition-summary" },
          h("div", { className: "summary-main" },
            h("b", null, conditionsCollapsed ? "검색 조건 축소됨" : "검색 조건"),
            h("span", null, conditionSummary)),
          h("button", {
            className: "btn btn-ghost btn-sm",
            type: "button",
            onClick: () => setConditionsCollapsed(!conditionsCollapsed)
          }, conditionsCollapsed ? "검색 조건 펼치기" : "검색 조건 접기")),
        h("div", { className: "search-condition-body" },
          h("div", { className: "seg" },
            h("button", { className: mode === "docs" ? "on" : "", onClick: () => setMode("docs") }, "로그 기준 문서 매칭"),
            h("button", { className: mode === "logs" ? "on" : "", onClick: () => setMode("logs") }, "문서 기준 로그 추적")),
          h("div", { className: "search-condition-grid primary" },
            h("div", { className: "field" }, h("label", null, "Top K"), h("input", { className: "input", type: "number", value: topK, onChange: (e) => setTopK(e.target.value) })),
            h("div", { className: "field" }, h("label", null, "Min Score"), h("input", { className: "input", type: "number", step: "0.01", value: minScore, onChange: (e) => setMinScore(e.target.value) })),
            h("div", { className: "field" }, h("label", null, "대상"),
              h("select", { className: "input", value: sourceType, onChange: (e) => setSourceType(e.target.value) },
                h("option", { value: "" }, "전체"), h("option", { value: "body" }, "본문"), h("option", { value: "attachment" }, "첨부")))),
          h("div", { className: "search-condition-grid secondary" },
            h("div", { className: "field" }, h("label", null, "svc"), h("input", { className: "input", placeholder: "NENS · MSM- · BORD", value: svc, onChange: (e) => setSvc(e.target.value) })),
            h("div", { className: "field" }, h("label", null, "user_id"), h("input", { className: "input", placeholder: "사용자 ID", value: userId, onChange: (e) => setUserId(e.target.value) }))),
          mode === "logs" && h("div", { className: "field" },
            h("label", null, "등록 문서 선택"),
            selectedDocument ? h("div", { className: "selected-doc-card" },
              h("div", { className: "selected-doc-main" },
                h("div", { className: "selected-doc-title" },
                  h(SecPill, { level: selectedDocument.security_level }),
                  h("strong", null, selectedDocument.title || selectedDocument.document_id)),
                h("div", { className: "selected-doc-meta mono" },
                selectedDocument.document_id),
                h("div", { className: "selected-doc-meta" },
                  (selectedDocument.metadata && selectedDocument.metadata.file_name) || "파일명 없음",
                  " · ",
                  formatBytes(selectedDocument.metadata && selectedDocument.metadata.file_size),
                  " · ",
                  selectedDocument.metadata && selectedDocument.metadata.file_retained === false ? "원본 미보관" : "원본 보관")),
              h("div", { className: "selected-doc-actions" },
                h("button", { className: "btn btn-soft btn-sm", type: "button", onClick: () => setPickerOpen(true) }, h(Icon, { name: "search", size: 14 }), "변경"),
                h("button", { className: "btn btn-ghost btn-sm", type: "button", onClick: clearDocument }, "해제")))
            : h("button", { className: "doc-picker-trigger", type: "button", onClick: () => setPickerOpen(true) },
              h("span", { className: "drop-mark" }, h(Icon, { name: "doc", size: 18 })),
              h("span", { className: "drop-main" },
                h("b", null, "등록 문서 검색 선택"),
              h("small", null, "문서명, ID, 파일명, 체크섬으로 검색합니다.")),
              h("span", { className: "drop-cta" }, "선택"))),
          h("div", { className: "field" },
            h("label", null, mode === "docs" ? "로깅된 본문/첨부 텍스트" : "문서 본문 텍스트"),
            h("textarea", {
              className: "input",
              rows: mode === "logs" && documentId ? 4 : 7,
              value: text,
              disabled: mode === "logs" && !!documentId,
              onChange: (e) => setText(e.target.value),
              placeholder: mode === "logs" && documentId ? "선택한 등록 문서의 저장 벡터로 로그를 추적합니다." : "검색할 텍스트를 입력하세요."
            })),
          h("input", { ref: fileRef, type: "file", style: { display: "none" }, onChange: fileSearch }),
          h("button", { className: "dropzone", type: "button", disabled: busy || (mode === "logs" && !!documentId), onClick: () => fileRef.current && fileRef.current.click() },
            h(Icon, { name: "upload" }), "파일로 검색 · 오피스/PDF/HWP 및 텍스트·소스코드 파일"),
          h("button", { className: "btn btn-primary", disabled: busy, style: { width: "100%", justifyContent: "center" }, onClick: runSearch },
            h(Icon, { name: "search", size: 16 }), busy ? "검색 중" : (mode === "docs" ? "로그 기준 문서 매칭" : (documentId ? "선택 문서로 로그 추적" : "문서 기준 로그 추적")))),
        h("div", { className: "search-result-head" },
          h("div", { className: "ttl" },
            h("h3", null, "검색 결과"),
            h("p", null, ran ? "결과를 선택하면 우측에 상세 근거가 표시됩니다." : "검색 실행 후 점수가 높은 순서로 표시됩니다.")),
          h("span", { className: "chip" }, h("b", null, results.length), "건")),
        h(ScoreLegend),
      ran ? h("div", { className: "result-list search-result-list" },
        results.map((m, i) => {
          const log = XCN.logs.find((l) => l.log_id === m.log_id) || { metadata: m.metadata || {} };
          const md = log.metadata;
          const risk = XCN.riskOf(m.score);
          const scope = m.review_scope || XCN.reviewScopeOf(m.score);
          return h("article", { className: "result result-risk-" + risk.key + (i === selectedIndex ? " active" : ""), key: m.id, onClick: () => setSelectedIndex(i) },
            h("div", { className: "result-top" },
              h("div", { className: "result-rank mono" }, "#" + (i + 1)),
              h("div", { className: "result-id" },
                h("div", { className: "rt" },
                  h(TitleKind, { kind: mode === "docs" ? "등록문서" : XCN.logTitleKind(log.metadata || m.metadata) }),
                  h("span", null, mode === "docs" ? m.doc_title : logDisplayName(m, log)),
                  mode === "docs" && h(SecPill, { level: m.doc_security }),
                  h("span", { className: "review-chip mini scope-" + scope }, XCN.reviewScopeLabel(scope)),
                  h("span", { className: "review-chip mini decision-" + (m.review_status || "unreviewed") }, m.review_status_label || "미분류")),
                h("div", { className: "rs" }, mode === "docs" ? m.document_id : `${XCN.displayLogId(m.log_id)} · ${md.user_id || "-"} · ${md.channel || md.svc || "-"} · ${XCN.fmtTime(md.ctime)}`)),
              h(ScorePill, { score: m.score })),
            h("div", { style: { padding: "0 14px 4px" } }, h(ScoreBar, { score: m.score })),
            h("div", { className: "result-snip" },
              h("div", { className: "snip-box mono" }, highlight(mode === "docs" ? m.doc_text : m.log_text, m.terms))),
            h("div", { className: "result-foot" },
              m.terms.slice(0, 3).map((t, k) => h("span", { className: "chip", key: k }, t)),
              h("span", { className: "grow" }),
              h("button", { className: "btn btn-soft btn-sm", onClick: (event) => { event.stopPropagation(); onMatch(m); } }, h(Icon, { name: "layers", size: 14 }), "팝업 근거")));
        })
      ) : h("div", { className: "empty" }, h("div", { className: "e-ico" }, h(Icon, { name: "search", size: 24 })), h("strong", null, "검색 결과 없음"), h("span", null, "텍스트나 파일로 검색을 실행하세요.")))
      ),

    h("section", { className: "panel search-detail-panel", style: { overflow: "hidden" } },
      h("div", { className: "panel-head" },
        h("div", { className: "ttl" },
          h("h2", null, "매칭 상세"),
          h("p", null, selectedMatch ? "선택 결과의 점수, 출처, 본문 근거를 한 화면에서 확인" : "검색 결과를 선택하면 상세 분석이 표시됩니다.")),
        h("div", { className: "actions" }, selectedMatch && h(ScorePill, { score: selectedMatch.score }))),
      h("div", { className: "search-detail-body" },
        h("div", { className: "search-summary-grid" },
          h(ProvCell, { icon: "search", k: "검색 방향" }, mode === "docs" ? "로그 기준 → 등록문서" : "문서 기준 → 로깅데이터"),
          h(ProvCell, { icon: "layers", k: "결과 / 최고점" }, `${results.length}건 · ${scoreMax ? scoreMax.toFixed(3) : "-"}`),
          h(ProvCell, { icon: "shield", k: "임계값 / 평균점수" }, `${Number(minScore || 0).toFixed(2)} · ${scoreAvg ? scoreAvg.toFixed(3) : "-"}`),
          h(ProvCell, { icon: "file", k: "대상 필터" }, `${sourceType || "전체"} · ${svc || "svc 전체"} · ${userId || "사용자 전체"}`)),
        selectedMatch ? h("div", { className: "match-detail-stack" },
          h("div", { className: "doc-content-card" },
            h("div", { className: "section-label", style: { marginBottom: 10 } }, "선택 결과"),
            h("div", { className: "match-title-row" },
              h("div", { className: "match-title-main" },
                h(TitleKind, { kind: mode === "docs" ? "등록문서" : XCN.logTitleKind(selectedMeta) }),
                h("strong", null, selectedTitle),
                h("span", { className: "mono" }, mode === "docs" ? (selectedMatch.document_id || "-") : `${XCN.displayLogId(selectedMatch.log_id)} · ${selectedMeta.user_id || "-"} · ${selectedMeta.channel || selectedMeta.svc || "-"}`),
                h("div", { className: "review-inline" },
                  h("span", { className: "review-chip scope-" + (selectedMatch.review_scope || XCN.reviewScopeOf(selectedMatch.score)) }, selectedMatch.review_scope_label || XCN.reviewScopeLabel(XCN.reviewScopeOf(selectedMatch.score))),
                  h("span", { className: "review-chip decision-" + (selectedMatch.review_status || "unreviewed") }, selectedMatch.review_status_label || "미분류"),
                  selectedMatch.review && h("span", { className: "review-meta" }, `${selectedMatch.review.reason_code || "-"} · ${XCN.fmtTime(selectedMatch.review.reviewed_at)}`))),
              h(ScorePill, { score: selectedMatch.score })),
            h("div", { style: { marginTop: 12 } }, h(ScoreBar, { score: selectedMatch.score }))),
          h("div", { className: "doc-content-card" },
            h("div", { className: "section-label", style: { marginBottom: 10 } }, "점수 분해"),
            h("div", { className: "score-breakdown" },
              (selectedMatch.breakdown || [["유사도", selectedMatch.score]]).map((item, idx) => h("div", { className: "score-break-row", key: idx },
                h("span", { title: item[0] }, XCN.scoreBreakdownLabel(item[0])),
                h("b", { className: "mono" }, Number(item[1] || 0).toFixed(3)),
                h("div", { className: "score-mini-bar" }, h("i", { style: { width: Math.max(0, Math.min(100, Number(item[1] || 0) * 100)) + "%" } })),
                h("p", { className: "score-break-desc" }, XCN.scoreBreakdownDescription(item[0], item[1])))))),
          h("div", { className: "doc-content-card" },
            h("div", { className: "section-label", style: { marginBottom: 10 } }, "공통 핵심어구"),
            selectedMatch.terms && selectedMatch.terms.length
              ? h("div", { className: "term-cloud" }, selectedMatch.terms.map((term, idx) => h("span", { className: "chip", key: idx }, term)))
              : h("div", { className: "empty compact" }, h("strong", null, "공통어구 없음"), h("span", null, "본문 미로딩 또는 짧은 청크는 AI 유사도 중심으로 판단합니다."))),
          h("div", { className: "doc-content-card compare-card" },
            h("div", { className: "section-label", style: { marginBottom: 10 } }, "등록문서 / 로깅데이터 비교"),
            h("div", { className: "compare search-compare" },
              h("div", { className: "compare-col doc" },
                h("div", { className: "cc-head" },
                  h("div", { className: "cc-kind" }, "등록문서"),
                  h("div", { className: "cc-title" }, selectedMatch.doc_title || (selectedDoc && selectedDoc.title) || selectedMatch.document_id || "-"),
                  h("div", { className: "cc-id" }, selectedMatch.document_id || "-")),
                h("div", { className: "cc-text" }, selectedMatch.doc_text || "문서 본문을 아직 불러오지 못했습니다.")),
              h("div", { className: "compare-col log" },
                h("div", { className: "cc-head" },
                  h("div", { className: "cc-kind" }, "로깅데이터"),
                  h("div", { className: "cc-title" }, logDisplayName(selectedMatch, selectedLog)),
                  h("div", { className: "cc-id" }, selectedMatch.log_id ? XCN.displayLogId(selectedMatch.log_id) : "-")),
                h("div", { className: "cc-text" }, selectedMatch.log_text || selectedMatch.text_preview || "로깅 본문이 없습니다.")))),
          h("button", { className: "btn btn-soft", style: { justifyContent: "center" }, onClick: () => onMatch(selectedMatch) },
            h(Icon, { name: "layers", size: 15 }), "매칭 근거 팝업으로 크게 보기"))
        : h("div", { className: "empty search-guide" },
          h("div", { className: "e-ico" }, h(Icon, { name: "layers", size: 24 })),
          h("strong", null, "우측 상세 영역"),
          h("span", null, "검색 결과 선택 시 출처, 점수 분해, 공통어구, 문서/로그 본문 비교를 표시합니다."))),
    pickerOpen && h("div", { className: "modal-scrim", onClick: () => setPickerOpen(false) },
      h("section", { className: "doc-picker-modal", onClick: (event) => event.stopPropagation() },
        h("div", { className: "drawer-head" },
          h("div", { className: "dh-main" },
            h("div", { className: "dh-eyebrow" }, "Document Picker"),
            h("h2", null, "등록 문서 검색 선택"),
            h("p", null, "문서가 많아도 검색과 페이지 이동으로 기준 문서를 선택합니다.")),
          h("button", { className: "icon-btn", type: "button", onClick: () => setPickerOpen(false) }, h(Icon, { name: "close", size: 18 }))),
        h("div", { className: "doc-picker-filters" },
          h("div", { className: "global-search", style: { width: "100%", marginLeft: 0 } },
            h(Icon, { name: "search", size: 15 }),
            h("input", {
              placeholder: "문서명 · ID · 파일명 · 체크섬",
              value: docQuery,
              onChange: (e) => setDocQuery(e.target.value),
              onKeyDown: (e) => { if (e.key === "Enter") loadDocumentPicker(0); }
            })),
          h("select", { className: "input", value: docSecurity, onChange: (e) => setDocSecurity(e.target.value) },
            h("option", { value: "" }, "보안등급 전체"),
            h("option", { value: "대외비" }, "대외비"),
            h("option", { value: "일반" }, "일반")),
          h("button", { className: "btn btn-primary btn-sm", type: "button", disabled: docPickerBusy, onClick: () => loadDocumentPicker(0) },
            h(Icon, { name: "search", size: 14 }), docPickerBusy ? "검색 중" : "검색")),
        h("div", { className: "doc-picker-list" },
          docResults.length ? docResults.map((doc) => h("button", { className: "doc-picker-row" + (doc.document_id === documentId ? " active" : ""), key: doc.document_id, type: "button", onClick: () => chooseDocument(doc) },
            h("div", { className: "doc-picker-row-top" },
              h("strong", null, doc.title || doc.document_id),
              h(SecPill, { level: doc.security_level })),
            h("div", { className: "doc-picker-row-meta mono" }, doc.document_id),
            h("div", { className: "doc-picker-row-meta" },
              (doc.metadata && doc.metadata.file_name) || "파일명 없음",
              " · ",
              formatBytes(doc.metadata && doc.metadata.file_size),
              " · SHA-256 ",
              shortChecksum(doc.metadata && doc.metadata.file_checksum_sha256))))
          : h("div", { className: "empty compact" }, h("strong", null, "검색 결과 없음"), h("span", null, "검색어 또는 필터를 변경하세요."))),
        h("div", { className: "pager" },
          h("button", { className: "btn btn-ghost btn-sm", type: "button", disabled: docPickerBusy || docOffset <= 0, onClick: () => loadDocumentPicker(Math.max(0, docOffset - 20)) }, "이전"),
          h("span", { className: "mono" }, "offset ", docOffset, docNextOffset ? " · 다음 있음" : " · 마지막"),
          h("button", { className: "btn btn-ghost btn-sm", type: "button", disabled: docPickerBusy || docNextOffset === null, onClick: () => loadDocumentPicker(Number(docNextOffset || 0)) }, "다음")))))
  );
}

/* ============================== KAFKA RESULTS ============================== */
function KafkaResults({ toast, dataVersion }) {
  const [rows, setRows] = React.useState(XCN.kafkaResults || []);
  const [deliveryStatus, setDeliveryStatus] = React.useState("");
  const [pageSize, setPageSize] = React.useState(50);
  const [offset, setOffset] = React.useState(0);
  const [nextOffset, setNextOffset] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [selected, setSelected] = React.useState(null);

  const load = React.useCallback(async (targetOffset = 0, status = deliveryStatus, limit = pageSize) => {
    setBusy(true);
    try {
      const result = await XCN.loadKafkaResults({ offset: targetOffset, limit, deliveryStatus: status });
      const data = result.data || [];
      setRows(data);
      setOffset(Number(targetOffset || 0));
      setNextOffset(result.next_offset ?? null);
      setSelected(data[0] || null);
    } catch (error) {
      toast && toast("Kafka 결과 조회 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  }, [deliveryStatus, pageSize, toast]);

  React.useEffect(() => { load(0); }, [dataVersion]);

  const counts = rows.reduce((acc, row) => {
    const key = row.delivery_status || "pending";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const sent = counts.sent || 0;
  const failed = counts.failed || 0;
  const pending = counts.pending || 0;
  const high = rows.filter((row) => row.risk_level === "high").length;

  const applyFilter = () => load(0, deliveryStatus, pageSize);
  const detail = selected || rows[0] || null;
  const detailResults = detail ? (detail.results || []) : [];
  const detailJson = detail ? JSON.stringify(detail.kafka_payload || { type: detail.type, msgid: detail.msgid, data: detail.data || {} }, null, 2) : "";

  const tableBody = rows.length
    ? rows.map((row) => h("tr", {
      key: row.msgid,
      className: detail && detail.msgid === row.msgid ? "active" : "",
      onClick: () => setSelected(row),
    },
      h("td", { className: "mono msgid-cell", title: row.msgid }, row.msgid || "-"),
      h("td", null, h(DeliveryBadge, { status: row.delivery_status })),
      h("td", null, h(RiskBadge, { level: row.risk_level })),
      h("td", { className: "mono" }, Number(row.max_score || 0).toFixed(3)),
      h("td", { className: "mono" }, XCN.num(row.match_count || 0)),
      h("td", { className: "mono" }, row.delivery_topic ? `${row.delivery_topic} / ${row.delivery_offset ?? "-"}` : "-"),
      h("td", null, XCN.fmtTime(row.generated_at))))
    : [h("tr", { key: "empty" }, h("td", { colSpan: 7 }, h("div", { className: "empty compact" },
      h("strong", null, "조회 결과 없음"),
      h("span", null, "전송 상태 필터를 변경하거나 새로고침하세요."))))];

  const listPanel = h("section", { className: "panel kafka-list-panel" },
    h("div", { className: "panel-head" },
      h("div", { className: "ttl" },
        h("h2", null, "Kafka 결과 테이블"),
        h("p", null, "SIM_SIMILARITY_RESULT에 저장된 Kafka 전송 상태와 analysis_result offset"))),
    h("div", { className: "kafka-toolbar" },
      h("select", { className: "input", value: deliveryStatus, onChange: (e) => setDeliveryStatus(e.target.value) },
        h("option", { value: "" }, "전송상태 전체"),
            h("option", { value: "sent" }, "sent"),
            h("option", { value: "failed" }, "failed"),
            h("option", { value: "pending" }, "pending"),
            h("option", { value: "skipped" }, "skipped")),
      h("select", { className: "input", value: pageSize, onChange: (e) => setPageSize(Number(e.target.value)) },
        h("option", { value: 25 }, "25개"),
        h("option", { value: 50 }, "50개"),
        h("option", { value: 100 }, "100개")),
      h("button", { className: "btn btn-primary btn-sm", disabled: busy, onClick: applyFilter },
        h(Icon, { name: "refresh", size: 14 }), busy ? "조회 중" : "조회")),
    h("div", { className: "kafka-table-wrap" },
      h("table", { className: "kafka-table" },
        h("thead", null, h("tr", null,
          h("th", null, "MSGID"),
          h("th", null, "전송"),
          h("th", null, "위험도"),
          h("th", null, "최고점수"),
          h("th", null, "매칭"),
          h("th", null, "Topic / Offset"),
          h("th", null, "생성시각"))),
        h("tbody", null, tableBody))),
    h("div", { className: "pager" },
      h("button", { className: "btn btn-ghost btn-sm", disabled: busy || offset <= 0, onClick: () => load(Math.max(0, offset - pageSize)) }, "이전"),
      h("span", { className: "chip" }, `${Math.floor(offset / pageSize) + 1} 페이지 · ${rows.length}건`),
      h("button", { className: "btn btn-ghost btn-sm", disabled: busy || nextOffset === null, onClick: () => load(Number(nextOffset || 0)) }, "다음")));

  const resultCards = detailResults.length
    ? detailResults.map((item, idx) => h("div", { className: "kafka-result-card", key: idx },
      h("div", { className: "kafka-result-top" },
        h("b", null, item.target || "body"),
        h(RiskBadge, { level: item.risk_level }),
        h("span", { className: "mono" }, Number(item.max_score || 0).toFixed(3))),
      h("div", { className: "kafka-match-list" },
        (item.matches || []).length
          ? (item.matches || []).map((match, mIdx) => h("div", { className: "kafka-match-row", key: mIdx },
            h("span", { title: match.document_id }, match.document_title || match.document_id || "-"),
            h("b", { className: "mono" }, Number(match.score || 0).toFixed(3))))
          : h("div", { className: "empty compact" }, "매칭 없음"))))
    : [h("div", { className: "empty compact", key: "empty" }, h("strong", null, "결과 상세 없음"), h("span", null, "저장된 results 배열이 없습니다."))];

  const detailPanel = h("section", { className: "panel kafka-detail-panel" },
    detail ? h(React.Fragment, null,
      h("div", { className: "detail-head" },
        h("div", { className: "dh-main" },
          h("div", { className: "meta-chips" },
            h(DeliveryBadge, { status: detail.delivery_status }),
            h(RiskBadge, { level: detail.risk_level }),
            h("span", { className: "chip" }, "matches ", h("b", { className: "mono" }, XCN.num(detail.match_count || 0)))),
          h("h2", { className: "mono", title: detail.msgid }, detail.msgid || "-"),
          h("div", { className: "meta-chips" },
            h(Chip, null, "topic ", h("b", null, detail.delivery_topic || "-")),
            h(Chip, null, "partition ", h("b", { className: "mono" }, detail.delivery_partition ?? "-")),
            h(Chip, null, "offset ", h("b", { className: "mono" }, detail.delivery_offset ?? "-")),
            h(Chip, null, "generated ", h("b", null, XCN.fmtTime(detail.generated_at)))))),
      detail.delivery_error && h("div", { className: "kafka-error" }, h(Icon, { name: "alert", size: 14 }), detail.delivery_error),
      h("div", { className: "detail-body" },
        h("div", { className: "prov" },
          h(ProvCell, { icon: "shield", k: "감지 여부" }, detail.detected ? "detected" : "none"),
          h(ProvCell, { icon: "layers", k: "최고 유사도" }, Number(detail.max_score || 0).toFixed(6)),
          h(ProvCell, { icon: "clock", k: "전송 갱신" }, XCN.fmtTime(detail.delivery_updated_at)),
          h(ProvCell, { icon: "database", k: "결과 타입" }, detail.type || "-")),
        h("div", { className: "section-label", style: { marginBottom: 10 } }, "결과 상세"),
        resultCards,
        h("div", { className: "kafka-json-head" },
          h("div", { className: "section-label" }, "전송 JSON"),
          h("button", {
            className: "btn btn-ghost btn-sm",
            type: "button",
            onClick: async () => {
              try {
                await navigator.clipboard.writeText(detailJson);
                toast && toast("전송 JSON을 복사했습니다.");
              } catch (error) {
                toast && toast("복사 실패 · " + error.message);
              }
            }
          }, h(Icon, { name: "download", size: 14 }), "복사")),
        h("pre", { className: "kafka-json-view" }, detailJson)))
      : h("div", { className: "empty" }, h("strong", null, "선택된 결과 없음"), h("span", null, "좌측 테이블에서 Kafka 결과를 선택하세요.")));

  return h("div", { className: "view kafka-view" },
    h("div", { className: "metric-grid kafka-metrics" },
      h(Metric, { icon: "database", label: "현재 페이지", value: XCN.num(rows.length), sub: `offset ${offset}` }),
      h(Metric, { icon: "check", label: "전송 완료", value: XCN.num(sent), sub: "delivery_status = sent" }),
      h(Metric, { icon: "alert", label: "전송 실패", value: XCN.num(failed), sub: "delivery_status = failed" }),
      h(Metric, { icon: "shield", label: "고위험 결과", value: XCN.num(high), sub: `대기 ${XCN.num(pending)}건` })),
    h("div", { className: "kafka-grid" }, listPanel, detailPanel)
  );
}

function DeliveryBadge({ status }) {
  const value = status || "pending";
  const label = value === "sent" ? "전송완료" : value === "failed" ? "전송실패" : value === "skipped" ? "전송제외" : "대기";
  return h("span", { className: "delivery-badge delivery-" + value }, h("span", { className: "dot" }), label);
}

function RiskBadge({ level }) {
  const value = level || "none";
  const label = value === "high" ? "고위험" : value === "grey" ? "주의" : value === "low" ? "저위험" : "없음";
  return h("span", { className: "risk-badge risk-" + value }, label);
}

/* ============================== LOGS ============================== */
function Logs({ toast, dataVersion }) {
  const [sel, setSel] = React.useState("");
  const [svc, setSvc] = React.useState("");
  const [userId, setUserId] = React.useState("");
  const [sourceType, setSourceType] = React.useState("");
  const [highRiskOnly, setHighRiskOnly] = React.useState(false);
  const [offset, setOffset] = React.useState(0);
  const [nextOffset, setNextOffset] = React.useState(null);
  const [pageSize, setPageSize] = React.useState(50);
  const [chunks, setChunks] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const list = XCN.logs;
  const log = XCN.logs.find((l) => l.log_id === sel);
  const selectedRiskMatch = log ? XCN.highRiskMatchForLog(log.log_id) : null;
  const mail = log ? mailInfo(log, chunks) : {};

  React.useEffect(() => {
    if (!sel && XCN.logs[0]) setSel(XCN.logs[0].log_id);
  }, [dataVersion, sel]);

  React.useEffect(() => {
    if (!sel) {
      setChunks([]);
      return;
    }
    XCN.fetchLogChunks(sel).then(setChunks).catch((error) => toast("로그 청크 조회 실패 · " + error.message));
  }, [sel, dataVersion]);

  const searchLogs = async (targetOffset = 0) => {
    setBusy(true);
    try {
      const result = highRiskOnly
        ? await XCN.loadHighRiskLogs({ sourceType, svc, userId, limit: pageSize, offset: targetOffset })
        : await XCN.loadLogs({ sourceType, svc, userId, limit: pageSize, offset: targetOffset, order: "desc" });
      setOffset(Number(targetOffset || 0));
      setNextOffset(result.next_offset || null);
      setSel("");
      if (result.data && result.data[0]) setSel(result.data[0].log_id);
      toast((highRiskOnly ? "고위험 로그 조회 완료 · " : "로그 조회 완료 · ") + (result.data || []).length + "건");
    } catch (error) {
      toast("로그 조회 실패 · " + error.message);
    } finally {
      setBusy(false);
    }
  };
  const runOnEnter = (event) => {
    if (event.key === "Enter") searchLogs(0);
  };

  return h("div", { className: "view split" },
    h("section", { className: "panel", style: { overflow: "hidden" } },
        h("div", { className: "list-toolbar" },
        h("div", { className: "panel-head", style: { padding: 0, border: 0 } }, h("div", { className: "ttl" },
          h("h2", null, "적재 로그"), h("p", null, "EMS_MESSAGE_202605 · 본문/첨부 임베딩"))),
        h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } },
          h("select", { className: "input", style: { height: 34 }, value: sourceType, onChange: (e) => setSourceType(e.target.value) },
            h("option", { value: "" }, "전체 대상"), h("option", { value: "body" }, "본문"), h("option", { value: "attachment" }, "첨부")),
          h("select", { className: "input", style: { height: 34 }, value: highRiskOnly ? "high" : "all", onChange: (e) => { setHighRiskOnly(e.target.value === "high"); setOffset(0); } },
            h("option", { value: "all" }, "전체 로그"),
            h("option", { value: "high" }, "고위험만")),
          h("input", { className: "input", style: { height: 34 }, placeholder: "svc 필터", value: svc, onChange: (e) => setSvc(e.target.value), onKeyDown: runOnEnter }),
          h("input", { className: "input", style: { height: 34 }, placeholder: "user_id 필터", value: userId, onChange: (e) => setUserId(e.target.value), onKeyDown: runOnEnter }),
          h("select", { className: "input", style: { height: 34 }, value: pageSize, onChange: (e) => { setPageSize(Number(e.target.value)); setOffset(0); } },
            h("option", { value: 25 }, "25개"),
            h("option", { value: 50 }, "50개"),
            h("option", { value: 100 }, "100개")),
          h("button", { className: "btn btn-primary btn-sm", disabled: busy, onClick: () => searchLogs(0) }, busy ? "조회 중" : "조회"))),
      h("div", { className: "list-scroll" },
        list.map((l) => {
          const riskMatch = XCN.highRiskMatchForLog(l.log_id);
          return h("button", { key: l.log_id, className: "row-item" + (l.log_id === sel ? " active" : ""), onClick: () => setSel(l.log_id) },
            h("div", { className: "ri-top" },
              h("span", { className: "ri-title", title: l.log_id }, h(TitleKind, { kind: "로깅ID" }), XCN.displayLogId(l.log_id)),
              h("span", { style: { display: "flex", gap: 6, alignItems: "center" } },
                riskMatch && h("span", { className: "chip", style: { fontSize: 10, color: "var(--risk-high)", borderColor: "color-mix(in srgb, var(--risk-high) 45%, transparent)" } },
                  "고위험 매칭 ", Math.round(Number(riskMatch.score || 0) * 100), "%"),
                h("span", { className: "chip", style: { fontSize: 10 } }, l.metadata.svc))),
            h("div", { className: "ri-meta" },
              h("span", { className: "log-id-label", title: logDisplayName({ metadata: l.metadata }, l) }, XCN.logTitleKind(l.metadata), " ", logDisplayName({ metadata: l.metadata }, l)),
              " · ", l.metadata.user_id || "-", " · chunks ", l.chunk_count),
            riskMatch && h("div", { className: "ri-meta", style: { color: "var(--risk-high)", fontWeight: 700 } },
              "등록문서 유사: ", riskMatch.doc_title || riskMatch.document_id || "-", " · ", Number(riskMatch.score || 0).toFixed(3)),
            h("div", { className: "ri-preview" }, l.sample_text || "-"));
        })),
      h("div", { className: "pager" },
        h("button", { className: "btn btn-ghost btn-sm", disabled: busy || offset <= 0, onClick: () => searchLogs(Math.max(0, offset - pageSize)) }, "이전"),
        h("span", { className: "chip" }, `${Math.floor(offset / pageSize) + 1} 페이지 · 최신순`),
        h("button", { className: "btn btn-ghost btn-sm", disabled: busy || !nextOffset, onClick: () => searchLogs(Number(nextOffset)) }, "다음"))),

    log ? h("section", { className: "panel", style: { overflow: "hidden" } },
      h("div", { className: "detail-head" },
        h("div", { className: "dh-main" },
          h("div", { style: { display: "flex", gap: 8, alignItems: "center" } },
            h("span", { className: "chip" }, "indexed log"),
            selectedRiskMatch && h("span", { className: "chip", style: { color: "var(--risk-high)", borderColor: "color-mix(in srgb, var(--risk-high) 45%, transparent)" } },
              "고위험 매칭 · ", Number(selectedRiskMatch.score || 0).toFixed(3)),
            log.metadata.direction === "out" && h("span", { className: "chip", style: { color: "var(--risk-high)" } }, "외부 발신")),
          h("h2", null, h(TitleKind, { kind: "로깅ID" }), h("span", { title: log.log_id }, XCN.displayLogId(log.log_id))),
          h("div", { className: "meta-chips" },
            h(Chip, null, "첨부파일ID ", h("b", { title: log.metadata.attach_id || "-" }, log.metadata.attach_id || "-")),
            h(Chip, null, "user ", h("b", null, log.metadata.user_id)),
            h(Chip, null, log.metadata.svc),
            h(Chip, null, log.metadata.channel || "-"),
            h(Chip, null, XCN.fmtTime(log.metadata.ctime))))),
      h("div", { className: "detail-body" },
        selectedRiskMatch && h("div", { className: "doc-content-card", style: { borderColor: "color-mix(in srgb, var(--risk-high) 40%, var(--line))" } },
          h("div", { className: "section-label", style: { marginBottom: 10, color: "var(--risk-high)" } },
            h(Icon, { name: "alert", size: 13 }), "등록문서 고위험 매칭"),
          h("div", { className: "prov" },
            h(ProvCell, { icon: "doc", k: "유사 등록문서" }, selectedRiskMatch.doc_title || selectedRiskMatch.document_id || "-"),
            h(ProvCell, { icon: "shield", k: "보안등급" }, selectedRiskMatch.doc_security || "-"),
            h(ProvCell, { icon: "layers", k: "유사도 / 청크" }, `${Number(selectedRiskMatch.score || 0).toFixed(3)} · ${selectedRiskMatch.matched_chunks || 1}개`),
            h(ProvCell, { icon: "database", k: "문서ID" }, selectedRiskMatch.document_id || "-"))),
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "로그 상세 정보"),
          h("div", { className: "prov" },
            h(ProvCell, { icon: "logs", k: "로깅ID" }, h("span", { title: log.log_id }, XCN.displayLogId(log.log_id))),
            h(ProvCell, { icon: "user", k: "사용자" }, `${log.metadata.user_name || "-"} · ${log.metadata.user_id || "-"}${log.metadata.user_email ? " · " + log.metadata.user_email : ""}`),
            h(ProvCell, { icon: "channel", k: "서비스 / 채널" }, `${log.metadata.svc || "-"} · ${log.metadata.channel || "-"}`),
            h(ProvCell, { icon: "file", k: "데이터 유형" }, `${log.metadata.source_type === "attachment" ? "첨부" : "본문"} · ${logDirectionLabel(log.metadata)}`),
            h(ProvCell, { icon: "layers", k: "청크 / 상태" }, `${log.chunk_count || 0}개 · ${log.status || "-"}`),
            h(ProvCell, { icon: "clock", k: "발생 시각" }, XCN.fmtTime(log.metadata.ctime)),
            h(ProvCell, { icon: "database", k: "원본 파일" }, log.metadata.fileName || log.metadata.file_name || "-"))),
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "메일 송수신 정보"),
          h("div", { className: "prov" },
            h(ProvCell, { icon: "user", k: "발신자" }, mail.from || "-"),
            h(ProvCell, { icon: "user", k: "수신자" }, mail.to || "-"),
            h(ProvCell, { icon: "channel", k: "참조 / 숨은참조" }, `${mail.cc || "-"} · ${mail.bcc || "-"}`),
            h(ProvCell, { icon: "file", k: "메일 제목" }, mail.subject || "-"))),
        h("div", { className: "prov" },
          h(ProvCell, { icon: "flow", k: "트래픽 경로" }, h("span", null, log.metadata.src_ip || "-", " → ", log.metadata.host || log.metadata.dst_ip || "-", log.metadata.dst_port ? ":" + log.metadata.dst_port : "")),
          h(ProvCell, { icon: "globe", k: "목적지" }, `${log.metadata.host || "-"} · ${log.metadata.dst_ip || "-"}${log.metadata.dst_port ? ":" + log.metadata.dst_port : ""}`),
          h(ProvCell, { icon: "file", k: "첨부파일" }, log.metadata.attach_name || log.metadata.attachment_name || log.metadata.file_name || "-"),
          h(ProvCell, { icon: "layers", k: "첨부 정보" }, `${log.metadata.attach_ext || "-"} · ${formatBytes(log.metadata.attach_size || log.metadata.file_size)}`)),
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "로그 청크", h("span", { className: "count" }, chunks.length)),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 10 } },
            (chunks.length ? chunks : [{ chunk_id: "sample", text: log.sample_text || "" }]).map((chunk, i) => h("div", { className: "chunk", key: chunk.chunk_id || i },
              h("div", { className: "chunk-head" }, h("span", { className: "cid" }, chunk.chunk_id || "ch-" + (i + 1)), h("span", { className: "cmeta" }, (chunk.text || "").length + "자")),
              h("div", { className: "chunk-text" }, chunk.text || "")))))
      )
    ) : null
  );
}

Object.assign(window, { Dashboard, SecurityInsights, Documents, Search, Logs, KafkaResults });
