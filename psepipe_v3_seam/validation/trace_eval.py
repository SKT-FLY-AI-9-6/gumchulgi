# -*- coding: utf-8 -*-
"""trace_eval.py — trace 코퍼스(ITU 세트)를 pse_bt1702 로 전수 판정, 정답 대조.

정답은 각 생성 JSON 의 expected_result.itu_r1702_4 ("pass"/"fail").
우리 판정은 ITU 축(플래시·적색·패턴·5초지속)만 본다 — 화면전환(NAB-J 추가축)은
trace 정답에 없는 축이라 제외. 결과를 JSON 으로 남긴다.
"""
import glob, json, os, sys, time

sys.path.insert(0, "/home/user/gumchulgi/psepipe_v3_seam")
import pse_bt1702 as BT

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pse-test-media",
                    "video_creation")
SETS = ["30fps_alternating_01", "broadcast_30fps_01", "broadcast_30fps_combo01",
        "broadcast_30fps_inf01", "broadcast_30fps_inf02",
        "broadcast_30fps_red01", "broadcast_30fps_red02"]

rows = []
t0 = time.time()
for s in SETS:
    for jp in sorted(glob.glob(os.path.join(ROOT, s, "*.json"))):
        name = os.path.splitext(os.path.basename(jp))[0]
        cfg = json.load(open(jp))
        exp = cfg.get("expected_result", {}).get("itu_r1702_4")
        if exp not in ("pass", "fail"):
            continue
        vid = os.path.join(ROOT, s, "videos", name + ".avi")
        if not os.path.exists(vid):
            rows.append({"set": s, "clip": name, "expected": exp, "ours": "없음"})
            continue
        r = BT.analyze(vid, with_cut=False)   # 화면전환 축은 ITU 밖 — 제외
        itu_axes = [x for x in r["failed_rules"] if x != "화면전환"]
        ours = "fail" if itu_axes else "pass"
        rows.append({
            "set": s, "clip": name, "expected": exp, "ours": ours,
            "match": ours == exp, "failed": itu_axes,
            "flash_max": r["rules"]["flash"]["max_per_sec"],
            "flash_area": r["rules"]["flash"].get("max_area_pct"),
            "red_max": r["rules"]["red"]["max_per_sec"],
            "raw_flash": r["supplementary"]["flash_raw"]["max_per_sec"],
        })
        print(f"{s}/{name}: 정답 {exp} / 우리 {ours} "
              f"{'O' if ours == exp else 'X  <=='}", flush=True)

json.dump(rows, open(os.path.join(os.path.dirname(ROOT), "..", "trace_eval.json"),
                     "w"), ensure_ascii=False, indent=1)
n = [r for r in rows if "match" in r]
ok = sum(r["match"] for r in n)
print(f"\n== {len(n)}편 판정, 일치 {ok} ({ok/len(n)*100:.1f}%)  "
      f"{time.time()-t0:.0f}s")
for s in SETS:
    ss = [r for r in n if r["set"] == s]
    if ss:
        m = sum(r["match"] for r in ss)
        print(f"  {s:<24} {m}/{len(ss)}")
bad = [r for r in n if not r["match"]]
fp = [r for r in bad if r["ours"] == "fail"]
fn = [r for r in bad if r["ours"] == "pass"]
print(f"불일치 {len(bad)} = 오탐(정답 pass/우리 fail) {len(fp)} + "
      f"미탐(정답 fail/우리 pass) {len(fn)}")
