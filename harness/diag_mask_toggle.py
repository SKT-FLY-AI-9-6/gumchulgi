# -*- coding: utf-8 -*-
"""Db2LyhvyHI5 는 순 방향성에서 헤일로가 **역행**한 유일한 클립이다.
가설: 관문이 프레임마다 켜졌다 꺼졌다 하면 마스크 경계가 깜빡여
      오히려 새 경계를 만든다. 프레임별 마스크 면적/차단 여부를 본다.
"""
import os, sys
sys.path.insert(0, os.getcwd())
import numpy as np
import pselive3 as P3, psegpu_full as PGF

SRC = os.path.join(os.environ.get("PSE_FLAGGED", "data/s1_flagged"), "Db2LyhvyHI5.mp4")

def trace(**kw):
    rec = []
    orig = PGF.FullFilterGPU._detect
    def patched(self, lin_s):
        before = int(self.stats["net_blocked"])
        M = orig(self, lin_s)
        rec.append((float(M.float().mean()),
                    int(self.stats["net_blocked"]) - before))
        return M
    PGF.FullFilterGPU._detect = patched
    try:
        PGF.run(SRC, P3.Cfg(**kw), PGF.OptF(), warmup=0, progress=False)
    finally:
        PGF.FullFilterGPU._detect = orig
    return rec

for tag, kw in (("기준", {}), ("순방향", {"net_directional": True})):
    r = trace(**kw)
    area = np.array([x[0] for x in r])
    blk = np.array([x[1] for x in r])
    on = area > 0.01
    # 마스크가 켜짐/꺼짐을 오간 횟수 = 경계가 새로 생기고 사라진 횟수
    toggles = int((on[1:] != on[:-1]).sum())
    print("%-5s 프레임 %d  마스크평균 %.4f  켜진프레임 %d  **토글 %d회**  차단 %d"
          % (tag, len(r), area.mean(), int(on.sum()), toggles, int(blk.sum())))
    if tag == "순방향":
        # 차단이 연속인지 산발인지
        b = blk > 0
        runs = int((b[1:] & ~b[:-1]).sum()) + int(b[0])
        print("      차단 구간 %d개 (산발일수록 깜빡임)" % runs)
