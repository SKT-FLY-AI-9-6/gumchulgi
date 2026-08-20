def test_settings_default_and_update(client, auth_headers):
    h = auth_headers()
    r = client.get("/me/settings", headers=h)
    assert r.status_code == 200
    assert r.json() == {"filter_on": True, "auto_skip": False}

    r = client.put("/me/settings", headers=h,
                   json={"filter_on": False, "auto_skip": True})
    assert r.status_code == 200
    assert client.get("/me/settings", headers=h).json() == {
        "filter_on": False, "auto_skip": True}
