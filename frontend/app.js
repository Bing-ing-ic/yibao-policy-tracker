/* 前台暂停开放闸门：到关闭时点后不再加载政策数据、不绑定后台事件（抓取流水线不受影响） */
const SITE_CLOSED = window.__SITE_CLOSED__ === true || document.documentElement.dataset.siteClosed === "1";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const state = { view: "dashboard", level: "", column: "", tag: "", keyword: "", sort: "date", page: 1, size: 12, total: 0, newIds: [], newBatchDate: "", onlyFav: false, onlyNew: false, validity: "" };
const expState = { level: "", kind: "", org_type: "", keyword: "", page: 1, size: 12, total: 0 };
const LEVEL_NAME = { national: "国家医保局", provincial: "云南省医保局", municipal: "玉溪市医保局" };

/* ---------------- 本地偏好：收藏 / 对比（纯前端，无外部依赖） ---------------- */
function readIdList(key) {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(v) ? v.map(Number).filter((n) => Number.isFinite(n)) : [];
  } catch (_) { return []; }
}
function saveIdList(key, arr) {
  try { localStorage.setItem(key, JSON.stringify(arr)); } catch (_) {}
}
const FAVS = new Set(readIdList("yb_favs"));
const COMPARE = [];
const COMPARE_MAX = 3;

/* 统一浅色主题（aurora） */
document.body.dataset.theme = "aurora";
function toggleFav(id) {
  id = +id;
  if (FAVS.has(id)) FAVS.delete(id); else FAVS.add(id);
  saveIdList("yb_favs", Array.from(FAVS));
  syncFavUI();
  return FAVS.has(id);
}
function syncFavUI() {
  $$(".fav-btn").forEach((b) => {
    const on = FAVS.has(+b.dataset.id);
    b.classList.toggle("on", on);
    b.textContent = on ? "★" : "☆";
    b.title = on ? "取消收藏" : "收藏";
  });
  const ff = $("#favFilter");
  if (ff) { ff.classList.toggle("on", !!state.onlyFav); ff.classList.toggle("active", !!state.onlyFav); }
}

// 常用主题快捷标签（与库内主题标签一致，按基层关注度排序）
const QUICK_TAGS = [
  "参保缴费", "异地就医", "长期护理保险", "个人账户共济", "定点机构管理",
  "基金监管/智能审核", "门诊统筹/慢特病", "医疗救助/困难群众", "基层医疗卫生", "药品目录/用药保障",
];

// 与后端 analyzer.LOW_RELEVANCE 保持一致：非医保事务检索时剔除
const LOW_RELEVANCE = ["遴选公务员", "面试", "大赛", "获奖名单", "公示名单", "网站升级", "平台升级维护", "小程序登录", "答疑", "筹备公告"];

/* ---------------- 静态数据缓存 ---------------- */
const DB = { stats: null, facets: null, expStats: null, policies: [], exposures: [], details: {} };
let _detailsPromise = null;

async function loadJSON(path, fallback) {
  try {
    let ctrl = null, timer = null;
    if (typeof AbortController !== "undefined") {
      ctrl = new AbortController();
      timer = setTimeout(function () { ctrl.abort(); }, 15000);
    }
    const r = await fetch(path, ctrl ? { signal: ctrl.signal } : {});
    if (timer) clearTimeout(timer);
    if (!r.ok) throw new Error(path + " HTTP " + r.status);
    return await r.json();
  } catch (e) {
    console.warn("静态数据加载失败：" + path, e);
    return fallback;
  }
}

async function initData() {
  // 五个静态文件并行下载，互不阻塞；单个失败由 loadJSON 兜底为空值
  const [stats, facets, expStats, policies, exposures] = await Promise.all([
    loadJSON("data/stats.json", {}),
    loadJSON("data/facets.json", { by_tag: [] }),
    loadJSON("data/exposure_stats.json", { org_type: {} }),
    loadJSON("data/policies.json", []),
    loadJSON("data/exposures.json", []),
  ]);
  DB.stats = stats;
  DB.facets = facets;
  DB.expStats = expStats;
  DB.policies = policies;
  DB.exposures = exposures;
}

/* 政策详情包（正文/落地动作/标准/关键数据）按需懒加载，仅在打开抽屉时取一次并缓存 */
function loadDetails() {
  if (_detailsPromise) return _detailsPromise;
  _detailsPromise = loadJSON("data/policy_details.json", {}).then(function (d) {
    DB.details = d && typeof d === "object" ? d : {};
    return DB.details;
  });
  return _detailsPromise;
}
function getDetail(id) {
  return DB.details[String(id)] || {};
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 2600);
}

/* 点击筛选 / 分页后定位到对应结果模块，避免结果停在视口外 */
function focusPolicyList() {
  const el = $("#policyList");
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
function focusExposureList() {
  const el = $("#exposureList");
  if (el) el.scrollTop = 0;
}

/* ---------------- 模块视图切换 ---------------- */
function switchView(view) {
  state.view = view;
  $$("#moduleTabs .mtab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  ["dashboard", "policy", "ask", "exposure"].forEach((v) => {
    const el = $("#" + v + "View");
    if (el) el.classList.toggle("hidden", v !== view);
  });
  if (view === "exposure") loadExposures();
  if (view === "dashboard") renderDashboard();
  requestAnimationFrame(() => {
    const el = $("#" + view + "View");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

/* KPI 卡片点击：跳转到关联模块（政策列表 / 曝光台 / 按相关度排序） */
function gotoKpi(target) {
  if (target === "exposure") { switchView("exposure"); return; }
  switchView("policy");
  state.page = 1;
  state.sort = target === "policy-relevance" ? "relevance" : "date";
  syncSortChips();
  loadList();
  focusPolicyList();
}

/* ---------------- 政策问答（本地规则检索，复刻后端回退口径） ---------------- */
const ASK_QUICK = ["参保缴费怎么缴", "异地就医怎么备案", "集采药品如何执行", "门诊统筹政策", "定点机构管理要求", "基金监管重点", "生育保险待遇", "个人账户家庭共济"];

function renderAskQuick() {
  $("#askQuick").innerHTML = ASK_QUICK.map((q) => `<button class="chip ask-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  $$("#askQuick .ask-chip").forEach((c) =>
    c.addEventListener("click", () => { $("#askInput").value = c.dataset.q; askQuestion(); })
  );
}

function renderAskEmpty() {
  $("#askResult").innerHTML = `<div class="ask-empty">输入问题或点击上方常见问题，将基于已抓取的官方政策检索相关条目，并列出可溯源的政策依据。</div>`;
}

async function askQuestion() {
  const q = $("#askInput").value.trim();
  if (!q) { toast("请先输入要咨询的问题"); return; }
  const box = $("#askResult");
  const btn = $("#askBtn");
  btn.disabled = true;
  box.innerHTML = `<div class="ask-loading">正在检索相关政策并整理要点…</div>`;

  // 中文 2-gram + 英文/数字词作为检索项
  const grams = new Set();
  const segRe = /[\u4e00-\u9fa5]{2,}/g;
  let seg;
  while ((seg = segRe.exec(q))) {
    for (let i = 0; i < seg[0].length - 1; i++) grams.add(seg[0].slice(i, i + 2));
  }
  const words = (q.match(/[A-Za-z0-9]{2,}/g) || []);

  const scored = [];
  for (const r of DB.policies) {
    const title = r.title || "";
    if (LOW_RELEVANCE.some((k) => title.includes(k))) continue;
    if (!r.title) continue;
    const tags = (r.topic_tags || []).join(" ");
    const summary = r.ai_summary || "";
    const blob = `${title} ${tags} ${summary}`;
    let score = 0, titleHit = false, tagHit = false;
    for (const g of grams) {
      if (title.includes(g)) { score += 5; titleHit = true; }
      else if (tags.includes(g)) { score += 4; tagHit = true; }
      else if (summary.includes(g)) { score += 1; }
    }
    for (const w of words) {
      if (blob.toLowerCase().includes(w.toLowerCase())) {
        score += 3;
        if (title.toLowerCase().includes(w.toLowerCase())) titleHit = true;
      }
    }
    if (score > 0 && (titleHit || tagHit)) scored.push({ score, r });
  }
  scored.sort((a, b) => b.score - a.score || (b.r.relevance || 0) - (a.r.relevance || 0));

  let result;
  if (!scored.length || scored[0].score < 8) {
    result = { question: q, answer: "未检索到与该问题直接相关的医保政策，可换用医保关键词（如：参保缴费、异地就医、集采药品、门诊统筹、定点管理、基金监管、生育保险、个人账户）再试。", points: [], note: "当前无强相关政策。", llm: false, sources: [] };
  } else {
    const topRows = scored.slice(0, 6).map((x) => x.r);
    // 要点提炼存于详情包，按需加载后补齐问答要点
    await loadDetails();
    const sources = topRows.map((r) => ({
      id: r.id, level: r.level, title: r.title, source_name: r.source_name,
      column_name: r.column_name, publish_date: r.publish_date, relevance: r.relevance, url: r.url,
    }));
    const answer = topRows.slice(0, 3).map((r) => r.ai_summary || "").filter(Boolean).join("；").slice(0, 300);
    const points = [];
    for (const r of topRows) {
      // 兼容新旧快照：要点优先取详情包，回退列表包（旧快照字段仍在列表包）
      const kp = (getDetail(r.id).key_points || r.key_points || []);
      for (const k of kp.slice(0, 2)) {
        if (!points.includes(k)) points.push(k);
      }
    }
    result = { question: q, answer, points: points.slice(0, 4), note: "当前为规则检索结果（静态站点未接入大模型），详细解读以政策原文为准。", llm: false, sources };
  }

  btn.disabled = false;
  renderAskResult(result);
}

function renderAskResult(r) {
  const box = $("#askResult");
  const engine = $("#askEngineTag");
  engine.textContent = r.llm ? "大模型问答" : "规则检索";
  engine.className = "ai-type " + (r.llm ? "llm" : "");
  const points = (r.points || []).map((k) => `<li>${esc(k)}</li>`).join("");
  const sources = (r.sources || []).map((s) => `
    <div class="ask-source" data-id="${s.id}" role="button" tabindex="0">
      <span class="badge level-${s.level}">${LEVEL_NAME[s.level] || ""}</span>
      <span class="ask-source-title">${esc(s.title)}</span>
      <span class="ask-source-meta">${esc(s.publish_date || "")}${s.relevance ? ` · 相关度 ${esc(s.relevance)}` : ""}</span>
    </div>`).join("");
  box.innerHTML = `
    <div class="ask-bubble">
      <div class="ask-q">${esc(r.question)}</div>
      <div class="ask-a">${esc(r.answer)}</div>
      ${points ? `<ul class="ask-points">${points}</ul>` : ""}
      ${r.note ? `<div class="ask-note">${esc(r.note)}</div>` : ""}
    </div>
    ${sources ? `<div class="ask-sources"><h3>政策依据（点击查看原文与解读）</h3>${sources}</div>` : ""}
  `;
  $$("#askResult .ask-source").forEach((el) => {
    el.addEventListener("click", () => openDetail(+el.dataset.id));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(+el.dataset.id); }
    });
  });
}

/* ---------------- 统计 ---------------- */
function loadStats() {
  const s = DB.stats;
  $("#lastRun").textContent = s.last_run_at ? `数据更新：${s.last_run_at}` : "静态快照数据";
  $("#policyCount").textContent = s.total;

  const levelMeta = {
    national: { icon: "🏛", theme: "theme-nat" },
    provincial: { icon: "🌿", theme: "theme-prov" },
    municipal: { icon: "🏥", theme: "theme-muni" },
  };
  const boxes = [
    `<div class="stat theme-total" data-level="" role="button" tabindex="0" aria-label="查看全部政策">
      <div class="stat-icon">📊</div>
      <div class="stat-body"><div class="num">${s.total}</div><div class="name">政策总数</div></div>
      <div class="latest">${esc(s.latest ? s.latest.title : "—")}</div>
    </div>`,
  ];
  for (const lv of ["national", "provincial", "municipal"]) {
    const d = s.by_level[lv];
    const m = levelMeta[lv];
    boxes.push(`<div class="stat ${m.theme}" data-level="${lv}" role="button" tabindex="0" aria-label="筛选${d.name}">
      <div class="stat-icon">${m.icon}</div>
      <div class="stat-body"><div class="num">${d.count}</div><div class="name">${d.name}</div></div>
      <div class="latest">最新：${esc(d.latest || "—")}</div>
    </div>`);
  }
  $("#stats").innerHTML = boxes.join("");

  const setCount = (key, val) => {
    const el = $(`#levelChips [data-count="${key}"]`);
    if (el) el.textContent = val;
  };
  setCount("all", s.total);
  for (const lv of ["national", "provincial", "municipal"]) {
    setCount(lv, s.by_level[lv].count);
    const chip = $(`#levelChips [data-level="${lv}"]`);
    if (chip) chip.style.display = s.by_level[lv].count > 0 ? "" : "none";
  }

  $$("#stats .stat").forEach((card) => {
    card.addEventListener("click", () => setLevel(card.dataset.level));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setLevel(card.dataset.level); }
    });
  });
  syncLevelUI();
}

