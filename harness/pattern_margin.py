# -*- coding: utf-8 -*-
"""패턴 위반이 한도에 얼마나 가까운지 — 경계 판정인지 확실한 위반인지."""
import csv, os, sys
sys.path.insert(0, os.getcwd())
import pse_bt1702 as BT

D = os.environ.get("PSE_EXPLORE", "data/explore_100")
rows = list(csv.DictReader(open("results_reels_3way.csv", encoding="utf-8-sig")))
viol = [r for r in rows if r["before"] != "적합"]
safe = [r for r in rows if r["before"] == "적합"]
worse = [r for r in safe if any(r[k] != "적합" for k in ("A", "Dste", "AD"))]

out = []
def look(path, clip, kind):
    r = BT.analyze(path, width=320)
    p = r["rules"]["pattern"] if "rules" in r else None
    if not p:
        for v in r.values():
            if isinstance(v, dict) and v.get("rule") == "패턴": p = v
    co = (p or {}).get("co_axes", {})
    out.append((clip, kind, co.get("closeness"), p.get("violation_seconds"),
                p.get("max_pairs"), p.get("max_area_pct"), len(p.get("segments") or [])))
    print("%-13s %-8s close %-6s 지속 %-6ss 쌍 %-5s 면적 %-5s%% 구간 %d"
          % out[-1], flush=True)

for r in viol:
    look(os.path.join(D, r["clip"] + ".mp4"), r["clip"], "원본위반")
for r in worse:
    k = "A" if r["A"] != "적합" else ("Dste" if r["Dste"] != "적합" else "AD")
    sub = {"A": "A", "Dste": "Dste", "AD": "AD"}[k]
    look(os.path.join("out", sub, r["clip"] + ".mp4"), r["clip"], "악화-" + sub)

cl = [o[2] for o in out if o[2]]
print("\nclosseness 1.0~1.2 (경계): %d / %d" % (sum(1 for c in cl if c <= 1.2), len(cl)))
dur = [o[3] for o in out if o[3]]
print("위반 지속 1초 미만: %d / %d" % (sum(1 for d in dur if d < 1.0), len(dur)))
