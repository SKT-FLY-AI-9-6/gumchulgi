import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "psepipe_v3_seam"))

import subprocess
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


@pytest.fixture(scope="session")
def small_mp4(tmp_path_factory):
    """2초 360x640 회색 테스트 영상 (오디오 포함)."""
    p = tmp_path_factory.mktemp("clips") / "gray.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=2:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(p)], check=True)
    return p


@pytest.fixture(scope="session")
def testclips(tmp_path_factory):
    """legacy_detectors/make_testclips.py 로 정답 알려진 합성 클립 생성."""
    out = tmp_path_factory.mktemp("testclips")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable,
                    str(REPO / "legacy_detectors" / "make_testclips.py"),
                    str(out)], check=True, cwd=str(REPO), env=env)
    return out  # 00_safe_gradient.mkv(안전), 01_flash_5hz.mkv(플래시 위반) 등
