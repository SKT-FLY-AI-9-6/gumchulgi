import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "psepipe_v3_seam"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import db
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    def _make(email="u@t.co", nickname="유저"):
        r = client.post("/auth/signup", json={
            "email": email, "password": "pw123456", "nickname": nickname})
        assert r.status_code == 201, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}
    return _make
