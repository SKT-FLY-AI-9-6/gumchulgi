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
