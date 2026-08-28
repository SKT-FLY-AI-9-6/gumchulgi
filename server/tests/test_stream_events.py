from app import db, storage


def _ready_video(client, small_mp4, risk="corrected"):
    import shutil
    conn = db.connect()
    conn.execute("INSERT INTO videos(uploader_id,title,status,risk,"
                 "original_path,n_flash) VALUES(1,'t','ready',?,'x',1)", (risk,))
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    shutil.copy(small_mp4, storage.original_path(vid))
    conn.execute("UPDATE videos SET original_path=? WHERE id=?",
                 (str(storage.original_path(vid)), vid))
    conn.commit(); conn.close()
    return vid


def test_stream_supports_range(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    r = client.get(f"/videos/{vid}/stream?variant=original", headers=h)
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-range"].startswith("bytes 0-99/")


def test_stream_accepts_scoped_media_query_token(
        client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    media = client.post("/auth/media-token", headers=h).json()["token"]

    r = client.get(
        f"/videos/{vid}/stream?variant=original&token={media}",
        headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100

    # 전체 access token을 쿼리에 넣는 이전 방식은 거부한다.
    access = h["Authorization"].split(" ", 1)[1]
    denied = client.get(
        f"/videos/{vid}/stream?variant=original&token={access}")
    assert denied.status_code == 401


def test_events_accumulate_exposure(client, auth_headers, small_mp4, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_BUDGET_S", 100)
    h = auth_headers()
    vid = _ready_video(client, small_mp4, risk="corrected")

    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 30, "variant": "original"}).json()
    assert r["today_percent"] == 30.0 and r["status"] == "good"

    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 55, "variant": "original"}).json()
    assert r["today_percent"] == 85.0 and r["status"] == "warning"

    # 보정본 시청은 노출에 미포함
    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 60, "variant": "filtered"}).json()
    assert r["today_percent"] == 85.0

    # 조회수는 전부 +1
    from app import db as db2
    conn = db2.connect()
    assert conn.execute("SELECT view_count FROM videos WHERE id=?",
                        (vid,)).fetchone()[0] == 3


def test_stream_range_suffix_serves_last_n_bytes(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    size = small_mp4.stat().st_size

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": "bytes=-100"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-range"] == f"bytes {size-100}-{size-1}/{size}"
    assert r.content == small_mp4.read_bytes()[-100:]


def test_stream_range_malformed_ignored_serves_full(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    size = small_mp4.stat().st_size

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": "bytes=abc-"})
    assert r.status_code == 200
    assert len(r.content) == size


def test_stream_range_multi_range_ignored_serves_full(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    size = small_mp4.stat().st_size

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": "bytes=0-10, 20-30"})
    assert r.status_code == 200
    assert len(r.content) == size


def test_stream_range_out_of_range_returns_416(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    size = small_mp4.stat().st_size

    r = client.get(f"/videos/{vid}/stream?variant=original",
                   headers={**h, "Range": f"bytes={size+1000}-"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{size}"


def test_stream_variant_rejects_bogus_value(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    r = client.get(f"/videos/{vid}/stream?variant=bogus", headers=h)
    assert r.status_code == 422


def test_events_variant_is_case_sensitive(client, auth_headers, small_mp4):
    h = auth_headers()
    vid = _ready_video(client, small_mp4)
    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 1, "variant": "ORIGINAL"})
    assert r.status_code == 422


def test_feed_stream_serves_filtered_bytes_not_original(client, auth_headers,
                                                         small_mp4):
    """corrected 영상 + filter_on=True 유저가 /feed 로 받은 stream_url 은
    filtered 파일 바이트를 서빙해야 한다 (원본이 아니라)."""
    import shutil
    h = auth_headers()
    conn = db.connect()
    conn.execute("INSERT INTO videos(uploader_id,title,status,risk) "
                 "VALUES(1,'t','ready','corrected')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    orig_path = storage.original_path(vid)
    filt_path = storage.filtered_path(vid)
    shutil.copy(small_mp4, orig_path)
    orig_bytes = small_mp4.read_bytes()
    filt_bytes = orig_bytes + b"__FILTERED_MARKER__"
    filt_path.write_bytes(filt_bytes)
    conn.execute(
        "UPDATE videos SET original_path=?, filtered_path=? WHERE id=?",
        (str(orig_path), str(filt_path), vid))
    conn.commit(); conn.close()

    feed = client.get("/feed", headers=h).json()
    video = next(v for v in feed["videos"] if v["id"] == vid)
    assert video["variant"] == "filtered"

    r = client.get(video["stream_url"], headers=h)
    assert r.status_code in (200, 206)
    assert r.content == filt_bytes
    assert r.content != orig_bytes
