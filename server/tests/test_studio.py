"""스튜디오 API — 본인 영상 전 상태 목록 + 삭제, 마커의 failed_rules 필터."""
import json

from app import db, storage


def _put_video(email, title="t", status="processing", risk=None,
               job_status="queued", error=None):
    conn = db.connect()
    uid = conn.execute("SELECT id FROM users WHERE email=?",
                       (email,)).fetchone()[0]
    conn.execute("INSERT INTO videos(uploader_id,title,status,risk)"
                 " VALUES(?,?,?,?)", (uid, title, status, risk))
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    conn.execute("INSERT INTO jobs(video_id,status,error_msg) VALUES(?,?,?)",
                 (vid, job_status, error))
    conn.commit(); conn.close()
    return vid


def test_my_videos_all_statuses_and_isolation(client, auth_headers):
    h = auth_headers(email="a@t.co")
    h2 = auth_headers(email="b@t.co")
    v1 = _put_video("a@t.co", "처리중")
    v2 = _put_video("a@t.co", "실패작", status="failed",
                    job_status="error", error="ffmpeg 죽음")
    _put_video("b@t.co", "남의것", status="ready", risk="safe")

    vids = client.get("/studio/api/videos", headers=h).json()["videos"]
    assert [v["id"] for v in vids] == [v2, v1]          # 최신순, 남의 것 제외
    assert vids[0]["status"] == "failed"
    assert vids[0]["job_error"] == "ffmpeg 죽음"
    assert vids[1]["job_status"] == "queued"

    other = client.get("/studio/api/videos", headers=h2).json()["videos"]
    assert len(other) == 1 and other[0]["title"] == "남의것"


def test_delete_owner_only_and_files(client, auth_headers, tmp_path):
    h = auth_headers(email="own@t.co")
    h2 = auth_headers(email="not@t.co")
    vid = _put_video("own@t.co", "지울것", status="ready", risk="safe",
                     job_status="done")
    d = storage.video_dir(vid)
    (d / "original.mp4").write_bytes(b"x")

    assert client.delete(f"/studio/api/videos/{vid}", headers=h2).status_code == 403
    r = client.delete(f"/studio/api/videos/{vid}", headers=h)
    assert r.status_code == 200 and r.json() == {"deleted": vid}
    assert not d.exists()
    assert client.get("/studio/api/videos", headers=h).json()["videos"] == []


def test_delete_blocked_while_running(client, auth_headers):
    h = auth_headers(email="run@t.co")
    vid = _put_video("run@t.co", "처리중", job_status="running")
    assert client.delete(f"/studio/api/videos/{vid}", headers=h).status_code == 409


def test_report_segments_only_failed_rules(client, auth_headers):
    """violation_segments 의 측정 마커(프레임간격 등)는 failed_rules 에 없으면
    리포트에서 제외 — 보정본 마커가 잔존 겹침 검사를 오염시키지 않는다."""
    h = auth_headers(email="seg@t.co")
    vid = _put_video("seg@t.co", "마커", status="ready", risk="corrected",
                     job_status="done")
    rp = storage.report_path(vid)
    rp.write_text(json.dumps({
        "compliant": False, "failed_rules": ["플래시"],
        "violation_segments": [
            {"rule": "플래시", "start_s": 1.0, "end_s": 2.0},
            {"rule": "프레임간격", "start_s": 0.0, "end_s": 9.0}]}),
        encoding="utf-8")
    storage.report_filtered_path(vid).write_text(json.dumps({
        "compliant": True, "failed_rules": [],
        "violation_segments": [
            {"rule": "프레임간격", "start_s": 0.0, "end_s": 9.0}]}),
        encoding="utf-8")
    conn = db.connect()
    conn.execute("UPDATE videos SET report_path=? WHERE id=?", (str(rp), vid))
    conn.commit(); conn.close()

    segs = client.get(f"/videos/{vid}/report", headers=h).json()["segments"]
    assert [s["rule"] for s in segs] == ["플래시"]
    assert segs[0]["resolved"] is True          # 보정본 잔존 위반 없음 → 해소
