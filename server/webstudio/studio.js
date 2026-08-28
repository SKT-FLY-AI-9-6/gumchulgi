/* SoftReel Studio — 프레임워크 없는 단일 SPA (해시 라우팅).
   디자인: 노션 "SoftReel 리디자인 v1" 토큰 + "Reimagined v2" Studio 구조.
   서버 계약: /auth/*, /me, /videos(업로드·스트림·리포트), /studio/api/*,
   /admin/metrics. 스트림·썸네일 <video>/<img> 는 Authorization 헤더를 못
   보내므로 API 권한이 없는 단기 media token을 쿼리로 쓴다. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const state = { token: localStorage.getItem("tk"), mediaToken: null,
                me: null, pollTimer: null };

const RISK_KO = { safe: "SAFE 인증", corrected: "보정됨 · 완화", uncorrected: "미보정 위험" };
const RULE_KO = { "플래시": "플래시", "적색": "적색", "패턴": "패턴",
                  "화면전환": "화면전환", "5초지속": "5초지속" };
const AXES = [["flash", "플래시"], ["red", "적색"], ["pattern", "패턴"], ["cut", "화면전환"]];

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
  if (state.me.is_admin) $("#nav-analytics").hidden = false;
  if (!location.hash) location.hash = "#/dashboard";
  route();
}

/* ── 라우팅 ───────────────────────────────────────────── */
window.addEventListener("hashchange", route);

function route() {
  if (!state.me) return;
  clearInterval(state.pollTimer);
  const h = location.hash || "#/dashboard";
  document.querySelectorAll(".rail a").forEach(a =>
    a.classList.toggle("on", h.startsWith("#/" + a.dataset.nav)));
  const mVid = h.match(/^#\/video\/(\d+)/);
  if (mVid) return viewDetail(+mVid[1]);
  if (h.startsWith("#/content")) return viewContent();
  if (h.startsWith("#/analytics")) return viewAnalytics();
  return viewDashboard();
}

/* ── 대시보드 ─────────────────────────────────────────── */
async function viewDashboard() {
  const main = $("#main");
  main.innerHTML = `<h1>채널 대시보드</h1><div id="dash"></div>`;
  const { videos } = await api("/studio/api/videos");
  const n = (f) => videos.filter(f).length;
  const views = videos.reduce((a, v) => a + (v.view_count || 0), 0);
  const nProc = videos.filter(v => v.status === "processing").length;
  const latest = videos[0];
  $("#dash").innerHTML = `
    <div class="tiles">
      <div class="tile hero"><div class="k">SAFE 인증</div><div class="v">${n(v => v.risk === "safe" || v.risk === "corrected")} <small>/ ${videos.length}편</small></div></div>
      <div class="tile"><div class="k">안전 처리 중</div><div class="v">${n(v => v.status === "processing")}</div></div>
      <div class="tile"><div class="k">보정됨 · 완화</div><div class="v">${n(v => v.risk === "corrected")}</div></div>
      <div class="tile"><div class="k">미보정 위험</div><div class="v">${n(v => v.risk === "uncorrected")}</div></div>
      <div class="tile"><div class="k">총 조회수</div><div class="v">${views}</div></div>
    </div>
    ${latest ? `
    <div class="card" style="cursor:pointer" onclick="location.hash='#/video/${latest.id}'">
      <h2>최근 업로드</h2>
      <div class="vcell">
        <div class="vthumb" style="${latest.thumb_url ? `background-image:url('${mediaUrl(latest.thumb_url)}')` : ""}">${latest.thumb_url ? "" : "처리 중"}</div>
        <div>
          <div class="vtitle">${esc(latest.title)}</div>
          <div class="vsub">${fmtDate(latest.created_at)} · ${fmtDur(latest.duration_s)}</div>
          <div style="margin-top:6px">${riskBadge(latest)} ${axisChips(latest.stimulus)}</div>
        </div>
      </div>
    </div>` : `<div class="card empty">아직 업로드한 영상이 없습니다 — 오른쪽 위 <b>업로드</b>로 시작하세요.</div>`}
    <div class="card">
      <h2>안전 처리 파이프라인 ${nProc ? "— 지금 " + nProc + "편 처리 중" : ""}</h2>
      <div class="pipe ${nProc ? "live" : ""}">
        <span class="step"><span class="dot">⬆</span><span class="lbl"><b>업로드</b>정규화</span></span><span class="bar"></span>
        <span class="step"><span class="dot">◉</span><span class="lbl"><b>검출</b>pse_bt1702</span></span><span class="bar"></span>
        <span class="step"><span class="dot">≋</span><span class="lbl"><b>보정</b>strong→base 사다리</span></span><span class="bar"></span>
        <span class="step"><span class="dot">✓</span><span class="lbl"><b>재판정</b>무해 보장</span></span><span class="bar"></span>
        <span class="step"><span class="dot">▶</span><span class="lbl"><b>배포</b>SAFE 인증</span></span>
      </div>
      <div class="mini-note">보정본 판정은 항상 원본 이상임이 보장됩니다 (실사 209편 회귀 퇴보 0 — REGRESS_0820).</div>
    </div>`;
  if (videos.some(v => v.status === "processing"))
    state.pollTimer = setInterval(viewDashboard, 4000);
}

/* ── 콘텐츠 목록 ─────────────────────────────────────── */
async function viewContent() {
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
  main.innerHTML = `<h1>채널 콘텐츠</h1>
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

/* ── 영상 상세 ───────────────────────────────────────── */
async function viewDetail(id) {
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

/* ── 운영 지표 (관리자) ───────────────────────────────── */
async function viewAnalytics() {
  const main = $("#main");
  main.innerHTML = `<h1>운영 지표</h1><div id="an" class="card">불러오는 중…</div>`;
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
