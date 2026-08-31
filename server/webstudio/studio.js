/* SoftReel Studio — 프레임워크 없는 단일 SPA (해시 라우팅).
   디자인: 노션 "SoftReel 리디자인 v1" 토큰 + 채널 대시보드 시안(2026-08).
   서버 계약: /auth/*, /me, /videos(업로드·스트림·리포트), /studio/api/*
   (+ /studio/api/dashboard 집계), /admin/metrics. 스트림·썸네일
   <video>/<img> 는 Authorization 헤더를 못 보내므로 API 권한이 없는 단기
   media token을 쿼리로 쓴다. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const state = { token: localStorage.getItem("tk"), mediaToken: null,
                me: null, pollTimer: null };

const RISK_KO = { safe: "SAFE 인증", corrected: "보정됨 · 완화", uncorrected: "미보정 위험" };
const RULE_KO = { "플래시": "플래시", "적색": "적색", "패턴": "패턴",
                  "화면전환": "화면전환", "5초지속": "5초지속" };
const AXES = [["flash", "플래시"], ["red", "적색"], ["pattern", "패턴"], ["cut", "화면전환"]];
const DOW = ["일", "월", "화", "수", "목", "금", "토"];

async function api(path, opt = {}) {
  opt.headers = Object.assign({}, opt.headers,
    state.token ? { Authorization: "Bearer " + state.token } : {});
  const r = await fetch(path, opt);
  if (r.status === 401) { logout(); throw new Error("로그인이 필요합니다"); }
  if (!r.ok) {
    let msg = r.status + "";
    try { msg = (await r.json()).detail || msg; } catch (e) { /* 본문 없음 */ }
    throw new Error(msg);
  }
  return r.json();
}

async function refreshMediaToken() {
  const d = await api("/auth/media-token", { method: "POST" });
  state.mediaToken = d.token;
}

const mediaUrl = (u) => u + (u.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(state.mediaToken);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDur = (s) => { if (s == null) return "–"; s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const fmtDate = (t) => t ? t.slice(0, 10) : "–";
const fmtK = (n) => n >= 1000 ? (Math.round(n / 100) / 10).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
const dowOf = (d) => DOW[new Date(d + "T00:00:00").getDay()];

function relTime(t) {
  if (!t) return "–";
  const then = new Date(t.replace(" ", "T") + "Z");   // DB 는 UTC 로 저장
  const s = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (s < 60) return "방금 전";
  if (s < 3600) return Math.floor(s / 60) + "분 전";
  if (s < 86400) return Math.floor(s / 3600) + "시간 전";
  const d = Math.floor(s / 86400);
  if (d === 1) return "어제";
  if (d < 7) return d + "일 전";
  return fmtDate(t);
}

function setHead(title, sub) {
  $("#page-title").textContent = title;
  const el = $("#page-sub");
  el.textContent = sub || "";
  el.style.display = sub ? "" : "none";
}

function riskBadge(v) {
  if (v.status === "processing") return `<span class="badge b-processing">안전 처리 중</span>`;
  if (v.status === "failed") return `<span class="badge b-failed">실패</span>`;
  const r = v.risk || "safe";
  return `<span class="badge b-${r}">${RISK_KO[r] || r}</span>`;
}

function axisChips(st) {
  if (!st) return "";
  return AXES.filter(([k]) => st[k] > 0)
    .map(([k, ko]) => `<span class="chip hot">${ko} ${st[k]}</span>`).join("")
    || `<span class="chip">위반 없음</span>`;
}

/* ── 인증 ─────────────────────────────────────────────── */
async function boot() {
  if (state.token) {
    try {
      state.me = await api("/me");
      await refreshMediaToken();
      return showApp();
    }
    catch (e) { /* 토큰 만료 → 로그인으로 */ }
  }
  $("#login-view").classList.remove("hidden");
}

function logout() {
  localStorage.removeItem("tk");
  state.token = state.mediaToken = state.me = null;
  location.hash = ""; location.reload();
}

$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("#login-msg").textContent = "";
  try {
    const body = JSON.stringify({ email: $("#login-email").value.trim(),
                                  password: $("#login-pw").value });
    const r = await fetch("/auth/login", { method: "POST",
      headers: { "Content-Type": "application/json" }, body });
    if (!r.ok) throw new Error((await r.json()).detail || "로그인 실패");
    const d = await r.json();
    state.token = d.token; state.me = d.user;
    localStorage.setItem("tk", d.token);
    await refreshMediaToken();
    $("#login-view").classList.add("hidden");
    showApp();
  } catch (e) { $("#login-msg").textContent = e.message; }
});

