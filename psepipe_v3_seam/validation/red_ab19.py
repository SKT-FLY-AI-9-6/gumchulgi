# -*- coding: utf-8 -*-
"""red_ab19.py — 선형광 적색 패치(f013de9)의 19편 확대 재실행.

compare19.json 에 기록된 감마 시절 판정을 기준선으로, 현행(선형광) 검출기로
같은 클립들을 다시 돌려 축별로 대조한다. 클립 영상은 저장소에 없으므로
`data/s2_rand20` 을 가진 사람이 돌린다:

    python validation/red_ab19.py data/s2_rand20

기대 결과: 적색 축 이벤트/판정 전부 불변(실영상 7편 선행 A/B 와 동일)이고,
다른 축 차이가 있다면 그것은 선형광 패치가 아니라 이후 커밋 기원이므로
따로 표기된다.
"""
from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pse_bt1702 as BT  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    base = {r["clip"]: r["bt"]
            for r in json.load(open(os.path.join(HERE, "compare19.json"),
                                    encoding="utf-8"))}
    rows, missing = [], []
    for clip, old in base.items():
        hits = glob.glob(os.path.join(folder, clip + ".*"))
        if not hits:
            missing.append(clip)
            continue
        r = BT.analyze(hits[0])
        o_red, n_red = old["rules"]["red"], r["rules"]["red"]
        rows.append({
            "clip": clip,
            "verdict": (old["verdict"],
                        "적합" if r["compliant"] else "위반"),
            "red_events": (o_red.get("total_events", 0),
                           n_red.get("total_events", 0)),
            "red_area": (o_red.get("max_area_pct"), n_red.get("max_area_pct")),
            "other_axes_changed": sorted(
                set(old.get("failed_rules", [])) ^ set(r.get("failed_rules", []))
                - {"적색"}),
        })
    w = max((len(x["clip"]) for x in rows), default=10)
    print(f"{'클립':<{w}}  {'판정 전→후':<14}{'적색이벤트':<12}{'적색면적%':<16}비적색축 변화")
    bad = 0
    for x in rows:
        v0, v1 = x["verdict"]
        flag = "" if v0 == v1 and x["red_events"][0] == x["red_events"][1] \
                  and not x["other_axes_changed"] else "  <== 확인 필요"
        if flag:
            bad += 1
        print(f"{x['clip']:<{w}}  {v0}→{v1:<8}"
              f"{x['red_events'][0]}→{x['red_events'][1]:<8}"
              f"{x['red_area'][0]}→{x['red_area'][1]:<10}"
              f"{','.join(x['other_axes_changed']) or '-'}{flag}")
    if missing:
        print(f"\n영상 없음 {len(missing)}편: {' '.join(missing)}")
    print(f"\n{len(rows)}편 재실행, 차이 {bad}편"
          + (" — 전부 불변, 패치 무해 확인" if bad == 0 and rows else ""))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
