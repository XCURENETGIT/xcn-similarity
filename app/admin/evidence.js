/* evidence.jsx — match evidence drawer (the hero view) */

function Gauge({ score }) {
  const r = XCN.riskOf(score);
  const pct = Math.round(score * 100);
  const col = r.key === "hi" ? "var(--risk-high)" : r.key === "md" ? "var(--risk-med)" : "var(--risk-low)";
  const ring = `conic-gradient(${col} ${pct * 3.6}deg, var(--line) 0)`;
  const hole = "radial-gradient(circle at center, transparent 0 25px, #000 26px)";
  return h("div", { className: "gauge" },
    h("div", { style: {
      position: "absolute", inset: 0, borderRadius: "50%", background: ring,
      WebkitMask: hole, mask: hole,
    } }),
    h("div", { className: "gv mono", style: { color: col } }, pct),
    h("div", { className: "gl" }, "RISK")
  );
}

function EvidenceDrawer({ match, onClose, toast }) {
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, []);

  if (!match) return null;
  const log = XCN.logs.find((l) => l.log_id === match.log_id) || { metadata: {} };
  const m = { ...(match.metadata || {}), ...(log.metadata || {}) };
  const r = XCN.riskOf(match.score);
  const isDocumentHit = match.target_type === "document";
  const rawScore = Number(match.raw_score ?? match.score ?? 0);
  const hasCoverage = match.coverage_score !== null && match.coverage_score !== undefined;
  const coverageScore = Number(match.coverage_score ?? 0);
  const doc = XCN.documents.find((item) => item.document_id === match.document_id) || {};
  const docTextHidden = !!(doc && doc.metadata && doc.metadata.file_retained === false);
  const docTextMissing = !String(match.doc_text || "").trim();
  const logKind = XCN.logTitleKind(m);

  return h(React.Fragment, null,
    h("div", { className: "drawer-scrim", onClick: onClose }),
    h("aside", { className: "drawer", role: "dialog", "aria-label": "매칭 근거" },
      h("div", { className: "drawer-head" },
        h("div", { style: { flex: 1, minWidth: 0 } },
          h("div", { className: "dh-eyebrow" }, "매칭 근거 · MATCH EVIDENCE"),
          h("h2", null, "등록 문서 ↔ 로깅 데이터 유사 구간")
        ),
        h("button", { className: "btn btn-soft btn-sm", onClick: () => toast && toast("감사 로그에 기록되었습니다 · 상세 조회") },
          h(Icon, { name: "check", size: 15 }), "정탐 확인"),
        h("button", { className: "icon-btn", onClick: onClose, "aria-label": "닫기" }, h(Icon, { name: "close", size: 18 }))
      ),
      h("div", { className: "drawer-body" },

        /* verdict */
        h("div", { className: "verdict " + r.key },
          h(Gauge, { score: match.score }),
          h("div", { className: "v-main" },
            h("b", null, r.key === "hi" ? "고위험 — 내부정보 유출 의심" : r.key === "md" ? "주의 — 추가 확인 권장" : "낮음 — 단순 유사"),
            h("p", null, isDocumentHit
              ? `검색 질의와 등록 문서 「${match.doc_title}」가 ${(match.score*100).toFixed(1)}% 유사합니다.`
              : hasCoverage
                ? `등록 문서 「${match.doc_title}」와 로깅 데이터의 대표 유사도는 ${(match.score*100).toFixed(1)}%입니다. AI 유사도는 ${(rawScore*100).toFixed(1)}%, 핵심어 일치는 ${(coverageScore*100).toFixed(1)}%입니다.`
                : `등록 문서 「${match.doc_title}」와 로깅 데이터의 최고 청크 벡터 유사도는 ${(rawScore*100).toFixed(1)}%입니다.`)
          ),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" } },
            h(SecPill, { level: match.doc_security }),
            m.direction === "out" && h("span", { className: "chip", style: { color: "var(--risk-high)" } }, "외부 발신")
          )
        ),

        /* shared terms */
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "공통 핵심 어구",
            h("span", { className: "count" }, match.terms.length)),
          match.terms.length
            ? h("div", { className: "terms" },
                match.terms.map((t, i) => h("span", { className: "term-chip", key: i }, t)))
            : h("div", { className: "empty mini" },
                h("strong", null, "표시할 공통 핵심 어구가 없습니다."),
                h("span", null, docTextMissing
                  ? (docTextHidden ? "등록 문서 원문이 보관되지 않아 공통어구 비교는 제외하고 벡터 유사도만 표시합니다." : "문서 또는 로그 본문을 아직 불러오지 못해 공통어구를 표시할 수 없습니다.")
                  : "유사도는 전체 문맥 임베딩 기준이며, 단순 인사말·직함·서명은 근거 어구에서 제외합니다."))
        ),

        /* provenance */
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 10 } }, "로그 출처 · PROVENANCE"),
          h("div", { className: "prov" },
            h(ProvCell, { icon: "user", k: "발신 사용자" }, m.user_id || "-"),
            h(ProvCell, { icon: "channel", k: "채널 / 서비스" }, `${m.channel || "-"} · ${m.svc || "-"}`),
            h(ProvCell, { icon: "flow", k: "트래픽 경로" },
              h("span", null, m.src_ip || "-", " ",
                h(Icon, { name: "arrowRight", size: 12, style: { verticalAlign: "-1px", color: "var(--ink-3)" } }),
                " ", m.dst_ip || "-")),
            h(ProvCell, { icon: "globe", k: "목적지 호스트" }, m.host || "-"),
            h(ProvCell, { icon: "clock", k: "발생 시각" }, m.ctime ? XCN.fmtTime(m.ctime) : "-"),
            h(ProvCell, { icon: "file", k: "데이터 유형" }, `${m.source_type === "attachment" ? "첨부" : "본문"}${m.ext ? " · " + m.ext : ""}`),
            h(ProvCell, { icon: "layers", k: "매칭 청크" }, `${match.matched_chunks || 1}개${match.matched_chunk_ids && match.matched_chunk_ids.length ? " · " + match.matched_chunk_ids.join(", ") : ""}`)
          )
        ),

        /* score breakdown */
        h("div", null,
          h("div", { className: "section-label", style: { marginBottom: 12 } }, "유사도 점수 분해"),
          h("div", { className: "breakdown" },
            match.breakdown.map(([k, v], i) =>
              h("div", { className: "bd-row", key: i },
                h("div", { className: "bk" }, k),
                h(ScoreBar, { score: v }),
                h("div", { className: "bv", style: { color: i === 0 ? "var(--brand-ink)" : "var(--ink)" } }, v.toFixed(3)))))
        ),

        /* side-by-side */
        h("div", { className: "compare" },
          h("div", { className: "compare-col doc" },
            h("div", { className: "cc-head" },
              h("div", { className: "cc-kind" }, "▦ 등록 문서"),
              h("div", { className: "cc-title" }, h("span", { className: "title-kind" }, "등록문서"), match.doc_title),
              h("div", { className: "cc-id" }, `${match.document_id || "-"} · ${match.doc_chunk_id || "-"}`)),
            h("div", { className: "cc-text" }, docTextMissing ? (docTextHidden ? "등록 문서 원문 미보관: 벡터는 저장되어 유사도 탐지는 가능하지만 원문 비교는 표시할 수 없습니다." : "문서 본문을 아직 불러오지 못했습니다. 목록을 새로고침한 뒤 다시 확인하세요.") : highlight(match.doc_text, match.terms))
          ),
          h("div", { className: "compare-col log" },
            h("div", { className: "cc-head" },
              h("div", { className: "cc-kind" }, "◇ 로깅 데이터"),
              h("div", { className: "cc-title" }, h("span", { className: "title-kind" }, logKind), match.log_title || m.title || m.subject || m.mail_subject || m.msg_subject || m.email_subject || m.attach_name || m.fileName || ((m.channel || m.svc || "로그") + " 본문")),
              h("div", { className: "cc-id", title: match.log_id || match.target_id || "-" }, `${XCN.displayLogId(match.log_id || match.target_id) || "-"} · ${match.log_chunk_id || "-"}`)),
            h("div", { className: "cc-text" }, highlight(match.log_text, match.terms))
          )
        ),

        /* actions */
        h("div", { style: { display: "flex", gap: 10, flexWrap: "wrap", paddingTop: 4 } },
          h("button", { className: "btn btn-ghost", onClick: () => toast && toast("오탐으로 표시 — 모델 피드백 큐 적재") },
            "오탐 처리")
        )
      )
    )
  );
}

Object.assign(window, { EvidenceDrawer });
