"""사다리(strong 1차 → 재검출 → base 폴백) 분기 검증 — 필터·검출은 가짜.

규칙(스펙 2026-08-20 개정): 위반 원본에 strong 을 먼저 적용하고, 재검출
적합이면 그대로 채택. 위반이 남으면 base 로 한 번 더 보정한 뒤 두 출력의
위반 규칙 집합을 비교해 strong ⊆ base 면 strong, 아니면 base 를 채택한다.
"""
import json
from pathlib import Path

from app import db, storage
from worker import main as worker_main
from worker import pipeline


def _fake_result(compliant, rules):
    return {"compliant": compliant,
            "axes": {"flash": 0 if compliant else 1, "red": 0,
                     "pattern": 0, "cut": 0},
            "duration_s": 2.0,
            "report": {"compliant": compliant, "failed_rules": sorted(rules),
                       "violation_segments": []}}


def _setup(tmp_path, monkeypatch, *, strong_rules, base_rules,
           original_rules=("플래시",)):
    """가짜 filter_video 는 출력 파일에 강도 태그를 쓰고, 가짜 detect 는
    그 태그(또는 원본 여부)를 보고 미리 정한 판정을 돌려준다."""
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('l@t.co','x','사다리')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    storage.upload_path(vid, ".mp4").write_bytes(b"fake")
    conn.execute("INSERT INTO jobs(video_id) VALUES(?)", (vid,))
    conn.commit()

    calls = []

    def fake_filter(src, dst, cfg=None, **kw):
        level = "strong" if getattr(cfg, "net_directional", False) else "base"
        calls.append(level)
        Path(dst).write_text(level, encoding="utf-8")
        return 60

    def fake_detect(path):
        p = Path(path)
        if p.name == "original.mp4":
            rules = set(original_rules)
            return _fake_result(not rules, rules)
        tag = p.read_text(encoding="utf-8")
        rules = strong_rules if tag == "strong" else base_rules
        return _fake_result(not rules, set(rules))

    monkeypatch.setattr(pipeline.filter_stream, "filter_video", fake_filter)
    monkeypatch.setattr(pipeline.detect, "detect", fake_detect)
    monkeypatch.setattr(pipeline.ffmpeg, "normalize",
                        lambda src, dst: Path(dst).write_text(
                            "original.mp4", encoding="utf-8"))
    monkeypatch.setattr(pipeline.ffmpeg, "thumbnail",
                        lambda src, dst: Path(dst).write_bytes(b"jpg"))
    return conn, vid, calls


def _video_row(conn, vid):
    return conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()


def test_strong_compliant_adopted_without_base(tmp_path, monkeypatch):
    conn, vid, calls = _setup(tmp_path, monkeypatch,
                              strong_rules=(), base_rules=("안 쓰임",))
    assert worker_main.run_once(conn) is True
    v = _video_row(conn, vid)
    assert v["risk"] == "corrected"
    assert v["filter_level"] == "strong"
    assert calls == ["strong"]          # base 는 아예 실행되지 않는다
    # 채택본은 통짜가 아니라 조각으로 남는다 — 전체를 덮는 조각 1 개가 곧 통짜다
    assert not storage.filtered_path(vid).exists()
    assert (storage.video_dir(vid) / "seg_000.mp4").read_text(
        encoding="utf-8") == "strong"
    rep = json.loads(storage.report_filtered_path(vid).read_text("utf-8"))
    assert rep["compliant"] is True


def test_fallback_to_base_when_strong_not_subset(tmp_path, monkeypatch):
    # strong 은 플래시를 남겼는데 base 는 다 고침 → base 채택 (209편의 폴백 5편 유형)
    conn, vid, calls = _setup(tmp_path, monkeypatch,
                              strong_rules=("플래시",), base_rules=())
    assert worker_main.run_once(conn) is True
    v = _video_row(conn, vid)
    assert v["risk"] == "corrected"
    assert v["filter_level"] == "base"
    assert calls == ["strong", "base"]
    assert not storage.filtered_path(vid).exists()
    assert (storage.video_dir(vid) / "seg_000.mp4").read_text(
        encoding="utf-8") == "base"
    # 채택되지 않은 시도본은 남기지 않는다
    leftovers = [p.name for p in storage.video_dir(vid).glob("_flt_*")]
    assert leftovers == []


def test_strong_kept_when_subset_even_if_not_compliant(tmp_path, monkeypatch):
    # 둘 다 잔존이지만 strong ⊆ base → strong 채택, risk 는 uncorrected
    conn, vid, calls = _setup(tmp_path, monkeypatch,
                              strong_rules=("패턴",),
                              base_rules=("패턴", "화면전환"))
    assert worker_main.run_once(conn) is True
    v = _video_row(conn, vid)
    assert v["risk"] == "uncorrected"
    assert v["filter_level"] == "strong"
    assert calls == ["strong", "base"]
    rep = json.loads(storage.report_filtered_path(vid).read_text("utf-8"))
    assert rep["failed_rules"] == ["패턴"]


def test_safe_clip_records_no_filter_level(tmp_path, monkeypatch):
    conn, vid, calls = _setup(tmp_path, monkeypatch,
                              strong_rules=(), base_rules=(),
                              original_rules=())
    assert worker_main.run_once(conn) is True
    v = _video_row(conn, vid)
    assert v["risk"] == "safe"
    assert v["filter_level"] is None
    assert calls == []