/* ---------------- 层级联动 ---------------- */
function setLevel(lv) {
  state.level = lv || "";
  state.column = "";
  state.tag = "";
  state.page = 1;
  renderActiveTag();
  syncQuickTags();
  refreshColumns();
  syncLevelUI();
  loadList();
  focusPolicyList();
}

function syncLevelUI() {
  $$("#levelChips .chip").forEach((c) => c.classList.toggle("active", c.dataset.level === state.level));
  $$("#stats .stat").forEach((card) => {
    const lv = card.dataset.level;
    const isTotal = lv === "";
    card.classList.toggle("active", !isTotal && lv === state.level);
    card.classList.toggle("dim", !isTotal && state.level && lv !== state.level);
  });
}

/* ---------------- 栏目（按真实条目数生成，空栏目不显示） ---------------- */
function loadFacets() {
  window._facets = DB.facets;
  refreshColumns();
  renderQuickTags();
}

function refreshColumns() {
  const facets = (window._facets && window._facets.by_column) || [];
  let rows = facets.filter((c) => c.count > 0 && c.key);
  if (state.level) {
    rows = rows.filter((c) => c.level === state.level);
  } else {
    const map = new Map();
    rows.forEach((c) => {
      if (map.has(c.name)) map.get(c.name).count += c.count;
      else map.set(c.name, { key: c.key, name: c.name, count: c.count });
    });
    rows = Array.from(map.values());
  }
  if (state.column && !rows.some((c) => c.key === state.column)) state.column = "";
  const wrap = $("#columnChips");
  wrap.innerHTML =
    `<button class="chip ${state.column === "" ? "active" : ""}" data-col=""><span class="chip-name">全部栏目</span></button>` +
    rows.map((c) => `<button class="chip ${state.column === c.key ? "active" : ""}" data-col="${esc(c.key)}"><span class="chip-name">${esc(c.name)}</span><span class="chip-count">${c.count}</span></button>`).join("");
  $$("#columnChips .chip").forEach((c) =>
    c.addEventListener("click", () => {
      state.column = c.dataset.col;
      state.page = 1;
      refreshColumns();
      loadList();
      focusPolicyList();
    })
  );
}

/* ---------------- 常用主题（按库内真实标签生成，空标签不显示） ---------------- */
function renderQuickTags() {
  const tags = ((window._facets && window._facets.by_tag) || []).filter((t) => t.count > 0);
  const fixed = QUICK_TAGS;
  const ordered = fixed.map((t) => tags.find((x) => x.tag === t)).filter(Boolean)
    .concat(tags.filter((x) => !fixed.includes(x.tag)).slice(0, 6));
  if (state.tag && !ordered.some((x) => x.tag === state.tag)) state.tag = "";
  const wrap = $("#quickTags");
  wrap.innerHTML = ordered.length
    ? ordered.map((t) => `<button class="chip ${state.tag === t.tag ? "active" : ""}" data-tag="${esc(t.tag)}"><span class="chip-name">${esc(t.tag)}</span><span class="chip-count">${t.count}</span></button>`).join("")
    : `<span class="chip none">暂无可用主题标签</span>`;
  $$("#quickTags .chip").forEach((c) =>
    c.addEventListener("click", () => {
      const t = c.dataset.tag;
      if (!t) return;
      state.tag = state.tag === t ? "" : t;
      state.page = 1;
      renderActiveTag();
      syncQuickTags();
      loadList();
      focusPolicyList();
    })
  );
}
function syncQuickTags() {
  $$("#quickTags .chip").forEach((c) => c.classList.toggle("active", c.dataset.tag === state.tag));
}

/* ---------------- 时效性筛选（基层最关心：政策是否现行有效） ---------------- */
const VALIDITY_ORDER = ["现行有效", "试行中", "征求意见", "已废止"];
function renderValidityChips() {
  const wrap = $("#validityChips");
  if (!wrap) return;
  const counts = {};
  (Array.isArray(DB.policies) ? DB.policies : []).forEach((p) => {
    const v = String(p.validity || "").trim();
    if (v) counts[v] = (counts[v] || 0) + 1;
  });
  const keys = VALIDITY_ORDER.filter((k) => counts[k]);
  Object.keys(counts).forEach((k) => { if (!keys.includes(k)) keys.push(k); });
  if (state.validity && state.validity !== "__none" && !counts[state.validity]) state.validity = "";
  const opts = [{ v: "", n: "全部" }]
    .concat(keys.map((k) => ({ v: k, n: k, c: counts[k] })))
    .concat([{ v: "__none", n: "未标注" }]);
  wrap.innerHTML = opts.map((o) =>
    `<button class="chip ${state.validity === o.v ? "active" : ""}" data-v="${esc(o.v)}"><span class="chip-name">${esc(o.n)}</span>${o.c != null ? `<span class="chip-count">${o.c}</span>` : ""}</button>`
  ).join("");
  $$("#validityChips .chip").forEach((c) =>
    c.addEventListener("click", () => {
      state.validity = c.dataset.v;
      state.page = 1;
      renderValidityChips();
      loadList();
      focusPolicyList();
    })
  );
}

/* ---------------- 本轮新增提示条：由 fetched_at 最新抓取批次驱动 ---------------- */
function computeNewBatch() {
  state.newIds = [];
  state.newBatchDate = "";
  const rows = Array.isArray(DB.policies) ? DB.policies : [];
  if (!rows.length) return;
  let latest = "";
  rows.forEach((r) => {
    const d = String(r.fetched_at || "").slice(0, 10);
    if (d > latest) latest = d;
  });
  if (!latest) return;
  const ids = rows.filter((r) => String(r.fetched_at || "").slice(0, 10) === latest).map((r) => r.id);
  // 首轮全量抓取时全部同批，不视作"新增"，避免提示条失真
  if (ids.length >= rows.length * 0.5) return;
  state.newBatchDate = latest;
  state.newIds = ids;
}
function renderNewBanner() {
  const b = $("#newBanner");
  if (!b) return;
  if (!state.newIds.length) { b.hidden = true; return; }
  b.hidden = false;
  b.classList.toggle("on", state.onlyNew);
  b.innerHTML = `<span class="nb-dot"></span><span class="nb-text">最近抓取批次（<b>${esc(state.newBatchDate)}</b>）新增 <b>${state.newIds.length}</b> 条政策${state.onlyNew ? " · 正在仅看新增" : "，点击查看"}</span><span class="nb-go">${state.onlyNew ? "退出新增视图 ✕" : "查看新增 →"}</span>`;
}
function bindNewBanner() {
  const b = $("#newBanner");
  if (!b) return;
  const go = () => {
    if (!state.newIds.length) return;
    state.onlyNew = !state.onlyNew;
    state.page = 1;
    renderNewBanner();
    loadList();
    focusPolicyList();
  };
  b.addEventListener("click", go);
  b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
}

/* ---------------- 排序标签 ---------------- */
function syncSortChips() {
  $$("#sortChips .chip").forEach((c) => c.classList.toggle("active", c.dataset.sort === state.sort));
}

/* ---------------- 结果计数条与可清除条件 ---------------- */
function columnName(key) {
  const f = (window._facets && window._facets.by_column) || [];
  const hit = f.find((c) => c.key === key);
  return hit ? hit.name : key;
}
function clearColumn() { state.column = ""; refreshColumns(); }
function renderResultBar() {
  const bar = $("#resultBar");
  if (!bar) return;
  const chips = [];
  if (state.onlyFav) chips.push({ label: "我的收藏", clear: () => { state.onlyFav = false; syncFavUI(); } });
  if (state.onlyNew) chips.push({ label: "本轮新增", clear: () => { state.onlyNew = false; renderNewBanner(); } });
  if (state.validity) chips.push({ label: state.validity === "__none" ? "未标注时效性" : `时效性：${state.validity}`, clear: () => { state.validity = ""; renderValidityChips(); } });
  if (state.level) chips.push({ label: LEVEL_NAME[state.level], clear: () => setLevel("") });
  if (state.column) chips.push({ label: columnName(state.column), clear: clearColumn });
  if (state.tag) chips.push({ label: state.tag, clear: () => { state.tag = ""; renderActiveTag(); syncQuickTags(); } });
  if (state.keyword) chips.push({ label: `关键词：${state.keyword}`, clear: () => { state.keyword = ""; $("#keyword").value = ""; } });
  const chipsHtml = chips
    .map((c, i) => `<button class="rb-chip" data-i="${i}">${esc(c.label)}<span class="rb-x">✕</span></button>`)
    .join("");
  bar.innerHTML = `<span class="rb-count">共 <b>${state.total}</b> 条政策</span>${chipsHtml}`;
  bar._clears = chips.map((c) => c.clear);
  Array.from(bar.querySelectorAll(".rb-chip")).forEach((b) =>
    b.addEventListener("click", () => {
      bar._clears[+b.dataset.i]();
      state.page = 1;
      loadList();
      focusPolicyList();
    })
  );
}

/* ---------------- 重置筛选 ---------------- */
function hasFilter() {
  return !!(state.level || state.column || state.tag || state.keyword || state.onlyFav || state.onlyNew || state.validity);
}
function resetFilters() {
  state.level = ""; state.column = ""; state.tag = ""; state.keyword = ""; state.sort = "date"; state.page = 1; state.onlyFav = false; state.onlyNew = false; state.validity = "";
  $("#keyword").value = "";
  syncFavUI();
  renderNewBanner();
  renderActiveTag();
  renderValidityChips();
  refreshColumns();
  syncLevelUI();
  syncQuickTags();
  syncSortChips();
  loadList();
  focusPolicyList();
}

