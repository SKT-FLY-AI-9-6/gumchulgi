# 플랫폼 서버

## 로컬 실행
```
cp server/.env.example server/.env   # JWT_SECRET 수정
docker compose up -d --build
curl http://localhost:8000/health    # {"ok":true}
```
docker-compose 는 두 서비스 모두 `APP_ENV=production` 으로 실행됩니다.
JWT_SECRET 이 기본값(dev-secret/change-me)이면 API 서버가 부팅 시
바로 종료되니, `.env` 의 JWT_SECRET 을 반드시 안전한 값으로 바꾸세요.

## 업로더 스튜디오 (웹 콘솔)

YouTube Studio 를 참조한 업로더용 웹 — 서버가 `/studio` 에 정적 서빙하므로
별도 빌드가 없다 (`server/webstudio/`, 프레임워크 없는 단일 SPA).

- **대시보드**: 채널 요약(전체/처리중/보정완료/적합/조회수) + 최근 업로드
- **콘텐츠**: 전 상태 목록 — 처리 중 폴링, 실패 사유, 판정·위반 축·필터 강도
- **상세**: 원본↔보정본 플레이어 전환, 위반 구간 타임라인(해소/잔존),
  pse_bt1702 리포트, 시청 반응
- **업로드**: 드래그&드롭 + 진행률 → 파이프라인 자동 큐잉
- **운영 지표**: 관리자 계정으로 로그인하면 /admin/metrics 노출

서버 실행 후 `http://<host>:8000/studio/` 접속. 시연은 `AUTH_OPEN=1` 로
아무 이메일 로그인, 스트림/썸네일은 비운영 환경 한정 `?token=` 쿼리 인증
(app/videos.py `media_user`). API 는 `/studio/api/*` (app/studio.py).

## 테스트
```
cd server && pip install -r requirements-dev.txt && python -m pytest tests/ -v
```

## EC2 배포 (Ubuntu)
1. Docker·compose 설치, git clone -b platform-mvp <repo>
2. server/.env 작성 (JWT_SECRET 필수 변경)
3. docker compose up -d --build
4. 보안그룹에서 8000/tcp 오픈 → 앱의 API_BASE 를 http://<EC2-IP>:8000 으로
