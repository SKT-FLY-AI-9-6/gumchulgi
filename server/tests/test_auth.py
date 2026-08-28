def test_signup_login_me(client):
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "pw123456", "nickname": "박"})
    assert r.status_code == 201
    assert r.json()["user"]["nickname"] == "박"

    dup = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "x2345678", "nickname": "박2"})
    assert dup.status_code == 409

    r = client.post("/auth/login", json={"email": "a@b.co", "password": "pw123456"})
    assert r.status_code == 200
    token = r.json()["token"]

    bad = client.post("/auth/login", json={"email": "a@b.co", "password": "wrong"})
    assert bad.status_code == 401

    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@b.co"
    assert client.get("/me").status_code in (401, 403)


def test_media_token_is_scoped(client, auth_headers):
    headers = auth_headers()
    r = client.post("/auth/media-token", headers=headers)
    assert r.status_code == 200
    media = r.json()["token"]

    # media token은 일반 API의 Bearer 권한으로 사용할 수 없다.
    assert client.get(
        "/me", headers={"Authorization": f"Bearer {media}"}).status_code == 401


def test_signup_short_password(client):
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "short", "nickname": "박"})
    assert r.status_code == 422


def test_signup_creates_user_settings(client):
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "pw123456", "nickname": "박"})
    assert r.status_code == 201
    user_id = r.json()["user"]["id"]

    from app.db import connect
    conn = connect()
    row = conn.execute("SELECT * FROM user_settings WHERE user_id=?",
                      (user_id,)).fetchone()
    assert row is not None
    conn.close()


def test_signup_long_password(client):
    # 73 bytes in UTF-8
    long_password = "a" * 73
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": long_password, "nickname": "박"})
    assert r.status_code == 422


def test_login_long_password(client):
    # First signup with a normal password
    r = client.post("/auth/signup", json={
        "email": "a@b.co", "password": "pw123456", "nickname": "박"})
    assert r.status_code == 201

    # Try to login with a long password (>72 bytes)
    long_password = "a" * 73
    r = client.post("/auth/login", json={
        "email": "a@b.co", "password": long_password})
    assert r.status_code == 401


def test_auth_open_mode_lets_anything_in(client, monkeypatch):
    """AUTH_OPEN=1 (시연 모드): 로그인 UI 는 그대로, 검증만 꺼진다."""
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_OPEN", True)
    # 없는 계정으로 로그인 → 자동 생성되어 통과
    r = client.post("/auth/login", json={"email": "new@demo.co",
                                         "password": "x"})
    assert r.status_code == 200
    assert r.json()["user"]["nickname"] == "new"
    # 같은 계정, 아무 비밀번호로 재로그인 → 통과
    r2 = client.post("/auth/login", json={"email": "new@demo.co",
                                          "password": "다른비번"})
    assert r2.status_code == 200
    assert r2.json()["user"]["id"] == r.json()["user"]["id"]
    # 중복 이메일 가입 → 409 대신 기존 계정으로 입장
    r3 = client.post("/auth/signup", json={
        "email": "new@demo.co", "password": "1", "nickname": "무시됨"})
    assert r3.status_code == 201
    assert r3.json()["user"]["id"] == r.json()["user"]["id"]
