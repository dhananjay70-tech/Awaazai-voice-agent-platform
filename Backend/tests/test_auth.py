import pytest

from tests.conftest import auth_headers, register

PASSWORD = "correct-horse-battery"


def test_register_success_does_not_leak_password_or_hash(client):
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["is_active"] is True
    assert "password" not in response.text
    assert "hash" not in response.text
    assert "$2b$" not in response.text


def test_register_normalises_email_case(client):
    response = register(client, email="  Alice@Example.COM ")
    assert response.status_code == 201
    assert response.json()["email"] == "alice@example.com"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com", "password": "x" * 73},  # bcrypt byte limit
        {"email": "a@example.com", "password": "é" * 40},  # 80 bytes
        {"email": "a@example.com"},
        {},
    ],
)
def test_register_validation_failures(client, payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_validation_error_does_not_echo_password(client):
    response = client.post("/api/v1/auth/register", json={"email": "bad", "password": "supersecret"})
    assert "supersecret" not in response.text


def test_duplicate_registration_is_409_case_insensitive(client):
    assert register(client, "bob@example.com").status_code == 201
    response = register(client, "BOB@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


def test_login_success(client, settings):
    register(client)
    response = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    assert body["access_token"]


def test_login_wrong_password_and_unknown_email_look_identical(client):
    register(client)
    wrong_password = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "wrong-pass"})
    unknown_email = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]


def test_current_user_with_valid_token(client):
    headers = auth_headers(client)
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    assert "hashed_password" not in response.json()


def test_protected_route_without_token_is_401(client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.parametrize("header", ["Bearer garbage", "Basic abc", "Bearer "])
def test_protected_route_with_bad_token_is_401(client, header):
    response = client.get("/api/v1/users/me", headers={"Authorization": header})
    assert response.status_code == 401


def test_token_for_deleted_user_is_rejected(client, database):
    from app.models.user import User

    headers = auth_headers(client)
    with next(database.session()) as session:
        session.delete(session.query(User).one())
        session.commit()
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401
