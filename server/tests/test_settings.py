import pytest


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


def test_validate_production_rejects_default_secret(monkeypatch):
    from app.config import settings, validate_production
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "change-me")
    with pytest.raises(RuntimeError):
        validate_production()


def test_validate_production_allows_real_secret(monkeypatch):
    from app.config import settings, validate_production
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "실제-운영-비밀값-123")
    monkeypatch.setattr(settings, "AUTH_OPEN", False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "실제-관리자-비밀번호-123")
    validate_production()  # 예외 없이 통과해야 함


def test_validate_production_rejects_demo_auth(monkeypatch):
    from app.config import settings, validate_production
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "실제-운영-비밀값-123")
    monkeypatch.setattr(settings, "AUTH_OPEN", True)
    with pytest.raises(RuntimeError):
        validate_production()


def test_validate_production_rejects_default_admin_password(monkeypatch):
    from app.config import settings, validate_production
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "JWT_SECRET", "실제-운영-비밀값-123")
    monkeypatch.setattr(settings, "AUTH_OPEN", False)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "admin1234")
    with pytest.raises(RuntimeError):
        validate_production()


def test_validate_production_ignores_dev_env(monkeypatch):
    from app.config import settings, validate_production
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret")
    validate_production()  # dev 환경에서는 기본값이어도 통과