/* ---------------- 主题标签回显 ---------------- */
function renderActiveTag() {
  const wrap = $("#activeTagWrap");
  if (!state.tag) { wrap.hidden = true; return; }
  wrap.hidden = false;
  $("#activeTag").textContent = state.tag;
}

/* ---------------- 曝光台 ---------------- */
function loadExposureStats() {
  const s = DB.expStats;
  window._expStats = s;
  $("#exposureCount").textContent = s.case_total + s.exit_total;
  $("#exposureStats").innerHTML =
    `<span>违规案例 <b>${s.case_total}</b>家</span>` +
    `<span>解除/中止协议 <b>${s.passive_exit}</b>家（被动）</span>` +
    `<span>主动退出 <b>${s.active_exit}</b>家</span>`;
  renderExpChips();
}

function expChip(value, name, count, active) {
  const cnt = count == null ? "" : `<span class="chip-count">${count}</span>`;
  return `<button class="chip ${active ? "active" : ""}" data-v="${esc(value)}"><span class="chip-name">${esc(name)}</span>${cnt}</button>`;
}

function bindExpChips(wrapId, stateKey) {
  $$(`#${wrapId} .chip`).forEach((c) =>
    c.addEventListener("click", () => {
      $$(`#${wrapId} .chip`).forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      expState[stateKey] = c.dataset.v;
      expState.page = 1;
      loadExposures();
      focusExposureList();
    })
  );
}

function renderExpChips() {
  const s = window._expStats || {};

  const kindOpts = [{ v: "", n: "全部" }];
  if (s.case_total > 0) kindOpts.push({ v: "case", n: "违规案例", c: s.case_total });
  if (s.exit_total > 0) kindOpts.push({ v: "exit", n: "退出协议", c: s.exit_total });
  $("#expKindChips").innerHTML = kindOpts.map((o) => expChip(o.v, o.n, o.c, expState.kind === o.v)).join("");
  bindExpChips("expKindChips", "kind");

  const lvOpts = [{ v: "", n: "全部层级" }];
  Object.entries(s.by_level || {}).forEach(([k, c]) => {
    if (c > 0) lvOpts.push({ v: k, n: LEVEL_NAME[k] || k, c });
  });
  $("#expLevelChips").innerHTML = lvOpts.map((o) => expChip(o.v, o.n, o.c, expState.level === o.v)).join("");
  bindExpChips("expLevelChips", "level");

  const otOpts = [{ v: "", n: "全部类型" }];
  Object.entries(s.org_type || {}).forEach(([k, c]) => {
    if (c > 0) otOpts.push({ v: k, n: k, c });
  });
  $("#expTypeChips").innerHTML = otOpts.map((o) => expChip(o.v, o.n, o.c, expState.org_type === o.v)).join("");
  bindExpChips("expTypeChips", "org_type");
}

function filterExposures() {
  let arr = DB.exposures.slice();
  if (expState.level) arr = arr.filter((e) => e.level === expState.level);
  if (expState.kind) arr = arr.filter((e) => e.kind === expState.kind);
  if (expState.org_type) arr = arr.filter((e) => e.org_type === expState.org_type);
  if (expState.keyword) {
    const k = expState.keyword.toLowerCase();
    arr = arr.filter((e) => [e.org_name, e.problem, e.penalty, e.title, e.summary].some((x) => (x || "").toLowerCase().includes(k)));
  }
  arr.sort((a, b) => (b.publish_date || "").localeCompare(a.publish_date || "") || b.id - a.id);
  return arr;
}

function loadExposures() {
  const filtered = filterExposures();
  expState.total = filtered.length;
  const pages = Math.max(1, Math.ceil(expState.total / expState.size));
  if (expState.page > pages) expState.page = pages;
  const start = (expState.page - 1) * expState.size;
  const items = filtered.slice(start, start + expState.size);

  if (!items.length) {
    $("#exposureList").innerHTML = '<div class="empty">暂无官方通报曝光记录。</div>';
    $("#expPager").innerHTML = "";
    return;
  }
  $("#exposureList").innerHTML = items.map((e) => {
    const exitBadge = e.exit_type === "主动"
      ? `<span class="exp-badge exit-active">主动·${esc(e.exit_status)}</span>`
      : e.exit_status === "未退出协议"
        ? `<span class="exp-badge noexit">未退出协议</span>`
        : `<span class="exp-badge exit-passive">${esc(e.exit_status)} · 被动</span>`;
    const expHit = expState.level || expState.kind || expState.org_type || expState.keyword;
    const levelBadge = `exp-badge level-${e.level}${expState.level === e.level ? " badge-active" : ""}`;
    const orgBadge = `exp-badge org${expState.org_type === e.org_type ? " badge-active" : ""}`;
    const kindBadge = `exp-badge org${expState.kind === e.kind ? " badge-active" : ""}`;
    const rows = [];
    if (e.problem) rows.push(`<div class="exp-row"><b>违规问题</b>${hiKw(e.problem, expState.keyword)}</div>`);
    if (e.penalty) rows.push(`<div class="exp-row"><b>处理结果</b>${hiKw(e.penalty, expState.keyword)}</div>`);
    if (e.amount) rows.push(`<div class="exp-row"><b>涉及金额</b>${hiKw(e.amount, expState.keyword)}</div>`);
    return `<div class="exp-card ${expHit ? "exp-hit" : ""}">
      <div class="exp-top">
        <div class="exp-org">${hiKw(e.org_name || "未列明机构", expState.keyword)}</div>
        ${exitBadge}
      </div>
      <div class="exp-badges">
        <span class="${levelBadge}">${LEVEL_NAME[e.level]}</span>
        <span class="${orgBadge}">${esc(e.org_type || "其他")}</span>
        <span class="${kindBadge}">${e.kind === "case" ? "违规案例" : "退出协议"}</span>
      </div>
      <div class="exp-meta">
        <span>通报日期：${esc(e.publish_date || "—")}</span>
        ${safeUrl(e.url) ? `<a class="exp-link" href="${safeUrl(e.url)}" target="_blank" rel="noopener">官方原文 ↗</a>` : ""}
      </div>
      ${rows.join("")}
    </div>`;
  }).join("");

  $("#expPager").innerHTML = expState.total > expState.size
    ? `<button class="btn ghost" id="expPrev" ${expState.page <= 1 ? "disabled" : ""}>上一页</button>
       <span class="pager-info">第 ${expState.page} / ${pages} 页 · 共 ${expState.total} 家</span>
       <button class="btn ghost" id="expNext" ${expState.page >= pages ? "disabled" : ""}>下一页</button>`
    : `<span class="pager-info">共 ${expState.total} 家</span>`;
  const prev = $("#expPrev"), next = $("#expNext");
  if (prev) prev.addEventListener("click", () => { expState.page--; loadExposures(); focusExposureList(); });
  if (next) next.addEventListener("click", () => { expState.page++; loadExposures(); focusExposureList(); });
}

/* ---------------- 政策列表（本地过滤 / 排序 / 分页） ---------------- */
function filterPolicies() {
  let arr = DB.policies.slice();
  if (state.level) arr = arr.filter((p) => p.level === state.level);
  if (state.column) arr = arr.filter((p) => p.column_key === state.column);
  if (state.tag) arr = arr.filter((p) => (p.topic_tags || []).includes(state.tag));
  if (state.onlyFav) arr = arr.filter((p) => FAVS.has(p.id));
  if (state.onlyNew) arr = arr.filter((p) => state.newIds.includes(p.id) || !!p.is_new);
  if (state.validity) {
    arr = arr.filter((p) => state.validity === "__none"
      ? !String(p.validity || "").trim()
      : String(p.validity || "").trim() === state.validity);
  }
  if (state.keyword) {
    const k = state.keyword.toLowerCase();
    arr = arr.filter((p) =>
      (p.title || "").toLowerCase().includes(k) ||
      (p.summary || "").toLowerCase().includes(k) ||
      (p.doc_no || "").toLowerCase().includes(k) ||
      (p.ai_summary || "").toLowerCase().includes(k)
    );
  }
  if (state.sort === "relevance") arr.sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
  else if (state.sort === "effective") arr.sort((a, b) =>
    String(b.effective_date || "").localeCompare(String(a.effective_date || "")) ||
    String(b.publish_date || "").localeCompare(String(a.publish_date || "")) || b.id - a.id);
  else arr.sort((a, b) => (b.publish_date || "").localeCompare(a.publish_date || "") || b.id - a.id);
  return arr;
}

function loadList() {
  const filtered = filterPolicies();
  state.total = filtered.length;
  const pages = Math.max(1, Math.ceil(state.total / state.size));
  if (state.page > pages) state.page = pages;
  const start = (state.page - 1) * state.size;
  const items = filtered.slice(start, start + state.size);

  $("#pageInfo").textContent = `第 ${state.page} / ${pages} 页 · 共 ${state.total} 条`;
  $("#prevPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= pages;
  renderResultBar();

  if (!items.length) {
    const resetBtn = hasFilter()
      ? '<div style="margin-top:14px"><button class="btn ghost reset-btn" id="emptyReset">清除筛选条件</button></div>'
      : "";
    $("#policyList").innerHTML = `<div class="empty">暂无政策条目${hasFilter() ? "，可调整筛选条件" : "。"}${resetBtn}</div>`;
    const er = $("#emptyReset");
    if (er) er.addEventListener("click", resetFilters);
    return;
  }
  syncSortChips();
  const hit = hasFilter();
  $("#policyList").innerHTML = items.map((p) => {
    const tags = (p.topic_tags || []).slice(0, 4)
      .map((t) => `<span class="badge tag-click${state.tag === t ? " badge-active" : ""}" data-tag="${esc(t)}">${esc(t)}</span>`).join("");
    const rel = p.relevance != null ? p.relevance : 0;
    const relCls = rel >= 60 ? "high" : "";
    const isNew = state.newIds.includes(p.id) || !!p.is_new;
    const aiBadge = `<span class="ai-type ${p.ai_type || "rule"}">${p.ai_type === "llm" ? "大模型解读" : "规则解读"}</span>`;
    const levelBadge = `badge level-${p.level}${state.level === p.level ? " badge-active" : ""}`;
    const columnBadge = `badge${state.column === p.column_key ? " badge-active" : ""}`;
    return `<div class="card lv-${esc(p.level)} ${hit ? "card-hit" : ""}${isNew ? " is-new" : ""}" data-id="${esc(p.id)}" role="button" tabindex="0" aria-label="查看政策详情：${esc(p.title || "")}">
      <div class="card-top">
        <div class="card-title">${isNew ? '<span class="badge new-badge"><i class="nb-dot"></i>新增</span>' : ""}${hi(p.title)}</div>
        <div class="card-side">
          <button class="fav-btn${FAVS.has(p.id) ? " on" : ""}" data-id="${p.id}" title="${FAVS.has(p.id) ? "取消收藏" : "收藏"}">${FAVS.has(p.id) ? "★" : "☆"}</button>
          <button class="compare-btn${COMPARE.includes(p.id) ? " on" : ""}" data-id="${p.id}" title="${COMPARE.includes(p.id) ? "移出对比" : "加入对比"}">${COMPARE.includes(p.id) ? "✓" : "⇄"}</button>
          ${aiBadge}
          <div class="rel ${relCls}"><span class="rel-bar"><i style="width:${rel}%"></i></span><span>${rel}分</span></div>
        </div>
      </div>
      <div class="badges">
        <span class="${levelBadge}">${LEVEL_NAME[p.level]}</span>
        ${p.level === "municipal" && p.source_name && p.source_name !== "玉溪市医疗保障局" ? `<span class="badge src">${esc(p.source_name)}</span>` : ""}
        <span class="${columnBadge}">${esc(p.column_name || "")}</span>
        ${p.doc_no ? `<span class="badge doc">${hi(p.doc_no)}</span>` : ""}
        ${p.validity ? `<span class="badge validity-badge v-${validityClass(p.validity)}" title="时效性：${esc(p.validity)}">${esc(p.validity)}</span>` : ""}
      </div>
      <div class="card-meta">
        <span>发布日期：${esc(p.publish_date || "—")}</span>
        ${p.effective_date ? `<span>生效日期：${esc(p.effective_date)}${effStatus(p.effective_date)}</span>` : ""}
      </div>
      ${p.ai_summary ? `<div class="card-summary">${hi(p.ai_summary)}</div>` : ""}
      <div class="badges" style="margin-top:8px">${tags}</div>
    </div>`;
  }).join("");

  $$("#policyList .card").forEach((el) => {
    el.addEventListener("click", () => openDetail(el.dataset.id));
    el.addEventListener("keydown", (e) => {
      if (e.target !== el) return; // 子元素（收藏/对比按钮）回车不触发详情
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(el.dataset.id); }
    });
  });
  $$("#policyList .tag-click").forEach((el) =>
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      state.tag = el.dataset.tag; state.page = 1;
      renderActiveTag();
      syncQuickTags();
      loadList();
      focusPolicyList();
    })
  );
  $$("#policyList .fav-btn").forEach((b) =>
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const on = toggleFav(+b.dataset.id);
      toast(on ? "已加入收藏" : "已取消收藏");
      if (state.onlyFav) loadList();
    })
  );
  $$("#policyList .compare-btn").forEach((b) =>
    b.addEventListener("click", (ev) => { ev.stopPropagation(); toggleCompare(+b.dataset.id); })
  );
  syncCompareUI();
}

