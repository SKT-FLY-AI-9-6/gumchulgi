import json
import shutil
import types
from pathlib import Path

from app import db, storage

# 공용 계약 v1 형태의 impact JSON 샘플
IMPACT = {"v": 1, "lum_mean_drop_pct": 18.4, "lum_peak_drop_pct": 42.7,
          "flash_before": 5, "flash_after": 0,
          "flash_viol_s_before": 3.2, "flash_viol_s_after": 0.0,
          "color_mean_duv": 0.004, "color_p95_duv": 0.011,
          "color_keep_pct": 92.5}


# ── GET /dashboard/recent_impact ─────────────────────────────────

def _seed_video(conn, *, impact_json, filtered="/m/filtered.mp4",
                thumb="/m/thumb.jpg", level="strong", title="보정영상"):
    conn.execute(
        "INSERT INTO videos(uploader_id,title,status,risk,filter_level,"
        " filtered_path,thumb_path,impact_json)"
        " VALUES(1,?,'ready','corrected',?,?,?,?)",
        (title, level, filtered, thumb, impact_json))
    return conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]


def _watch(conn, uid, vid, created_at, variant="filtered"):
    conn.execute(
        "INSERT INTO watch_events(user_id,video_id,watched_s,variant,"
        "created_at) VALUES(?,?,10,?,?)", (uid, vid, variant, created_at))


def _uid(conn, email):
    return conn.execute("SELECT id FROM users WHERE email=?",
                        (email,)).fetchone()[0]


def test_recent_impact_contract(client, auth_headers):
    h = auth_headers(email="i@t.co")
    other = auth_headers(email="other@t.co")
    conn = db.connect()
    uid = _uid(conn, "i@t.co")
    a = _seed_video(conn, impact_json=json.dumps(IMPACT), title="A")
    b = _seed_video(conn, impact_json=json.dumps({**IMPACT, "flash_after": 1}),
                    level="base", title="B", thumb=None)
    _watch(conn, uid, a, "2026-08-24 01:00:00")   # A 를 두 번 시청 —
    _watch(conn, uid, a, "2026-08-24 03:00:00")   # 최신 1행만 남아야 한다
    _watch(conn, uid, b, "2026-08-24 02:00:00")
    _watch(conn, _uid(conn, "other@t.co"), b, "2026-08-24 09:00:00")  # 남의 것
    conn.commit(); conn.close()

    r = client.get("/dashboard/recent_impact", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["video_id"] for i in items] == [a, b]   # 영상별 1행, 최신순
    top = items[0]
    assert top == {"video_id": a, "title": "A",
                   "thumb_url": f"/videos/{a}/thumb",
                   "watched_at": "2026-08-24 03:00:00",
                   "filter_level": "strong", "impact": IMPACT}
    assert items[1]["thumb_url"] is None              # 썸네일 없으면 null
    assert items[1]["impact"]["flash_after"] == 1

    r = client.get("/dashboard/recent_impact?limit=1", headers=h)
    assert [i["video_id"] for i in r.json()["items"]] == [a]


def test_recent_impact_excludes_original_variant(client, auth_headers):
    # 보정본이 아니라 **원본**으로 본 이벤트는 "최근 필터 적용 영상"이 아니다
    h = auth_headers(email="ov@t.co")
    conn = db.connect()
    vid = _seed_video(conn, impact_json=json.dumps(IMPACT), title="OV")
    _watch(conn, _uid(conn, "ov@t.co"), vid, "2026-08-24 01:00:00",
           variant="original")
    conn.commit(); conn.close()
    r = client.get("/dashboard/recent_impact", headers=h)
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_recent_impact_excludes_without_impact_or_filtered(
        client, auth_headers):
    h = auth_headers(email="n@t.co")
    conn = db.connect()
    uid = _uid(conn, "n@t.co")
    no_impact = _seed_video(conn, impact_json=None)          # impact NULL
    no_filtered = _seed_video(conn, impact_json=json.dumps(IMPACT),
                              filtered=None)                 # 보정본 없음
    ok = _seed_video(conn, impact_json=json.dumps(IMPACT))
    for vid in (no_impact, no_filtered, ok):
        _watch(conn, uid, vid, "2026-08-24 01:00:00")
    conn.commit(); conn.close()

    items = client.get("/dashboard/recent_impact", headers=h).json()["items"]
    assert [i["video_id"] for i in items] == [ok]


