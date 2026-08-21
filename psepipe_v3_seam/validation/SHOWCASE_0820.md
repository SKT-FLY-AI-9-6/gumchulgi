# 발표용 성공 사례 — 플래시(①)·적색(②) 중심 (2026-08-20)

깃허브 전 브랜치 + 로컬 작업 폴더를 훑어 **위반 → 적합으로 뒤집힌 클립** 중
**플래시·적색 축**만 골랐다. 패턴(③)·화면전환(⑤)은 부록으로 뺐다.

> **먼저 — 지표를 섞지 말 것.**
> `eval_real_all.csv` 의 "제거율 100%" 는 **psecore 채널 초**(LUM/RGB/RED/RB)
> 합계이고 패턴·화면전환 채널이 없다. **규격 적합과 다른 수치다.**
> 아래는 전부 정본 심판 `pse_bt1702` 의 6축 판정으로 뒤집힌 것만 골랐다.
> 발표에서 그 수치를 쓸 거면 **"휘도·색 채널 위반 초 100% 제거"** 라고 말할 것.

---

## 1순위 — 완전 무흔적: 위반 제거 + 헤일로 0 + 잔상 0

### `07_iso_red_blue_desat` — 이 한 편이 가장 강하다

| | 값 |
|---|---|
| 원본 | **적색 위반** |
| 결과 | **적합** |
| 헤일로+ | **0.0** |
| 잔상 lag/drag | **0.00 / 0.000** |
| BlazeBVD(D) 같은 클립 | **적색 잔존 — 실패** |

**새 구조를 하나도 만들지 않고 위반만 제거했다.** 이질감 3축이 전부 0 인
유일한 사례이고, 같은 클립에서 **AI 는 못 고쳤다.**

**등휘도 적↔청**이라 휘도가 거의 안 변한다 — 밝기만 보는 검출기는 통째로
놓치는 자극이다. "왜 채널별로 봐야 하는가"와 "왜 우리 필터가 AI 를 이겼는가"를
한 슬라이드에서 말할 수 있다.

→ `regress_synth14_netfix.csv`, `three_way_synth.csv`

---

## 2순위 — 합성 클립: 헤일로 0 인 플래시·적색 해결

`regress_synth14_netfix.csv` (base·cand 양쪽 적합, 대조 "동일")

| 클립 | 원본 위반 | 결과 | 헤일로+ | 잔상 lag/drag |
|---|---|---|---|---|
| `03_red_black_5hz` | **플래시 + 적색** | 적합 | **0.0** | 0.47/0.433 |
| `01_flash_5hz` | 플래시 | 적합 | **0.0** | 0.45/0.431 |
| `06_iso_red_blue_sat` | 적색 | 적합 | **0.0** | 0.51/1.689 |
| `08_iso_red_green` | 적색 | 적합 | **0.0** | 0.49/0.725 |
| `07_iso_red_blue_desat` | 적색 | 적합 | **0.0** | **0.00/0.000** |

`regress_27.csv` (2026-08-20 GPU 실측, 27클립 세트 — 번호 체계가 위와 다름)

| 클립 | 원본 위반 | 결과 | 헤일로+ | 잔상 lag/drag |
|---|---|---|---|---|
| **`12_porygon_redblue_12hz`** | **플래시 + 적색** | 적합 | **0.0** | 0.50/0.494 |
| `08_red_black_5hz` | 플래시 + 적색 | 적합 | **0.0** | 0.47/0.397 |
| `01_lum_strobe_5hz` | 플래시 | 적합 | **0.0** | 0.47/0.484 |
| `03_isolum_redgreen_8hz` | 적색 | 적합 | **0.0** | 0.48/2.464 |
| `10_red_depth_6hz` | 플래시 | 적합 | **0.0** | 0.50/0.457 |

**`12_porygon_redblue_12hz` 를 대표 슬라이드로.** 1997년 포켓몬 사건의 적↔청
12Hz 자극을 재현한 클립이고, **플래시·적색 두 축 동시 위반**을 **새 아티팩트 0**
으로 해결했다. 스토리와 수치가 같이 선다.

---

## 3순위 — A vs BlazeBVD 정면 비교: 이긴 사례가 전부 플래시·적색이다

`three_way_synth.csv` — 같은 심판, 같은 클립, A(우리) vs D(BlazeBVD)

| 클립 | 원본 | **A (우리)** | A 헤일로 | A 펌핑 | **D (BlazeBVD)** |
|---|---|---|---|---|---|
| `01_flash_5hz` | 플래시 | **적합** | **0.0** | **0.0** | **플래시 잔존 — 실패** |
| `07_iso_red_blue_desat` | 적색 | **적합** | 0.033 | **0.0** | **적색 잔존 — 실패** |
| `03_red_black_5hz` | 플래시 + 적색 | **적합** | **0.0** | **0.0** | 적합 (무승부) |

**2승 1무.** 아키텍처 문서의 *"AI 를 안 쓴 게 아니라, 만들어 재봤더니 아직
자체 필터를 못 이겨서 파인튜닝 트랙으로 보냈다"* 를 뒷받침하는 실측이다.

같은 표에 BlazeBVD 의 잔상이 A 의 2~3배라는 근거도 있다 (`ad_ghost_synth.csv`).

---

## 4순위 — 실사 209편: 플래시 해결

`regress_real.csv` (2026-08-20 GPU 실측). 원본 위반 41편 중 14편 적합,
그중 **플래시가 걸린 것**만:

### 플래시 + 화면전환 + 5초지속 3축 동시 → 적합 (base·cand 양쪽)

