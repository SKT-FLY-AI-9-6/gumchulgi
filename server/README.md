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

## 테스트
```
cd server && pip install -r requirements-dev.txt && python -m pytest tests/ -v
```

## EC2 배포 (Ubuntu)
1. Docker·compose 설치, git clone -b platform-mvp <repo>
2. server/.env 작성 (JWT_SECRET 필수 변경)
3. docker compose up -d --build
4. 보안그룹에서 8000/tcp 오픈 → 앱의 API_BASE 를 http://<EC2-IP>:8000 으로
