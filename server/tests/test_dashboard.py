from app import db


def _seed(client, uid_email, events):
    """events: (risk, watched_s, variant, days_ago, hour)"""
    conn = db.connect()
    for i, (risk, w, var, days, hour) in enumerate(events):
        conn.execute("INSERT INTO videos(uploader_id,title,status,risk,"
                     "n_flash,n_red) VALUES(1,'t','ready',?,1,1)", (risk,))
        vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
        uid = conn.execute("SELECT id FROM users WHERE email=?",
                           (uid_email,)).fetchone()[0]
        conn.execute(
            "INSERT INTO watch_events(user_id,video_id,watched_s,variant,"
            "created_at) VALUES(?,?,?,?,"
            " datetime(datetime('now','localtime'),'start of day',"
            f" '-{days} days', '+{hour} hours', 'utc'))",
            (uid, vid, w, var))
    conn.commit(); conn.close()


def test_today_and_weekly(client, auth_headers, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_BUDGET_S", 100)
    h = auth_headers(email="d@t.co")
    _seed(client, "d@t.co", [
        ("corrected", 40, "original", 0, 9),    # 오늘 09시
        ("uncorrected", 50, "original", 0, 10), # 오늘 10시
        ("corrected", 30, "filtered", 0, 11),   # 노출 미포함
        ("safe", 30, "original", 0, 12),        # 노출 미포함
        ("corrected", 20, "original", 2, 9),    # 이틀 전
    ])
    t = client.get("/dashboard/today", headers=h).json()
    assert t["risky_views"] == 2
    assert t["exposure_s"] == 90.0
    assert t["percent"] == 90.0 and t["status"] == "warning"
    assert t["budget_s"] == 100
    assert t["stimulus"]["flash"] == 2 and t["stimulus"]["red"] == 2
    # 곡선: 9시 40%, 10시 이후 90%
    curve = {c["hour"]: c["percent"] for c in t["curve"]}
    assert curve[9] == 40.0 and curve[10] == 90.0

    w = client.get("/dashboard/weekly", headers=h).json()
    assert len(w["days"]) == 7
    assert w["days"][-1]["risky_views"] == 2      # 오늘
    assert w["days"][-3]["risky_views"] == 1      # 이틀 전
    assert w["avg"] == round(3 / 7, 1)