/* ---------------- 详情 ---------------- */
async function openDetail(id) {
  const raw = DB.policies.find((x) => x.id === +id);
  if (!raw) { toast("未找到该政策详情"); return; }
  await loadDetails();
  const p = Object.assign({}, raw, getDetail(id));
  const tags = (p.topic_tags || []).map((t) => `<span class="badge">${esc(t)}</span>`).join("");
  const apps = (p.applicable_to || []).map((t) => `<span class="badge">${esc(t)}</span>`).join("");
  const rel = Number(p.relevance || 0);
  const relCls = rel >= 70 ? "rel-high" : rel >= 40 ? "rel-mid" : "rel-low";
  const relTxt = rel >= 70 ? "高度相关" : rel >= 40 ? "一般相关" : "参考性";
  const points = (p.key_points || []).map((k, i) =>
    `<li class="pt"><span class="pt-no">${i + 1}</span><span class="pt-txt">${esc(k)}</span></li>`
  ).join("") || `<li class="pt"><span class="pt-txt">—</span></li>`;
  const elements = (p.core_elements || []).map((e) =>
    `<div class="kv elem"><b>${esc(e.label || "要素")}</b><span>${esc(e.value || "")}</span></div>`
  ).join("");
  const actions = (p.actions || []).map((k) =>
    `<li class="pt act"><span class="pt-no">✓</span><span class="pt-txt">${esc(k)}</span></li>`
  ).join("");
  const risks = (p.risks || []).map((k) => `<li class="risk-item">${esc(k)}</li>`).join("");
  const standards = (p.standards || []).map((k) => `<li class="std-item">${esc(k)}</li>`).join("");
  const IMP_META = {
    "高": ["高影响", "imp-high"], "中": ["中影响", "imp-mid"],
    "低": ["低影响", "imp-low"], "未涉及": ["未涉及", "imp-none"],
  };
  const impLevel = IMP_META[p.impact_level] ? p.impact_level : "未涉及";
  const [impTxt, impCls] = IMP_META[impLevel];
  const keyData = (p.key_data || []).map((k) => `<span class="badge kd">${esc(k)}</span>`).join("");
  const matrixRows = (p.impact_matrix || []).map((m) => {
    const lv = IMP_META[m.level] ? m.level : "未涉及";
    const [mtxt, mcls] = IMP_META[lv];
    const w = lv === "高" ? 100 : lv === "中" ? 60 : lv === "低" ? 30 : 0;
    const note = lv === "未涉及" ? "该维度未提及" : esc(m.note || "");
    return `<div class="mx-row ${mcls}">
      <span class="mx-dim">${esc(m.dimension)}</span>
      <span class="mx-tag ${mcls}">${mtxt}</span>
      <span class="mx-bar"><i style="width:${w}%"></i></span>
      <span class="mx-note ${lv === "未涉及" ? "muted" : ""}">${note}</span>
    </div>`;
  }).join("");
  $("#drawer").innerHTML = `
    <button class="drawer-close" id="drawerClose" aria-label="关闭">✕</button>
    <button class="fav-btn detail-fav${FAVS.has(p.id) ? " on" : ""}" data-id="${p.id}" title="${FAVS.has(p.id) ? "取消收藏" : "收藏"}">${FAVS.has(p.id) ? "★" : "☆"}</button>
    <div class="badges">
      <span class="badge level-${p.level}">${LEVEL_NAME[p.level]}</span>
      ${p.level === "municipal" && p.source_name && p.source_name !== "玉溪市医疗保障局" ? `<span class="badge src">${esc(p.source_name)}</span>` : ""}
      <span class="badge">${esc(p.column_name || "")}</span>
      ${p.policy_type ? `<span class="badge tag-type">${esc(p.policy_type)}</span>` : ""}
      ${p.validity ? `<span class="badge tag-validity validity-badge v-${validityClass(p.validity)}">${esc(p.validity)}</span>` : ""}
      <span class="badge ${impCls}">${impTxt}</span>
      <span class="ai-type ${p.ai_type}">${p.ai_type === "llm" ? "大模型解读" : "规则解读"}</span>
    </div>
    <h2 style="margin-top:12px">${esc(p.title)}</h2>
    <div class="d-meta">
      ${p.doc_no ? `<span>文号：${esc(p.doc_no)}</span>` : `<span class="muted">文号：留空待核验</span>`}
      <span>发布：${esc(p.publish_date || "—")}</span>
      ${p.effective_date ? `<span>生效：${esc(p.effective_date)}${effStatus(p.effective_date)}</span>` : ""}
    </div>
    ${keyData ? `<div class="kd-row"><span class="kd-label">关键数据</span>${keyData}</div>` : ""}
    ${p.parent_basis ? `<div class="basis-panel"><span class="basis-label">上位依据</span><span>${esc(p.parent_basis)}</span></div>` : ""}
    ${p.city_impact ? `<div class="city-panel"><span class="city-label">对市级 / 经办层面的影响</span><span>${esc(p.city_impact)}</span></div>` : ""}

    <div class="ai-panel ${p.ai_type}">
      <div class="ai-panel-head">
        <span class="ai-panel-icon">🤖</span>
        <div class="ai-panel-title">
          <h3>AI 解读摘要</h3>
          <span class="ai-type ${p.ai_type}">${p.ai_type === "llm" ? "大模型解读" : "规则解读"}</span>
        </div>
      </div>
      <div class="ai-summary">${esc(p.ai_summary || "暂无解读")}</div>
      <div class="rel-meter-row">
        <div class="rel-meter"><div class="rel-fill ${relCls}" style="width:${rel}%"></div></div>
        <span class="rel-score">${rel} 分</span>
        <span class="rel-level ${relCls}">${relTxt}</span>
      </div>
      <div class="kv"><b>解读建议</b><span>${esc(p.relevance_note || "—")}</span></div>
    </div>

    ${elements ? `
    <div class="panel">
      <div class="panel-head"><span class="panel-icon">🧩</span><h3>核心要素</h3></div>
      <div class="elem-grid">${elements}</div>
    </div>` : ""}

    <div class="panel">
      <div class="panel-head"><span class="panel-icon">🏷</span><h3>主题标签</h3></div>
      <div class="badges">${tags || "—"}</div>
      <div class="panel-head sub"><h3>适用对象</h3></div>
      <div class="badges">${apps || "—"}</div>
    </div>

    <div class="panel">
      <div class="panel-head"><span class="panel-icon">✦</span><h3>要点提炼</h3></div>
      <ul class="pt-list">${points}</ul>
    </div>

    ${matrixRows ? `
    <div class="panel matrix-panel">
      <div class="panel-head"><span class="panel-icon">🗂</span><h3>对乡镇卫生院的影响</h3><span class="mx-overall ${impCls}">整体影响：${impTxt}</span></div>
      <div class="mx-list">${matrixRows}</div>
    </div>` : ""}

    ${actions ? `
    <div class="panel">
      <div class="panel-head"><span class="panel-icon">✅</span><h3>基层落地动作</h3></div>
      <ul class="pt-list">${actions}</ul>
    </div>` : ""}

    ${standards ? `
    <div class="panel">
      <div class="panel-head"><span class="panel-icon">💰</span><h3>待遇 / 支付标准</h3></div>
      <ul class="std-list">${standards}</ul>
    </div>` : ""}

    ${risks ? `
    <div class="panel risk-panel">
      <div class="panel-head"><span class="panel-icon">⚠️</span><h3>合规风险红线</h3></div>
      <ul class="risk-list">${risks}</ul>
    </div>` : ""}

    <div class="panel original-panel">
      <div class="panel-head"><span class="panel-icon">📄</span><h3>政策原文</h3></div>
      <div class="original">${esc(p.content || "（正文未抓取到，见官方链接）")}</div>
      ${safeUrl(p.url) ? `<a class="link-official" href="${safeUrl(p.url)}" target="_blank" rel="noopener">前往官方原文 ↗</a>` : `<span class="muted">（暂无官方原文链接）</span>`}
    </div>`;
  $("#drawer").classList.remove("hidden");
  $("#drawerMask").classList.remove("hidden");
  $("#drawerClose").addEventListener("click", closeDrawer);
  const df = $("#drawer .detail-fav");
  if (df) df.addEventListener("click", () => {
    toggleFav(+df.dataset.id);
    toast(FAVS.has(p.id) ? "已加入收藏" : "已取消收藏");
  });
}
function closeDrawer() {
  $("#drawer").classList.add("hidden");
  $("#drawerMask").classList.add("hidden");
}

