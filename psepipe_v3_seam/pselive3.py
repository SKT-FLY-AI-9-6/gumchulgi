# -*- coding: utf-8 -*-
"""
pselive3.py — 실시간 PSE 필터 : **화소별 변화율 제한(slew limit)**

설계 원리
================================================================================
BT.1702 의 플래시는 화소의 값이 임계 이상 **변할 때** 성립한다.
그러니 위험 화소의 프레임 간 변화 벡터 d = 현재 - 직전출력 을 **하나의 스칼라 k 로**
줄인다.

    out = prev + k·d ,    k = min(1, S_lum/|dY|, S_chr/|d_chr|_max)

출력이 prev -> 현재 선분 위에 남으므로
  · 휘도 변화 |ΔY| <= S_lum
  · 색 성분 변화 <= S_chr
  · **색도 경로가 정확히 보존된다** (성분별로 자르면 색상이 회전한다)
공간 연산이 없으므로 블러가 원리적으로 불가능하고, 상태는 직전 출력 한 장이라
O(1) 메모리 · 선행 버퍼 0 · **지연 0 프레임**이다.

S 는 판정기 정의에서 유도한다.
psecore 의 PeakValley 는 직전 프레임이 아니라 T_qualify(50ms) 창 안의 **극값**과
비교하므로, 창 안에서 누적 가능한 변화는 n_look × S 다.

    n_look × S < θ      ->      S = safety × θ / n_look

--------------------------------------------------------------------------------
여기까지 오면서 실측으로 밟은 지뢰 (전부 되돌리지 말 것)
--------------------------------------------------------------------------------
1. 머리 프레임 누락 (v2)
   pop() 이 버퍼가 찬 뒤에야 첫 프레임을 내보내서 앞 1.4초가 생스트로브로 통과.
   v3 는 인과적이라 구조적으로 사라졌다.

2. 섬광을 컷으로 오인
   컬러 히스토그램 교집합으로 컷을 잡으면 전면 흑<->백 스트로브가 매 프레임 '컷'.
   매 프레임 상태 리셋 -> 제한이 아예 안 걸림 (합성 01: 6.40s -> 6.40s).
   -> 대비 정규화 NCC 로 교체. 추가로 **단색 프레임은 컷의 증거가 될 수 없다**
      (정규화하면 0 이라 NCC 도 0) -> 구조 없는 프레임은 판정 보류.

3. 감마 공간에서 제한 금지
   psecore 는 sRGB EOTF 를 거친 **선형** 값으로 임계를 잰다.
   밝은 쪽에서 8비트 20 스텝은 선형 0.136 — 임계 0.10 초과.
   (seg6: S 를 올렸더니 0.12s -> 1.04s 로 역행)

4. 휘도 하나만 보면 색 점멸을 못 잡는다
   등휘도 적<->녹(03)은 휘도가 안 변해 마스크가 안 켜졌다(13.93s 그대로).
   -> 검출도 선형 R,G,B **채널별**로 돌려 OR.

5. 성분별로 자르면 색상이 회전한다  <- 가장 큰 실패
   d_ach = dY·(1,1,1) 를 더하는 순간 순수 적색의 G,B 가 0 에서 들린다.
   10번은 입력이 LUM 만 위반했는데 출력에 **없던 BY 위반(d=0.68)** 이 생겼다.
   -> 벡터 전체를 스칼라 k 하나로 줄이는 현재 형태로 교체.
      (03/08/10/12 가 전부 FAIL -> PASS 로 뒤집힌 지점)

6. 페더링이 보증을 깬다
   0<A<1 화소의 실제 변화는 A·(제한) + (1-A)·(원본) 이라 상한을 넘는다.
   그런 반쯤 처리된 띠가 넓게 이어지면 면적 규칙(25%)을 그대로 만족시킨다.
   (14번 흐르는 줄무늬: 페더 5px -> 5.60s, 페더 0 -> 0.26s)
   -> **알파를 k 에 되먹여 보정한다.** 합성 결과가 상한을 만족하도록
      k = (kmax - (1-A))/A 로 풀고, 그래도 모자라면 A 를 필요한 만큼만 올린다.

7. 원추 대비 공간 제한 시도 — **실패, 채택 안 함**
   RG/BY 가 cc = LMS/LMS_bg - 1 위에 정의되니 그 좌표계에서 자르는 게 맞아 보였다.
   그러나 배경 LMS 가 시간 적응이라 제한->배경이동->대비재계산 되먹임이 생기고,
   판정기는 **자기 배경**으로 다시 재기 때문에 우리 배경과 어긋난다.
   실측 평균적으로 더 나빴다(03: 5.14 -> 8.71, 12: 1.77 -> 9.33). 코드에서 제거.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass

import cv2
import numpy as np

import psecore as PC

__version__ = "3.1.0"


@dataclass
class Cfg:
    # ---- 검출 (psecore 와 같은 정의)
    theta_lum: float = 0.10
    theta_dark: float = 0.80
    michelson: float = 1.0 / 17.0
    T_qualify_ms: float = 50.0
    arm_count: float = 2.0          # 3회가 되기 전에 미리 무장
    arm_area: float = 0.20          # **면적 규칙**: 10도 창 점유율이 이 아래면 개입하지 않는다
                                    #   (표준 임계 0.25 보다 살짝 낮게 — 경계 직전부터 잡는다)
    # ---- 변화율 상한
    slew_frac: float = 0.0          # 0 이면 fps 에서 자동 유도
    slew_safety: float = 0.80
    slew_chroma: float = 0.010      # 색 성분 상한 (선형 RGB 절대량, **경험값**)
    alpha_compensate: bool = False  # 페더 보정 — 14번엔 도움, 나머지엔 손해라 기본 off
    # ---- 자기감시 폐루프 (never-worse)
    guard: bool = True              # 출력에도 검출기를 돌려 악화하면 스스로 물러난다
    guard_margin: float = 0.01      # 출력 위험면적이 입력보다 이만큼 크면 악화로 본다
    guard_tau_s: float = 0.4        # 판단용 EMA 시상수
    guard_down: float = 0.85        # 악화 시 개입 강도 배율
    guard_up: float = 0.03          # 정상 시 회복 속도
    # 후퇴 금지 기준 면적 — "입력이 이미 대규모 위반"의 기준은 **규격 선점
    # 면적(0.20)** 이지 티어의 arm_area 가 아니다. T4 실측(travis)에서
    # arm_area 를 0.08 로 좁히자 후퇴 금지 조건도 따라 좁아져 가드가 다시
    # 붕괴했다(gain_min 0.0 — 판정은 살았지만 같은 구멍의 재발이다).
    guard_hold_area: float = 0.20
    # ---- 마스크 성형
    dilate_px: int = 3
    # 0 이 아니면 **지뢰 6** 이 살아난다 — 0<A<1 인 페더 띠의 실제 변화는
    # A·k + (1-A) 라 상한을 넘고, 그 반쯤 처리된 띠가 넓게 이어지면 면적 규칙을
    # 그대로 만족시켜 **없던 위반이 생긴다**(14번 흐르는 줄무늬).
    # 27클립 전수 실측 (악화 = 안전한 원본을 위반으로 만든 클립 수):
    #   페더 5.0 -> 악화 1 (14번 0.00->1.54)      2.0 -> 악화 0, 잔여 0.16
    #   페더 1.5 -> 악화 0, 잔여 0.16             1.0 -> 악화 1 (0.00->0.94)
    #   페더 0.5 -> 악화 1 (0.00->1.20)           0.0 -> 악화 0, 잔여 0.00
    # **비단조다.** 1.5/2.0 이 통과하는 건 이 코퍼스에서 우연히 면적 규칙을
    # 안 넘은 것이고, 0 만이 페더 띠라는 기전 자체를 없앤다.
    # (alpha_smooth 때문에 시간축 부분 알파는 남는다 — 완전한 증명은 아니다.)
    # alpha_compensate 로도 막히지만 마스크 면적이 넓어져 선명도가 80%->46% 로
    # 깎인다(01번). 페더 0 은 선명도를 그대로 두므로 이쪽을 쓴다.
    # 대가: 마스크 경계가 딱딱해져 헤일로가 는다 (22번 13.0 -> 17.5).
    feather_px: float = 0.0
    # 시간축 부분 알파(전이 구간의 0<A<1)도 페더와 같은 이유로 상한을 깬다.
    # GPU 14번 실측: alpha_smooth 0.5 -> 1.14s, 0.75 -> 0.14s, 1.0 -> 0.00s (단조).
    # 그런데 1.0 으로 올리면 **CPU 가 0.00 -> 0.26 으로 역행**하고 선명도도
    # 광범위하게 깎인다 (01번 80%->46%, 02번 94%->65%). 그래서 채택하지 않았다.
    alpha_smooth: float = 0.5
    hold_s: float = 0.25
    # ---- 질감 복원
    detail_sigma: float = 2.0       # >0 이면 레벨만 제한, 밝기 고역은 현재 프레임에서
    # ---- 부호 일관성 게이트 (잔상 대책)
    # 슬루 제한은 **모든 변화**를 누른다. 그런데 위반은 점멸이지 움직임이 아니다.
    # 움직이는 화소까지 눌리니 잔상이 생긴다 (실측 drag 0.31~0.46 — 움직인 화소에서
    # 출력이 입력 변화의 31~46% 를 못 따라간다).
    #
    # **두 가지를 시도했고 둘 다 실패했다. 다시 하지 말 것.**
    #
    #   (a) 부호 일관성 — 플래시는 넓은 영역이 같은 방향으로 변하고 움직임은
    #       경계에서 엇갈린다고 보고 sign(Δ) 의 국소 평균으로 갈랐다.
    #         gate 0.0/0.3/0.5/0.7/1.0 -> 제거율 92.8 / 60.0 / 59.7 / 59.1 / 56.7 %
    #       공간적으로 복잡한 점멸을 움직임으로 오인한다 (TXeDgXiytM0 99->0%).
    #
    #   (b) 국소 정규화 상관(NCC) — 플래시는 레벨만 바꾸고 구조는 유지한다고 보고
    #       창 단위 NCC 로 갈랐다.  더 나쁘다:
    #         gate 0.0/0.3/0.5 -> 제거율 92.8 / 47.1 / 40.6 %,  악화 0 / 1 / 1
    #       실사에서는 스트로브가 포화·클리핑을 일으켜 **구조도 바꾼다**.
    #
    # 공통 원인: 점멸과 움직임은 **같은 곳에서 동시에** 일어난다 (스트로브 아래
    # 춤추는 사람). 움직임이 있는 곳의 개입을 줄이면 곧 위반이 있는 곳의 개입을
    # 줄이는 것이다. **입력을 보고 '어디에 개입할지' 정하는 방식으로는 잔상을
    # 못 잡는다.** 남은 정공법은 움직임 보상을 국소화해서(광학흐름/블록매칭)
    # d = lin - warp(prev) 에서 움직임 성분을 빼는 것이다 — 그러면 슬루 제한이
    # 플래시 성분에만 걸린다. 현재 워프는 전역 평행이동 하나뿐이다.
    coh_gate: float = 0.0           # 0 = 꺼짐. 위 이유로 켜지 말 것
    coh_win: int = 9
    # ---- 순 방향성 관문 [seunghoon 브랜치에서 가져옴]
    # 위 잔상 게이트들이 "어디에 개입할지"를 국소로 판단하려다 실패한 것과 달리,
    # 이건 **심판이 실제로 쓰는 판별자**를 그대로 가져온다.
    #
    # 화소 단위로는 팬과 플래시가 구분되지 않는다. 카메라가 움직이면 어두운 벽에
    # 있던 화소 자리에 밝은 창문이 들어오고, 그 ΔY 는 플래시의 정의를 만족한다.
    # 심판(pse_bt1702)은 net = 밝아진면적 - 어두워진면적 으로 막는다 — 팬은 양쪽이
    # 맞먹어 상쇄되고(실측 0.239/0.237 -> 0.089) 점멸은 한 방향이 압도한다(1.000).
    # 그런데 필터가 쓰는 psecore 에는 그 관문이 없다. psecore 의 움직임 보상은
    # 주석대로 "전역(팬) 한정"이라 줌·회전·피사체 움직임에 뚫린다.
    #
    # seunghoon 실측 (대표 8편, pse_bt1702 기준, 불응기 0.2 위에서):
    #   기준    헤일로 35.59  악화 4/8
    #   순방향  헤일로  9.40  악화 0/8
    # 미탐 검증: 진짜 플래시는 놓치지 않는다 (cera 마스크 0.4002->0.3503 이지만
    # 판정은 플래시->적합, 움직임 클립은 마스크가 통째로 꺼진다 0.3594->0.0000).
    # **지뢰: 순방향은 채널별 최댓값으로 잴 것** (2026-08-18). 채널 OR 마스크로
    # 재면 등휘도 색 점멸(같은 화소 R↑·B↓ 동시)이 상쇄돼 관문이 닫히고 합성
    # 06/07 적색 위반이 잔존했다(퇴보 2). 채널별로 바꾼 뒤 14클립 회귀 재통과.
    net_directional: bool = False
    # ---- 국소 움직임 보상 (잔상 대책 — 위 게이트 실패의 정공법)
    # 전역 평행이동 워프는 화면 전체가 같이 움직일 때만 맞다. 배경 고정 +
    # 인물 이동 같은 국소 움직임은 보상되지 않아 슬루 제한에 걸리고 그게 잔상이다.
    # 블록매칭으로 화소별 벡터를 구해 prev 를 끌어오면 d 에서 움직임이 상쇄되고
    # 점멸만 남는다.
    #
    # **구현했고 측정했다. 원리는 맞지만 효과가 없어 기본값 off 로 둔다.**
    #   설정                    제거율   drag    악화   ms
    #   끔                      100.0%  0.492    0     8.5
    #   blk16 r8 s2 gain.15      99.1%  0.469    0    12.2
    #   blk16 r8 s2 gain.05      98.9%  0.468    0    12.5
    # 앞의 두 게이트(coh_gate)와 달리 **제거율이 유지된다** — 개입 범위를 안
    # 건드리고 d 에서 움직임만 빼기 때문이다. 그런데 잔상 개선이 4.7% 뿐이고
    # 시간은 44% 는다. 채택할 근거가 없다.
    #
    # 이유: **잔상의 대부분이 움직임 때문이 아니라 기전 자체다.** 점멸을 누른다는
    # 건 휘도를 직전 수준에 붙잡아 둔다는 뜻이고, 화면이 '이전 프레임에 머무는'
    # 것처럼 보이는 그 현상이 곧 보정이 작동하는 모습이다. 움직임 보상으로 걷어낼
    # 수 있는 건 움직임 때문에 **추가로** 걸린 몫뿐인데 그게 5% 수준이었다.
    # 잔상과 점멸 억제는 같은 동전의 양면이라 슬루 제한 설계 안에서는 못 넘는다.
    local_mc: bool = False
    lmc_radius: int = 8             # 탐색 반경 (분석 해상도 화소)
    lmc_step: int = 2               # 탐색 간격
    lmc_block: int = 16             # 블록 크기
    lmc_min_gain: float = 0.15      # 무변위 대비 SAD 가 이만큼 좋아야 채택
    # ---- 움직임 보상
    motion_comp: bool = True
    motion_resp: float = 0.10       # 위상상관 신뢰도 하한 (주기 패턴이 여기서 걸러진다)
    motion_max_px: float = 24.0
    # ---- 컷 리셋
    cut_thresh: float = 0.45
    flat_sd: float = 6.0
    # **불응기** — 컷 직후 이만큼은 추가 컷을 인정하지 않는다.
    # 지뢰 2 의 재발이다. 히스토그램에서 NCC 로 바꿔 한 번 막았지만 실사의
    # 강한 점멸 + 빠른 편집에서는 NCC 도 뚫린다. 실측(유튜브 실사 40초 클립,
    # 1000~1200 프레임):
    #   실패군 7편  컷 278~1106  제거율 0~41%   <- 초당 25회 컷을 주장한다
    #   성공군      컷 0         제거율 100%
    # 위반량·규칙 조합·마스크(0.997)·무장률(100%)이 같은데 컷 수만 다르고
    # 결과가 100% 대 0% 로 갈렸다. 컷마다 prev 가 리셋되니 시간축 평활이
    # 한 번도 누적되지 못한 것이다.
    # 대가: 진짜 컷이 이 간격 안에 연달아 오면 한 번을 놓쳐 잔상이 남는다.
    #
    # 유튜브 실사 24편(위반 16) 스윕 — 악화는 전 구간 0:
    #   0.00  제거 64.3%  완전 9/16   컷 255   drag 0.370
    #   0.10       81.0%      10/16       82
    #   0.20       95.5%      10/16       53   drag 0.394
    #   0.30       98.6%      11/16       39   drag 0.390
    #   0.50      100.0%      16/16       26   drag 0.392   <- 채택
    # **잔상 비용은 불응기를 켜는 순간 한 번 발생하고 그 뒤로는 평평하다.**
    # 그래서 0.2 -> 0.5 는 잔상을 더 내주지 않고 제거율만 얻는다.
    # 0.5 는 초당 2회 컷 상한이라 빠른 편집의 진짜 컷을 놓칠 수 있지만,
    # 초당 6회·10회 컷 합성 클립(21/27번)에서 판정이 유지되는 것을 확인했다 —
    # 컷 리셋을 놓치면 그 지점에 잔상이 생길 뿐 위반을 만들지는 않는다.
    cut_min_gap_s: float = 0.5
    # ---- 외부 컷 트리거 주입 (AI 이식 2번 — TransNetV2)
    # None 이면 기존 NCC + 불응기. 프레임 번호 집합(set)이면 그 프레임에서만
    # 컷 리셋 — NCC 판별과 불응기를 완전히 대체한다. 플래시는 컷이 아니라고
    # 학습된 모델이 경계를 주므로 헛컷 리셋(위 실패군)과 불응기 워크어라운드가
    # 함께 사라진다. 워커는 업로드형 배치라 사전 패스(수 초/클립)가 가능하다.
    # 승격 전 관문: regress_ab --tn-cand 로 합성 27 + 실사 209 악화 0·퇴보 0.
    cut_frames: object = None
    # ---- 실행
    short_side: int = 240
    strength: float = 1.0
    fast: bool = False

    @classmethod
    def strong(cls) -> "Cfg":
        """강한 컨트롤 프리셋 — "점멸이 강하게 나오는 영상을 보이게 누른다".

        실사 3편(cera·pinkvenom·travis) 강도 스윕(2026-08-19)에서 확정한 조합.
        slew 만 낮추는 것은 세 클립 모두 효과 0 이었고(잔존은 진폭 누출이
        아니라 무장 전 앞단 누출), 첫 플래시 무장이 실제로 움직이는 손잡이다:
          pinkvenom  플래시 3->2회, 대역에너지 11.8->8.8%, 헤일로 12.4->9.6
          travis     플래시 7->5회, 대역 67.5->59.7%, 헤일로 6.8->5.3,
                     **화면전환 축까지 적합** (컷 경계 휘도 점프도 눌림)
        대가는 잔상 lag 소폭 증가 (0.97->1.15 / 0.18->0.31).
        detail_sigma 32 는 억제량과 무관한 자연스러움 축이라 함께 켠다
        (seunghoon 스윕: 억제 -0.7~2%p 에 헤일로 1/6, 판정·마스크 불변)."""
        c = cls()
        c.net_directional = True
        c.detail_sigma = 32.0
        c.slew_safety = 0.65
        c.arm_count = 1.0
        c.hold_s = 0.5
        return c

    @classmethod
    def for_tier(cls, tier: str = "t3") -> "Cfg":
        """티어 선택형 프리셋 — 통합 티어 표 v2 의 플래시 공유축 번역.

        t3 = 규격 표준 (STRONG 그대로)
        t4 = 편두통 기본: 휘도 임계 10cd/m²(theta 0.05) · 면적 한도 10%
             선점(arm_area 0.08) · 첫 플래시 무장(STRONG 이 이미 충족)

        실사 3편 실측 (validation/tier_real3.csv, 2026-08-19):
        - T4 출력도 규격 판정(pse_bt1702) 전부 적합 — 안전선 유지.
        - comfort 선량 추가 감소는 **콘텐츠 축 의존** — 플래시 지배(cera)
          -7.5%, 색·글레어 지배(pinkvenom) 0%. 임계 클램프 전략은 문턱
          아래 잔여 깜빡임을 남기므로 연속 선량 지표는 크게 못 내린다.
          T4/T5 의 본체는 고유 축 작동기(패턴 감쇠·색·휘도)다 — 이 프리셋은
          그중 플래시 공유축의 강화만 담당한다."""
        t = tier.lower()
        if t == "t3":
            return cls.strong()
        if t == "t4":
            c = cls.strong()
            c.theta_lum = 0.05
            c.arm_area = 0.08
            return c
        if t == "t5":
            # 편두통 보수: 휘도 5cd/m² · 면적 5% 선점 · 1회/s (기충족).
            # 주의 — T4/T5 의 완전체는 고유 축 체인 포함이다:
            #   pselive3 --tier tN  ->  pse_soften --tier tN  ->  (M2 색상, 미구현)
            # 이 프리셋은 플래시 공유축만 담당한다.
            c = cls.strong()
            c.theta_lum = 0.025
            c.arm_area = 0.04
            return c
        raise ValueError(f"지원 티어: t3, t4, t5 (요청: {tier})")


def _build_oetf(n: int = 4096) -> np.ndarray:
    x = np.linspace(0.0, 1.0, n)
    y = np.where(x <= 0.0031308, x * 12.92,
                 1.055 * np.power(np.maximum(x, 0), 1 / 2.4) - 0.055)
    return np.clip(np.rint(y * 255.0), 0, 255).astype(np.uint8)


class LiveFilter3:
    """완전 인과적. push(frame) -> 즉시 출력 프레임. 선행 버퍼 0."""

    def __init__(self, fps: float, shape_hw, cfg: Cfg = None):
        self.c = c = cfg or Cfg()
        self.fps = float(fps)
        n_look = max(1, int(round(c.T_qualify_ms / (1000.0 / fps))))
        self.n_look = n_look
        self.pv = [PC.PeakValley(shape_hw, n_look, c.theta_lum) for _ in range(3)]
        self.ctr = [PC.FlashCounter(shape_hw, max(1, int(round(fps))), 1e9)
                    for _ in range(3)]
        self.frame_ms = 1000.0 / fps
        self.S = float(c.slew_frac) if c.slew_frac > 0 else \
            c.slew_safety * c.theta_lum / max(1, n_look)
        self.hold_n = max(1, int(round(c.hold_s * fps)))
        self.hold = np.zeros(shape_hw, np.int32)
        # psecore 와 **같은 함수**로 WCAG 창 크기를 구한다
        self.win_px = PC.wcag_window_px(shape_hw[1], shape_hw[0],
                                        PC.Cfg().wcag_field_deg, PC.Cfg().fov_h_deg)
        self.alpha = None
        self.prevV = None
        self._OETF = _build_oetf()
        self._prev_ncc = None
        self._prev_flat = True
        self._prev_gray = None
        self._cut_gap_n = max(0, int(round(c.cut_min_gap_s * fps)))
        self._since_cut = 10 ** 9        # 첫 컷은 막지 않는다
        self.n = 0
        # ---- 자기감시: **출력에도 같은 검출기를 돌린다**
        # 인과적 필터는 원본보다 나빠질 수 있다(14번 흐르는 줄무늬 1.26s -> 6.86s).
        # 배치판에는 '되돌림' 가드가 있었지만 스트리밍에는 없었다.
        # 전체를 다시 재는 대신 **출력 위험면적을 실시간으로 추적**해
        # 입력보다 커지면 개입 강도를 스스로 낮춘다. 지연은 여전히 0.
        self.pv_o = [PC.PeakValley(shape_hw, n_look, c.theta_lum) for _ in range(3)]
        self.ctr_o = [PC.FlashCounter(shape_hw, max(1, int(round(fps))), 1e9)
                      for _ in range(3)]
        self.g_alpha = 1.0 - float(np.exp(-1.0 / max(1.0, fps * c.guard_tau_s)))
        self.err_ema = 0.0
        self.gain = 1.0
        self.in_frac = 0.0
        self.stats = {"armed": 0, "cuts": 0, "warped": 0, "mean_area": 0.0,
                      "alpha_raised": 0.0, "gain_sum": 0.0, "gain_min": 1.0}
        # **무장한 프레임 번호.** 개수만 세면 "어디를 건드렸나" 를 잃는다 —
        # 구간 저장(docs/구간저장-토글-설계.md)에 필요하다. 원본과 diff 로
        # 역산하면 인코딩 손실 때문에 임계값 문제가 생긴다. 필터가 자기
        # 판단을 그대로 알려주는 편이 정확하다.
        self.armed_at: list[int] = []

    # ------------------------------------------------------------------ 검출
    def _mask(self, bgr_small):
        c = self.c
        lin = PC._LIN[bgr_small]

        def qual(hi, lo):
            mich = (hi - lo) / np.maximum(hi + lo, 1e-6)
            return (lo < c.theta_dark) | (mich > c.michelson)

        hot = None
        ups, dns = [], []                      # 채널별 상승/하강 (순방향 관문용)
        for ch in range(3):
            X = np.ascontiguousarray(lin[..., ch])
            flash, _, anytr = self.pv[ch].step(X, qualify=qual)
            # step 은 (up, delta, down|up) 을 준다. up 과 down 은 both 해소 뒤
            # 서로소이므로 down = anytr & ~up 으로 되살릴 수 있다.
            dn = anytr & ~flash
            ups.append(flash); dns.append(dn)
            self.ctr[ch].push(flash, self.n * self.frame_ms)
            h = self.ctr[ch].counts(False) >= c.arm_count
            hot = h if hot is None else (hot | h)
        # **전역 화소 비율로는 판정을 못 흉내낸다** — 판정기는 10도 창의 25% 를 본다.
        # 14번은 전역 비율이 비슷한데 위험이 공간적으로 뭉쳐서 창 규칙을 통과했다.
        # 그래서 가드도 psecore 와 같은 창 면적(적분영상)으로 잰다.
        self.in_frac = max(
            PC.area_wcag(self.ctr[ch].counts(False) > 3.0, self.win_px)[0]
            for ch in range(3))
        # **면적 규칙을 개입 조건에도 건다.**
        # 실측: 흔들리는 안전 영상(26)과 흐르는 줄무늬(14)는 화소별로는 점멸처럼 보이지만
        # 표준의 면적 조건을 넘지 않아 위반이 아니다. 그런데 필터가 개입해서
        # 오히려 위반을 만들었다(0.00 -> 0.43 / 3.54).
        # 표준이 위험하다고 하는 곳에만 손대는 게 맞다.
        if c.arm_area > 0:
            a_hot, _ = PC.area_wcag(hot, self.win_px)
            if a_hot < c.arm_area:
                hot = np.zeros_like(hot)
        # **순 방향성 관문** (Cfg.net_directional 주석 참고)
        # 순방향은 **채널별로 재서 최댓값**을 쓴다. 채널 OR 마스크(up_any/dn_any)로
        # 재면 등휘도 색 점멸이 뚫린다 — 같은 화소에서 R↑·B↓ 가 동시에 일어나
        # 합산 순방향이 0 이 되고, 관문이 이를 움직임으로 오인해 개입을 꺼서
        # 합성 06/07(등휘도 적↔청 12Hz)의 적색 위반이 잔존했다 (base 는 고침).
        # 채널별로 재면 색 점멸은 한 채널이 압도(순방향 큼)하고, 팬·줌·회전은
        # 모든 채널이 각각 상쇄돼 관문 의도가 그대로 산다.
        if c.net_directional and hot.any():
            net = 0.0
            for u, d in zip(ups, dns):
                au, _ = PC.area_wcag(u, self.win_px)
                ad, _ = PC.area_wcag(d, self.win_px)
                net = max(net, abs(au - ad))
            if net < c.arm_area:
                hot = np.zeros_like(hot)
                self.stats["net_blocked"] = self.stats.get("net_blocked", 0) + 1
        self.hold[hot] = self.hold_n
        np.maximum(self.hold - 1, 0, out=self.hold)
        return self.hold > 0

    def _is_cut(self, bgr_small):
        g = cv2.resize(cv2.cvtColor(bgr_small, cv2.COLOR_BGR2GRAY).astype(np.float32),
                       (64, 64), interpolation=cv2.INTER_AREA)
        g -= g.mean()
        sd = float(g.std())
        flat = sd < self.c.flat_sd                    # 지뢰 2
        gn = g / sd if sd > 1e-3 else np.zeros_like(g)
        cut = False
        if self._prev_ncc is not None and not flat and not self._prev_flat:
            cut = float((gn * self._prev_ncc).mean()) < self.c.cut_thresh
        self._prev_ncc = gn
        self._prev_flat = flat
        # **TN 동의 게이트** (AI 이식 2번, cut_frames = TransNetV2 경계 ±허용창).
        # 27클립 관문 실측(0825)의 결론으로 "대체"가 아니라 "거부권"이다:
        #   순수 교체 -> 악화 3 + 퇴보 2. TN 이 전면 색 교대를 전환으로 오인해
        #   리셋을 만들고, 억제 중 리셋 1회는 억제->원본->억제 점프 **두 개**라
        #   2회/s 리셋도 심판에는 4변화/s 로 보여 없던 화면전환이 생긴다.
        #   불응기 유지 교체 -> 여전히 악화 3 + 퇴보 1 (같은 기전).
        # 그래서 NCC 후보 중 TN 이 실제 샷 경계라고 동의한 것만 리셋한다.
        # 플래시가 NCC 를 뚫은 헛컷(TN 은 경계 아님)만 정확히 걸러진다 —
        # 로드맵 2번이 노린 "플래시 구간 오탐 리셋 제거" 그 자체다.
        if cut and self.c.cut_frames is not None:
            cut = self.n in self.c.cut_frames
        # 불응기 (Cfg.cut_min_gap_s 주석 참고)
        if cut and self._since_cut < self._cut_gap_n:
            cut = False
        self._since_cut = 0 if cut else self._since_cut + 1
        return cut

    # ------------------------------------------------------------------ 처리
    def push(self, bgr: np.ndarray, bgr_small: np.ndarray = None) -> np.ndarray:
        c = self.c
        if bgr_small is None:
            bgr_small = bgr

        # ---- 움직임 추정을 **검출보다 먼저** 한다.
        #
        # psecore 는 검출 단계에서 이미 움직임을 보상한다("흔들림 오탐 방지").
        # 필터 쪽 검출기에는 그게 없어서 손떨림 영상(26)이 화소별로는 점멸처럼 보였고,
        # 마스크가 95.5% 켜진 뒤 개입이 없던 위반을 만들었다(0.00 -> 0.63).
        # 현재 프레임을 옮기면 마스크 좌표가 틀어지므로, 대신 **검출기의 과거
        # 프레임(PeakValley 링)과 직전 출력을 현재 좌표로 끌어온다.**
        dx = dy = 0.0
        if c.motion_comp:
            g = cv2.cvtColor(bgr_small, cv2.COLOR_BGR2GRAY).astype(np.float32)
            if self._prev_gray is not None:
                try:
                    (ex, ey), resp = cv2.phaseCorrelate(self._prev_gray, g)
                except cv2.error:
                    ex = ey = resp = 0.0
                # 주기 패턴은 위상상관이 다봉이라 신뢰도가 낮게 나온다 -> 걸러진다
                if (resp > c.motion_resp and (abs(ex) > 0.5 or abs(ey) > 0.5)
                        and abs(ex) < c.motion_max_px and abs(ey) < c.motion_max_px):
                    dx, dy = ex, ey
                    Mw = np.float32([[1, 0, dx], [0, 1, dy]])
                    for pv in self.pv:
                        pv._ring = [cv2.warpAffine(r, Mw, (r.shape[1], r.shape[0]),
                                                   flags=cv2.INTER_LINEAR,
                                                   borderMode=cv2.BORDER_REPLICATE)
                                    for r in pv._ring]
                    self.stats["warped"] += 1
            self._prev_gray = g

        M = self._mask(bgr_small)
        cut = self._is_cut(bgr_small)
        self.n += 1
        self.stats["mean_area"] += float(M.mean())
        if M.any():
            self.stats["armed"] += 1
            self.armed_at.append(self.n - 1)

        H, W = bgr.shape[:2]
        src = bgr_small if c.fast else bgr
        lin = PC._LIN[src]

        # ---- 알파맵
        a = M.astype(np.float32)
        if c.dilate_px > 0:
            kk = int(c.dilate_px) | 1
            a = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))
        gate_small = a > 0                             # 알파를 올려도 되는 영역
        if c.feather_px > 0:
            a = cv2.GaussianBlur(a, (0, 0), c.feather_px)
        a = np.clip(a, 0, 1) * float(np.clip(c.strength, 0, 1)) * self.gain
        if self.alpha is not None and self.alpha.shape == a.shape:
            a = (1 - c.alpha_smooth) * self.alpha + c.alpha_smooth * a
        self.alpha = a

        if self.prevV is None or self.prevV.shape != lin.shape or cut:
            if cut:
                self.stats["cuts"] += 1
            self.prevV = lin.copy()
            return bgr

        # ---- 직전 출력도 같은 이동만큼 끌어온다 (전체 해상도 배율 적용)
        if dx or dy:
            sc = self.prevV.shape[1] / float(bgr_small.shape[1])
            Mw = np.float32([[1, 0, dx * sc], [0, 1, dy * sc]])
            self.prevV = cv2.warpAffine(
                self.prevV, Mw, (self.prevV.shape[1], self.prevV.shape[0]),
                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

        # ---- 변화 벡터를 스칼라 하나로 (지뢰 5)
        d = lin - self.prevV
        dY = d[..., 2] * 0.2126 + d[..., 1] * 0.7152 + d[..., 0] * 0.0722
        mchr = np.abs(d - dY[..., None]).max(axis=2)
        kmax = np.minimum(np.minimum(1.0, self.S / np.maximum(np.abs(dY), 1e-6)),
                          c.slew_chroma / np.maximum(mchr, 1e-6))

        hw = (kmax.shape[1], kmax.shape[0])
        A = a if a.shape == kmax.shape else cv2.resize(a, hw, interpolation=cv2.INTER_LINEAR)
        if c.alpha_compensate:
            # 합성 keff = A·k + (1-A) 가 kmax 를 넘지 않게 (지뢰 6)
            gate = (gate_small if gate_small.shape == kmax.shape else
                    cv2.resize(gate_small.astype(np.uint8), hw,
                               interpolation=cv2.INTER_NEAREST) > 0)
            need = np.clip(1.0 - kmax, 0.0, 1.0)
            raised = np.where(gate, np.maximum(A, need), A)
            self.stats["alpha_raised"] += float((raised > A + 1e-3).mean())
            A = raised
            k = np.clip((kmax - (1.0 - A)) / np.maximum(A, 1e-6), 0.0, 1.0)
        else:
            k = kmax
        keff = (A * k + (1.0 - A))[..., None]
        out_lin = np.clip(self.prevV + keff * d, 0.0, 1.0)

        if c.detail_sigma > 0 and float(A.max()) > 1e-3:
            # 레벨은 제한하되 밝기 질감은 현재 프레임에서 (색도는 건드리지 않는다)
            sg = float(c.detail_sigma)
            Y_o = (out_lin[..., 2] * 0.2126 + out_lin[..., 1] * 0.7152
                   + out_lin[..., 0] * 0.0722)
            Y_i = lin[..., 2] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 0] * 0.0722
            tex = np.clip(Y_i / np.maximum(cv2.GaussianBlur(Y_i, (0, 0), sg), 1e-4),
                          0.25, 4.0)
            Y_t = cv2.GaussianBlur(Y_o, (0, 0), sg) * tex
            # **알파 밖에는 절대 손대지 않는다** — 이게 두 건의 악화 원인이었다.
            # 질감 복원이 마스크와 무관하게 전면 적용되고 있었다.
            # 수식상으로는 무개입 화소에서 항등이어야 하지만 tex 를 [0.25,4] 로
            # 자르기 때문에 고대비 경계(줄무늬)에서 항등이 깨진다.
            # 그 결과 마스크 0% 인 정지 줄무늬(13)도 선명도가 89.4% 로 변했고,
            # 안전한 14/26 에서는 없던 위반이 생겼다(0.00 -> 3.54 / 0.43).
            det = np.clip(out_lin * (Y_t / np.maximum(Y_o, 1e-4))[..., None], 0.0, 1.0)
            Ad = A[..., None]
            out_lin = Ad * det + (1.0 - Ad) * out_lin

        self.prevV = out_lin

        if not c.fast:
            idx = np.clip((out_lin * (len(self._OETF) - 1)).astype(np.int32),
                          0, len(self._OETF) - 1)
            outb = self._OETF[idx]
        else:
            # **거듭제곱을 작은 맵에서 끝낸다.** 전체 해상도에서 np.power 를 돌리면
            # 빠른 경로의 의미가 없다.   OETF(EOTF(x)·g) ~= x · g^(1/2.4)
            g2 = np.power(np.clip(out_lin / np.maximum(lin, 1e-4), 0.0, 8.0),
                          1.0 / 2.4).astype(np.float32)
            if (g2.shape[0], g2.shape[1]) != (H, W):
                g2 = cv2.resize(g2, (W, H), interpolation=cv2.INTER_LINEAR)
            # cv2.multiply + convertScaleAbs 는 오히려 느렸다(1080p 43 -> 192ms). numpy 유지.
            outb = np.clip(bgr * g2, 0, 255).astype(np.uint8)

        if c.guard:
            self._guard(outb if outb.shape == bgr_small.shape else
                        cv2.resize(outb, (bgr_small.shape[1], bgr_small.shape[0]),
                                   interpolation=cv2.INTER_AREA))
        self.stats["gain_sum"] += self.gain
        self.stats["gain_min"] = min(self.stats["gain_min"], self.gain)
        return outb

    def _guard(self, out_small):
        """출력에도 같은 검출기를 돌려 **악화하면 스스로 물러난다**."""
        c = self.c
        lino = PC._LIN[out_small]

        def qual(hi, lo):
            mich = (hi - lo) / np.maximum(hi + lo, 1e-6)
            return (lo < c.theta_dark) | (mich > c.michelson)

        fr = []
        for ch in range(3):
            X = np.ascontiguousarray(lino[..., ch])
            f, _, _ = self.pv_o[ch].step(X, qualify=qual)
            self.ctr_o[ch].push(f, (self.n - 1) * self.frame_ms)
            fr.append(PC.area_wcag(self.ctr_o[ch].counts(False) > 3.0, self.win_px)[0])
        out_frac = float(max(fr))
        err = out_frac - self.in_frac
        self.err_ema = (1 - self.g_alpha) * self.err_ema + self.g_alpha * err
        # **입력이 이미 대규모로 위반 중인 구간에서는 후퇴하지 않는다.**
        # 가드의 존재 이유는 "안전한 원본에 필터가 위반을 만드는" 악화 방지다
        # (14번 흐르는 줄무늬 1.26s -> 6.86s). 입력 위험면적이 개입 임계를 넘는
        # 구간에서 출력에 위험이 남은 것은 악화가 아니라 **억제 부족**인데,
        # 여기서 물러나면 억제가 통째로 무력화된다 — cera 재인코딩본 실측:
        # 플래시 구간 내내 err_ema 양수 -> gain 0 까지 붕괴 -> 판정 플래시 잔존,
        # 같은 설정 guard=False 는 적합. 입력 위반 구간을 조건에서 빼면
        # 가드 본연의 방어(안전 원본 보호)는 그대로 남는다.
        if self.err_ema > c.guard_margin and self.in_frac < c.guard_hold_area:
            self.gain = max(0.0, self.gain * c.guard_down)
        else:
            self.gain = min(1.0, self.gain + c.guard_up)


def _segments(idx, fps, gap=6, pad=0.0):
    """무장 프레임 번호 -> [시작초, 끝초] 목록.

    gap 프레임 이내로 떨어진 것은 한 구간으로 잇는다 — 조각이 잘게 쪼개지면
    저장·재생이 오히려 비싸진다. pad 는 앞뒤 여유(초).
    """
    if not idx:
        return []
    segs, a, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            segs.append((a, prev)); a = i
        prev = i
    segs.append((a, prev))
    return [[round(max(0.0, s / fps - pad), 3), round((e + 1) / fps + pad, 3)]
            for s, e in segs]


def run(src, cfg: Cfg = None, video_out=None, lossless=False, verbose=True):
    cfg = cfg or Cfg()
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise IOError(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = cfg.short_side / min(W, H) if min(W, H) > cfg.short_side else 1.0
    aw, ah = max(2, int(W * s)), max(2, int(H * s))
    live = LiveFilter3(fps, (ah, aw), cfg)

    out, t_proc, n = [], 0.0, 0
    t0all = time.time()
    while True:
        ok, f = cap.read()
        if not ok:
            break
        sm = cv2.resize(f, (aw, ah), interpolation=cv2.INTER_AREA) if s != 1.0 else f
        t0 = time.time()
        g = live.push(f, sm)
        t_proc += time.time() - t0
        out.append(g)
        n += 1
    cap.release()

    dur = n / fps
    rep = {"src": src, "frames": n, "fps": round(fps, 3), "duration_s": round(dur, 2),
           "proc_sec": round(t_proc, 3),
           "ms_per_frame": round(t_proc / max(n, 1) * 1000, 2),
           "realtime_x": round(dur / max(t_proc, 1e-9), 2),
           "wall_x": round(dur / max(time.time() - t0all, 1e-9), 2),
           "armed_frames": live.stats["armed"], "cuts": live.stats["cuts"],
           "warped": live.stats["warped"],
           "alpha_raised": round(live.stats["alpha_raised"] / max(n, 1), 4),
           "mean_mask_area": round(live.stats["mean_area"] / max(n, 1), 4),
           "gain_mean": round(live.stats["gain_sum"] / max(n, 1), 3),
           "gain_min": round(live.stats["gain_min"], 3),
           "slew_S": round(live.S, 4), "n_look": live.n_look, "latency_frames": 0,
           "armed_segments": _segments(live.armed_at, fps),
           "armed_pct": round(len(live.armed_at) / max(n, 1) * 100, 1)}
    if video_out:
        import subprocess
        import rawmeasure as RM
        if lossless:
            RM.write_lossless(out, video_out, fps)
        else:
            p = subprocess.Popen(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo",
                 "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                 "-i", src, "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "copy",
                 "-shortest",
                 "-sws_flags", "bicubic+accurate_rnd+full_chroma_int",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                 "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                 "-color_primaries", "bt709", "-color_trc", "bt709",
                 "-movflags", "+faststart", video_out], stdin=subprocess.PIPE)
            for g in out:
                p.stdin.write(np.ascontiguousarray(g).tobytes())
            p.stdin.close()
            p.wait()
        rep["video_out"] = video_out
    return rep, out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--video", default=None)
    ap.add_argument("--slew", type=float, default=None)
    ap.add_argument("--slewc", type=float, default=None)
    ap.add_argument("--arm", type=float, default=None)
    ap.add_argument("--hold", type=float, default=None)
    ap.add_argument("--detail", type=float, default=None)
    ap.add_argument("--strength", type=float, default=None)
    ap.add_argument("--short", type=int, default=None)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--no-alpha-comp", action="store_true")
    ap.add_argument("--no-motion", action="store_true")
    ap.add_argument("--no-guard", action="store_true")
    ap.add_argument("--lossless", action="store_true")
    ap.add_argument("--strong", action="store_true",
                    help="강한 컨트롤 프리셋 (Cfg.strong 주석 참조). "
                         "개별 플래그를 주면 프리셋 위에 덮어쓴다")
    ap.add_argument("--tier", choices=["t3", "t4", "t5"], default=None,
                    help="티어 선택형 프리셋 (Cfg.for_tier 주석 참조). "
                         "t3=규격 표준(STRONG), t4=편두통 플래시 강화")
    a = ap.parse_args()
    c = Cfg.for_tier(a.tier) if a.tier else (Cfg.strong() if a.strong else Cfg())
    for name, val in (("slew_frac", a.slew), ("slew_chroma", a.slewc),
                      ("arm_count", a.arm), ("hold_s", a.hold),
                      ("detail_sigma", a.detail), ("strength", a.strength),
                      ("short_side", a.short)):
        if val is not None:
            setattr(c, name, val)
    if a.fast:
        c.fast = True
    if a.no_alpha_comp:
        c.alpha_compensate = False
    if a.no_motion:
        c.motion_comp = False
    if a.no_guard:
        c.guard = False
    rep, _ = run(a.src, c, video_out=a.video, lossless=a.lossless)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