function showApp() {
  $("#app-view").classList.remove("hidden");
  $("#avatar").textContent = (state.me.nickname || "?")[0].toUpperCase();
  $("#avatar").title = `${state.me.nickname} (${state.me.email})`;
  $("#chan-name").textContent = state.me.nickname + " 채널";
  fillRailFoot();
  if (!location.hash) location.hash = "#/dashboard";
  route();
}

async function fillRailFoot() {
  try {
    const d = await api("/studio/api/dashboard");
    $("#chan-sub").textContent =
      `구독자 ${d.stats.viewers.toLocaleString()} · 영상 ${d.stats.videos_total}개`;
  } catch (e) { /* 집계 실패는 치명적이지 않다 */ }
}

/* ── 라우팅 ───────────────────────────────────────────── */
window.addEventListener("hashchange", route);

function route() {
  if (!state.me) return;
  clearInterval(state.pollTimer);
  const h = location.hash || "#/dashboard";
  const mVid = h.match(/^#\/video\/(\d+)/);
  let key = mVid ? "content" : ((h.match(/^#\/(\w+)/) || [])[1] || "dashboard");
  if (key === "analytics") key = "revenue";      // 구 경로 호환
  document.querySelectorAll(".rail-nav a").forEach(a =>
    a.classList.toggle("on", a.dataset.nav === key));
  if (mVid) return viewDetail(+mVid[1]);
  if (key === "content") return viewContent();
  if (key === "safety") return viewSafety();
  if (key === "viewers") return viewViewers();
  if (key === "revenue") return viewRevenue();
  if (key === "settings") return viewSettings();
  return viewDashboard();
}

/* ── 대시보드 (시안: 통계 4칸 + 주간 차트 + 최근 업로드 +
      민감도 도넛 + 인사이트) ──────────────────────────── */
const SENS_META = [
  ["표준",        "standard_pct",       "#818CF8"],
  ["편두통 민감", "sensitive_pct",      "#34D399"],
  ["광과민성",    "photosensitive_pct", "#F04B64"],
];

function donutSVG(parts) {
  const R = 50, C = 2 * Math.PI * R;
  const live = parts.filter(p => p.pct > 0);
  if (!live.length)
    return `<svg class="donut" viewBox="0 0 140 140"><circle r="${R}" cx="70" cy="70" fill="none" stroke="#232338" stroke-width="17"/></svg>`;
  const gap = live.length > 1 ? 3 : 0;
  let off = 0;
  const segs = live.map(p => {
    const len = C * p.pct / 100;
    const s = `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${p.color}"
      stroke-width="17"
      stroke-dasharray="${Math.max(0.1, len - gap).toFixed(2)} ${(C - len + gap).toFixed(2)}"
      stroke-dashoffset="${(-off).toFixed(2)}"/>`;
    off += len; return s;
  }).join("");
  return `<svg class="donut" viewBox="0 0 140 140" role="img" aria-label="시청자 민감도 구성"><g transform="rotate(-90 70 70)">${segs}</g></svg>`;
}

function sensitivityBlock(sen) {
  const legend = SENS_META.map(([name, k, c]) => `
      <div class="row"><span class="dot" style="background:${c}"></span>${name}<span class="pct">${sen[k]}%</span></div>`).join("");
  const sensTotal = sen.sensitive_pct + sen.photosensitive_pct;
  const note = !sen.viewers
    ? "아직 시청 데이터가 없어요 — 영상이 시청되면 프로파일 구성이 나타납니다."
    : sensTotal <= 0
      ? "시청자 대부분이 표준 프로파일이에요."
      : sensTotal >= 60
        ? "시청자 대부분이 민감 프로파일 — 안전 처리가 곧 도달률이에요."
        : `시청자 ${Math.round(100 / sensTotal)}명 중 1명이 민감 프로파일 — 안전 처리가 곧 도달률이에요.`;
  return `
    <div class="donut-wrap">
      ${donutSVG(SENS_META.map(([, k, c]) => ({ pct: sen[k], color: c })))}
      <div class="legend">${legend}</div>
    </div>
    <div class="donut-note">${note}</div>`;
}

function weekChartSVG(weekly) {
  const W = 640, H = 262, L = 16, Rp = 24, TOP = 20, BASE = 218;
  const n = weekly.length || 1;
  const slot = (W - L - Rp) / n, bw = Math.min(46, slot * 0.52);
  const maxV = Math.max(1, ...weekly.map(d => d.views));
  const bh = (v) => v ? Math.max(9, (BASE - TOP) * v / maxV) : 5;
  const cx = (i) => L + slot * i + slot / 2;
  const py = (p) => BASE - (BASE - TOP) * p / 100;

  const bars = weekly.map((d, i) => {
    const h = bh(d.views), last = i === n - 1;
    return `<rect x="${(cx(i) - bw / 2).toFixed(1)}" y="${(BASE - h).toFixed(1)}"
      width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="10"
      fill="${last ? "url(#barGrad)" : "#232338"}"${last ? ' filter="url(#barGlow)"' : ""}>
      <title>${d.date} · 조회 ${d.views}${d.filter_on_pct != null ? ` · 필터 ON ${d.filter_on_pct}%` : ""}</title>
    </rect>`;
  }).join("");

  const pts = weekly.map((d, i) => d.filter_on_pct == null ? null : [cx(i), py(d.filter_on_pct)]);
  const line = pts.filter(Boolean);
  const path = line.length > 1
    ? `<polyline points="${line.map(p => p.map(x => x.toFixed(1)).join(",")).join(" ")}"
        fill="none" stroke="var(--safe)" stroke-width="2.5"
        stroke-linejoin="round" stroke-linecap="round"/>` : "";
  const dots = pts.map((p, i) => !p ? "" : (i === n - 1
    ? `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="6.5" fill="#ECECF4" stroke="var(--safe)" stroke-width="2.5"/>`
    : `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="4" fill="var(--safe)" stroke="var(--bg)" stroke-width="2"/>`)).join("");

  const labels = weekly.map((d, i) =>
    `<text class="xlab" x="${cx(i).toFixed(1)}" y="${H - 14}" text-anchor="middle">${dowOf(d.date)}</text>`).join("");

  return `<svg class="wchart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
      role="img" aria-label="주간 조회수와 필터 ON 시청 비율">
    <defs>
      <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#8B5CF6"/><stop offset="1" stop-color="#F28AA0"/>
      </linearGradient>
      <filter id="barGlow" x="-40%" y="-40%" width="180%" height="180%">
        <feDropShadow dx="0" dy="0" stdDeviation="7" flood-color="#B06CF0" flood-opacity="0.45"/>
      </filter>
    </defs>
    ${bars}${path}${dots}${labels}</svg>`;
}

async function viewDashboard() {
  setHead("채널 대시보드", "최근 28일");
  const main = $("#main");
  main.innerHTML = `<div class="card empty">불러오는 중…</div>`;
  let dash, videos;
  try {
    [dash, { videos }] = await Promise.all([
      api("/studio/api/dashboard"), api("/studio/api/videos")]);
  } catch (e) {
    main.innerHTML = `<div class="card empty">대시보드를 불러올 수 없습니다: ${esc(e.message)}</div>`;
    return;
  }
  const s = dash.stats;
  $("#chan-sub").textContent =
    `구독자 ${s.viewers.toLocaleString()} · 영상 ${s.videos_total}개`;

  const delta = (v, unit) => v == null
    ? `<div class="delta na">—</div>`
    : `<div class="delta ${v >= 0 ? "up" : "down"}">${v >= 0 ? "▲" : "▼"} ${Math.abs(v)}${unit}</div>`;

  const stats = `
    <div class="stat-grid">
      <div class="stat"><div class="k">총 조회</div><div class="v">${fmtK(s.views)}</div>${delta(s.views_delta_pct, "%")}</div>
      <div class="stat"><div class="k">필터 ON 시청</div><div class="v">${s.filter_on_pct != null ? s.filter_on_pct + "%" : "–"}</div>${delta(s.filter_on_delta_pp, "%p")}</div>
      <div class="stat"><div class="k">안전 인증률</div><div class="v">${s.cert.pct != null ? s.cert.pct + "%" : "–"}</div>
        <div class="delta ${s.cert.total ? "up" : "na"}">${s.cert.total ? `${s.cert.total}편 중 ${s.cert.certified}편` : "인증된 영상 없음"}</div></div>
      <div class="stat"><div class="k">구독자</div><div class="v">${s.viewers.toLocaleString()}</div>${delta(s.viewers_new > 0 ? s.viewers_new : null, "")}</div>
    </div>`;

  const PLACE = ["linear-gradient(135deg,#8B5CF6,#F04B64)",
                 "linear-gradient(135deg,#2DD4BF,#3B82F6)",
                 "linear-gradient(135deg,#F59E0B,#F04B64)"];
  const pill = (v) => v.status === "processing" ? `<span class="pill p-proc">보정 중</span>`
    : v.status === "failed" ? `<span class="pill p-warn">실패</span>`
    : v.risk === "safe" ? `<span class="pill p-ok">인증됨</span>`
    : v.risk === "corrected" ? `<span class="pill p-cor">완화됨</span>`
    : `<span class="pill p-warn">미보정</span>`;
  const upsub = (v) => relTime(v.created_at) + (v.status === "ready"
    ? ` · 조회 ${(v.view_count || 0).toLocaleString()}`
    : v.status === "failed" ? " · 처리 실패" : " · 처리 중");
  const uprows = videos.slice(0, 3).map((v, i) => `
    <div class="uprow" onclick="location.hash='#/video/${v.id}'">
      <div class="upthumb" style="${v.thumb_url
        ? `background-image:url('${mediaUrl(v.thumb_url)}')`
        : `background:${PLACE[i % PLACE.length]}`}"></div>
      <div class="upmeta"><div class="upname">${esc(v.title)}</div>
        <div class="upsub">${upsub(v)}</div></div>
      ${pill(v)}
    </div>`).join("")
    || `<div class="empty" style="padding:22px 0">아직 업로드한 영상이 없어요 — 오른쪽 위 <b>새 릴 업로드</b>로 시작하세요.</div>`;

  const ip = dash.insight;
  const insightTail = (ip && ip.delta_pp > 0)
    ? ` 최근 28일 인증 영상의 완주율이 미인증 대비 <b class="pos">+${ip.delta_pp}%p</b> 높았어요.`
    : "";
  const insight = `<div class="insight"><span class="tag">✦ 인사이트</span> —
    필터 ON 시청 비율이 높을수록 평균 시청 시간이 길어져요.${insightTail}
    안전 인증률이 높은 채널은 피드 추천 가중치를 받아요.</div>`;

  main.innerHTML = `
    ${stats}
    <div class="dash-grid">
      <div class="dash-col">
        <div class="card">
          <div class="chart-head"><h2>주간 조회 · 필터 ON 비율</h2>
            <span class="chart-cap">막대 = 조회수, 선 = 필터 ON 시청 비율</span></div>
          ${weekChartSVG(dash.weekly)}
        </div>
        ${insight}
      </div>
      <div class="dash-col">
        <div class="card"><h2>최근 업로드</h2>${uprows}</div>
        <div class="card"><h2>시청자 민감도 구성</h2>${sensitivityBlock(dash.sensitivity)}</div>
      </div>
    </div>`;
  if (videos.some(v => v.status === "processing"))
    state.pollTimer = setInterval(viewDashboard, 4000);
}

/* ── 콘텐츠 목록 ─────────────────────────────────────── */
async function viewContent() {
  setHead("채널 콘텐츠", "");
  const main = $("#main");
  const { videos } = await api("/studio/api/videos");
  const rows = videos.map(v => `
    <tr onclick="location.hash='#/video/${v.id}'">
      <td><div class="vcell">
        <div class="vthumb" style="${v.thumb_url ? `background-image:url('${mediaUrl(v.thumb_url)}')` : ""}">${v.thumb_url ? "" : (v.status === "failed" ? "실패" : "처리 중")}</div>
        <div><div class="vtitle">${esc(v.title)}</div>
             <div class="vsub">${v.filter_level ? "필터: " + v.filter_level : (v.risk === "safe" ? "보정 불필요" : "")}${v.job_error ? " · " + esc(v.job_error) : ""}</div></div>
      </div></td>
      <td>${riskBadge(v)}</td>
      <td>${axisChips(v.stimulus)}</td>
      <td>${fmtDate(v.created_at)}</td>
      <td class="num">${fmtDur(v.duration_s)}</td>
      <td class="num">${v.view_count}</td>
      <td class="num">${v.like_count}</td>
      <td><button class="rowdel" title="삭제" onclick="event.stopPropagation();delVideo(${v.id},'${esc(v.title).replace(/'/g, "\\'")}')">🗑</button></td>
    </tr>`).join("");
  main.innerHTML = `
    <div class="card" style="padding:0">
    <table class="vids">
      <thead><tr><th>영상</th><th>판정</th><th>위반 축</th><th>날짜</th>
      <th class="num">길이</th><th class="num">조회수</th><th class="num">좋아요</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="8" class="empty">영상이 없습니다</td></tr>`}</tbody>
    </table></div>`;
  if (videos.some(v => v.status === "processing"))
    state.pollTimer = setInterval(viewContent, 4000);
}

window.delVideo = async (id, title) => {
  if (!confirm(`'${title}' 영상을 삭제할까요? 되돌릴 수 없습니다.`)) return;
  try { await api(`/studio/api/videos/${id}`, { method: "DELETE" }); route(); }
  catch (e) { alert("삭제 실패: " + e.message); }
};

/* ── 안전 리포트 (채널 전체) ─────────────────────────── */
async function viewSafety() {
  setHead("안전 리포트", "채널 전체");
  const main = $("#main");
  main.innerHTML = `<div class="card empty">불러오는 중…</div>`;
  const { videos } = await api("/studio/api/videos");
  const ready = videos.filter(v => v.status === "ready");
  const n = (f) => ready.filter(f).length;
  const cert = n(v => v.risk === "safe" || v.risk === "corrected");
  const rows = videos.map(v => `
    <tr onclick="location.hash='#/video/${v.id}'">
      <td><div class="vtitle">${esc(v.title)}</div></td>
      <td>${riskBadge(v)}</td>
      <td>${axisChips(v.stimulus)}</td>
      <td>${v.filter_level || "–"}</td>
      <td>${fmtDate(v.created_at)}</td>
    </tr>`).join("");
  main.innerHTML = `
    <div class="tiles">
      <div class="tile hero"><div class="k">SAFE 인증</div><div class="v">${cert} <small>/ ${ready.length}편</small></div></div>
      <div class="tile"><div class="k">보정됨 · 완화</div><div class="v">${n(v => v.risk === "corrected")}</div></div>
      <div class="tile"><div class="k">미보정 위험</div><div class="v">${n(v => v.risk === "uncorrected")}</div></div>
      <div class="tile"><div class="k">안전 처리 중</div><div class="v">${videos.filter(v => v.status === "processing").length}</div></div>
    </div>
    <div class="card" style="padding:0">
      <table class="vids">
        <thead><tr><th>영상</th><th>판정</th><th>위반 축</th><th>적용 필터</th><th>업로드</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5" class="empty">영상이 없습니다</td></tr>`}</tbody>
      </table>
    </div>
    <p class="mini-note">구간별 검출 내역과 안전 리포트 JSON 내보내기는 각 영상 상세에서 확인할 수 있어요.</p>`;
  if (videos.some(v => v.status === "processing"))
    state.pollTimer = setInterval(viewSafety, 4000);
}

/* ── 시청자 ──────────────────────────────────────────── */
async function viewViewers() {
  setHead("시청자", "최근 28일");
  const main = $("#main");
  main.innerHTML = `<div class="card empty">불러오는 중…</div>`;
  const d = await api("/studio/api/dashboard");
  const s = d.stats;
  main.innerHTML = `
    <div class="tiles">
      <div class="tile hero"><div class="k">시청자 (구독자)</div><div class="v">${s.viewers.toLocaleString()}</div></div>
      <div class="tile"><div class="k">신규 시청자 (28일)</div><div class="v">${s.viewers_new}</div></div>
      <div class="tile"><div class="k">필터 ON 시청 비율</div><div class="v">${s.filter_on_pct != null ? s.filter_on_pct + "%" : "–"}</div></div>
    </div>
    <div class="card"><h2>시청자 민감도 구성</h2>${sensitivityBlock(d.sensitivity)}
      <p class="mini-note">프로파일은 시청자의 보호 설정(자동 스킵 = 광과민성, 필터 ON = 편두통 민감)을 기준으로 집계돼요.</p>
    </div>`;
}

/* ── 수익 (관리자는 운영 지표 포함) ───────────────────── */
async function viewRevenue() {
  setHead("수익", "");
  const main = $("#main");
  if (!state.me.is_admin) {
    main.innerHTML = `<div class="card"><h2>수익 리포트</h2>
      <p class="mini-note" style="margin-top:0">조회 기반 정산이 열리면 여기에 채널 수익이 표시됩니다.
      지금은 <b>안전 인증률</b>을 높여 피드 추천 가중치를 확보하는 것이 수익의 출발점이에요.</p></div>`;
    return;
  }
  main.innerHTML = `<div id="an" class="card">불러오는 중…</div>`;
  try {
    const m = await api("/admin/metrics");
    const g = m.groups;
    $("#an").outerHTML = `
      <div class="tiles">
        <div class="tile"><div class="k">위험 영상 시청 (필터 ON)</div><div class="v">${g.filtered.views}</div></div>
        <div class="tile"><div class="k">위험 영상 시청 (필터 OFF)</div><div class="v">${g.original.views}</div></div>
        <div class="tile"><div class="k">시청 유지율 개선</div><div class="v">+${m.delta.watch_ratio_pp}<small>%p</small></div></div>
        <div class="tile"><div class="k">이탈율 개선</div><div class="v">−${m.delta.bounce_pp}<small>%p</small></div></div>
      </div>
      <div class="card"><h2>B2C 환산 (추정 모델 — 가정 노출)</h2>
        <div class="kv">
          <span class="k">지켜낸 시청시간</span><span>${m.savings.kept_min_actual}분</span>
          <span class="k">절약 추정액 (실측 노출)</span><span>${m.savings.saved_krw_actual.toLocaleString()}원</span>
          <span class="k">1만 노출당</span><span>${m.savings.saved_krw_per_10k.toLocaleString()}원</span>
          <span class="k">가정</span><span>CPM ${m.assumptions.cpm.toLocaleString()}원 · 분당 노출 ${m.assumptions.imp_per_min}</span>
        </div></div>`;
  } catch (e) { $("#an").textContent = "지표를 불러올 수 없습니다: " + e.message; }
}

/* ── 설정 ────────────────────────────────────────────── */
function viewSettings() {
  setHead("설정", "");
  $("#main").innerHTML = `
    <div class="card"><h2>계정</h2>
      <div class="kv">
        <span class="k">채널명</span><span>${esc(state.me.nickname)}</span>
        <span class="k">이메일</span><span>${esc(state.me.email)}</span>
        <span class="k">권한</span><span>${state.me.is_admin ? "관리자" : "크리에이터"}</span>
      </div>
      <div class="card-actions"><button class="btn" id="btn-logout2">로그아웃</button></div>
    </div>
    <div class="card"><h2>채널 설정</h2>
      <p class="mini-note" style="margin-top:0">알림 · 팀 관리 · 기본 공개 범위 설정은 준비 중이에요.</p></div>`;
  $("#btn-logout2").addEventListener("click", logout);
}

/* ── 영상 상세 ───────────────────────────────────────── */
async function viewDetail(id) {
  setHead("콘텐츠 상세", "");
  const main = $("#main");
  const { videos } = await api("/studio/api/videos");
  const v = videos.find(x => x.id === id);
  if (!v) { main.innerHTML = `<a class="back" href="#/content">← 콘텐츠</a><div class="card empty">영상을 찾을 수 없습니다</div>`; return; }

  if (v.status !== "ready") {
    main.innerHTML = `<a class="back" href="#/content">← 콘텐츠</a>
      <h1>${esc(v.title)}</h1>
      <div class="card">${riskBadge(v)}
        <p class="mini-note">${v.status === "failed"
          ? "처리에 실패했습니다: " + esc(v.job_error || "원인 미기록")
          : "검출·보정 파이프라인이 실행 중입니다. 이 페이지는 자동으로 갱신됩니다."}</p></div>`;
    if (v.status === "processing")
      state.pollTimer = setInterval(() => viewDetail(id), 4000);
    return;
  }

  const rep = await api(`/videos/${id}/report`);
  const hasFiltered = v.has_filtered;
  const variant0 = hasFiltered ? "filtered" : "original";
  const action = (s) => s.resolved
    ? (rep.filter_level ? `${rep.filter_level} 필터로 완화` : "원본 적합")
    : "잔존 — 재검토 필요";
  const segRows = rep.segments.map(s => `
    <tr><td>${RULE_KO[s.rule] || esc(s.rule)}</td>
        <td>${fmtDur(s.start_s)}–${fmtDur(s.end_s)}</td>
        <td>${esc(action(s))}</td>
        <td>${s.resolved ? '<span class="badge b-safe">해소</span>'
                         : '<span class="badge b-uncorrected">잔존</span>'}</td></tr>`).join("");
  const segMarks = (dur) => rep.segments.map(s =>
    `<div class="seg ${s.resolved ? "ok" : ""}" style="left:${100 * s.start_s / dur}%;width:${Math.max(0.8, 100 * (s.end_s - s.start_s) / dur)}%" title="${esc(s.rule)} ${fmtDur(s.start_s)}–${fmtDur(s.end_s)}"></div>`).join("");

  const certified = v.risk === "safe" ||
    (v.risk === "corrected" && rep.segments.every(s => s.resolved));
  main.innerHTML = `<a class="back" href="#/content">← 콘텐츠</a>
    <div class="title-row"><h1>${esc(v.title)}</h1>
      ${certified ? '<span class="cert">✓ SAFE 인증 — 재판정 통과</span>' : ""}</div>
    <div class="detail">
      <div class="card player-card">
        <video id="player" controls playsinline
               src="${mediaUrl(`/videos/${id}/stream?variant=${variant0}`)}"></video>
        <div class="variant-tabs" id="vtabs">
          ${hasFiltered ? `<button data-var="filtered" class="on">보정본 (배포판)</button>` : ""}
          <button data-var="original" class="${hasFiltered ? "" : "on"}">원본</button>
        </div>
        <div class="heatmap">${segMarks(rep.duration_s || v.duration_s || 1)}</div>
        <div class="tl-cap">위험 히트맵 — <span style="color:var(--safe)">■ 완화됨</span> · <span style="color:var(--danger)">■ 잔존</span></div>
      </div>
      <div>
        <div class="card">
          <h2>검출 리포트 (pse_bt1702)</h2>
          <div class="kv">
            <span class="k">판정</span><span>${riskBadge(v)}</span>
            <span class="k">원본 적합 여부</span><span>${rep.compliant_original ? "적합" : "위반 검출"}</span>
            <span class="k">적용 필터</span><span>${rep.filter_level ? rep.filter_level + (rep.filter_level === "strong" ? " (σ32+순방향 관문)" : " (안전 기본값)") : "없음 — 보정 불필요"}</span>
            <span class="k">위반 축</span><span>${axisChips(v.stimulus)}</span>
            <span class="k">길이 · 조회수</span><span>${fmtDur(rep.duration_s)} · ${rep.view_count}회</span>
          </div>
          ${rep.segments.length ? `
          <table class="seglist">
            <thead><tr><th>규칙</th><th>구간</th><th>조치</th><th>상태</th></tr></thead>
            <tbody>${segRows}</tbody></table>` : `<p class="mini-note">위반 구간이 없습니다.</p>`}
        </div>
        <div class="card">
          <h2>시청 반응</h2>
          <div class="kv">
            <span class="k">보정본 시청 비율</span><span>${rep.filter_on_watch_percent != null ? rep.filter_on_watch_percent + "%" : "데이터 없음"}</span>
            <span class="k">평균 시청 유지율</span><span>${rep.avg_watch_percent != null ? rep.avg_watch_percent + "%" : "데이터 없음"}</span>
          </div>
          <div class="card-actions">
            <button class="btn" id="btn-export">안전 리포트 내보내기 (JSON)</button>
          </div>
        </div>
      </div>
    </div>`;

  $("#btn-export").addEventListener("click", () => {
    // v2 Studio: 안전 리포트 — 검출·조치 내역을 파일로 (B2B 인증 자료의 씨앗)
    const blob = new Blob([JSON.stringify(rep, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `softreel_safety_report_${id}.json`;
    a.click(); URL.revokeObjectURL(a.href);
  });

  $("#vtabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    document.querySelectorAll("#vtabs button").forEach(x => x.classList.toggle("on", x === b));
    const p = $("#player"); const t = p.currentTime;
    p.src = mediaUrl(`/videos/${id}/stream?variant=${b.dataset.var}`);
    p.currentTime = t; p.play().catch(() => {});
  });
}

/* ── 업로드 ──────────────────────────────────────────── */
const modal = $("#upload-modal");
let pickedFile = null;

$("#btn-upload").addEventListener("click", () => {
  pickedFile = null;
  $("#upload-form").classList.add("hidden");
  $("#drop").classList.remove("hidden");
  $("#upload-bar").style.width = "0";
  $("#upload-state").textContent = "";
  $("#upload-title").value = "";
  $("#upload-limits").textContent = "최대 500MB · 180초 (서버 설정에 따름)";
  modal.classList.remove("hidden");
});
$("#upload-close").addEventListener("click", () => modal.classList.add("hidden"));
$("#upload-cancel").addEventListener("click", () => modal.classList.add("hidden"));

const drop = $("#drop");
drop.addEventListener("click", () => $("#file-input").click());
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault(); drop.classList.remove("over");
  if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]);
});
$("#file-input").addEventListener("change", (e) => e.target.files[0] && pickFile(e.target.files[0]));

function pickFile(f) {
  pickedFile = f;
  $("#drop").classList.add("hidden");
  $("#upload-form").classList.remove("hidden");
  $("#upload-filename").textContent = `${f.name} (${(f.size / (1 << 20)).toFixed(1)}MB)`;
  if (!$("#upload-title").value)
    $("#upload-title").value = f.name.replace(/\.[^.]+$/, "");
}

$("#upload-go").addEventListener("click", () => {
  if (!pickedFile) return;
  const fd = new FormData();
  fd.append("file", pickedFile);
  fd.append("title", $("#upload-title").value.trim() || "무제");
  const xhr = new XMLHttpRequest();          // fetch 는 업로드 진행률이 없다
  xhr.open("POST", "/videos");
  xhr.setRequestHeader("Authorization", "Bearer " + state.token);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable)
      $("#upload-bar").style.width = (100 * e.loaded / e.total) + "%";
  };
  xhr.onload = () => {
    if (xhr.status === 202) {
      $("#upload-state").textContent = "업로드 완료 — 검출·보정 파이프라인에 들어갔습니다.";
      setTimeout(() => { modal.classList.add("hidden"); location.hash = "#/content"; route(); }, 900);
    } else {
      let msg = xhr.status;
      try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (e) { /* */ }
      $("#upload-state").textContent = "실패: " + msg;
    }
  };
  xhr.onerror = () => { $("#upload-state").textContent = "네트워크 오류"; };
  $("#upload-state").textContent = "업로드 중…";
  xhr.send(fd);
});

$("#btn-logout").addEventListener("click", logout);
boot();
