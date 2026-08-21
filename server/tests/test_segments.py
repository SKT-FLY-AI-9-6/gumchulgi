"""구간 저장 — 격자 정렬과 후퇴 조건.

절단·이어붙이기는 ffmpeg 가 필요해서 여기서는 순수 로직만 본다
(로컬 실측 검증은 docs/구간저장-토글-설계.md 10절).
"""
import pytest

from app import db, storage
from app.config import settings
from worker import segments


def test_snap_격자정렬_및_병합():
    # 0.5초 격자로 넓히고, 겹치면 하나로 합친다
    got = segments.snap([[0.13, 0.80], [4.27, 5.40]], dur=14.7, gop=0.5)
    assert got == [[0.0, 1.0], [4.0, 5.5]]


def test_snap_붙은구간은_하나로():
    # 0.9~1.1 과 1.2~1.4 는 넓히면 [0.5,1.5] / [1.0,1.5] 로 겹친다
    got = segments.snap([[0.9, 1.1], [1.2, 1.4]], dur=10.0, gop=0.5)
    assert got == [[0.5, 1.5]]


def test_snap_영상길이를_안_넘는다():
    got = segments.snap([[9.8, 9.9]], dur=10.0, gop=0.5)
    assert got[-1][1] == 10.0


def test_구간없으면_통짜(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    mode, seg_s = segments.store(conn, 1, tmp_path / "o.mp4",
                                 tmp_path / "f.mp4", [], 10.0)
    assert (mode, seg_s) == ("full", 0.0)


def test_사실상_전체면_통짜(tmp_path, monkeypatch):
    """무장이 영상 전체에 걸치면 쪼갤 이유가 없다 — 조각을 만들지도 않는다."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    mode, seg_s = segments.store(conn, 1, tmp_path / "o.mp4",
                                 tmp_path / "f.mp4", [[0.0, 9.9]], 10.0)
    assert mode == "full"          # TIME_GUARD 0.95 에 걸린다


def test_스키마에_구간표와_컬럼이_있다(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    assert {"storage_mode", "seg_total_s", "seg_ratio"} <= cols
    seg_cols = {r[1] for r in conn.execute("PRAGMA table_info(video_segments)")}
    assert {"video_id", "idx", "start_s", "end_s", "path", "bytes"} <= seg_cols


def test_storage_mode_기본값은_full(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname)"
                 " VALUES('s@t.co','x','구간')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    row = conn.execute("SELECT storage_mode FROM videos").fetchone()
    assert row["storage_mode"] == "full"
