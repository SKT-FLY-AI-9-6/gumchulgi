import pytest

from app.feed import pick_variant


# 스펙 노출 규칙 표의 전 케이스 (risk 3종 × 설정 3조합)
@pytest.mark.parametrize("risk,filter_on,auto_skip,expected", [
    ("safe",        True,  False, "original"),
    ("safe",        False, False, "original"),
    ("safe",        False, True,  "original"),
    ("corrected",   True,  False, "filtered"),
    ("corrected",   False, False, "original"),
    ("corrected",   True,  True,  None),
    ("corrected",   False, True,  None),
    ("uncorrected", True,  False, None),
    ("uncorrected", False, False, "original"),
    ("uncorrected", False, True,  None),
])
def test_pick_variant(risk, filter_on, auto_skip, expected):
    assert pick_variant(risk, filter_on, auto_skip) == expected


def _insert_video(client, risk, title):
    from app import db
    conn = db.connect()
    conn.execute(
        "INSERT INTO videos(uploader_id,title,status,risk,original_path,"
        "filtered_path,n_flash) VALUES(1,?, 'ready',?, 'o.mp4',"
        " CASE WHEN ?='safe' THEN NULL ELSE 'f.mp4' END, 2)",
        (title, risk, risk))
    conn.commit(); conn.close()


def test_feed_applies_rules_and_pagination(client, auth_headers):
    h = auth_headers()
    for i, risk in enumerate(["safe", "corrected", "uncorrected"] * 2):
        _insert_video(client, risk, f"v{i}")

    # 기본 설정: filter_on=True, auto_skip=False → uncorrected 제외
    r = client.get("/feed?limit=10", headers=h).json()
    risks = [v["risk"] for v in r["videos"]]
    assert "uncorrected" not in risks
    assert all(v["variant"] == ("filtered" if v["risk"] == "corrected"
                                else "original") for v in r["videos"])
    assert all("stream_url" in v and "stimulus" in v for v in r["videos"])

    # 커서: limit=2 두 번 → 겹치지 않게 이어짐
    p1 = client.get("/feed?limit=2", headers=h).json()
    p2 = client.get(f"/feed?limit=2&cursor={p1['next_cursor']}", headers=h).json()
    ids1 = {v["id"] for v in p1["videos"]}
    assert ids1.isdisjoint({v["id"] for v in p2["videos"]})


def test_like_toggle(client, auth_headers):
    h = auth_headers()
    _insert_video(client, "safe", "좋아요용")
    vid = client.get("/feed?limit=1", headers=h).json()["videos"][0]["id"]
    r = client.post(f"/videos/{vid}/like", headers=h).json()
    assert r == {"like_count": 1, "liked": True}
    r = client.post(f"/videos/{vid}/like", headers=h).json()   # 멱등
    assert r == {"like_count": 1, "liked": True}
    r = client.delete(f"/videos/{vid}/like", headers=h).json()
    assert r == {"like_count": 0, "liked": False}
