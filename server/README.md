# 플랫폼 서버

## 로컬 실행
```
cp server/.env.example server/.env   # JWT_SECRET 수정
docker compose up -d --build
curl http://localhost:8000/health    # {"ok":true}
```

## 테스트
```
cd server && pip install -r requirements-dev.txt && python -m pytest tests/ -v
```

## EC2 배포 (Ubuntu)
1. Docker·compose 설치, git clone -b platform-mvp <repo>
2. server/.env 작성 (JWT_SECRET 필수 변경)
3. docker compose up -d --build
4. 보안그룹에서 8000/tcp 오픈 → 앱의 API_BASE 를 http://<EC2-IP>:8000 으로
