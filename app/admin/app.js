/* app.jsx — shell, navigation, theme + tweaks, toasts */

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "#0e6f7b",
  "density": "regular",
  "fontSize": 14,
  "riskColor": true
}/*EDITMODE-END*/;

const ACCENTS = {
  "#0e6f7b": { ink: "#0a525c", b2: "#128795", on: "#ffffff", dark: "#2bb4c2", darkInk: "#5fd0db", darkB2: "#34c6d4" }, // teal
  "#1f5fae": { ink: "#174a86", b2: "#2a72c4", on: "#ffffff", dark: "#5b9be8", darkInk: "#8fbdf2", darkB2: "#6ea8ec" }, // blue
  "#6a4bd0": { ink: "#523aa6", b2: "#7d5fe0", on: "#ffffff", dark: "#9d83ec", darkInk: "#bda7f3", darkB2: "#a98ef0" }, // violet
  "#1f7a4d": { ink: "#175c3a", b2: "#2a9160", on: "#ffffff", dark: "#46bd84", darkInk: "#79d4a9", darkB2: "#56c690" }, // forest
};

const NAV = [
  { id: "dashboard", label: "현황", icon: "dashboard", badge: "riskLogs" },
  { id: "documents", label: "문서 관리", icon: "doc", badge: null },
  { id: "search", label: "유사도 검색", icon: "search", badge: null },
  { id: "logs", label: "로그 확인", icon: "logs", badge: null },
  { id: "insights", label: "AI 인사이트 이력", icon: "spark", badge: null },
  { id: "operations", label: "운영 상태", icon: "cpu", badge: null },
];
const TITLES = {
  dashboard: ["Operations Overview", "현황"],
  insights: ["AI Security Insight History", "AI 인사이트 이력"],
  documents: ["Document Catalog", "문서 관리"],
  search: ["Similarity Search", "유사도 검색"],
  logs: ["Indexed Logs", "로그 확인"],
  operations: ["Runtime Operations", "운영 상태"],
};

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = React.useState("dashboard");
  const [match, setMatch] = React.useState(null);
  const [toasts, setToasts] = React.useState([]);
  const [version, setVersion] = React.useState(0);
  const [loading, setLoading] = React.useState(true);

  const toast = React.useCallback((msg) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((ts) => [...ts, { id, msg }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 3200);
  }, []);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      await XCN.loadInitial();
      setVersion((v) => v + 1);
    } catch (error) {
      XCN.lastError = error.message;
      toast("데이터 로딩 실패 · " + error.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { refresh(); }, [refresh]);

  // apply theme + accent + density + fontsize to <html>
  React.useEffect(() => {
    const el = document.documentElement;
    el.dataset.theme = t.theme;
    el.dataset.density = t.density;
    el.style.setProperty("--fs", t.fontSize + "px");
    const a = ACCENTS[t.accent] || ACCENTS["#0e6f7b"];
    if (t.theme === "dark") {
      el.style.setProperty("--brand", a.dark);
      el.style.setProperty("--brand-ink", a.darkInk);
      el.style.setProperty("--brand-2", a.darkB2);
    } else {
      el.style.setProperty("--brand", t.accent);
      el.style.setProperty("--brand-ink", a.ink);
      el.style.setProperty("--brand-2", a.b2);
      el.style.setProperty("--on-brand", a.on);
    }
  }, [t.theme, t.accent, t.density, t.fontSize]);

  const ViewComp = { dashboard: Dashboard, insights: SecurityInsights, documents: Documents, search: Search, logs: Logs, operations: Operations }[view];
  const [eyebrow, title] = TITLES[view];
  const navBadge = (badge) => {
    if (badge === "riskLogs") {
      const ids = new Set((XCN.recentMatches || []).map((m) => XCN.displayLogId(m.log_id)).filter(Boolean));
      return ids.size ? XCN.num(ids.size) : null;
    }
    return badge;
  };

  return h("div", { className: "app" },
    /* sidebar */
    h("aside", { className: "sidebar" },
      h("div", { className: "brand" },
        h("div", { className: "brand-mark" }, h(Icon, { name: "shieldCheck", size: 22 })),
        h("div", { className: "brand-name" }, h("b", null, "XCN Similarity"), h("span", null, "내부정보 유출 추적"))),
      h("nav", { className: "nav" },
        NAV.map((n) => {
          const badge = navBadge(n.badge);
          return h("button", { key: n.id, className: "nav-item" + (view === n.id ? " active" : ""), onClick: () => setView(n.id) },
            h(Icon, { name: n.icon, size: 18 }), n.label,
            badge && h("span", { className: "nav-badge", title: n.id === "dashboard" ? "최근 고위험 확인 대상 로그" : "" }, badge));
        }))),

    /* main */
    h("div", { className: "main" },
      h("header", { className: "topbar" },
        h("div", { className: "crumbs" },
          h("div", { className: "eyebrow" }, eyebrow),
          h("h1", null, title)),
        h("button", { className: "icon-btn", onClick: () => toast("알림 3건 · 신규 고위험 매칭"), "aria-label": "알림" }, h(Icon, { name: "bell", size: 18 })),
        h("button", { className: "icon-btn", onClick: () => setTweak("theme", t.theme === "dark" ? "light" : "dark"), "aria-label": "테마" },
          h(Icon, { name: t.theme === "dark" ? "sun" : "moon", size: 18 })),
        h("button", { className: "icon-btn", onClick: () => refresh().then(() => toast("최신 상태로 새로고침했습니다.")), "aria-label": "새로고침" }, h(Icon, { name: "refresh", size: 18 }))),
      h("main", { className: "content" },
        loading ? h("div", { className: "empty" }, h("strong", null, "데이터 로딩 중"), h("span", null, "실제 API에서 현황을 불러오고 있습니다."))
          : h(ViewComp, { onMatch: setMatch, toast, refresh, dataVersion: version }))),

    /* evidence drawer */
    match && h(EvidenceDrawer, { match, onClose: () => setMatch(null), toast }),

    /* toasts */
    h("div", { className: "toast-wrap" },
      toasts.map((x) => h("div", { className: "toast", key: x.id },
        h(Icon, { name: "check", size: 16 }), x.msg))),

    /* tweaks */
    h(TweaksPanel, null,
      h(TweakSection, { label: "테마 · Theme" }),
      h(TweakRadio, { label: "모드", value: t.theme, options: ["light", "dark"], onChange: (v) => setTweak("theme", v) }),
      h(TweakColor, { label: "강조색", value: t.accent, options: Object.keys(ACCENTS), onChange: (v) => setTweak("accent", v) }),
      h(TweakSection, { label: "레이아웃 · Layout" }),
      h(TweakRadio, { label: "밀도", value: t.density, options: ["compact", "regular", "comfy"], onChange: (v) => setTweak("density", v) }),
      h(TweakSlider, { label: "기본 글자 크기", value: t.fontSize, min: 12, max: 17, step: 1, unit: "px", onChange: (v) => setTweak("fontSize", v) })
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
