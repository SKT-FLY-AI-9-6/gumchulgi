# -*- coding: utf-8 -*-
"""tier.py — 3단계 판정.  OR 은 반증됐고(안전 10편 중 8편 오탐), AND 만으로는
여백을 못 본다. 그래서 **규칙 안에서 모든 축이 한도의 X% 이상이면 '여백 없음'**
으로 본다. AND 규칙이니 어느 한 축이 확실히 낮으면 그게 곧 안전 여유다."""
import os, sys
import pse_bt1702 as BT, psepipe as PP

def rule_axes(r):
    A = PP.axes(r)
    g = {}
    for n, m, l, act in A:
        g.setdefault(n[0], []).append((n, m / l if l else 0, act))
    return g

def tier(r, warn=0.60):
    if not r["compliant"]:
        return "위반", [x for x in r["failed_rules"]]
    tight = []
    for rule, ax in rule_axes(r).items():
        if len(ax) >= 2 and all(v >= warn for _, v, _ in ax):
            tight.append(f"{rule}({'/'.join(f'{n[1:]}{v*100:.0f}%' for n, v, _ in ax)})")
    return ("여백없음" if tight else "안전"), tight

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="3단계 판정 — 위반 / 여백없음 / 안전")
    ap.add_argument("srcs", nargs="+", help="영상 파일 (여러 개 가능)")
    ap.add_argument("--warn", type=float, default=0.60,
                    help="한 규칙의 모든 축이 한도의 이 비율 이상이면 '여백없음' (기본 0.60)")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--no-pattern", action="store_true", help="패턴 검사 생략 (빠름)")
    ap.add_argument("--no-cut", action="store_true", help="화면전환 검사 생략")
    ap.add_argument("--migraine", choices=["t4", "t5"], default=None,
                    help="편두통 축(M1 정적패턴·M2 색상)도 검사 — WARN 전용, "
                         "3단계 판정에는 반영하지 않는다 (pse_migraine.py)")
    a = ap.parse_args()

    print(f"{'영상':<34}{'판정':<12} 근거")
    print("-" * 88)
    for c in a.srcs:
        if not os.path.exists(c):
            print(f"{os.path.basename(c):<34}{'파일없음':<12} {c}")
            continue
        try:
            r = BT.analyze(c, width=a.width, with_pattern=not a.no_pattern,
                           with_cut=not a.no_cut)
        except Exception as exc:
            print(f"{os.path.basename(c):<34}{'오류':<12} {type(exc).__name__}: {exc}")
            continue
        t, why = tier(r, a.warn)
        print(f"{os.path.basename(c):<34}{t:<12} {', '.join(why) or '-'}")
        if t != "안전":
            for n, m, l, act in PP.axes(r):
                if l:
                    print(f"      {n:<8}{m:8.1f} / {l:6.1f} = {m/l*100:5.0f}%"
                          f"   작동기 {act}")
        if a.migraine:
            # 별도 디코드로 돈다 (규격 판정과 뒤섞이지 않도록 의도적 분리).
            # 속도가 문제가 되면 pse_migraine.Stream 을 BT.analyze 루프에
            # pat_stream 과 나란히 끼우는 것이 다음 단계다.
            import pse_migraine
            try:
                mr = pse_migraine.analyze(c, tier=a.migraine, width=a.width)
                print(pse_migraine.brief(mr))
            except Exception as exc:
                print(f"      MIGRAINE 오류: {type(exc).__name__}: {exc}")