/* ---------------- 工具 ---------------- */
function esc(s) {
  return String(s != null ? s : "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* 仅放行 http/https 链接，避免抓取数据里的 javascript: 等协议注入到 href */
function safeUrl(u) {
  const s = String(u != null ? u : "").trim();
  return /^https?:\/\//i.test(s) ? esc(s) : "";
}

/* 时效性语义色：已废止/征求意见需醒目，现行有效为常态 */
function validityClass(v) {
  if (v === "已废止") return "void";
  if (v === "征求意见") return "draft";
  if (v === "试行中") return "trial";
  return "valid";
}

/* 生效状态：已生效 / 即将生效（无效日期返回空串，防御脏数据） */
function effStatus(dateStr) {
  const d = String(dateStr || "").trim();
  if (!/^\d{4}-\d{1,2}-\d{1,2}$/.test(d)) return "";
  const ts = new Date(d.replace(/-/g, "/")).getTime();
  if (!Number.isFinite(ts)) return "";
  return ts > Date.now()
    ? '<span class="eff-tag pending">即将生效</span>'
    : '<span class="eff-tag live">已生效</span>';
}

/* 关键词命中高亮：先按原文切片再逐段转义，避免拆散 &amp; 等 HTML 实体 */
function hiKw(text, kw) {
  const src = String(text != null ? text : "");
  kw = (kw || "").trim();
  if (!kw) return esc(src);
  let re;
  try { re = new RegExp(kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"); }
  catch (_) { return esc(src); }
  let out = "", last = 0, m;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index)) + '<mark class="kw-hl">' + esc(m[0]) + "</mark>";
    last = m.index + m[0].length;
    if (m[0].length === 0) re.lastIndex++;
  }
  return out + esc(src.slice(last));
}
function hi(text) { return hiKw(text, state.keyword); }

/* ================= 态势总览：前端聚合 / 纯 SVG 图表 / 时间轴 / 星云 ================= */
function chartEmpty(msg) { return '<div class="chart-empty">' + esc(msg || "暂无数据") + '</div>'; }

function last12Months() {
  const now = new Date();
  const months = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const key = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
    months.push({ key: key, count: 0, label: (d.getMonth() + 1) + "月" });
  }
  const map = new Map(months.map((m) => [m.key, m]));
  (Array.isArray(DB.policies) ? DB.policies : []).forEach((p) => {
    const k = (p.publish_date || "").slice(0, 7);
    if (map.has(k)) map.get(k).count++;
  });
  return months;
}
function relevanceBuckets() {
  const b = [{ label: "低 0-39", n: 0 }, { label: "中 40-69", n: 0 }, { label: "高 70-100", n: 0 }];
  (Array.isArray(DB.policies) ? DB.policies : []).forEach((p) => {
    const r = Number(p.relevance) || 0;
    if (r < 40) b[0].n++; else if (r < 70) b[1].n++; else b[2].n++;
  });
  return b;
}
function countUp(el) {
  if (!el) return;
  const raw = el.dataset.target != null ? el.dataset.target : String(el.textContent || "0");
  const target = Number(String(raw).replace(/[^\d.-]/g, "")) || 0;
  const fmt = (v) => Math.round(v).toLocaleString("en-US");
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(target); return; }
  const dur = 850, start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(target * e);
    if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
  };
  requestAnimationFrame(step);
}

function renderChartLevel() {
  const el = $("#chartLevel");
  if (!el) return;
  const stats = DB.stats || {}, lv = stats.by_level || {};
  const data = ["national", "provincial", "municipal"].map((k) => ({ key: k, name: LEVEL_NAME[k] || k, count: Number((lv[k] || {}).count) || 0 }));
  const total = Number(stats.total) || data.reduce((s, d) => s + d.count, 0);
  if (!total) { el.innerHTML = chartEmpty("暂无层级分布数据"); return; }
  const C = 2 * Math.PI * 70, gap = 26; // 配合圆角端点留出约 6px 视觉间隙
  let acc = 0;
  const segs = data.map((d, i) => {
    const frac = d.count / total, len = Math.max(0, frac * C - gap);
    const s = '<circle class="donut-seg-' + (i + 1) + '" cx="160" cy="100" r="70" fill="none" stroke-width="20" stroke-linecap="round" stroke-dasharray="' + len.toFixed(2) + ' ' + (C - len).toFixed(2) + '" stroke-dashoffset="' + (-acc).toFixed(2) + '"><title>' + esc(d.name) + '：' + d.count + ' 条（' + (frac * 100).toFixed(1) + '%）</title></circle>';
    acc += frac * C;
    return s;
  }).join("");
  const legend = data.map((d, i) => '<span class="lg-item"><i class="seg-l' + (i + 1) + '" style="background:var(--chart-l' + (i + 1) + ')"></i>' + esc(d.name) + ' <b>' + d.count + '</b></span>').join("");
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 320 200" role="img" aria-label="三级层级分布环形图">'
    + '<circle class="donut-ring" cx="160" cy="100" r="86" />'
    + '<circle class="donut-ring" cx="160" cy="100" r="53" />'
    + '<circle class="donut-track" cx="160" cy="100" r="70" fill="none" stroke-width="20" />'
    + '<g transform="rotate(-90 160 100)">' + segs + '</g>'
    + '<text class="val-text" x="160" y="98" text-anchor="middle" style="font-size:34px;letter-spacing:-.5px">' + total + '</text>'
    + '<text class="axis-text" x="160" y="121" text-anchor="middle" style="font-size:11px;letter-spacing:1px">政策总数</text>'
    + '</svg><div class="chart-legend">' + legend + '</div>';
}

/* Catmull-Rom 转三次贝塞尔：折线平滑但不过度过冲 */
function smoothPath(pts) {
  if (!pts.length) return "";
  if (pts.length === 1) return "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
  let d = "M" + pts[0][0].toFixed(1) + " " + pts[0][1].toFixed(1);
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const t = 0.16;
    const c1x = p1[0] + (p2[0] - p0[0]) * t, c1y = p1[1] + (p2[1] - p0[1]) * t;
    const c2x = p2[0] - (p3[0] - p1[0]) * t, c2y = p2[1] - (p3[1] - p1[1]) * t;
    d += " C" + c1x.toFixed(1) + " " + c1y.toFixed(1) + " " + c2x.toFixed(1) + " " + c2y.toFixed(1) + " " + p2[0].toFixed(1) + " " + p2[1].toFixed(1);
  }
  return d;
}

function renderChartTrend() {
  const el = $("#chartTrend");
  if (!el) return;
  const months = last12Months();
  if (!months.some((m) => m.count > 0)) { el.innerHTML = chartEmpty("近 12 月暂无发布数据"); return; }
  const max = Math.max.apply(null, [1].concat(months.map((m) => m.count)));
  const W = 720, H = 210, L = 40, R = 16, T = 18, B = 30;
  const pw = W - L - R, ph = H - T - B;
  const x = (i) => L + (months.length <= 1 ? pw / 2 : i * pw / (months.length - 1));
  const y = (v) => T + ph - (v / max) * ph;
  const pts = months.map((m, i) => [x(i), y(m.count)]);
  const line = smoothPath(pts);
  const area = line + " L " + x(months.length - 1).toFixed(1) + " " + (T + ph) + " L " + x(0).toFixed(1) + " " + (T + ph) + " Z";
  const dots = pts.map((p, i) => '<circle class="dot-trend" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3"><title>' + months[i].key + '：' + months[i].count + ' 条</title></circle>').join("");
  const gridLines = [0, 0.5, 1].map((f) => '<line class="grid-h" x1="' + L + '" y1="' + (T + ph * f).toFixed(1) + '" x2="' + (W - R) + '" y2="' + (T + ph * f).toFixed(1) + '" />').join("");
  const labels = months.map((m, i) => (i % 2 === 0 || i === months.length - 1) ? '<text class="axis-text" x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle">' + m.label + '</text>' : "").join("");
  let peak = 0;
  months.forEach((m, i) => { if (m.count > (months[peak] ? months[peak].count : 0)) peak = i; });
  const peakMark = '<circle class="peak-dot" cx="' + x(peak).toFixed(1) + '" cy="' + y(months[peak].count).toFixed(1) + '" r="5"><title>峰值：' + months[peak].key + ' · ' + months[peak].count + ' 条</title></circle>';
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="近12月发布趋势">'
    + '<defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1"><stop class="grad-stop-top" offset="0%"/><stop class="grad-stop-bottom" offset="100%"/></linearGradient></defs>'
    + gridLines
    + '<path class="area-trend" d="' + area + '" />'
    + '<path class="line-trend-glow" d="' + line + '" />'
    + '<path class="line-trend" d="' + line + '" />'
    + dots + peakMark + labels
    + '<text class="val-text" x="' + L + '" y="' + (T + 4) + '" style="font-size:12px;letter-spacing:.5px">峰值 ' + max + ' 条</text>'
    + '</svg>';
}

function renderChartTopics() {
  const el = $("#chartTopics");
  if (!el) return;
  const tags = (((DB.facets || {}).by_tag) || []).slice().filter((t) => Number(t.count) > 0).sort((a, b) => Number(b.count) - Number(a.count)).slice(0, 10);
  if (!tags.length) { el.innerHTML = chartEmpty("暂无主题标签数据"); return; }
  const max = Math.max.apply(null, [1].concat(tags.map((t) => Number(t.count))));
  const W = 360, rowH = 22, L = 104, R = 34, T = 6, barW = W - L - R;
  const H = T + tags.length * rowH + 6;
  const rows = tags.map((t, i) => {
    const c = Number(t.count) || 0, w = Math.max(2, (c / max) * barW);
    const name = String(t.tag || ""), short = name.length > 9 ? name.slice(0, 9) + "…" : name;
    const yy = T + i * rowH + 4;
    return '<text class="axis-text" x="' + (L - 6) + '" y="' + (yy + 10) + '" text-anchor="end">' + esc(short) + '</text>'
      + '<rect class="bar-track" x="' + L + '" y="' + yy + '" width="' + barW + '" height="13" rx="6.5" />'
      + '<rect class="bar-topic" x="' + L + '" y="' + yy + '" width="' + w.toFixed(1) + '" height="13" rx="6.5" style="fill:url(#topicBarFill)"><title>' + esc(name) + '：' + c + '</title></rect>'
      + '<text class="val-text" x="' + (L + w + 5).toFixed(1) + '" y="' + (yy + 10) + '">' + c + '</text>';
  }).join("");
  const defs = '<defs><linearGradient id="topicBarFill" x1="0" y1="0" x2="1" y2="0"><stop class="gstop-topic-a" offset="0%"/><stop class="gstop-topic-b" offset="100%"/></linearGradient></defs>';
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="主题热度TOP10">' + defs + rows + '</svg>';
}

function renderChartAi() {
  const el = $("#chartAi");
  if (!el) return;
  const rows = Array.isArray(DB.policies) ? DB.policies : [];
  if (!rows.length) { el.innerHTML = chartEmpty("暂无政策数据"); return; }
  const llm = rows.filter((p) => p.ai_type === "llm").length;
  const pct = Math.round(llm / rows.length * 100);
  const C = 2 * Math.PI * 66, len = C * pct / 100;
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 200 200" role="img" aria-label="AI解读覆盖率 ' + pct + '%">'
    + '<circle class="donut-track" cx="100" cy="100" r="86" fill="none" stroke-width="1" opacity=".4" />'
    + '<circle class="donut-track" cx="100" cy="100" r="66" fill="none" stroke-width="18" />'
    + '<g transform="rotate(-90 100 100)"><circle class="donut-ai" cx="100" cy="100" r="66" fill="none" stroke-width="18" stroke-linecap="round" stroke-dasharray="' + len.toFixed(2) + ' ' + (C - len).toFixed(2) + '" /></g>'
    + '<text class="val-text" x="100" y="104" text-anchor="middle" style="font-size:28px">' + pct + '%</text>'
    + '<text class="axis-text" x="100" y="128" text-anchor="middle">AI 解读覆盖</text>'
    + '<text class="axis-text" x="100" y="148" text-anchor="middle">' + llm + ' / ' + rows.length + '</text>'
    + '</svg>';
}

