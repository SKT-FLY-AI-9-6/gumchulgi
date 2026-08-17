# -*- coding: utf-8 -*-
"""results_reels_3way.csv -> 단일 HTML 리포트.

70편 표를 손으로 옮기면 반드시 틀린다. CSV 를 읽어 생성한다.
"""
from __future__ import annotations

import csv
import html

CSV_PATH = "results_reels_3way.csv"
OUT = "reels_3way_report.html"

rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
fl = lambda r, k: float(r[k]) if r[k] not in ("", None) else 0.0

viol = [r for r in rows if r["before"] != "적합"]
safe = [r for r in rows if r["before"] == "적합"]
worse = [r for r in safe if any(r[k] != "적합" for k in ("A", "Dste", "AD"))]
clean = [r for r in safe if r not in worse]

HMAX = max(max(fl(r, "A_halo"), fl(r, "Dste_halo"), fl(r, "AD_halo")) for r in rows)


def med(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def fixed(k):
    return sum(1 for r in viol if r[k] == "적합")


def worsened(k):
    return sum(1 for r in safe if r[k] != "적합")


def chip(v):
    if v == "적합":
        return '<span class="c ok">적합</span>'
    return '<span class="c bad">%s</span>' % html.escape(v)


def bar(v, kind):
    pct = min(100.0, v / HMAX * 100.0)
    return ('<div class="hb"><span class="hbf %s" style="width:%.1f%%"></span>'
            '<em>%.2f</em></div>' % (kind, pct, v))


def table(rs, cls=""):
    out = ['<div class="tw"><table class="%s">' % cls]
    out.append("<thead><tr><th>클립</th><th>해상도</th><th class=n>프레임</th>"
               "<th>원본</th><th>A</th><th>D_ste</th><th>A→D_ste</th>"
               "<th class=n>헤일로+ A</th><th class=n>D_ste</th><th class=n>A→D_ste</th></tr></thead><tbody>")
    for r in rs:
        sev = ("w" if r in worse else "v" if r in viol else "")
        out.append(
            '<tr class="%s"><th scope=row class=id>%s</th><td class=dim>%s×%s</td>'
            '<td class="n dim">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            "<td>%s</td><td>%s</td><td>%s</td></tr>"
            % (sev, html.escape(r["clip"]), r["w"], r["h"], r["frames"],
               chip(r["before"]), chip(r["A"]), chip(r["Dste"]), chip(r["AD"]),
               bar(fl(r, "A_halo"), "a"), bar(fl(r, "Dste_halo"), "d"),
               bar(fl(r, "AD_halo"), "ad")))
    out.append("</tbody></table></div>")
    return "\n".join(out)


stats = []
for k, lab in (("A", "A"), ("Dste", "D_ste"), ("AD", "A→D_ste")):
    hk = {"A": "A_halo", "Dste": "Dste_halo", "AD": "AD_halo"}[k]
    hs = [fl(r, hk) for r in rows]
    stats.append((lab, fixed(k), worsened(k), med(hs), sum(hs) / len(hs), max(hs)))

a_better = sum(1 for r in rows if fl(r, "A_halo") < fl(r, "Dste_halo"))
chain_worst = sum(1 for r in rows
                  if fl(r, "AD_halo") > max(fl(r, "A_halo"), fl(r, "Dste_halo")))

CSS = """
:root{
  --ground:#F5F7F8; --surface:#FFFFFF; --sunk:#EDF1F3;
  --ink:#131A1F; --ink2:#3D4A54; --muted:#67757F; --line:#D9E0E4;
  --accent:#0E6D8A; --bad:#A8291D; --badbg:#F7E7E4;
  --warn:#96660A; --ok:#456A60; --okbg:#E9F0ED;
  --ha:#A8291D; --hd:#0E6D8A; --had:#7A5C9E;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0D1216; --surface:#151C22; --sunk:#1B242B;
    --ink:#E6ECF0; --ink2:#B9C5CD; --muted:#85939D; --line:#2A353D;
    --accent:#54B6D4; --bad:#E8695F; --badbg:#3A1F1C;
    --warn:#DBA84A; --ok:#7BA396; --okbg:#1D2A27;
    --ha:#E8695F; --hd:#54B6D4; --had:#A98CD0;
  }
}
:root[data-theme="dark"]{
  --ground:#0D1216; --surface:#151C22; --sunk:#1B242B;
  --ink:#E6ECF0; --ink2:#B9C5CD; --muted:#85939D; --line:#2A353D;
  --accent:#54B6D4; --bad:#E8695F; --badbg:#3A1F1C;
  --warn:#DBA84A; --ok:#7BA396; --okbg:#1D2A27;
  --ha:#E8695F; --hd:#54B6D4; --had:#A98CD0;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Malgun Gothic",sans-serif;
  font-size:16px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1080px; margin:0 auto; padding:0 24px 96px}
.prose{max-width:68ch}
p{color:var(--ink2); margin:0 0 1em}
h1,h2,h3{color:var(--ink); text-wrap:balance; margin:0}
h1{font-size:2.5rem; line-height:1.12; letter-spacing:-.022em; font-weight:650}
h2{font-size:1.4rem; letter-spacing:-.012em; font-weight:640; margin:0 0 4px}
h3{font-size:1.02rem; font-weight:640; margin:0 0 6px}
.n,.id,.hb em,.big{font-family:"Cascadia Mono",Consolas,ui-monospace,"SF Mono",monospace;
  font-variant-numeric:tabular-nums}
header{padding:64px 0 40px}
.eyebrow{font-size:.72rem; letter-spacing:.16em; text-transform:uppercase;
  color:var(--accent); font-weight:660; margin:0 0 14px}
.lede{font-size:1.12rem; color:var(--ink2); max-width:62ch; margin:18px 0 0}
.meta{display:flex; flex-wrap:wrap; gap:8px 22px; margin:26px 0 0;
  font-size:.82rem; color:var(--muted); border-top:1px solid var(--line); padding-top:16px}
.meta b{color:var(--ink2); font-weight:600}
section{margin:52px 0 0}
.sechead{border-top:2px solid var(--ink); padding-top:14px; margin:0 0 22px}
.cards{display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; margin:0 0 26px}
.card{background:var(--surface); border:1px solid var(--line); border-radius:3px;
  padding:18px 18px 16px; border-top:3px solid var(--accent)}
.card.alert{border-top-color:var(--bad)}
.card h3{font-size:.76rem; letter-spacing:.1em; text-transform:uppercase; color:var(--muted);
  font-weight:660; margin:0 0 10px}
.big{font-size:2.1rem; line-height:1; font-weight:650; letter-spacing:-.02em}
.card.alert .big{color:var(--bad)}
.sub{font-size:.82rem; color:var(--muted); margin:8px 0 0}
.tw{overflow-x:auto; border:1px solid var(--line); border-radius:3px; background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:.84rem; min-width:840px}
th,td{text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:middle}
thead th{position:sticky; top:0; background:var(--sunk); color:var(--muted); font-size:.68rem;
  letter-spacing:.09em; text-transform:uppercase; font-weight:660; white-space:nowrap; z-index:1}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
th.n,td.n{text-align:right}
.id{font-size:.8rem; font-weight:500; color:var(--ink); white-space:nowrap}
.dim{color:var(--muted)}
tr.w th.id{box-shadow:inset 3px 0 0 var(--bad)}
tr.v th.id{box-shadow:inset 3px 0 0 var(--warn)}
.c{display:inline-block; font-size:.72rem; padding:2px 7px; border-radius:2px; white-space:nowrap;
  font-weight:600; letter-spacing:.01em}
.c.ok{background:var(--okbg); color:var(--ok)}
.c.bad{background:var(--badbg); color:var(--bad)}
.hb{display:flex; align-items:center; gap:8px; min-width:112px}
.hbf{height:7px; border-radius:1px; flex:0 0 auto; min-width:2px}
.hbf.a{background:var(--ha)} .hbf.d{background:var(--hd)} .hbf.ad{background:var(--had)}
.hb em{font-style:normal; font-size:.74rem; color:var(--muted); margin-left:auto}
.note{background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--accent);
  border-radius:2px; padding:16px 18px; margin:22px 0; font-size:.9rem; color:var(--ink2)}
.note b{color:var(--ink)}
ul{color:var(--ink2); padding-left:1.1em; margin:0 0 1em}
li{margin:0 0 .45em}
code{font-family:"Cascadia Mono",Consolas,ui-monospace,monospace; font-size:.86em;
  background:var(--sunk); padding:1px 5px; border-radius:2px; color:var(--ink)}
.legend{display:flex; flex-wrap:wrap; gap:16px; font-size:.78rem; color:var(--muted); margin:12px 0 0}
.legend i{display:inline-block; width:9px; height:9px; border-radius:1px; margin-right:6px}
footer{margin:64px 0 0; padding-top:18px; border-top:1px solid var(--line);
  font-size:.8rem; color:var(--muted)}
"""

doc = f"""<title>릴스 70편 필터 3파전</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <p class="eyebrow">광과민성 위험 완화 · 실사 검증</p>
  <h1>릴스 70편에서<br>필터 3종을 같은 자로 쟀다</h1>
  <p class="lede">인스타그램 Explore에서 무작위 수집한 실사 릴스를 원본 해상도 그대로
  A · D_ste · A→D_ste 에 통과시키고, 규격 판정과 이질감을 함께 측정했다.
  08-15 실측이 릴스 3편·360p 였던 자리를 채운다.</p>
  <div class="meta">
    <span><b>표본</b> 70편 / 100편</span>
    <span><b>해상도</b> 원본 (최대 3.10 MP)</span>
    <span><b>심판</b> pse_bt1702</span>
    <span><b>이질감</b> seam.py (인코딩 대조군 차감)</span>
    <span><b>장비</b> RTX 3050 Laptop 4GB</span>
    <span><b>일자</b> 2026-08-16~17</span>
  </div>
</header>

<section>
  <div class="sechead"><h2>결과 요약</h2></div>
  <div class="cards">
    <div class="card alert"><h3>악화 — A</h3><div class="big">4</div>
      <p class="sub">안전한 원본 60편 중</p></div>
    <div class="card alert"><h3>악화 — D_ste</h3><div class="big">3</div>
      <p class="sub">안전한 원본 60편 중</p></div>
    <div class="card alert"><h3>악화 — A→D_ste</h3><div class="big">5</div>
      <p class="sub">체인이 가장 나쁘다</p></div>
    <div class="card"><h3>체인이 최악인 클립</h3><div class="big">61<span
      style="font-size:1rem;color:var(--muted)">/70</span></div>
      <p class="sub">A→D_ste 헤일로 &gt; 두 단독</p></div>
  </div>

  <div class="prose">
  <p><b>08-15가 세운 “악화 0”이 무너졌다.</b> 합성 27클립과 실사 24편(720p, A 단독)에서는
  성립했지만, 원본 해상도 실사 70편에서는 세 구성 모두 안전한 영상을 위반으로 만들었다.
  그리고 <b>악화는 전부 ③패턴 축</b>에서 났다.</p>
  <p>두 번째 반전은 헤일로다. 08-15는 “A 3승 0패, D 헤일로만 한 자릿수 크다”였는데,
  D_ste 만 놓고 70편을 재니 <b>A 가 D_ste 보다 헤일로가 작은 클립은 {a_better}/70</b> 뿐이다.
  그때 D 는 D_full(신경망)이었고 표본이 3편이었다.</p>
  </div>

  <div class="tw"><table>
    <thead><tr><th>구성</th><th class=n>고침</th><th class=n>악화</th>
      <th class=n>헤일로+ 중앙</th><th class=n>평균</th><th class=n>최대</th></tr></thead>
    <tbody>
    {''.join('<tr><th scope=row class=id>%s</th><td class=n>%d/10</td>'
             '<td class="n"><b style="color:var(--bad)">%d</b></td>'
             '<td class=n>%.2f</td><td class=n>%.2f</td><td class=n>%.2f</td></tr>'
             % s for s in stats)}
    </tbody></table></div>
</section>

<section>
  <div class="sechead"><h2>악화 5편 — 필터가 만들어낸 위반</h2></div>
  <div class="prose"><p>원본은 규격 적합인데 출력이 위반으로 바뀐 클립이다.
  전부 <b>패턴 축</b>이고, 전부 <b>헤일로가 큰 쪽</b>에 몰려 있다.
  <code>pselive3.py</code> 헤더의 <b>지뢰 6</b>이 예측한 기전 — 반쯤 처리된 띠가 넓게
  이어지면 면적 규칙을 그대로 만족시킨다 — 과 일치한다.</p></div>
  {table(worse)}
</section>

<section>
  <div class="sechead"><h2>원본 위반 10편 — 전부 패턴</h2></div>
  <div class="prose"><p>수집된 70편 중 규격 위반은 10편이고 <b>플래시 위반이 한 편도 없었다.</b>
  A 가 잘하는 축이 플래시인데 그 표본이 안 잡혔다. 패턴 축에는 세 구성 모두 작동기가 없어,
  고쳐진 경우는 부수효과로 봐야 한다.</p></div>
  {table(viol)}
</section>

<section>
  <div class="sechead"><h2>전체 70편</h2></div>
  <div class="legend">
    <span><i style="background:var(--bad)"></i>악화</span>
    <span><i style="background:var(--warn)"></i>원본 위반</span>
    <span><i style="background:var(--ha)"></i>헤일로 A</span>
    <span><i style="background:var(--hd)"></i>D_ste</span>
    <span><i style="background:var(--had)"></i>A→D_ste</span>
  </div>
  <div style="height:14px"></div>
  {table(rows)}
</section>

<section>
  <div class="sechead"><h2>읽을 때 감안할 것</h2></div>
  <div class="prose">
  <ul>
    <li><b>라벨이 없다.</b> 위반 여부는 검출기가 매긴 것이라 검출기의 오탐이 그대로 섞인다.
      필터끼리의 순위는 같은 심판을 쓰므로 유효하지만, 성공률을 절대값으로 인용할 수는 없다.</li>
    <li><b>70/100편이다.</b> 앞 40편은 짧은 순, 뒤 30편은 무작위(seed 20260817)로 뽑았다.
      길이 편향이 완전히 제거되지는 않았다.</li>
    <li><b>실패 5편.</b> 1080×1920·2000프레임대 클립에서 A 가 실패했다. 4GB VRAM OOM 으로 보이며
      표에서 빠져 있다.</li>
    <li><b>D_full 은 재지 않았다.</b> 4GB 로는 원본 해상도에서 돌지 않는다.</li>
    <li>헤일로는 인코딩 대조군을 뺀 초과분이다. 절대값이 아니라 구성 간 비교로 읽어야 한다.</li>
  </ul>
  </div>
</section>

<footer>results_reels_3way.csv 에서 생성 · mkreport.py · 70편 / 총 {sum(int(r['frames']) for r in rows):,}프레임</footer>
</div>
"""

open(OUT, "w", encoding="utf-8").write(doc)
print("생성:", OUT, len(doc), "bytes")
print("악화 %d · 위반 %d · 무사 %d" % (len(worse), len(viol), len(clean)))
