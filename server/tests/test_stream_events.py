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
