# 자체 숏폼 플랫폼 MVP — 설계 (2026-08-20)

BM 전환에 따른 자체 플랫폼 앱. 틱톡/쇼츠형 세로 피드에 PSE 필터 적용
영상을 서비스한다. 업로드 → 서버 보정 → 피드 노출 전 과정이 실동작하는
MVP. 브랜치 `platform-mvp`, 코드는 `server/`(FastAPI+워커)와
`app/`(Flutter)에 둔다.

## 확정 사항

| 항목 | 결정 |
|---|---|
| 목적 | 동작하는 MVP — 업로드→보정→피드 전체 흐름 실동작 |
| 클라이언트 | Flutter 앱, Android 우선, 다크 테마 고정 (목업 색감) |
| 백엔드 | FastAPI + 워커, Docker Compose, EC2 배포 (로컬 개발 동일 compose) |
| 업로드 | 일반 사용자 업로드 |
| 계정 | 이메일+비밀번호 로그인 (JWT) |
| 필터 | ON=보정본 / OFF=원본 (원본 시청 시 광 노출 누적) |
| 파이프라인 | 검출(pse_bt1702) + 1패스 STRONG(pselive3) + 재판정만. 사다리(psepipe) 제외 |
| 소셜 | 좋아요 + 조회수만. 댓글·공유·리믹스는 더미 버튼 |

## 1. 전체 아키텍처

```
Flutter 앱 (Android / iOS)
   │  HTTPS — REST API + 영상 스트리밍(HTTP Range)
   ▼
EC2 인스턴스 — Docker Compose
 ├── api  (FastAPI)
 │     · 인증(JWT, 이메일+비밀번호)
 │     · 피드 / 좋아요 / 조회수 / 시청·노출 이벤트 / 대시보드 API
 │     · 영상 파일 서빙 (Range 지원)
 │     · 업로드 수신 → jobs 테이블에 큐잉만 하고 즉시 응답
 ├── worker  (Python, 같은 이미지)
 │     · jobs 폴링 → [1] pse_bt1702 검출
 │     · 위반 시 → [2] pselive3 STRONG → [3] 재판정
 │     · ffmpeg 표준화(H.264 mp4) + 원본 오디오 재합성
 │     · 원본·보정본·검출 리포트 저장, 영상 상태 갱신
 └── 공유 볼륨 /data  (SQLite DB + 영상 파일, EBS 디스크)
```

- 워커는 API와 같은 코드베이스·같은 Docker 이미지, 프로세스만 분리.
  컨테이너 2개가 `/data` 볼륨과 SQLite(WAL)를 공유한다.
- 영상 저장은 EBS 파일시스템. 저장 경로 접근을 한 모듈로 모아 나중에
  S3로 교체 가능하게 한다 (S3 자체는 MVP 범위 밖).
- 서버는 저장소의 `psepipe_v3_seam/`을 직접 import 한다.
- pselive3 출력(OpenCV)에는 오디오가 없다 → 보정 후 ffmpeg 로 원본
  오디오를 다시 합친다(mux). 원본도 업로드 시 H.264/AAC 로 표준화.

## 2. 백엔드 상세

### DB (SQLite, WAL — API·워커 동시 접근)

| 테이블 | 주요 컬럼 |
|---|---|
| users | email(유니크), password_hash(bcrypt), nickname, created_at |
| videos | uploader_id, title, status(processing/ready/failed), risk(safe/corrected/uncorrected), original_path, filtered_path, thumb_path, duration_s, report_path, 자극 축별 횟수 요약(flash/red/pattern/cut), view_count, created_at |
| likes | user_id + video_id (유니크 쌍) |
| watch_events | user_id, video_id, watched_s, variant(original/filtered), created_at |
| jobs | video_id, status(queued/running/done/error), error_msg, started_at, finished_at |
| user_settings | user_id, filter_on, auto_skip |

### API

```
POST /auth/signup · /auth/login → JWT     GET  /me · /me/videos (내 업로드+상태)
GET  /feed?cursor=                         GET/PUT /me/settings {filter_on, auto_skip}
GET  /videos/{id}/stream?variant=          POST /videos (multipart 업로드 → 202)
POST·DELETE /videos/{id}/like              POST /videos/{id}/events {watched_s, variant}
GET  /dashboard/today · /dashboard/weekly
```

### 영상 노출 규칙 (서버가 피드에서 판단)

| risk \ 설정 | 필터 ON | 필터 OFF | 자동스킵 ON |
|---|---|---|---|
| safe | 원본 | 원본 | 원본 |
| corrected | **보정본** | 원본 (노출 누적+경고) | 피드 제외 |
| uncorrected | 피드 제외 (안전본 없음) | 원본 (노출 누적+경고) | 피드 제외 |

- 두 토글의 의미: `filter_on`은 "위험 영상을 보정본으로 재생",
  `auto_skip`은 "위험 영상(보정 여부 무관)을 피드에서 아예 제외".

### 워커 처리 순서 (업로드 1건 = job 1건, 순차)

1. ffmpeg 표준화: H.264/AAC mp4 · faststart · 세로 720p 상한, 썸네일 추출
2. pse_bt1702 검출 → 리포트 JSON (축별 위반·구간)
3. 무위반 → risk=safe, 완료
4. 위반 → pselive3 STRONG → 같은 심판 재판정 → 합격 corrected /
   불합격 uncorrected (보정 시도본도 보관)
5. 보정본에 원본 오디오 mux → status=ready
6. 실패 → job=error, video=failed → 업로더에게 "처리 실패" 표시

