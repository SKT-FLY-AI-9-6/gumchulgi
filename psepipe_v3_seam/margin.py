# -*- coding: utf-8 -*-
"""margin.py — 규칙별로 '얼마나 아슬아슬한가'를 잰다. 통과/위반만으로는 안 보인다."""
import sys, json
import cv2, numpy as np
sys.path.append("..")
import pse_bt1702 as BT

def red_profile(path, width=320):
    cap = cv2.VideoCapture(path); fps = cap.get(5) or 30.0
    rows = []
    while True:
        ok, f = cap.read()
        if not ok: break
        h0, w0 = f.shape[:2]
        s = cv2.resize(f, (width, max(2, int(round(h0*width/w0)))), interpolation=cv2.INTER_AREA)
        lin = BT.decode_linear(s)          # 채도비는 정본과 같이 선형광에서
        r, g, b = lin[...,0], lin[...,1], lin[...,2]
        tot = r+g+b+1e-6
        ratio = r/tot
        lit = s[...,2] >= int(BT.RED_MIN_V*255)
        rows.append([float((( ratio>=0.80)&lit).mean()),
                     float((( ratio>=0.70)&lit).mean()),
                     float((( ratio>=0.60)&lit).mean()),
                     float((( ratio>=0.50)&lit).mean()),
                     float(ratio[lit].mean()) if lit.any() else 0.0,
                     float(lit.mean())])
    cap.release()
    return fps, np.array(rows)

def report(path):
    r = BT.analyze(path, width=320)
    fps, P = red_profile(path)
    L=[f"═══ {path}   {r['duration_s']}s @ {r['fps']:.0f}fps"]
    L.append(f"  판정 {'적합' if r['compliant'] else '위반 — '+', '.join(r['failed_rules'])}")
    L.append("")
    L.append(f"  {'규칙':<12}{'측정':>12}{'한도':>10}{'여백':>10}  판정")
    def line(name, meas, lim, fmt="{:.2f}", higher_bad=True):
        m = meas/lim if lim else 0
        ok = meas <= lim if higher_bad else meas >= lim
        L.append(f"  {name:<12}{fmt.format(meas):>12}{fmt.format(lim):>10}"
                 f"{m*100:>9.0f}%  {'적합' if ok else '위반'}")
    f_, rd = r["rules"]["flash"], r["rules"]["red"]
    line("① 플래시 빈도", f_["max_per_sec"], 3, "{:.0f}")
    line("① 플래시 면적", f_["max_area_pct"], 25.0, "{:.1f}")
    line("② 적색 빈도", rd["max_per_sec"], 3, "{:.0f}")
    line("② 적색 면적", rd["max_area_pct"], 25.0, "{:.1f}")
    if "pattern" in r["rules"] and r["rules"]["pattern"].get("pass") is not None:
        p = r["rules"]["pattern"]
        line("③ 패턴 쌍수", p["max_pairs"], 5.0, "{:.1f}")
        line("③ 패턴 면적", p["max_area_pct"], 40.0, "{:.1f}")
    if "cut" in r["rules"] and r["rules"]["cut"].get("pass") is not None:
        c = r["rules"]["cut"]
        line("⑤ 컷 빈도", c["max_per_sec"], c["limit_per_sec"], "{:.0f}")
    fs = r["frame_separation"]
    obs = fs["observed_min_frames"]
    if obs is not None:
        line("⑥ 최소간격", obs, fs["required_frames"], "{:.0f}", higher_bad=False)
    sup = r["supplementary"]["rb"]
    L.append(f"  {'[보조] 적↔청':<12}{sup['max_per_sec']:>12}{3:>10}{'':>10}  "
             f"{'없음' if sup['pass'] else '검출'}")
    L.append("")
    L.append("  적색 채도 분포 — 왜 ② 가 안 걸렸는가 (R/(R+G+B), R>=0.25 화소만)")
    for i, th in enumerate((0.80, 0.70, 0.60, 0.50)):
        L.append(f"    비율>={th:.2f} 인 화면비율   최대 {P[:,i].max()*100:5.1f}%   "
                 f"평균 {P[:,i].mean()*100:5.1f}%   "
                 f"{'<- ② 의 정의' if th==0.80 else ''}")
    L.append(f"    밝은 화소의 평균 적색비   최대 {P[:,4].max():.3f}  평균 {P[:,4].mean():.3f}")
    L.append(f"    R>=0.25 화소 비율         최대 {P[:,5].max()*100:5.1f}%")
    return "\n".join(L)

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(report(p)); print()