def test_recent_impact_requires_auth(client):
    assert client.get("/dashboard/recent_impact").status_code in (401, 403)
    r = client.get("/dashboard/recent_impact",
                   headers={"Authorization": "Bearer bad-token"})
    assert r.status_code == 401


# ── pipeline 의 impact 저장 (measure 스텁, test_worker 스타일) ────

def _worker_setup(tmp_path, monkeypatch, clip):
    from app.config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    conn = db.connect()
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('w@t.co','x','워커')")
    conn.execute("INSERT INTO videos(uploader_id,title) VALUES(1,'t')")
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    shutil.copy(clip, storage.upload_path(vid, clip.suffix))
    conn.execute("INSERT INTO jobs(video_id) VALUES(?)", (vid,))
    conn.commit()
    return conn, vid


def _stub_heavy_stages(monkeypatch, pipeline, first_report, second_report):
    """검출·보정 사다리를 스텁해 위반→보정 성공 경로만 가볍게 재현한다."""
    monkeypatch.setattr(pipeline, "ffmpeg", types.SimpleNamespace(
        normalize=lambda src, dst: shutil.copy(src, dst),
        thumbnail=lambda src, dst: Path(dst).write_bytes(b"jpg")))
    monkeypatch.setattr(pipeline, "detect", types.SimpleNamespace(
        detect=lambda p: {"compliant": False,
                          "axes": {"flash": 1, "red": 0,
                                   "pattern": 0, "cut": 0},
                          "duration_s": 2.0, "report": first_report},
        save_report=lambda r, p: Path(p).write_text("{}", encoding="utf-8")))

    def fake_ladder(video_id, orig):
        flt = storage.filtered_path(video_id)
        shutil.copy(orig, flt)
        return flt, {"compliant": True, "report": second_report}, "strong"
    monkeypatch.setattr(pipeline, "_correct_with_ladder", fake_ladder)


def test_pipeline_saves_impact_json(tmp_path, monkeypatch, small_mp4):
    from worker import main as worker_main
    from worker import pipeline
    conn, vid = _worker_setup(tmp_path, monkeypatch, small_mp4)
    first_report = {"compliant": False, "failed_rules": ["플래시 위반"]}
    second_report = {"compliant": True, "failed_rules": []}
    _stub_heavy_stages(monkeypatch, pipeline, first_report, second_report)

    calls = {}

    def fake_measure(src, out, report_before=None, report_after=None):
        calls["args"] = (src, out, report_before, report_after)
        return IMPACT
    monkeypatch.setattr(pipeline, "impact",
                        types.SimpleNamespace(measure=fake_measure))

    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready" and v["risk"] == "corrected"
    assert json.loads(v["impact_json"]) == IMPACT
    assert calls["args"] == (str(storage.original_path(vid)),
                             str(storage.filtered_path(vid)),
                             first_report, second_report)


def test_pipeline_impact_failure_leaves_null(tmp_path, monkeypatch, small_mp4):
    """measure 가 죽어도 업로드 처리(ready 전환)는 깨지지 않는다."""
    from worker import main as worker_main
    from worker import pipeline
    conn, vid = _worker_setup(tmp_path, monkeypatch, small_mp4)
    _stub_heavy_stages(monkeypatch, pipeline,
                       {"compliant": False}, {"compliant": True})
    monkeypatch.setattr(pipeline, "impact", types.SimpleNamespace(
        measure=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("붐"))))

    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready" and v["risk"] == "corrected"
    assert v["impact_json"] is None
    job = conn.execute("SELECT status FROM jobs WHERE video_id=?",
                       (vid,)).fetchone()
    assert job["status"] == "done"