자극 유형 요약(고휘도 플래시·포화 적색·패턴·화면 전환)은 검출 리포트의
축별 결과를 매핑해 videos 에 저장한다. 정확한 매핑은 구현 때 실제 리포트
JSON 을 보고 확정한다.

스택: FastAPI + 표준 sqlite3(래퍼 모듈, ORM 없음) + passlib(bcrypt) + PyJWT.

## 3. 광 노출 모델

**원천 데이터**: 영상 이탈(스와이프·앱 이탈) 시 클라이언트가
`POST /videos/{id}/events {watched_s, variant}` 1건 전송.
**위험 노출 = risk≠safe 영상을 variant=original 로 시청한 이벤트**만.
보정본 시청은 조회수에만 반영, 노출 미포함.

| 목업 항목 | 정의 |
|---|---|
| 오늘 위험 영상 N회 | 오늘의 위험 노출 이벤트 건수 (재시청 각각 카운트) |
| 위험 노출 시간 | 해당 이벤트 watched_s 합 |
| 누적 % | 노출 시간 ÷ 일일 노출 예산 × 100. 예산은 `.env` 설정 (기본 300초, 시연 때 줄여 배너 발동 시연) |
| 임계치 80% 선 | 고정 기준선. <50% 양호 · 50~80% 주의 · ≥80% 경고(배너) |
| 자극 유형별 횟수 | 위험 노출 이벤트 1건마다 그 영상의 위반 축 각각 +1 |
| 시간대별 누적 곡선 | 오늘 이벤트 시간순 누적 % (00시~현재) |
| 주간 바 차트 | 최근 7일 일별 위험 노출 횟수 + 주간 평균 |

- 오늘 = 서버 로컬 자정 기준.
- 이벤트 POST 응답에 `{today_percent, status}` 포함 → 클라이언트는 폴링
  없이 매 영상 이탈 시점에 갱신, **percent≥80 이고 필터 OFF** 면 배너
  표시 → [필터 ON](설정 PUT) / [대시보드 확인].
- 단순화: 자극 강도 가중치 없이 시간만으로 계산. comfort/migraine
  WARN 축 미반영 (파이프라인 규격 판정과 일관). 이벤트에 축별 데이터가
  남으므로 가중치가 필요해지면 계산식만 교체.

## 4. Flutter 앱

| 화면 | 내용 |
|---|---|
| 로그인/가입 | 이메일+비밀번호, JWT는 secure storage |
| 피드 | 세로 PageView 전체화면. 우상단 필터 버튼, 우측 레일(좋아요 동작 / 댓글·공유·리믹스 더미), 하단 업로더·제목. 탭바 5개 중 홈·＋·내 페이지만 동작 |
| 설정 바텀시트 | 필터 켜기 · 위험 영상 자동 스킵 · 대시보드 진입 |
| 대시보드 | 상태 카드 → 누적 % 라인차트(80% 기준선) → 주간 바차트 → 자극 유형별 횟수 → [필터 켜기] |
| 업로드 | 갤러리 선택 + 제목 → dio 진행률 → "처리 중" 안내 |
| 내 페이지 | 내 업로드 목록 + 처리중/게시됨/보정미완/실패 뱃지, 로그아웃 |
| 경고 배너 | 피드 오버레이, [필터 ON]·[대시보드 확인] |

- 상태관리 Riverpod, HTTP dio, 재생 video_player(+다음 1개 프리로드),
  차트 fl_chart, 선택 image_picker, 토큰 flutter_secure_storage.
- 필터 토글 변경 시 현재 영상을 해당 variant 로 즉시 교체 재생(처음부터),
  피드 목록은 다음 로드부터 서버 규칙 반영.
- 이 PC에 Flutter 미설치 → 설치(+Android SDK)가 구현 계획 첫 단계.

## 5. 에러 처리 · 테스트 · 배포

### 에러 처리

- 업로드 검증: ffprobe 형식 확인, 200MB · 3분 상한. 위반 시 4xx+이유.
- 워커: 단계별 실패 → job.error_msg, video.status=failed. 재시작 시
  오래 running 인 job 자동 재큐잉 (크래시 복구).
- 앱: 401→로그인 화면, 네트워크 오류→재시도, 재생 실패→토스트 후 다음.

### 테스트 (성공 기준)

- 서버 pytest: ① 인증 ② 노출 규칙 표 전 케이스 (risk 3 × 설정 3)
  ③ 노출 계산 (이벤트→오늘 수치·%·자극별·주간) ④ 워커 통합 —
  `legacy_detectors/make_testclips.py` 로 생성한 합성 클립(정답 알려짐,
  9:16 세로)으로 위반→corrected, 안전→safe 확인.
- 앱: 배너 판단·API 파싱 단위 테스트 + 수동 체크리스트.
- **최종 E2E**: 실기기에서 "위반 영상 업로드 → 처리 완료 → 필터 OFF
  시청 → 대시보드 상승 → 임계 초과 배너 → [필터 ON] → 보정본 재생"
  전 과정 통과.

### 배포

- `server/Dockerfile` 1개 + `docker-compose.yml`(api·worker·`/data`).
  로컬과 EC2 동일 파일.
- EC2(Ubuntu): `docker compose up -d`. MVP는 HTTP+퍼블릭 IP
  (Android cleartext 허용 설정 포함). HTTPS 필요 시 Caddy 컨테이너 추가.
- `.env`: JWT 시크릿, 일일 노출 예산, 업로드 상한.

## 범위 밖 (명시)

댓글·팔로우·공유·리믹스 실동작, psepipe 사다리 폴백, S3 저장,
iOS 빌드·서명, HTTPS, 푸시 알림, 관리자 페이지, 추천 알고리즘
(피드는 최신순).
