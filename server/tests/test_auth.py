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
