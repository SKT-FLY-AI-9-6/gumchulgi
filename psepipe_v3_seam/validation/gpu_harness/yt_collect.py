# -*- coding: utf-8 -*-
"""유튜브 쇼츠 수집 + 검출기 라벨링.

인스타 표본(pse_collect.py)의 유튜브판. 로그인이 필요 없다는 게 차이다.
받은 뒤 pse_bt1702 로 바로 라벨을 붙여 위반/안전을 가른다 — 인스타 세트는
라벨이 이미 있었지만 여기는 직접 만들어야 한다.

사용:
    python yt_collect.py <출력폴더> <편수> "검색어1" "검색어2" ...
"""
import os, sys, csv, json, subprocess, time
sys.path.insert(0, os.getcwd())

OUT = sys.argv[1] if len(sys.argv) > 1 else "yt_reels"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TERMS = sys.argv[3:] or ["techno rave light show", "anime fight scene",
                         "gaming montage effects"]
os.makedirs(OUT, exist_ok=True)


def fetch(term, n):
    """검색어당 n 편.

    쇼츠만 노리면 표본이 안 모인다 — ytsearch 가 주는 건 대부분 장편이다.
    대신 **장편에서 40초 구간을 잘라 온다.** 제작자가 'flash warning' 을
    직접 단 영상이 많아 적중률도 이쪽이 높다. 30초부터 자르는 건 인트로
    (정지 로고·검은 화면)를 건너뛰기 위해서다.
    """
    got = []
    # --force-keyframes-at-cuts 는 재인코딩을 강제해서 일부 스트림에서
    # ffmpeg 이 죽는다(실측: 검색어 하나가 통째로 실패). 키프레임 경계 절단은
    # 시작점이 몇 프레임 어긋날 뿐이라 우리 용도엔 문제없다.
    cmd = ["python", "-m", "yt_dlp", f"ytsearch{n}:{term}",
           "--download-sections", "*30-70",
           "-f", "bv*[height<=720]+ba/b[height<=720]/b",
           "--merge-output-format", "mp4",
           "-o", os.path.join(OUT, "%(id)s.%(ext)s"),
           "--no-playlist", "--no-warnings", "--quiet", "--ignore-errors",
           "--print", "after_move:filepath"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        p = line.strip()
        if p and os.path.exists(p):
            got.append(p)
    if r.returncode != 0 and not got:
        print(f"  '{term}' 실패: {(r.stderr or '')[-200:]}", file=sys.stderr)
    return got


files = []
for t in TERMS:
    print(f"-- 검색: {t}", flush=True)
    g = fetch(t, N)
    print(f"   받음 {len(g)}편", flush=True)
    files += g

print(f"\n총 {len(files)}편 수집 -> 검출 시작\n", flush=True)

import pse_bt1702 as BT
import psepipe as PP
import tier as T

rows = []
for i, p in enumerate(files, 1):
    try:
        r = BT.analyze(p, width=320)
        t, why = T.tier(r)
        failed = r["failed_rules"]
        rows.append({"file": os.path.basename(p), "tier": t,
                     "failed": ";".join(failed), "path": p})
        print(f"  [{i}/{len(files)}] {os.path.basename(p):<20} {t:<8} "
              f"{','.join(failed) or '-'}", flush=True)
    except Exception as e:
        print(f"  [{i}/{len(files)}] {os.path.basename(p)} 오류 {type(e).__name__}: {e}",
              flush=True)

viol = [r for r in rows if r["failed"]]
print(f"\n검출 {len(rows)}편  위반 {len(viol)}편  "
      f"적중률 {len(viol)/max(len(rows),1)*100:.0f}%")
with open(os.path.join(OUT, "labels.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["file", "tier", "failed", "path"])
    w.writeheader(); w.writerows(rows)
print(f"CSV -> {OUT}/labels.csv")
