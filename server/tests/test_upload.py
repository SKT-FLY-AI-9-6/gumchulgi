def test_upload_queues_job(client, auth_headers, small_mp4):
    h = auth_headers()
    with open(small_mp4, "rb") as f:
        r = client.post("/videos", headers=h, data={"title": "테스트"},
                        files={"file": ("a.mp4", f, "video/mp4")})
    assert r.status_code == 202
    vid = r.json()["video_id"]

    mine = client.get("/me/videos", headers=h).json()["videos"]
    assert mine[0]["id"] == vid and mine[0]["status"] == "processing"


def test_upload_rejects_non_video(client, auth_headers):
    h = auth_headers()
    r = client.post("/videos", headers=h, data={"title": "x"},
                    files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_upload_rejects_file_over_configured_limit(
        client, auth_headers, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)
    h = auth_headers()
    r = client.post("/videos", headers=h, data={"title": "too-big"},
                    files={"file": ("a.mp4", b"x", "video/mp4")})
    assert r.status_code == 413
    assert r.json()["detail"] == "0MB 초과"
