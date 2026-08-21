"""구간 저장 — 격자 정렬과 "통짜 = 조각 1개" 계약.

절단·이어붙이기는 ffmpeg/ffprobe 가 필요해서 여기서는 순수 로직과 DB 계약만
본다 (실측 검증은 docs/구간저장-토글-설계.md 10절).
"""
from app import db, storage
from app.config import settings
from worker import segments


def test_snap_격자정렬_및_병합():
    got = segments.snap([[0.13, 0.80], [4.27, 5.40]], dur=14.7, gop=0.5)
    assert got == [[0.0, 1.0], [4.0, 5.5]]


def test_snap_붙은구간은_하나로():
    got = segments.snap([[0.9, 1.1], [1.2, 1.4]], dur=10.0, gop=0.5)
    assert got == [[0.5, 1.5]]


def test_snap_영상길이를_안_넘는다():
    got = segments.snap([[9.8, 9.9]], dur=10.0, gop=0.5)
    assert got[-1][1] == 10.0


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname)"
                 " VALUES('s@t.co','x','구간')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    return conn, vid


def test_구간이_없으면_전체를_덮는_조각_하나(tmp_path, monkeypatch):
    """통짜 = 조각 1개. 별도 모드가 없다."""
    conn, vid = _setup(tmp_path, monkeypatch)
    flt = storage.filtered_path(vid)
    flt.write_bytes(b"filtered-bytes")

    seg_s = segments.store(conn, vid, storage.original_path(vid), flt, [], 10.0)

    rows = conn.execute("SELECT * FROM video_segments WHERE video_id=?",
                        (vid,)).fetchall()
    assert len(rows) == 1
    assert (rows[0]["start_s"], rows[0]["end_s"]) == (0.0, 10.0)
    assert seg_s == 10.0


def test_통짜는_남지_않는다(tmp_path, monkeypatch):
    """filtered.mp4 를 조각으로 옮긴다 — 중복 저장이 없어야 절감이 생긴다."""
    conn, vid = _setup(tmp_path, monkeypatch)
    flt = storage.filtered_path(vid)
    flt.write_bytes(b"filtered-bytes")

    segments.store(conn, vid, storage.original_path(vid), flt, [], 10.0)

    assert not flt.exists()
    assert (storage.video_dir(vid) / "seg_000.mp4").read_bytes() == b"filtered-bytes"


def test_무장이_전체면_쪼개지_않는다(tmp_path, monkeypatch):
    """구간합이 영상 길이와 같으면 잘게 나눌 이유가 없다 — 조각 1개."""
    conn, vid = _setup(tmp_path, monkeypatch)
    flt = storage.filtered_path(vid)
    flt.write_bytes(b"x")

    segments.store(conn, vid, storage.original_path(vid), flt,
                   [[0.0, 10.0]], 10.0)

    rows = conn.execute("SELECT * FROM video_segments WHERE video_id=?",
                        (vid,)).fetchall()
    assert len(rows) == 1


def test_다시_저장하면_이전_조각이_지워진다(tmp_path, monkeypatch):
    conn, vid = _setup(tmp_path, monkeypatch)
    for _ in range(2):
        flt = storage.filtered_path(vid)
        flt.write_bytes(b"x")
        segments.store(conn, vid, storage.original_path(vid), flt, [], 10.0)
    n = conn.execute("SELECT COUNT(*) FROM video_segments WHERE video_id=?",
                     (vid,)).fetchone()[0]
    assert n == 1


def test_스키마에_구간표와_컬럼이_있다(tmp_path, monkeypatch):
    conn, _ = _setup(tmp_path, monkeypatch)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    assert {"seg_total_s", "seg_ratio"} <= cols
    assert "storage_mode" not in cols          # 통짜 모드는 없다
    seg_cols = {r[1] for r in conn.execute("PRAGMA table_info(video_segments)")}
    assert {"video_id", "idx", "start_s", "end_s", "path", "bytes"} <= seg_cols
