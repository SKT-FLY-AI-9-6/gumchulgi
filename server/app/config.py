import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
        self.JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
        self.DAILY_BUDGET_S = int(os.environ.get("DAILY_BUDGET_S", "300"))
        self.MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
        self.MAX_DURATION_S = int(os.environ.get("MAX_DURATION_S", "180"))
        self.TOKEN_DAYS = int(os.environ.get("TOKEN_DAYS", "30"))


settings = Settings()