function renderChartExposure() {
  const el = $("#chartExposure");
  if (!el) return;
  const ot = (DB.expStats || {}).org_type || {};
  const entries = Object.entries(ot).filter((e) => Number(e[1]) > 0).sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!entries.length) { el.innerHTML = chartEmpty("暂无曝光机构数据"); return; }
  const sum = entries.reduce((s, e) => s + Number(e[1]), 0);
  const max = Math.max.apply(null, [1].concat(entries.map((e) => Number(e[1]))));
  const W = 360, rowH = 34, L = 74, R = 48, T = 8, barW = W - L - R;
  const H = T + entries.length * rowH + 8;
  const rows = entries.map((e, i) => {
    const c = Number(e[1]), w = Math.max(2, (c / max) * barW), pct = Math.round(c / sum * 100), yy = T + i * rowH + 8;
    return '<text class="axis-text" x="' + (L - 6) + '" y="' + (yy + 11) + '" text-anchor="end">' + esc(e[0]) + '</text>'
      + '<rect class="bar-track" x="' + L + '" y="' + yy + '" width="' + barW + '" height="15" rx="7.5" />'
      + '<rect class="bar-exposure" x="' + L + '" y="' + yy + '" width="' + w.toFixed(1) + '" height="15" rx="7.5" style="fill:url(#expoBarFill)"><title>' + esc(e[0]) + '：' + c + ' 家（' + pct + '%）</title></rect>'
      + '<text class="val-text" x="' + (L + w + 5).toFixed(1) + '" y="' + (yy + 12) + '">' + c + ' · ' + pct + '%</text>';
  }).join("");
  const defs = '<defs><linearGradient id="expoBarFill" x1="0" y1="0" x2="1" y2="0"><stop class="gstop-expo-a" offset="0%"/><stop class="gstop-expo-b" offset="100%"/></linearGradient></defs>';
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="曝光机构类型占比">' + defs + rows + '</svg>';
}

function renderChartRelevance() {
  const el = $("#chartRelevance");
  if (!el) return;
  const rows = Array.isArray(DB.policies) ? DB.policies : [];
  if (!rows.length) { el.innerHTML = chartEmpty("暂无相关度数据"); return; }
  const buckets = relevanceBuckets();
  const max = Math.max.apply(null, [1].concat(buckets.map((b) => b.n)));
  const W = 300, H = 200, L = 30, R = 10, T = 20, B = 42;
  const pw = W - L - R, ph = H - T - B;
  const bw = Math.min(56, pw / buckets.length * 0.5);
  const bars = buckets.map((b, i) => {
    const h = Math.max(2, (b.n / max) * ph), cx = L + (i + 0.5) * pw / buckets.length, xx = cx - bw / 2, yy = T + ph - h;
    return '<rect class="bar-track" x="' + xx.toFixed(1) + '" y="' + T + '" width="' + bw.toFixed(1) + '" height="' + ph + '" rx="7" />'
      + '<rect class="bar-rel" x="' + xx.toFixed(1) + '" y="' + yy.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="7" style="fill:url(#relBarFill)"><title>' + b.label + '：' + b.n + ' 条</title></rect>'
      + '<text class="val-text" x="' + cx.toFixed(1) + '" y="' + (yy - 6).toFixed(1) + '" text-anchor="middle">' + b.n + '</text>'
      + '<text class="axis-text" x="' + cx.toFixed(1) + '" y="' + (H - 20) + '" text-anchor="middle">' + b.label + '</text>';
  }).join("");
  const defs = '<defs><linearGradient id="relBarFill" x1="0" y1="1" x2="0" y2="0"><stop class="gstop-rel-a" offset="0%"/><stop class="gstop-rel-b" offset="100%"/></linearGradient></defs>';
  el.innerHTML = '<svg class="chart-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="相关度分布">'
    + defs
    + '<line class="grid-h" x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '" />'
    + bars + '</svg>';
}

function renderTimeline() {
  const el = $("#policyTimeline");
  if (!el) return;
  const rows = (Array.isArray(DB.policies) ? DB.policies : []).slice();
  rows.sort((a, b) => (b.publish_date || "").localeCompare(a.publish_date || "") || (b.id || 0) - (a.id || 0));
  const top = rows.slice(0, 6);
  if (!top.length) { el.innerHTML = chartEmpty("暂无政策时间轴数据"); return; }
  el.innerHTML = top.map((p) => '<div class="tl-item"><span class="tl-dot"></span><span class="tl-date">' + esc(p.publish_date || "—") + '</span><span class="tl-title" data-id="' + p.id + '" role="button" tabindex="0">' + esc(p.title || "") + '</span></div>').join("");
  $$("#policyTimeline .tl-title").forEach((t) => {
    t.addEventListener("click", () => openDetail(+t.dataset.id));
    t.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(+t.dataset.id); } });
  });
}

