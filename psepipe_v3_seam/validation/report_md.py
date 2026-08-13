# -*- coding: utf-8 -*-
"""report_md.py — compare19 결과를 마크다운 보고서로 정리한다.

    python report_md.py --outdir out
"""
from __future__ import annotations

import argparse
import glob
import json
import os

CRIT = """
## 두 검출기의 기준 차이

| 항목 | A · pse_bt1702 | B · psecore v2.0 (bt1702 프로파일) |
|---|---|---|
| 위치 | 규격 판정 **정본** | 규격 밖 임상 채널 분석용 (파일 주석에 "정본 아님") |
| ① 플래시(휘도) | 프레임간 휘도차 · 어두운쪽 <160cd/m² 면 절대차 20cd/m², 이상이면 Michelson 1/17 | peak-valley 히스테리시스 상태기 · Δ상대휘도 ≥0.10 · 유효지속 50ms |
| ② 채도 적색 | R/(R+G+B) ≥0.8 & Δu'v' ≥0.2 | 동일 임계, 상태기 방식 |
| ③ 패턴(줄무늬·바둑판) | **있음** (pse_pattern) | **채널 없음 → 무조건 통과** |
| ④ 5초 지속 | **있음** (플래시·적색·패턴·컷 중 하나라도) | strict 모드에만 있음 (bt1702 프로파일엔 없음) |
| ⑤ 화면전환(빠른 컷) | **있음** (pse_cut) | **채널 없음 → 무조건 통과** |
| ⑥ 프레임 간격 | 보고만, 판정 제외 (BT.1702-3 허용 문언) | 갭 예외 334ms 로 시퀀스 분할에만 사용 |
| 적청 교대 RB | 보조 지표 — **판정에 넣지 않음** (규격 밖) | **FAIL 판정에 반영** (chroma_mode=fail) |
| RGB 채널별 | 없음 | warn 전용 (판정 미반영) |
| 빈도·면적 한도 | 3회/s 초과 & 화면 25% 이상 | 동일 |
| 면적 판정 | 전역 25% + **화소 동일성**(시퀀스 교집합 25% 미만이면 시퀀스 절단) | 전역 25% + **동기화 그룹**(20ms 내 전환을 한 묶음으로 면적 합산) |
| 움직임 보상 | **없음** | 위상상관 전역 보상 **ON** (흔들림 오탐 방지) |
| 분석 해상도 | 폭 320px | 짧은 변 240px |

**요약** — A 는 규격 조항(패턴·화면전환·5초지속)을 더 넓게 덮고, B 는 규격 밖
임상 축(RB 적청)을 판정에 넣는 대신 움직임 보상·상태기로 휘도 전환에 더 보수적이다.
그래서 불일치는 **양방향**으로 난다.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="out")
    a = ap.parse_args()

    agg = os.path.join(a.outdir, "compare19.json")
    rows = (json.load(open(agg, encoding="utf-8")) if os.path.exists(agg) else
            [json.load(open(p, encoding="utf-8"))
             for p in sorted(glob.glob(os.path.join(a.outdir, "json", "*.json")))])
    rows.sort(key=lambda r: r["clip"])

    L = ["# s2_rand20 — 두 검출기 위험 판정 비교", "",
         f"대상 {len(rows)}편 · `data/s2_rand20/` · "
         "A=`pse_bt1702.py`(분석폭 320px) / B=`psecore.py`(bt1702 프로파일)", "",
         "## 판정표", "",
         "| # | 영상 | A 판정 | A 단계 | A 위반 규칙 | B 판정 | B 위반 채널 | 일치 |",
         "|---|---|---|---|---|---|---|---|"]
    dis = []
    for i, r in enumerate(rows, 1):
        bt, pc = r.get("bt", {}), r.get("pc", {})
        ok = "O" if r.get("agree") else "**X**"
        if r.get("agree") is False:
            dis.append(r)
        L.append(f"| {i} | {r['clip']} | {bt.get('verdict','오류')} | "
                 f"{bt.get('tier','-')} | {', '.join(bt.get('failed_rules',[])) or '-'} | "
                 f"{pc.get('verdict','오류')} | "
                 f"{', '.join(pc.get('failed_channels',[])) or '-'} | {ok} |")
    nv_a = sum(1 for r in rows if r.get("bt", {}).get("verdict") == "위반")
    nv_b = sum(1 for r in rows if r.get("pc", {}).get("verdict") == "위반")
    L += ["", f"- A(pse_bt1702) 위반 **{nv_a}편** / {len(rows)}편",
          f"- B(psecore) 위반 **{nv_b}편** / {len(rows)}편",
          f"- 두 검출기 일치 **{len(rows)-len(dis)}편**, 불일치 **{len(dis)}편**"
          + (f" — {', '.join(r['clip'] for r in dis)}" if dis else ""), ""]

    # 여백없음(경계) 목록
    tight = [r for r in rows if r.get("bt", {}).get("tier") == "여백없음"]
    if tight:
        L += ["### A 기준 '여백없음'(통과지만 경계) 영상", "",
              "`tier.py` 는 한 규칙의 **모든 축**이 한도의 60% 이상이면 '여백없음'으로 "
              "본다. 통과이지만 조금만 바뀌어도 뒤집힌다는 뜻이다.", "",
              "| 영상 | 경계 규칙(축 = 측정/한도) |", "|---|---|"]
        for r in tight:
            L.append(f"| {r['clip']} | {', '.join(r['bt'].get('tier_why', [])) or '-'} |")
        L += ["", "> ③패턴 축이 100% 를 넘는데도 '적합'인 영상이 있다"
              "(Db4bFuguKZf 쌍수 438%·면적 269%, Db4XZ1vRDr9 100%·178%). "
              "패턴 규칙은 쌍수·면적 두 축을 **동시에** 넘은 상태가 "
              "**0.5초 이상 지속**돼야 위반으로 세는데, 이 영상들은 한순간만 넘고 "
              "곧 풀린다. `tier.py` 의 축 비율은 지속 조건을 반영하지 않으므로 "
              "100% 초과가 곧 위반은 아니다.", ""]

        L += ["### ③패턴 동시성 지표 (같은 프레임에서 잰 두 축)", "",
              "| 영상 | 쌍수 / 한도 | 면적% / 한도 | 근접도 | 위반 지속 |",
              "|---|---|---|---|---|"]
        for r in rows:
            p = (r.get("bt", {}).get("rules", {}) or {}).get("pattern") or {}
            c = p.get("co_axes") or {}
            if not c:
                continue
            L.append(f"| {r['clip']} | {c.get('pairs',0):.1f} / {c.get('need_pairs',0)} | "
                     f"{c.get('area_pct',0):.1f} / {c.get('need_area_pct',0)} | "
                     f"{c.get('closeness',0):.2f} | {p.get('violation_seconds',0)}s |")
        L += ["", "근접도 = min(쌍수/한도, 면적/한도). 1.00 이상이면 두 축을 동시에 "
              "넘은 프레임이 있다는 뜻이고, 그 상태가 0.5초 이상 이어져야 위반이 된다.", ""]

    if dis:
        L += ["## 불일치 영상 상세", ""]
        for r in dis:
            bt, pc = r["bt"], r["pc"]
            L += [f"### {r['clip']}", "",
                  f"- **A(pse_bt1702): {bt['verdict']}** — "
                  f"{', '.join(bt.get('failed_rules',[])) or '-'}",
                  f"- **B(psecore): {pc['verdict']}** — "
                  f"{', '.join(pc.get('failed_channels',[])) or '-'}", ""]
            R = bt.get("rules", {})
            L += ["| A 규칙 | 실측 | 판정 |", "|---|---|---|"]
            f, rd = R.get("flash", {}), R.get("red", {})
            L.append(f"| ① 플래시 | {f.get('max_per_sec',0)}회/s · 최대면적 "
                     f"{f.get('max_area_pct',0):.0f}% · {f.get('violation_seconds',0)}s |"
                     f" {'적합' if f.get('pass') else '위반'} |")
            L.append(f"| ② 적색 | {rd.get('max_per_sec',0)}회/s · 최대면적 "
                     f"{rd.get('max_area_pct',0):.0f}% |"
                     f" {'적합' if rd.get('pass') else '위반'} |")
            if "pattern" in R:
                p = R["pattern"]
                L.append(f"| ③ 패턴 | {p.get('max_pairs',0)}쌍 · 면적 "
                         f"{p.get('max_area_pct',0):.0f}% · "
                         f"{p.get('violation_seconds',0)}s |"
                         f" {'적합' if p.get('pass') else '위반'} |")
            L.append(f"| ④ 5초지속 | - | "
                     f"{'위반' if bt.get('sustained_over_5s') else '적합'} |")
            if "cut" in R:
                c = R["cut"]
                L.append(f"| ⑤ 화면전환 | 최대 {c.get('max_per_sec',0)}컷/s · 총 "
                         f"{c.get('total_cuts',0)}컷 · {c.get('violation_seconds',0)}s |"
                         f" {'적합' if c.get('pass') else '위반'} |")
            L += ["", "| B 채널 | 실측 | 판정 |", "|---|---|---|"]
            cs = pc.get("channel_seconds", {})
            best: dict = {}
            for v in pc.get("violations", []) + pc.get("warnings", []):
                m = v["measured"]
                b = best.setdefault(v["channel"], [0, 0.0])
                b[0] = max(b[0], m["flashes_per_sec"])
                b[1] = max(b[1], m["area_ratio"])
            fail, warn = set(pc.get("failed_channels", [])), set(pc.get("warn_channels", []))
            for ch, lab in (("LUM", "휘도"), ("RED", "채도 적색"), ("RB", "적청 교대"),
                            ("RGB", "RGB 채널별")):
                n, ar = best.get(ch, [0, 0.0])
                st = "위반" if ch in fail else ("주의(warn)" if ch in warn else "적합")
                L.append(f"| {lab} | {n}회/s · 면적 {ar*100:.0f}% · "
                         f"{cs.get(ch,0)}s | {st} |")
            ov = f"overlay_{r['clip']}.mp4"
            if os.path.exists(os.path.join(a.outdir, ov)):
                L += ["", f"오버레이: `out/{ov}` (스틸 `out/overlay_{r['clip']}_still.png`)"]
            L.append("")
    L.append(CRIT)

    p = os.path.join(a.outdir, "REPORT.md")
    with open(p, "w", encoding="utf-8") as fp:
        fp.write("\n".join(L))
    print(f"-> {p}")


if __name__ == "__main__":
    main()
