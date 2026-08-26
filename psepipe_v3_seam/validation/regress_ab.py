# -*- coding: utf-8 -*-
"""regress_ab.py — 필터 설정 A/B 회귀 (기본값 승격 관문).

같은 클립 무리에 대해 base 설정과 cand(후보) 설정으로 A 필터를 돌리고,
심판(pse_bt1702) 판정과 이질감 3축(펌핑/헤일로/잔상, seam)을 나란히 잰다.
net_directional / detail_sigma 같은 후보를 기본값으로 승격하기 전의 관문:

    악화 0 (적합 원본을 위반으로 만들거나, 위반 원본에 없던 규칙을 추가) 이
    절대 조건이고, 제거(위반->적합)가 base 대비 줄면 안 된다.

사용 (CPU, 저장소 합성 클립):
    python regress_ab.py testclips/*.mkv --cand "net_directional=True,detail_sigma=32"

사용 (GPU 노트북 — 27클립 + 실사 209편, psegpu_full 경로):
    python regress_ab.py synth/*.mp4 genre/*.mp4 run3/seg6.mp4 --gpu \
        --cand "net_directional=True,detail_sigma=32" --csv regress_27.csv
    python regress_ab.py 실사폴더/*.mp4 --gpu \
        --cand "net_directional=True,detail_sigma=32" --csv regress_real.csv

--lossless 는 출력을 FFV1 로 저장해 인코더 양자화를 판정에서 제거한다
(rawmeasure 발견 — 디스크를 크게 먹으므로 최종 확정 측정에만).
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pse_bt1702 as BT
import pselive3 as P3
import seam


def parse_cfg(spec: str) -> dict:
    """"net_directional=True,detail_sigma=32" -> dict. 값은 파이썬 리터럴."""
    out = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        k, v = part.split("=", 1)
        out[k.strip()] = eval(v.strip(), {"__builtins__": {}})  # noqa: S307 — 리터럴만
    return out


def build_cfg(kw: dict):
    c = P3.Cfg()
    for k, v in kw.items():
        if not hasattr(c, k):
            raise SystemExit(f"Cfg 에 없는 필드: {k}")
        setattr(c, k, v)
    return c


def run_filter(src, out_path, kw, use_gpu, lossless):
    cfg = build_cfg(kw)
    if use_gpu:
        import psegpu_full as PGF
        rep = PGF.run(src, cfg, PGF.OptF(), video_out=out_path, lossless=lossless,
                      progress=False)
        rep = rep[0] if isinstance(rep, tuple) else rep
    else:
        rep, _ = P3.run(src, cfg, video_out=out_path, lossless=lossless,
                        verbose=False)
    return rep


def vmaf_score(dist: str, ref: str) -> float | None:
    """ffmpeg libvmaf 지각 화질 점수. 없거나 실패하면 None.

    **읽는 법**: 필터는 원본을 의도적으로 바꾸므로 절대값이 아니라 base 대비
    Δ 로만 읽는다. 강억제 클립의 낮은 절대 점수는 정상이고, 반대로 억제가
    샌 클립은 "원본에 가깝다"는 이유로 점수가 높게 나온다 — VMAF 는 심판을
    대체하지 못하는 **보조축**이다(2026-08-26 PoC 실측, docs/AI-이식-PoC-실측.md).
    """
    import re as _re
    import subprocess
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", dist, "-i", ref, "-lavfi",
           "[0:v]setpts=PTS-STARTPTS[d0];[1:v]setpts=PTS-STARTPTS[r0];"
           "[d0][r0]scale2ref=flags=bicubic[d][r];[d][r]libvmaf=n_threads=4",
           "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except OSError:
        return None
    m = _re.search(r"VMAF score:\s*([\d.]+)", p.stderr)
    return round(float(m.group(1)), 2) if m else None


def classify(before, base_after, cand_after):
    """cand 를 base 와 대조해 한 단어로: 동일 / 개선 / 악화 / 변화."""
    if cand_after == base_after:
        return "동일"
    worse_vs_src = [r for r in cand_after if r not in before]
    if worse_vs_src:
        return "악화(신규 " + ",".join(worse_vs_src) + ")"
    if len(cand_after) < len(base_after):
        return "개선"
    if len(cand_after) > len(base_after):
        return "퇴보"
    return "변화"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--base", default="", help='base 설정 (기본: Cfg() 그대로)')
    ap.add_argument("--cand", required=True,
                    help='후보 설정, 예: "net_directional=True,detail_sigma=32"')
    ap.add_argument("--gpu", action="store_true", help="psegpu_full 경로 사용")
    ap.add_argument("--lossless", action="store_true", help="출력 FFV1 (최종 확정용)")
    ap.add_argument("--no-ghost", action="store_true", help="이질감 3축 측정 생략(판정만)")
    ap.add_argument("--vmaf", action="store_true",
                    help="지각 화질(VMAF) 열 추가 — base 대비 Δ 로만 읽을 것")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--workdir", default="_regress")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    base_kw, cand_kw = parse_cfg(a.base), parse_cfg(a.cand)
    ext = ".mkv" if a.lossless else ".mp4"

    srcs = []
    for s in a.srcs:
        srcs += sorted(glob.glob(s)) if any(ch in s for ch in "*?[") else [s]

    rows = []
    n_worse = n_gain = n_loss = 0
    for src in srcs:
        name = os.path.splitext(os.path.basename(src))[0]
        before = BT.analyze(src)["failed_rules"]
        row = {"clip": name, "전": ",".join(before) or "적합"}
        ctrl = None
        if not a.no_ghost:
            ctrl = os.path.join(a.workdir, name + "_ctrl.mp4")
            if not os.path.exists(ctrl):
                seam.make_control(src, ctrl)
        for tag, kw in (("base", base_kw), ("cand", cand_kw)):
            out = os.path.join(a.workdir, f"{name}_{tag}{ext}")
            t0 = time.time()
            run_filter(src, out, kw, a.gpu, a.lossless)
            after = BT.analyze(out)["failed_rules"]
            row[tag] = ",".join(after) or "적합"
            row[tag + "_sec"] = round(time.time() - t0, 1)
            row[tag + "_신규위반"] = ",".join(r for r in after if r not in before)
            if a.vmaf:
                row[tag + "_vmaf"] = vmaf_score(out, src)
            if not a.no_ghost:
                m = seam.measure(src, out)
                b = seam.measure(src, ctrl)
                row[tag + "_헤일로+"] = round(max(m["halo"] - b["halo"], 0.0), 2)
                row[tag + "_잔상"] = f"{m['ghost_lag']:.2f}/" \
                                     f"{max(m['ghost_drag']-b['ghost_drag'],0.0):.3f}"
        row["대조"] = classify(before, row["base"].split(",") if row["base"] != "적합" else [],
                             row["cand"].split(",") if row["cand"] != "적합" else [])
        if row["대조"].startswith("악화"):
            n_worse += 1
        elif row["대조"] == "개선":
            n_gain += 1
        elif row["대조"] == "퇴보":
            n_loss += 1
        rows.append(row)
        print(f"{name:<28} 전 {row['전']:<16} base {row['base']:<16} "
              f"cand {row['cand']:<16} {row['대조']}", flush=True)

    cols = list(rows[0].keys()) if rows else []
    print(f"\n총 {len(rows)}편 — 동일 {sum(r['대조']=='동일' for r in rows)} / "
          f"개선 {n_gain} / 퇴보 {n_loss} / 악화 {n_worse}")
    print("악화 0" if n_worse == 0 else "** 악화 발생 — 승격 불가 **")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
        print(f"CSV -> {a.csv}")


if __name__ == "__main__":
    main()
