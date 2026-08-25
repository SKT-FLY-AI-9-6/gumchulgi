# -*- coding: utf-8 -*-
"""관리자 운영 대시보드 시연용 합성 시청 이벤트 주입 (멱등).

사용 (저장소 루트에서, 서버가 위험 영상을 1편 이상 처리해 둔 상태):
    python scripts/seed_admin_demo.py

가상 시청자 40명 — ON 20명은 위험 영상 보정본을 유지율 0.72~1.0 로,
OFF 20명은 원본을 유지율 0.10~0.55 로 시청한 것으로 기록한다.
관리자 계정(admin@gumchulgi.app)의 내 페이지 → 운영 대시보드에서
필터 ON/OFF 비교·비용 환산이 이 데이터 + 실제 시청 합산으로 계산된다.
이미 심어진 시청자는 건너뛰므로 여러 번 실행해도 안전하다.
"""
import random
import sqlite3
from pathlib import Path

random.seed(42)
DB = Path(__file__).resolve().parents[1] / "server" / "data" / "db.sqlite3"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

risky = conn.execute(
    "SELECT id, duration_s FROM videos"
    " WHERE status='ready' AND risk IS NOT NULL AND risk != 'safe'"
    " AND duration_s > 0").fetchall()
assert risky, "위험 영상이 없습니다 — 먼저 위반 클립을 업로드/처리할 것"

made_u = made_e = 0
for grp, variant, lo, hi in (("on", "filtered", 0.72, 1.00),
                             ("off", "original", 0.10, 0.55)):
    for i in range(20):
        email = f"seed_{grp}{i:02d}@demo"
        row = conn.execute("SELECT id FROM users WHERE email=?",
                           (email,)).fetchone()
        if row:
            uid = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO users(email,password_hash,nickname)"
                " VALUES(?, 'x', ?)", (email, f"게스트{grp}{i:02d}"))
            uid = cur.lastrowid
            conn.execute("INSERT INTO user_settings(user_id,filter_on)"
                         " VALUES(?,?)", (uid, 1 if grp == "on" else 0))
            made_u += 1
        if conn.execute("SELECT 1 FROM watch_events WHERE user_id=? LIMIT 1",
                        (uid,)).fetchone():
            continue                     # 이미 심어진 시청자
        for v in random.sample(risky, k=min(len(risky),
                                            random.randint(1, len(risky)))):
            ratio = random.uniform(lo, hi)
            hours_ago = random.randint(0, 6)
            conn.execute(
                "INSERT INTO watch_events(user_id,video_id,watched_s,variant,"
                " created_at) VALUES(?,?,?,?,"
                " datetime('now', ?))",
                (uid, v["id"], round(v["duration_s"] * ratio, 1), variant,
                 f"-{hours_ago} hours"))
            made_e += 1
conn.commit()
n = conn.execute("SELECT COUNT(*) FROM watch_events").fetchone()[0]
print(f"신규 시청자 {made_u}명, 신규 이벤트 {made_e}건 (총 이벤트 {n}건)")
