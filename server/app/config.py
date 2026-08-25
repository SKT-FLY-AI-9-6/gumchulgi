import os
from pathlib import Path


_INSECURE_SECRETS = ("", "dev-secret", "change-me")


class Settings:
    def __init__(self):
        self.DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
        self.JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
        self.APP_ENV = os.environ.get("APP_ENV", "dev")
        self.DAILY_BUDGET_S = int(os.environ.get("DAILY_BUDGET_S", "300"))
        self.MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
        self.MAX_DURATION_S = int(os.environ.get("MAX_DURATION_S", "180"))
        self.TOKEN_DAYS = int(os.environ.get("TOKEN_DAYS", "30"))
        # 데모 개방 인증 — 로그인 UI 는 그대로 두고 검증만 끈다:
        # 아무 이메일/비밀번호나 통과, 없는 계정은 자동 생성. 시연 전용.
        self.AUTH_OPEN = os.environ.get("AUTH_OPEN", "0") == "1"


settings = Settings()


def validate_production():
    """운영 환경(APP_ENV=production)에서 JWT_SECRET 이 기본값이면 부팅을
    막는다 — 조용히 dev-secret/change-me 로 뜨는 사고를 방지."""
    if settings.APP_ENV == "production" and settings.JWT_SECRET in _INSECURE_SECRETS:
        raise RuntimeError(
            "운영 환경(APP_ENV=production)에서는 JWT_SECRET을 기본값이 "
            "아닌 안전한 값으로 반드시 설정해야 합니다.")