function renderTagCloud() {
  const el = $("#tagCloud");
  if (!el) return;
  const tags = (((DB.facets || {}).by_tag) || []).filter((t) => Number(t.count) > 0)
    .sort((a, b) => Number(b.count) - Number(a.count)).slice(0, 24);
  if (!tags.length) { el.innerHTML = chartEmpty("暂无主题标签数据"); return; }
  const counts = tags.map((t) => Number(t.count));
  const max = Math.max.apply(null, counts), min = Math.min.apply(null, counts);
  el.innerHTML = tags.map((t) => {
    const c = Number(t.count);
    const f = max === min ? 0.5 : (c - min) / (max - min);
    const lvl = f > 0.75 ? "hot lg" : f > 0.5 ? "lg" : f > 0.25 ? "md" : "sm";
    return '<span class="cloud-tag ' + lvl + '" data-tag="' + esc(t.tag) + '" role="button" tabindex="0" title="' + esc(t.tag) + ' · ' + c + ' 条">' + esc(t.tag) + '</span>';
  }).join("");
  $$("#tagCloud .cloud-tag").forEach((t) => {
    const go = () => filterByTag(t.dataset.tag);
    t.addEventListener("click", go);
    t.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
}

function filterByTag(tag) {
  if (!tag) return;
  switchView("policy");
  state.level = ""; state.column = ""; state.tag = tag; state.keyword = ""; state.page = 1;
  const kw = $("#keyword"); if (kw) kw.value = "";
  renderActiveTag(); syncQuickTags(); refreshColumns(); syncLevelUI(); syncSortChips();
  loadList();
}

function renderSparks() {
  const lv = (DB.stats || {}).by_level || {};
  const series = {
    level: ["national", "provincial", "municipal"].map((k) => Number((lv[k] || {}).count) || 0),
    trend: last12Months().map((m) => m.count),
    exposure: Object.values((DB.expStats || {}).org_type || {}).map(Number),
    relevance: relevanceBuckets().map((b) => b.n),
  };
  $$("#dashboardView .kpi-spark").forEach((el) => {
    const key = el.dataset.spark || "spark";
    const arr = series[key] || [];
    if (!arr.length || arr.every((v) => !v)) { el.innerHTML = ""; return; }
    const max = Math.max.apply(null, arr.concat([1])), w = 120, h = 36, base = h - 1;
    const coords = arr.map((v, i) => [i * (w / Math.max(1, arr.length - 1)), h - 3 - (v / max) * (h - 6)]);
    const pts = coords.map((p) => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    const area = "M" + coords[0][0].toFixed(1) + " " + base
      + " L" + coords.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L")
      + " L" + coords[coords.length - 1][0].toFixed(1) + " " + base + " Z";
    const gid = "sparkFill-" + key;
    el.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
      + '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop class="gstop-spark-a" offset="0%"/><stop class="gstop-spark-b" offset="100%"/></linearGradient></defs>'
      + '<path class="spark-area" d="' + area + '" fill="url(#' + gid + ')" />'
      + '<polyline class="spark-line" points="' + pts + '" fill="none" style="stroke:var(--chart-trend, #3b82f6)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>';
  });
}

function renderDashboard() {
  renderChartLevel(); renderChartTrend(); renderChartTopics();
  renderChartAi(); renderChartExposure(); renderChartRelevance();
  renderTimeline(); renderTagCloud();
  const rows = Array.isArray(DB.policies) ? DB.policies : [];
  const total = Number((DB.stats || {}).total) || rows.length;
  const llm = rows.filter((p) => p.ai_type === "llm").length;
  const aiPct = rows.length ? Math.round(llm / rows.length * 100) : 0;
  const exp = DB.expStats || {};
  const expTotal = (Number(exp.case_total) || 0) + (Number(exp.exit_total) || 0);
  const avgRel = rows.length ? Math.round(rows.reduce((s, p) => s + (Number(p.relevance) || 0), 0) / rows.length) : 0;
  const recent = last12Months().reduce((s, m) => s + m.count, 0);
  const setNum = (sel, v) => { const e = $(sel); if (e) { e.dataset.target = String(v); countUp(e); } };
  setNum("#dashboardView .hero-metric:nth-child(1) .count-up", total);
  setNum("#dashboardView .hero-metric:nth-child(3) .count-up", aiPct);
  const vals = [total, recent, expTotal, avgRel];
  $$("#dashboardView .kpi-value.count-up").forEach((e, i) => { e.dataset.target = String(vals[i] || 0); countUp(e); });
  renderSparks();
}

/* ================= 政策对比 ================= */
function toggleCompare(id) {
  id = +id;
  const i = COMPARE.indexOf(id);
  if (i >= 0) COMPARE.splice(i, 1);
  else {
    if (COMPARE.length >= COMPARE_MAX) { toast("最多同时对比 " + COMPARE_MAX + " 条政策"); return false; }
    COMPARE.push(id);
  }
  renderCompareBar(); syncCompareUI();
  return true;
}
function syncCompareUI() {
  $$(".compare-btn").forEach((b) => {
    const on = COMPARE.includes(+b.dataset.id);
    b.classList.toggle("on", on);
    b.textContent = on ? "✓" : "⇄";
    b.title = on ? "移出对比" : "加入对比";
  });
}
function renderCompareBar() {
  const bar = $("#compareBar");
  if (!bar) return;
  if (!COMPARE.length) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const list = $("#compareList");
  if (list) {
    list.innerHTML = COMPARE.map((id) => {
      const p = DB.policies.find((x) => x.id === id);
      return '<span class="cb-item" data-id="' + id + '"><span>' + esc(p ? p.title : ("政策 #" + id)) + '</span><b>✕</b></span>';
    }).join("");
    $$("#compareList .cb-item").forEach((c) => c.addEventListener("click", () => toggleCompare(+c.dataset.id)));
  }
  const start = $("#compareStart");
  if (start) start.disabled = COMPARE.length < 2;
}
async function openCompare() {
  if (COMPARE.length < 2) { toast("请至少选择 2 条政策进行对比"); return; }
  // 对比所需的核心要素 / 要点 / 风险 / 影响分级等字段在详情包中，按需加载后合并
  await loadDetails();
  const rows = COMPARE.map((id) => {
    const raw = DB.policies.find((x) => x.id === id);
    return raw ? Object.assign({}, raw, getDetail(id)) : null;
  }).filter(Boolean);
  if (rows.length < 2) { toast("对比数据不完整"); return; }
  const body = $("#compareBody");
  if (!body) return;
  const IMP = { "高": ["高影响", "imp-high"], "中": ["中影响", "imp-mid"], "低": ["低影响", "imp-low"], "未涉及": ["未涉及", "imp-none"] };
  const col = (p) => {
    const elems = (p.core_elements || []).map((e) => '<div class="cmp-kv"><b>' + esc(e.label || "要素") + '</b><span>' + esc(e.value || "—") + '</span></div>').join("") || '<div class="cmp-none">—</div>';
    const pts = (p.key_points || []).slice(0, 5).map((k) => '<li>' + esc(k) + '</li>').join("") || '<li>—</li>';
    const risks = (p.risks || []).slice(0, 5).map((k) => '<li>' + esc(k) + '</li>').join("") || '<li>—</li>';
    const imp = IMP[p.impact_level] || IMP["未涉及"];
    return '<div class="cmp-col"><div class="cmp-col-head"><span class="badge level-' + p.level + '">' + (LEVEL_NAME[p.level] || "") + '</span><h3>' + esc(p.title) + '</h3><div class="cmp-meta">' + esc(p.publish_date || "") + (p.doc_no && p.doc_no !== "-" ? " · " + esc(p.doc_no) : "") + '</div></div>'
      + '<div class="cmp-sec"><h4>核心要素</h4>' + elems + '</div>'
      + '<div class="cmp-sec"><h4>要点提炼</h4><ul>' + pts + '</ul></div>'
      + '<div class="cmp-sec"><h4>合规风险</h4><ul>' + risks + '</ul></div>'
      + '<div class="cmp-sec"><h4>影响分级</h4><span class="badge ' + imp[1] + '">' + imp[0] + '</span>' + (p.city_impact ? '<p class="cmp-impact">' + esc(p.city_impact) + '</p>' : "") + '</div></div>';
  };
  body.innerHTML = '<div class="cmp-grid">' + rows.map(col).join("") + '</div>';
  const d = $("#compareDrawer"), m = $("#compareMask");
  if (d) d.classList.remove("hidden");
  if (m) m.classList.remove("hidden");
}
function closeCompare() {
  const d = $("#compareDrawer"), m = $("#compareMask");
  if (d) d.classList.add("hidden");
  if (m) m.classList.add("hidden");
}
function clearCompare() { COMPARE.length = 0; renderCompareBar(); syncCompareUI(); }

/* ================= 命令面板 Ctrl / ⌘ + K ================= */
function openCmd() {
  const p = $("#cmdPalette");
  if (!p) return;
  p.classList.remove("hidden");
  const inp = $("#cmdInput");
  if (inp) { inp.value = ""; inp.focus(); }
  renderCmdResults("");
}
function closeCmd() { const p = $("#cmdPalette"); if (p) p.classList.add("hidden"); }
function renderCmdResults(q) {
  const box = $("#cmdResults");
  if (!box) return;
  q = (q || "").trim();
  let rows = [];
  if (!q) {
    rows = (Array.isArray(DB.policies) ? DB.policies : []).slice()
      .sort((a, b) => (b.publish_date || "").localeCompare(a.publish_date || "") || (b.id || 0) - (a.id || 0)).slice(0, 8);
  } else {
    const k = q.toLowerCase();
    rows = (Array.isArray(DB.policies) ? DB.policies : []).filter((p) =>
      (p.title || "").toLowerCase().includes(k) ||
      (p.doc_no || "").toLowerCase().includes(k) ||
      (p.ai_summary || "").toLowerCase().includes(k) ||
      (p.topic_tags || []).some((t) => String(t).toLowerCase().includes(k))
    ).slice(0, 10);
  }
  if (!rows.length) { box.innerHTML = '<div class="cmd-empty">未找到匹配政策，换个关键词试试</div>'; return; }
  box.innerHTML = rows.map((p, i) => '<div class="cmd-item' + (i === 0 ? " active" : "") + '" data-id="' + p.id + '">'
    + '<span class="ci-icon">📄</span>'
    + '<span class="ci-title">' + esc(p.title || "") + '</span>'
    + '<span class="ci-meta">' + esc(p.publish_date || "") + '</span></div>').join("");
  $$("#cmdResults .cmd-item").forEach((it) => {
    it.addEventListener("mouseenter", () => { $$("#cmdResults .cmd-item").forEach((x) => x.classList.remove("active")); it.classList.add("active"); });
    it.addEventListener("click", () => { closeCmd(); openDetail(+it.dataset.id); });
  });
}
function cmdMove(delta) {
  const items = $$("#cmdResults .cmd-item");
  if (!items.length) return;
  let i = items.findIndex((x) => x.classList.contains("active"));
  if (i < 0) i = 0; else i = (i + delta + items.length) % items.length;
  items.forEach((x) => x.classList.remove("active"));
  items[i].classList.add("active");
  items[i].scrollIntoView({ block: "nearest" });
}
function cmdOpenSelected() {
  const it = $("#cmdResults .cmd-item.active");
  if (it) { closeCmd(); openDetail(+it.dataset.id); }
}

/* ---------------- 事件 ---------------- */
$$("#moduleTabs .mtab").forEach((t) =>
  t.addEventListener("click", () => switchView(t.dataset.view))
);

$$("#dashboardView .kpi-card[data-goto]").forEach((card) => {
  const go = () => gotoKpi(card.dataset.goto);
  card.addEventListener("click", go);
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
  });
});

$$("#levelChips .chip").forEach((c) =>
  c.addEventListener("click", () => setLevel(c.dataset.level))
);

$$("#sortChips .chip").forEach((c) =>
  c.addEventListener("click", () => { state.sort = c.dataset.sort; state.page = 1; syncSortChips(); loadList(); focusPolicyList(); })
);
$("#keyword").addEventListener("input", (e) => { state.keyword = e.target.value.trim(); state.page = 1; clearTimeout(window._kt); window._kt = setTimeout(loadList, 350); });
$("#prevPage").addEventListener("click", () => { state.page--; loadList(); focusPolicyList(); });
$("#nextPage").addEventListener("click", () => { state.page++; loadList(); focusPolicyList(); });
$("#resetFilters").addEventListener("click", resetFilters);

window.addEventListener("scroll", () => {
  $("#backTop").classList.toggle("hidden", window.scrollY < 300);
  const sp = $("#scrollProgress");
  if (sp) {
    const h = document.documentElement.scrollHeight - window.innerHeight;
    sp.style.width = (h > 0 ? Math.min(100, (window.scrollY / h) * 100) : 0) + "%";
  }
});
$("#backTop").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

$("#activeTag").addEventListener("click", () => { state.tag = ""; renderActiveTag(); syncQuickTags(); loadList(); focusPolicyList(); });

$("#drawerMask").addEventListener("click", closeDrawer);

$("#expKeyword").addEventListener("input", (e) => {
  expState.keyword = e.target.value.trim(); expState.page = 1;
  clearTimeout(window._ekt); window._ekt = setTimeout(loadExposures, 350);
});

$("#askBtn").addEventListener("click", askQuestion);
$("#askInput").addEventListener("keydown", (e) => { if (e.key === "Enter") askQuestion(); });

/* 新增模块事件 */
const favFilter = $("#favFilter");
if (favFilter) favFilter.addEventListener("click", () => {
  state.onlyFav = !state.onlyFav; state.page = 1;
  syncFavUI(); loadList(); focusPolicyList();
});
const cmpStart = $("#compareStart"); if (cmpStart) cmpStart.addEventListener("click", openCompare);
const cmpClear = $("#compareClear"); if (cmpClear) cmpClear.addEventListener("click", clearCompare);
const cmpClose = $("#compareClose"); if (cmpClose) cmpClose.addEventListener("click", closeCompare);
const cmpMask = $("#compareMask"); if (cmpMask) cmpMask.addEventListener("click", closeCompare);
const cmdInp = $("#cmdInput");
if (cmdInp) {
  cmdInp.addEventListener("input", (e) => renderCmdResults(e.target.value));
  cmdInp.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); cmdMove(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); cmdMove(-1); }
    else if (e.key === "Enter") { e.preventDefault(); cmdOpenSelected(); }
  });
}
const cmdMask = $("#cmdPalette .cmd-mask");
if (cmdMask) cmdMask.addEventListener("click", closeCmd);

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault();
    openCmd();
    return;
  }
  if (e.key === "Escape") {
    closeDrawer();
    closeCompare();
    closeCmd();
    ["loginModal", "settingsModal", "logsModal"].forEach((id) => closeModal(id));
  }
});

if (!SITE_CLOSED) (async function init() {
  renderAskQuick();
  renderAskEmpty();
  if (typeof fetch === "undefined") {
    toast("当前浏览器版本过低，无法加载数据，请升级后重试");
    return;
  }
  try {
    await initData();
  } catch (e) {
    toast("静态数据加载失败：" + (e.message || e));
    return;
  }
  if (!Array.isArray(DB.policies) || !DB.policies.length) {
    toast("政策数据尚未就绪，请稍后刷新重试");
  }
  loadFacets();
  renderValidityChips();
  computeNewBatch();
  renderNewBanner();
  bindNewBanner();
  loadStats();
  loadExposureStats();
  loadExposures();
  loadList();
  loadLastRun();
  syncFavUI();
  renderCompareBar();
  renderDashboard();
})();

/* ==================================================================
 * 本地后台模块（仅 127.0.0.1 / localhost 启用；公网 Pages 纯静态不显示）
 * 依赖后端：/api/auth/login、/api/crawl、/api/crawl/status、/api/reanalyze、
 * /api/reanalyze/status、/api/logs、/api/settings、/api/auth/password、/api/stats
 * ================================================================== */
const IS_LOCAL = ["127.0.0.1", "localhost", "[::1]", ""].includes(location.hostname);
const ADMIN = { token: localStorage.getItem("yb_admin_token") || "" };
let _crawlTimer = null, _reanalyzeTimer = null;

