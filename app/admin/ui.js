/* ui.jsx — icon set + shared primitives. Exports to window. */
const { createElement: h } = React;

/* ---- minimal stroke icon set ---- */
const PATHS = {
  dashboard: "M4 13h6V4H4v9zm0 7h6v-5H4v5zm10 0h6V11h-6v9zm0-16v5h6V4h-6z",
  doc: "M14 3v5h5 M7 3h8l5 5v13H7z M9 13h6 M9 17h6",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14z M21 21l-4-4",
  logs: "M4 6h16 M4 12h16 M4 18h10 M3 6h.01 M3 12h.01 M3 18h.01",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  shieldCheck: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
  flow: "M5 12h12 M13 6l6 6-6 6",
  arrowRight: "M5 12h14 M13 6l6 6-6 6",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8z M5 20a7 7 0 0114 0",
  globe: "M12 21a9 9 0 100-18 9 9 0 000 18z M3.5 9h17 M3.5 15h17 M12 3c2.5 2.5 2.5 15.5 0 18 M12 3c-2.5 2.5-2.5 15.5 0 18",
  channel: "M4 4h16v12H7l-3 3z",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18z M12 7v5l3 2",
  ip: "M4 7h16v10H4z M8 7v10 M12 11h4 M12 14h4",
  refresh: "M20 11A8 8 0 105 6 M20 4v4h-4 M4 13a8 8 0 0015 5 M4 20v-4h4",
  plus: "M12 5v14 M5 12h14",
  trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13",
  close: "M6 6l12 12 M18 6L6 18",
  upload: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  edit: "M4 20h4l10.5-10.5a2.1 2.1 0 00-3-3L5 17v3z M13.5 6.5l3 3",
  save: "M5 4h12l2 2v14H5z M8 4v6h8V4 M8 20v-6h8v6",
  file: "M14 3v5h5 M7 3h8l5 5v13H7z",
  filter: "M3 5h18 M6 12h12 M10 19h4",
  bell: "M18 9a6 6 0 10-12 0c0 7-3 8-3 8h18s-3-1-3-8 M13.5 21a2 2 0 01-3 0",
  chevron: "M9 6l6 6-6 6",
  spark: "M12 3l2.2 6.3L21 11l-5 4 1.8 6L12 17l-5.8 4L8 15l-5-4 6.8-1.7z",
  link: "M9 15l6-6 M10 7l1-1a4 4 0 016 6l-1 1 M14 17l-1 1a4 4 0 01-6-6l1-1",
  layers: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
  database: "M12 7c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3z M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5 M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  cpu: "M9 3v2 M15 3v2 M9 19v2 M15 19v2 M3 9h2 M3 15h2 M19 9h2 M19 15h2 M6 6h12v12H6z M9 9h6v6H9z",
  alert: "M12 9v4 M12 17h.01 M10.3 4.3L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 4.3a2 2 0 00-3.4 0z",
  check: "M5 12l5 5 9-11",
  download: "M12 4v12 M7 11l5 5 5-5 M4 20h16",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10z M12 1v3 M12 20v3 M4.2 4.2l2 2 M17.8 17.8l2 2 M1 12h3 M20 12h3 M4.2 19.8l2-2 M17.8 6.2l2-2",
  moon: "M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z",
};

function Icon({ name, size = 18, style, strokeWidth = 1.9, fill }) {
  return h("svg", {
    width: size, height: size, viewBox: "0 0 24 24",
    fill: fill || "none", stroke: "currentColor",
    strokeWidth, strokeLinecap: "round", strokeLinejoin: "round", style,
  }, (PATHS[name] || "").split(" M").map((seg, i) =>
    h("path", { key: i, d: (i === 0 ? seg : "M" + seg) })
  ));
}

/* ---- badges / pills ---- */
function StatusBadge({ status }) {
  const labelMap = { INDEXED: "인덱싱 완료", PROCESSING: "처리 중", PENDING: "대기", FAILED: "실패", SKIPPED: "건너뜀", DELETED: "삭제됨" };
  return h("span", { className: "badge " + XCN.statusClass(status) },
    h("span", { className: "dot" }), labelMap[status] || status);
}

function SecPill({ level }) {
  if (!level) return null;
  return h("span", { className: "sec " + XCN.secClass(level) },
    h(Icon, { name: "shield", size: 12 }), level);
}

function ScorePill({ score }) {
  const r = XCN.riskOf(score);
  const value = Number(score || 0);
  return h("span", { className: "score-pill risk-" + r.tone, title: `${r.label} · ${r.range} · ${r.desc}` },
    h("b", null, value.toFixed(3)),
    h("small", { className: "score-label" }, r.label));
}

function ScoreBar({ score }) {
  const r = XCN.riskOf(score);
  const value = Math.max(0, Math.min(1, Number(score || 0)));
  return h("div", { className: "score-bar " + r.key },
    h("i", { style: { width: Math.round(value * 100) + "%" } }));
}

function ScoreLegend() {
  return h("div", { className: "score-legend", "aria-label": "유사도 점수 기준" },
    (XCN.scoreRiskLevels || []).map((item) =>
      h("div", { className: "score-legend-item risk-" + item.tone, key: item.key, title: `${item.label} · ${item.range} · ${item.desc}` },
        h("span", { className: "legend-dot" }),
        h("b", null, item.label),
        h("span", { className: "mono" }, item.range),
        h("small", null, item.desc))));
}

/* highlight shared terms inside a text block */
function highlight(text, terms) {
  if (!terms || !terms.length) return text;
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).sort((a, b) => b.length - a.length);
  const re = new RegExp("(" + escaped.join("|") + ")", "g");
  const parts = String(text).split(re);
  return parts.map((p, i) =>
    terms.some((t) => t === p) ? h("mark", { key: i }, p) : h(React.Fragment, { key: i }, p)
  );
}

function Chip({ children }) { return h("span", { className: "chip" }, children); }

function ProvCell({ icon, k, children }) {
  return h("div", { className: "prov-cell" },
    h("div", { className: "pk" }, h(Icon, { name: icon, size: 13 }), k),
    h("div", { className: "pv" }, children));
}

Object.assign(window, { h, Icon, StatusBadge, SecPill, ScorePill, ScoreBar, ScoreLegend, highlight, Chip, ProvCell });
