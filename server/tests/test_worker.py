import sqlite3

from app import db, storage
from worker import main as worker_main
from worker import pipeline


def _setup(tmp_path, monkeypatch, clip):
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('w@t.co','x','워커')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    import shutil
    shutil.copy(clip, storage.upload_path(vid, clip.suffix))
    conn.execute("INSERT INTO jobs(video_id) VALUES(?)", (vid,))
    conn.commit()
    return conn, vid


def test_safe_clip_pipeline(tmp_path, monkeypatch, testclips):
    conn, vid = _setup(tmp_path, monkeypatch, testclips / "00_safe_gradient.mkv")
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready" and v["risk"] == "safe"
    assert v["filtered_path"] is None
    assert storage.original_path(vid).exists()
    assert storage.thumb_path(vid).exists()


def test_flash_clip_pipeline(tmp_path, monkeypatch, testclips):
    conn, vid = _setup(tmp_path, monkeypatch, testclips / "01_flash_5hz.mkv")
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready"
    assert v["risk"] in ("corrected", "uncorrected")   # 기계 동작 검증
    assert v["n_flash"] > 0
    assert storage.filtered_path(vid).exists()
    assert storage.report_path(vid).exists()
    job = conn.execute("SELECT * FROM jobs WHERE video_id=?", (vid,)).fetchone()
    assert job["status"] == "done"


def test_error_marks_failed(tmp_path, monkeypatch, small_mp4):
    conn, vid = _setup(tmp_path, monkeypatch, small_mp4)
    monkeypatch.setattr(pipeline, "detect",
                        type("D", (), {"detect": staticmethod(
                            lambda p: (_ for _ in ()).throw(RuntimeError("붐"))),
                            "save_report": staticmethod(lambda r, p: None)}))
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT status FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "failed"
    job = conn.execute("SELECT * FROM jobs WHERE video_id=?", (vid,)).fetchone()
    assert job["status"] == "error" and "붐" in job["error_msg"]


def test_requeue_stale(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('r@t.co','x','재큐')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    conn.execute("INSERT INTO jobs(video_id,status,started_at) "
                 "VALUES(1,'running',datetime('now','-2 hours'))")
    worker_main.requeue_stale(conn)
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