async function apiFetch(path, opts) {
  opts = opts || {};
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (ADMIN.token) headers["X-Admin-Token"] = ADMIN.token;
  const r = await fetch(path, Object.assign({}, opts, { headers: headers }));
  if (r.status === 401) {
    ADMIN.token = ""; localStorage.removeItem("yb_admin_token"); refreshAdminUI();
    throw new Error("未授权，请先登录");
  }
  if (!r.ok) {
    let msg = "请求失败";
    try { const e = await r.json(); msg = e.detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

function openModal(id) {
  const map = { loginModal: "loginMask", settingsModal: "settingsMask", logsModal: "logsMask" };
  const m = $(`#${id}`);
  m.style.left = ""; m.style.top = ""; m.style.transform = ""; m.style.animation = "";
  m.classList.remove("hidden");
  const mask = $(`#${map[id]}`); if (mask) mask.classList.remove("hidden");
}
function closeModal(id) {
  const map = { loginModal: "loginMask", settingsModal: "settingsMask", logsModal: "logsMask" };
  $(`#${id}`).classList.add("hidden");
  const mask = $(`#${map[id]}`); if (mask) mask.classList.add("hidden");
}

/* 弹窗标题栏拖拽：按住标题栏可移动弹窗，位置约束在视口内 */
function makeModalDraggable(modal) {
  const head = modal.querySelector(".modal-head");
  if (!head) return;
  let dragging = false;
  let startX = 0, startY = 0, baseLeft = 0, baseTop = 0;

  const insideInteractive = (el) => {
    while (el && el !== head) {
      const tag = el.tagName;
      if (tag === "BUTTON" || tag === "INPUT" || tag === "SELECT" || tag === "A" || tag === "TEXTAREA") return true;
      el = el.parentNode;
    }
    return false;
  };

  head.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (insideInteractive(e.target)) return;
    dragging = true;
    const rect = modal.getBoundingClientRect();
    startX = e.clientX; startY = e.clientY;
    baseLeft = rect.left; baseTop = rect.top;
    modal.style.animation = "none";
    modal.style.transform = "none";
    modal.style.left = rect.left + "px";
    modal.style.top = rect.top + "px";
    head.style.cursor = "grabbing";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });

  const onMove = (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    const w = modal.offsetWidth, h = modal.offsetHeight;
    let nl = baseLeft + dx;
    let nt = baseTop + dy;
    nl = Math.max(0, Math.min(nl, window.innerWidth - w));
    nt = Math.max(0, Math.min(nt, window.innerHeight - 40));
    modal.style.left = nl + "px";
    modal.style.top = nt + "px";
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    head.style.cursor = "";
    document.body.style.userSelect = "";
  };
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function refreshAdminUI() {
  if (!IS_LOCAL) return;
  $("#adminActions").hidden = false;
  $("#btnLogin").textContent = ADMIN.token ? "🚪 退出" : "🔑 登录";
}

async function doLogin() {
  const pwd = $("#loginPwd").value;
  const err = $("#loginError"); err.hidden = true;
  if (!pwd) { err.textContent = "请输入管理密码"; err.hidden = false; return; }
  try {
    const res = await apiFetch("/api/auth/login", { method: "POST", body: JSON.stringify({ password: pwd }) });
    ADMIN.token = res.token; localStorage.setItem("yb_admin_token", res.token);
    closeModal("loginModal"); $("#loginPwd").value = "";
    refreshAdminUI();
    toast(res.must_change ? "登录成功，建议在设置中修改默认密码" : "登录成功");
  } catch (e) { err.textContent = e.message; err.hidden = false; }
}

async function doLogout() {
  try { await apiFetch("/api/auth/logout", { method: "POST" }); } catch (_) {}
  ADMIN.token = ""; localStorage.removeItem("yb_admin_token");
  refreshAdminUI(); toast("已退出登录");
}

function setProgress(st) {
  const box = $("#crawlProgress");
  if (!st) { box.hidden = true; return; }
  box.hidden = false;
  const pct = Math.max(0, Math.min(100, st.percent || 0));
  $("#cpFill").style.width = pct + "%";
  $("#cpPct").textContent = pct + "%";
  $("#cpStage").textContent = st.stage || "准备开始…";
  const parts = [];
  if (st.source_total > 1) parts.push(`源 ${st.source_idx}/${st.source_total}`);
  if (st.count) parts.push(`已处理 ${st.count} 条`);
  $("#cpCount").textContent = parts.join(" · ");
}

async function startCrawl() {
  if (!ADMIN.token) { openModal("loginModal"); return; }
  const btn = $("#btnCrawl"); btn.disabled = true;
  try {
    await apiFetch("/api/crawl", { method: "POST" });
    toast("已开始抓取，进度见上方进度条");
    pollCrawlStatus();
  } catch (e) { toast("抓取启动失败：" + e.message); btn.disabled = false; }
}

async function pollCrawlStatus() {
  clearInterval(_crawlTimer);
  _crawlTimer = setInterval(async () => {
    try {
      const st = await apiFetch("/api/crawl/status");
      setProgress(st);
      if (!st.running) {
        clearInterval(_crawlTimer);
        $("#btnCrawl").disabled = false;
        if (st.error) toast("抓取异常：" + st.error);
        else toast(`抓取完成：新增 ${st.added || 0}，更新 ${st.updated || 0}`);
        setTimeout(() => location.reload(), 900);
      }
    } catch (e) { clearInterval(_crawlTimer); $("#btnCrawl").disabled = false; }
  }, 1200);
}

async function startReanalyze() {
  if (!ADMIN.token) { openModal("loginModal"); return; }
  const btn = $("#btnReanalyze"); btn.disabled = true;
  setProgress({ percent: 0, stage: "准备批量重解读…", source_total: 0, count: 0 });
  try {
    await apiFetch("/api/reanalyze?limit=100&only=rule", { method: "POST" });
    toast("已开始批量重解读");
    pollReanalyze();
  } catch (e) { toast("重解读启动失败：" + e.message); btn.disabled = false; setProgress(null); }
}

async function pollReanalyze() {
  clearInterval(_reanalyzeTimer);
  _reanalyzeTimer = setInterval(async () => {
    try {
      const st = await apiFetch("/api/reanalyze/status");
      if (st.running) {
        $("#crawlProgress").hidden = false;
        $("#cpFill").style.width = `${st.total ? Math.round((st.done / st.total) * 100) : 0}%`;
        $("#cpPct").textContent = st.total ? `${Math.round((st.done / st.total) * 100)}%` : "0%";
        $("#cpStage").textContent = `重解读 ${st.done}/${st.total}（失败 ${st.failed || 0}）`;
        $("#cpCount").textContent = "";
      } else {
        clearInterval(_reanalyzeTimer); $("#btnReanalyze").disabled = false; setProgress(null);
        toast(`重解读完成：成功 ${(st.total || 0) - (st.failed || 0)}，失败 ${st.failed || 0}`);
        setTimeout(() => location.reload(), 900);
      }
    } catch (e) { clearInterval(_reanalyzeTimer); $("#btnReanalyze").disabled = false; setProgress(null); }
  }, 1500);
}

async function openLogs() {
  if (!ADMIN.token) { openModal("loginModal"); return; }
  openModal("logsModal");
  try {
    const rows = await apiFetch("/api/logs?limit=50");
    $("#logsBody").innerHTML = rows.length ? rows.map((r) => `
      <tr>
        <td>${esc(r.run_at || "")}</td>
        <td>${esc(r.level || "")}</td>
        <td>${esc(r.source_name || "")}</td>
        <td>${esc(r.added != null ? r.added : 0)}</td>
        <td>${esc(r.found != null ? r.found : 0)}</td>
        <td>${esc(r.status || "")}</td>
        <td>${esc(r.duration_ms != null ? r.duration_ms : "")}</td>
        <td>${esc(r.message || "")}</td>
      </tr>`).join("")
      : `<tr><td class="empty" colspan="8">暂无抓取日志</td></tr>`;
  } catch (e) {
    $("#logsBody").innerHTML = `<tr><td class="empty" colspan="8">加载失败：${esc(e.message)}</td></tr>`;
  }
}

async function openSettings() {
  if (!ADMIN.token) { openModal("loginModal"); return; }
  openModal("settingsModal");
  try {
    const s = await apiFetch("/api/settings");
    $("#setSiteOrg").value = s.site_org || "";
    $("#setNewDays").value = s.new_days != null ? s.new_days : "3";
    $("#setMinDate").value = s.min_policy_date || "";
    $("#setListPages").value = s.list_pages != null ? s.list_pages : "4";
    $("#setSchedule").value = s.schedule || "manual";
    $("#setDailyHour").value = s.daily_hour != null ? s.daily_hour : "8";
    $("#setWeekday").value = s.weekly_weekday || "1";
    $("#setWeeklyHour").value = s.weekly_hour != null ? s.weekly_hour : "8";
    $("#setLlmEnabled").value = s.llm_enabled || "0";
    $("#setLlmBase").value = s.llm_base_url || "";
    $("#setLlmModel").value = s.llm_model || "";
    $("#setLlmKey").value = "";
    $("#setOldPwd").value = ""; $("#setNewPwd").value = "";
    $("#settingsError").hidden = true;
  } catch (e) { toast("设置加载失败：" + e.message); }
}

async function saveSettings() {
  const body = {
    site_org: $("#setSiteOrg").value.trim(),
    new_days: $("#setNewDays").value,
    min_policy_date: $("#setMinDate").value,
    list_pages: $("#setListPages").value,
    schedule: $("#setSchedule").value,
    daily_hour: $("#setDailyHour").value,
    weekly_weekday: $("#setWeekday").value,
    weekly_hour: $("#setWeeklyHour").value,
    llm_enabled: $("#setLlmEnabled").value,
    llm_base_url: $("#setLlmBase").value.trim(),
    llm_model: $("#setLlmModel").value.trim(),
  };
  const key = $("#setLlmKey").value.trim();
  if (key) body.llm_api_key = key;
  const err = $("#settingsError"); err.hidden = true;
  try {
    await apiFetch("/api/settings", { method: "POST", body: JSON.stringify(body) });
    const oldP = $("#setOldPwd").value, newP = $("#setNewPwd").value;
    if (oldP || newP) {
      if (newP.length < 6) throw new Error("新密码至少 6 位");
      await apiFetch("/api/auth/password", { method: "POST", body: JSON.stringify({ old_password: oldP, new_password: newP }) });
    }
    closeModal("settingsModal"); toast("设置已保存");
  } catch (e) { err.textContent = e.message; err.hidden = false; }
}

async function loadLastRun() {
  if (!IS_LOCAL) return;
  try {
    const s = await apiFetch("/api/stats");
    const parts = [];
    if (s.last_run_at) parts.push("最近抓取：" + s.last_run_at);
    if (s.next_run) parts.push("下次：" + s.next_run);
    $("#lastRun").textContent = parts.join("　") || "本地后台模式";
  } catch (_) { $("#lastRun").textContent = ""; }
}

function bindAdminEvents() {
  if (!IS_LOCAL) return;
  $("#btnLogin").addEventListener("click", () => { ADMIN.token ? doLogout() : openModal("loginModal"); });
  $("#btnLoginConfirm").addEventListener("click", doLogin);
  $("#loginPwd").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
  $("#btnCrawl").addEventListener("click", startCrawl);
  $("#btnReanalyze").addEventListener("click", startReanalyze);
  $("#btnLogs").addEventListener("click", openLogs);
  $("#btnSettings").addEventListener("click", openSettings);
  $("#btnSaveSettings").addEventListener("click", saveSettings);
  $$("[data-close]").forEach((b) => b.addEventListener("click", () => closeModal(b.dataset.close)));
  ["loginMask", "settingsMask", "logsMask"].forEach((id) => {
    $(`#${id}`).addEventListener("click", () => closeModal(id.replace("Mask", "Modal")));
  });
  $$(".modal").forEach((m) => makeModalDraggable(m));
}

if (!SITE_CLOSED) {
  bindAdminEvents();
  refreshAdminUI();
}