`MFC0eGtaF5M` · `_3-eqclZgQc` · `xbawhCyMsRI`

양쪽 설정 모두 적합이라 발표에 안전하다.

### 플래시 단독 → 적합 (base·cand 양쪽)

`Ben_8tA6Eyg` · `Db1wkdUotyf` · `Db2D03pxZjy` · `Db2GfqYxNWW` · `Db3zgE5zqix`

**원본 영상이 로컬에 있다** (5편 중 4편):
`Downloads/pse_detectors final/pse_detectors/data/s1_flagged/` (Db1wkdUotyf,
Db2D03pxZjy, Db2GfqYxNWW), `s2_labeled/` (Db3zgE5zqix).
→ **보정 출력은 없다. 생성 필요** — ffmpeg 는 `gumchulgi-Kim-Moon/work/bin/ffmpeg.exe`

### 설정 명시 없이 쓰지 말 것

`CIHun1gx7zU` · `PFSDW2g3D8o` — base 는 적합이지만 **cand(σ32)에서 뒤집힌다.**

---

## 5순위 — 실사 3편: **비교 영상이 이미 완성돼 있다**

2026-08-20 자체 측정 (`pselive3` CPU, `Cfg.strong()`, σ·net 2x3 격자)

| 클립 | 원본 | 결과 | 억제 |
|---|---|---|---|
| **`pinkvenom`** | 플래시 35회 max6/s + 화면전환 9컷/s | **적합 (전축)** | 플래시 2회 max0.5/s, 컷 3/s |
| **`cera_khin`** | 플래시 12회 max5.5/s **면적 57.1%** | **적합** | **플래시 0회, 면적 7.6%** |

- **`pinkvenom`** — 사다리 없이 **1패스 필터 단독으로 두 축**을 적합으로.
- **`cera_khin`** — 플래시 면적 **57.1% → 7.6%**, 횟수 12 → **0회**. 억제가
  숫자로 가장 극적이다. 천장 스트로브가 눈에 보이게 잡힌다.

**데모 자산 완비** — 6칸 비교 영상 + 최악 프레임 시트 (원본 |ΔY| 최대 3지점):
`sbs_cera_khin.mp4`, `sbs_pinkvenom.mp4`, `sheet_cera_khin_*.png` 등

`travis_fein` 은 성공 사례가 아니지만 **한계 슬라이드**로 값이 있다 —
플래시 151 → 23회(85% 감소)인데 max 7.5회/s 로 한도 3 을 여전히 넘는다.

---

## 부록 — 검토했으나 뺀 것

**`gumchulgi-Kim-Moon/work/out/A/` (릴스 70편).** 우리 필터 출력이 맞다
(`psegpu_full.py` 기본 설정 = `P3.Cfg()`, σ2·net=False). 다만 그 코퍼스에서
뒤집힌 3편이 **전부 패턴**이라 플래시·적색 사례집에는 기여가 없다.
A vs BlazeBVD 비교용으로만 값이 있고 그것도 패턴 클립이다
(`Db0guCQDwsq` — A 적합 / BlazeBVD 실패).

before/after 영상 자산은 완비돼 있으니(`out/_ctrl` = 인코딩만 한 대조군,
`out/A` = 필터), 패턴 슬라이드가 필요해지면 바로 쓸 수 있다.

---

## 발표에서 반드시 같이 말할 것

1. **악화 5편** — 릴스 70편에서 필터가 원본에 없던 위반을 만들었다
   (`reels_3way_report.html` 3절). 무해보장이 그래서 존재한다.
2. **퇴보 6편** — 209편에서 σ32 가 base 가 고친 것을 되돌렸다. 기본값 승격이
   이것 때문에 보류 중이다 (`REGRESS_0820.md`).
3. **화면전환이 풀리는 건 부수효과다** — `ACTUATOR` 맵에 "없음"으로 박힌 축이고,
   필터가 컷 경계 휘도 점프를 눌러 컷 검출이 임계 아래로 내려간 결과다.
4. **표본이 무작위가 아니다** — "이 태그 집합에서 뽑은 N편 중 M%" 로 말할 것
   (`pse_collect.py` 주석).

---

## 근거 파일

| 사례 | 파일 | 위치 |
|---|---|---|
| 합성 14 A/B (헤일로 0) | `regress_synth14_netfix.csv` | fix `validation/` |
| A vs BlazeBVD | `three_way_synth.csv`, `ad_ghost_synth.csv` | fix `validation/` |
| 합성 27 (신규) | `regress_27.csv`, `regress_27_log.txt` | fix `validation/` (e52d891) |
| 실사 209 (신규) | `regress_real.csv`, `REGRESS_0820.md` | 같은 커밋 |
| 실사 3편 | `strong_real3.csv`, `strength_sweep_real3.csv` | fix `validation/` |
| σ 2x3 격자 | 이 세션 측정 | `SIGMA_LADDER_0820.md` |
| 릴스 70 (부록) | `results_reels_3way.csv`, `reels_3way_report.html` | seunghoon `results/` |

## 다음 단계

1. **`12_porygon_redblue_12hz` · `07_iso_red_blue_desat` 비교 영상 제작** —
   1·2순위 슬라이드인데 영상이 없다. `make_testclips.py` 로 재현 후 before/after.
2. **209편 플래시 뒤집힘 4편 보정 출력 생성** — 원본이 로컬에 있고 ffmpeg 확보됨.
3. **A vs BlazeBVD 4분할 영상** — `01_flash_5hz` · `07_iso_red_blue_desat` 로.
