# EA IRIS 교차검증 v0.1 — 합성 클립 24편

*2026-08-13 · 검출기: gumchulgi `fix/ste-report-consistency` 브랜치 `psepipe_v3_seam/pse_bt1702.py` (커밋 7e1e38a)*
*비교 대상: [electronicarts/IRIS](https://github.com/electronicarts/IRIS) main, C++ 원본을 직접 빌드 (CPU 전용 — GPU 불필요)*

## 왜 했나

합성 클립 24편의 정답은 우리가 정했다("자기 채점" 약점, 사양 v1.0 남은 작업 4번).
EA IRIS 는 우리 코드를 본 적 없는 제3자가 같은 계열 기준을 독립 구현한 검출기라,
같은 클립에서 판정이 일치하면 "남이 채점해도 같다"는 근거가 된다.
통합 방안 v0.1 의 "EA IRIS 교차검증(P2)" 항목의 실행이다.

## 방법

- 합성 클립 24편(점멸·색·줄무늬 11 + 컷·모션 10 + 시퀀스 3)을 소스 번들 v1.0 의
  생성기로 재생성 (FFV1 무손실, 360×640@30, 4초)
- 우리: `pse_bt1702.py --brief` (전체 축)
- IRIS: `IrisApp -v <clip> -j 1` (기본: 패턴 꺼짐) 및 `-p 1` (패턴 켬) 두 번 실행
- IRIS 판정 해석: `OverallResult` Fail = 위반, Pass/PassWithWarning = 적합

## 결과 — 판정 비교 (IRIS 는 패턴 축 제외 기준, §패턴 참조)

| 클립 | 정답(설계) | 우리 | IRIS | 일치 |
|---|---|---|---|---|
| 00 안전 그라데이션 | 적합 | 적합 | Pass | ✓ |
| 01 휘도 5Hz | 위반 | 위반—플래시 | Fail—Lum | ✓ |
| 02 휘도 2Hz | 적합 | 적합 | PassWithWarning | ✓ (경고 대역도 정확히 2–3회/s) |
| 03 적↔흑 5Hz | 위반 | 위반—플래시·적색 | Fail—Lum·Red | ✓ 축까지 일치 |
| 04 정지 줄무늬 10쌍 | 위반 | 위반—패턴 | Fail—Pattern (`-p 1`) | ✓ |
| 05 등휘도 청↔황 8Hz | 적합(규격) | 적합 | Pass | ✓ (공통의 규격 공백, Parra 68%) |
| 06 등휘도 적↔청(채도高) | 위반 | 위반—적색 | Fail—Red | ✓ |
| 07 등휘도 적↔청(탈채도) | **적합(규격 구멍)** | 적합 `[보조:적청]` | **Fail—Red** | ✗ ① |
| 08 등휘도 적↔녹 | 적합(규격) | 적합 | **Fail—Red** | ✗ ① |
| 09 국소 10% 점멸 | 적합 | 적합 | Pass | ✓ (둘 다 면적 25% 기준) |
| 10 이동 줄무늬 10쌍 | 위반 | 위반—패턴 | Fail—Pattern (`-p 1`) | ✓ |
| 20 정지 | 적합 | 적합 | Pass | ✓ |
| 21 컷 1Hz | 적합 | 적합 | Pass | ✓ |
| 22 컷 3Hz | 적합 | 적합 | Pass | ✓ |
| 23 컷 6Hz (휘도 동일) | 위반 | 위반—화면전환 | Pass | ✗ ② |
| 24 컷 10Hz | 위반 | 위반—화면전환 | PassWithWarning(Red) | ✗ ② |
| 25 휙 팬 | 적합 | 적합 | Pass | ✓ 오탐 없음 |
| 26 급줌 | 적합 | 적합 | Pass | ✓ 오탐 없음 |
| 27 손떨림 | 적합 | 적합 | Pass | ✓ 오탐 없음 |
| 28 전면 점멸 5Hz | 위반 | 위반—플래시 | Fail—Lum | ✓ |
| 29 장면+섬광 5Hz | 위반 | 위반—플래시 | Fail—Lum | ✓ |
| 30 버스트+0.9s 고립 | ITU 적합/WCAG 위반 | 적합(ITU 모드) | Fail | ✗ ③ **검증됨** |
| 31 두 영역 교대 | 적합(화소 동일성) | 적합 | Fail | ✗ ④ |
| 32 한 영역 4회/s | 위반 | 위반—플래시 | Fail—Lum | ✓ |

**일치 18 / 24 (75%). 불일치 6건 전부 원인 규명 — 미해명 불일치 0건.**
공유 축(휘도 플래시·면적·모션 강건성·패턴 양성)만 보면 **일치 100%**.

## 불일치 4가지 원인 — 전부 규칙·정의 차이지 버그가 아니다

**① 적색 정의 차이 (07·08) — 가장 흥미로운 발견.**
IRIS 는 채도비 R/(R+G+B) ≥ 0.8 을 **선형광(EOTF 복원 후)** 에서 계산한다
(`RedSaturation.h` 실측 확인). 감마 공간에서 0.62 인 탈채도 적색 (138,42,42) 이
선형광에서는 0.87 로 "채도 적색"이 된다. 그 결과 **IRIS 는 우리가 '규격의 구멍'
이라 부르던 클립 07(포리곤 유사 탈채도 적↔청)을 규격 적색 축 안에서 잡는다.**
우리는 보조 채널(적청교대)로만 잡고 규격 판정은 적합으로 뒀던 케이스다.
→ 후속 과제: WCAG/ITU 원문이 채도비를 어느 색공간에서 정의하는지 확인.
선형광 해석이 맞다면 임계 하나 안 바꾸고 07 구멍이 규격 축 안에서 메워진다.
단, 24번 클립에서 적색 경고 48프레임이 나온 것처럼 붉은 계열 실사에서
오탐 여지도 같이 커지므로 실영상 표본에서 A/B 필요.

**② 화면전환(컷) 축 부재 (23·24).**
IRIS 에는 NAB-J "장면 전환 초당 3회" 조항이 없다 (WCAG 계열에도 없음).
휘도를 맞춘 빠른 컷은 IRIS 의 어떤 축에도 안 걸린다. 우리 검출기의 추가분이
설계대로 동작한다는 확인이지 IRIS 의 결함이 아니다.

**③ ITU-R 334ms 시퀀스 규칙 (30) — 메타모픽으로 검증 완료.**
IRIS 는 WCAG 식(시퀀스 분할 없음)으로 센다. 우리 검출기를
`sequence_rule=False`(WCAG 모드)로 바꿔 재실행하면 **30번이 위반으로 뒤집혀
IRIS 와 정확히 일치한다.** 불일치가 구현 오류가 아니라 규격 계열 차이임이
실행으로 증명된 것. (설계 문서의 "ITU-R 통과 / WCAG 위반이 정상" 예측 그대로)

**④ 화소 동일성 규칙 (31).**
Jordan HCII 2025 가 방송 기준의 요건으로 지적한 "같은 화소가 겹쳐야 시퀀스"
규칙이 IRIS 에는 없다. 두 영역이 번갈아 번쩍이면 IRIS 는 합산 4회/s 로 위반,
우리는 방송 기준대로 분리해 적합. WCAG 모드로 바꿔도 우리는 적합(교집합
검사는 유지되므로) — 이 축은 우리가 IRIS 보다 방송 규격에 더 충실한 지점.

## IRIS 는 쇼츠 검출에 신뢰성이 있는가 (질문에 대한 답)

**플래시·적색 축: 있다.** 판정 기준이 게임 특화가 아니라 콘텐츠 무관의 화소
기반 일반 기준이고, 쇼츠형 오탐 함정(휙 팬·급줌·손떨림·컷 편집)에서 휘도·적색
오탐 0 을 실측으로 확인했다. 세로 종횡비도 무관하다(면적이 비율 기준).

**패턴 축: 없다.** `-p 1` 로 켜자 자연 텍스처 대조군 7편(컷 1Hz·3Hz·6Hz,
휙 팬, 급줌, 손떨림, 장면+섬광)이 전부 PatternFailure 로 오탐됐다. 게임의
기하학적 패턴에 맞춰진 축이라 실사 텍스처를 구분하지 못한다 — 우리가 v1.0
에서 링 정규화(집중도 0.75)로 고친 바로 그 실패 양상이다. EA 도 예제 앱에서
패턴 검출을 기본 꺼짐으로 배포한다.

**결론: IRIS 는 플래시·적색 축 한정 교차검증 심판으로 쓰고, 패턴 축은 판정에서
제외한다** (패턴 양성 클립 04·10 을 잡는지 확인하는 민감도 체크용으로만).
컷 축·시퀀스 규칙은 IRIS 가 커버하지 않으므로 그 축의 검증은 별도 수단
(trace 코퍼스, 사람 판독) 필요.

## 재현 방법

```bash
# IRIS 빌드 (Ubuntu, vcpkg 없이 — CPU 전용, GPU 불필요)
apt install libopencv-dev nlohmann-json3-dev libspdlog-dev libgif-dev \
            libavcodec-dev libavformat-dev libavutil-dev libswscale-dev
git clone https://github.com/electronicarts/IRIS
# cmake/FindFFMPEG.cmake 추가 (vcpkg 의 FFMPEG config 대체):
#   find_package(PkgConfig REQUIRED)
#   pkg_check_modules(PC_FFMPEG REQUIRED IMPORTED_TARGET libavcodec libavformat libavutil libswscale)
#   set(FFMPEG_LIBRARIES PkgConfig::PC_FFMPEG)
#   set(FFMPEG_FOUND TRUE)
cmake -S IRIS -B IRIS/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_EXAMPLE_APP=ON -DEXPORT_IRIS=OFF
cmake --build IRIS/build

# 클립 생성 + 우리 판정 (소스 번들 v1.0 의 생성기)
python3 make_testclips.py testclips && python3 make_cutclips.py cutclips \
  && python3 make_seqclips.py seqclips
python3 pse_bt1702.py --brief testclips/*.mkv cutclips/*.mkv seqclips/*.mkv

# IRIS 판정 (Results/<clip>/result.json 에 출력)
cd IRIS/build/example
for f in .../*.mkv; do ./IrisApp -v "$f" -j 1; done        # 패턴 제외
```

속도: IRIS 는 24편(각 4초)에 총 ~40초 (CPU). GPU 장비 불필요.

## 남은 것

1. **적색 선형광 정의 확인** (①) — WCAG 2.3.1 / ITU-R BT.1702 원문 대조.
   맞다면 pse_bt1702 의 `saturated_red()` 를 선형광 기준으로 바꾸는 패치 검토
   → 07 구멍이 규격 안에서 닫힌다. 실영상 오탐 A/B 와 함께.
2. **실영상 표본에서 같은 프로토콜** — 위반 판정 편 + 무작위 적합 편을
   IRIS(플래시·적색 한정)에 돌려 일치율 산출. 불일치 편만 사람 판독.
3. **trace 코퍼스** (`traceRERC/pse-test-media`) — 제3자 정답 라벨 검증은
   여전히 별도 과제 (IRIS 교차검증은 "정답 일치"가 아니라 "판정 일치" 검증).

## 산출물

- `iris_results.json` / `iris_results_p1.json` — IRIS 편별 판정 (패턴 꺼짐/켬)
- `ours_brief.txt` — 우리 검출기 24편 판정
- 본 문서
