import sqlite3

import pytest

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
    assert v["filter_level"] in ("strong", "base")
    assert v["n_flash"] > 0
    # 통짜 filtered.mp4 는 남기지 않는다 — 조각으로만 보관한다
    assert not storage.filtered_path(vid).exists()
    assert (storage.video_dir(vid) / "seg_000.mp4").exists()
    assert storage.report_path(vid).exists()
    assert storage.report_filtered_path(vid).exists()
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
    # CPU 폴백 사다리(보정 2회)는 3분 영상에서 10분을 넘길 수 있어
    # stale 기준을 30분으로 올렸다 — 31분 전 시작 잡이 재큐잉되는지 확인.
    conn.execute("INSERT INTO jobs(video_id,status,started_at) "
                 "VALUES(1,'running',datetime('now','-31 minutes'))")
    worker_main.requeue_stale(conn)
    row = conn.execute("SELECT status, started_at FROM jobs").fetchone()
    assert row["status"] == "queued"
    assert row["started_at"] is None


def test_main_calls_requeue_stale_on_idle_tick(tmp_path, monkeypatch):
    """도커가 몇 초 만에 워커를 재시작해도, 시작 시 1회뿐 아니라
    idle 틱마다 requeue_stale 이 호출되어야 오래 걸린 잡이 풀린다."""
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    calls = []
    monkeypatch.setattr(worker_main, "requeue_stale",
                        lambda c: calls.append("requeue"))
    monkeypatch.setattr(worker_main, "run_once", lambda c: False)  # 항상 idle

    def _stop_sleep(_s):
        raise SystemExit
    monkeypatch.setattr(worker_main.time, "sleep", _stop_sleep)

    with pytest.raises(SystemExit):
        worker_main.main()

    # 시작 시 1회 + 첫 idle 틱에서 1회 = 최소 2회 호출돼야 함
    assert len(calls) >= 2
