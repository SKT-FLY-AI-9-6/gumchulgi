# -*- coding: utf-8 -*-
"""기록이 대화에만 남았던 진단 2건을 파일로 재생성한다.

  ① GPU 회귀 — 이식 후에도 기존 동작(cera 플래시 -> 적합)이 유지되는가
  ② 마스크 토글 — 순 방향성 관문의 진동이 헤일로 역행을 만드는가
"""
import os, sys
sys.path.insert(0, os.getcwd())
import numpy as np
import pselive3 as P3, psegpu_full as PGF, pse_bt1702 as BT

CERA = os.environ.get("PSE_CERA", "cera_640.mp4")
TOG = os.path.join(os.environ.get("PSE_FLAGGED", "data/s1_flagged"), "Db2LyhvyHI5.mp4")

print("=" * 66)
print("① GPU 회귀 — 순 방향성을 켜도 진짜 플래시를 놓치지 않는가")
print("=" * 66)
print("원본:", BT.analyze(CERA, width=320)["failed_rules"] or "적합", flush=True)
for tag, kw in (("기준", {}), ("워프", {"warp_alpha": True}),
                ("순방향", {"net_directional": True}),
                ("둘다", {"warp_alpha": True, "net_directional": True})):
    dst = "_rg_%s.mp4" % tag
    r, _ = PGF.run(CERA, P3.Cfg(**kw), PGF.OptF(), video_out=dst,
                   warmup=4, progress=False)
    v = BT.analyze(dst, width=320)["failed_rules"] or ["적합"]
    print("%-5s 마스크 %.4f  차단 %4d/%-5d ms %.1f  판정 %s"
          % (tag, r["mean_mask_area"], r["net_blocked"], r["frames"],
             r["ms_per_frame"], ";".join(v)), flush=True)
    os.remove(dst)

print()
print("=" * 66)
print("② 마스크 토글 — Db2LyhvyHI5 헤일로 역행의 원인")
print("=" * 66)
for tag, kw in (("기준", {}), ("순방향", {"net_directional": True}),
                ("유지", {"net_directional": True, "net_hold": True})):
    rec = []
    orig = PGF.FullFilterGPU._detect
    def patched(self, lin_s, _r=rec, _o=orig):
        M = _o(self, lin_s); _r.append(float(M.float().mean())); return M
    PGF.FullFilterGPU._detect = patched
    try:
        r, _ = PGF.run(TOG, P3.Cfg(**kw), PGF.OptF(), warmup=0, progress=False)
    finally:
        PGF.FullFilterGPU._detect = orig
    on = np.array(rec) > 0.01
    tg = int((on[1:] != on[:-1]).sum())
    print("%-5s 프레임 %d  마스크 %.4f  켜짐 %3d  **토글 %2d회**  차단 %d"
          % (tag, len(rec), r["mean_mask_area"], int(on.sum()), tg,
             r["net_blocked"]), flush=True)
print()
print("토글이 늘수록 헤일로가 는다 — 헤일로는 면적이 아니라")
print("'원본에 없던 경계'를 재기 때문이다. (results_hyst.csv 참조)")
