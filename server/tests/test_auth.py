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
