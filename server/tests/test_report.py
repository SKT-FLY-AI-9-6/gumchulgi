import json


def _make_video(client, auth_headers, tmp_path, small_mp4, *, risk="corrected"):
    h = auth_headers()
    with open(small_mp4, "rb") as f:
        r = client.post("/videos", headers=h, data={"title": "리포트"},
                        files={"file": ("a.mp4", f, "video/mp4")})
    vid = r.json()["video_id"]
    rep = tmp_path / f"rep{vid}.json"
    rep.write_text(json.dumps({
        "compliant": False, "duration_s": 10.0,
        "violation_segments": [
            {"start_s": 1.0, "end_s": 1.5, "rule": "플래시"},
            {"start_s": 1.6, "end_s": 2.2, "rule": "플래시"},   # 0.5s 이내 → 병합
            {"start_s": 5.0, "end_s": 6.0, "rule": "적색포화"},
        ]}), encoding="utf-8")
    repf = tmp_path / f"rep{vid}.json".replace("rep", "x")  # placeholder
    filtered = str(rep).replace("report.json", "report_filtered.json")
    import sqlite3
    from app.config import settings
    conn = sqlite3.connect(settings.DATA_DIR / "db.sqlite3")
    conn.execute("UPDATE videos SET status='ready', risk=?, report_path=?,"
                 " duration_s=10.0 WHERE id=?", (risk, str(rep), vid))
    conn.commit(); conn.close()
    return h, vid


def test_report_merges_and_marks_resolved(client, auth_headers, tmp_path,
                                          small_mp4):
    h, vid = _make_video(client, auth_headers, tmp_path, small_mp4)
    r = client.get(f"/videos/{vid}/report", headers=h)
    assert r.status_code == 200
    body = r.json()
    segs = body["segments"]
    assert len(segs) == 2                       # 플래시 2건 병합 + 적색 1건
    flash = next(s for s in segs if s["rule"] == "플래시")
    assert flash["start_s"] == 1.0 and flash["end_s"] == 2.2
    # corrected + 잔존 리포트 없음 → 전부 완화됨
    assert all(s["resolved"] for s in segs)


def test_report_owner_only(client, auth_headers, tmp_path, small_mp4):
    h, vid = _make_video(client, auth_headers, tmp_path, small_mp4)
    other = auth_headers("other@t.co")
    assert client.get(f"/videos/{vid}/report",
                      headers=other).status_code == 403
