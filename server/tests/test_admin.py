"""관리자 수익 대시보드 — 권한·지표·환산식 검증."""


def _admin_headers(client):
    r = client.post("/auth/login", json={
        "email": "admin@gumchulgi.app", "password": "admin1234"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["is_admin"] is True
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(client, conn):
    """위험 영상 1편(20초) + ON/OFF 시청 이벤트를 심는다.
    filtered: 18s, 20s (유지율 0.9·1.0, 이탈 0)
    original: 4s, 6s, 16s (유지율 0.2·0.3·0.8, 이탈 2/3)
    """
    conn.execute("INSERT INTO users(email,password_hash,nickname) "
                 "VALUES('v@t.co','x','시청자')")
    uid = conn.execute("SELECT MAX(id) FROM users").fetchone()[0]
    conn.execute(
        "INSERT INTO videos(uploader_id,title,status,risk,duration_s)"
        " VALUES(?, '위험', 'ready', 'corrected', 20.0)", (uid,))
    vid = conn.execute("SELECT MAX(id) FROM videos").fetchone()[0]
    for w, var in ((18, "filtered"), (20, "filtered"),
                   (4, "original"), (6, "original"), (16, "original")):
        conn.execute(
            "INSERT INTO watch_events(user_id,video_id,watched_s,variant)"
            " VALUES(?,?,?,?)", (uid, vid, w, var))
    conn.commit()


def test_metrics_requires_admin(client, auth_headers):
    r = client.get("/admin/metrics", headers=auth_headers())
    assert r.status_code == 403


def test_admin_account_seeded_and_metrics_math(client):
    h = _admin_headers(client)
    from app import db
    conn = db.connect()
    _seed(client, conn)
    r = client.get("/admin/metrics", params={"cpm": 5000, "imp_per_min": 1},
                   headers=h)
    assert r.status_code == 200, r.text
    m = r.json()
    on, off = m["groups"]["filtered"], m["groups"]["original"]
    assert on["views"] == 2 and off["views"] == 3
    assert abs(on["avg_watch_ratio"] - 0.95) < 1e-3
    assert abs(off["avg_watch_ratio"] - (0.2 + 0.3 + 0.8) / 3) < 1e-3
    assert on["bounce_rate"] == 0.0
    assert abs(off["bounce_rate"] - 2 / 3) < 1e-3
    # 환산: delta=0.95-0.4333=0.5167, 지켜낸 분(실측)=0.5167*3회*20s/60
    kept = 0.5167 * 3 * 20 / 60
    assert abs(m["savings"]["kept_min_actual"] - round(kept, 1)) < 0.11
    # 1만 노출 환산: 0.5167*10000*20/60 분 * 1imp/min * 5000/1000 원
    per10k = 0.5167 * 10_000 * 20 / 60 * 1 * 5.0
    assert abs(m["savings"]["saved_krw_per_10k"] - per10k) / per10k < 0.01


def test_metrics_empty_db_is_zero(client):
    h = _admin_headers(client)
    r = client.get("/admin/metrics", headers=h)
    assert r.status_code == 200
    m = r.json()
    assert m["total_risky_views"] == 0
    assert m["savings"]["saved_krw_per_10k"] == 0
