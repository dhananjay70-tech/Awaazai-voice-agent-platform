import uuid

import pytest

from tests.conftest import AGENT_PAYLOAD, auth_headers

URL = "/api/v1/agents"


@pytest.fixture
def alice(client):
    return auth_headers(client, "alice@example.com")


@pytest.fixture
def mallory(client):
    return auth_headers(client, "mallory@example.com")


def create(client, headers, **overrides):
    return client.post(URL, json={**AGENT_PAYLOAD, **overrides}, headers=headers)


def test_all_agent_routes_require_auth(client):
    some_id = uuid.uuid4()
    assert client.post(URL, json=AGENT_PAYLOAD).status_code == 401
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/{some_id}").status_code == 401
    assert client.patch(f"{URL}/{some_id}", json={"name": "x"}).status_code == 401
    assert client.delete(f"{URL}/{some_id}").status_code == 401


def test_create_agent(client, alice):
    response = create(client, alice)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Support Bot"
    assert body["language"] == "hi-IN"
    assert body["voice_config"] == {"provider": "example", "voice_id": "v1", "speed": 1.2}
    assert body["is_active"] is True
    assert body["owner_id"] == client.get("/api/v1/users/me", headers=alice).json()["id"]
    assert body["created_at"] and body["updated_at"]


def test_create_agent_defaults(client, alice):
    response = client.post(URL, json={"name": "Min", "system_prompt": "Be nice."}, headers=alice)
    assert response.status_code == 201
    assert response.json()["language"] == "en"
    assert response.json()["voice_config"]["speed"] == 1.0


def test_list_only_returns_own_agents(client, alice, mallory):
    create(client, alice, name="A1")
    create(client, alice, name="A2")
    create(client, mallory, name="M1")
    assert {a["name"] for a in client.get(URL, headers=alice).json()} == {"A1", "A2"}
    assert [a["name"] for a in client.get(URL, headers=mallory).json()] == ["M1"]


def test_list_pagination(client, alice):
    for i in range(3):
        create(client, alice, name=f"A{i}")
    assert len(client.get(URL, params={"limit": 2}, headers=alice).json()) == 2
    assert len(client.get(URL, params={"limit": 2, "offset": 2}, headers=alice).json()) == 1
    assert client.get(URL, params={"limit": 0}, headers=alice).status_code == 422


def test_get_agent(client, alice):
    agent_id = create(client, alice).json()["id"]
    response = client.get(f"{URL}/{agent_id}", headers=alice)
    assert response.status_code == 200
    assert response.json()["id"] == agent_id


def test_get_missing_agent_is_404(client, alice):
    assert client.get(f"{URL}/{uuid.uuid4()}", headers=alice).status_code == 404


def test_malformed_agent_id_is_422(client, alice):
    assert client.get(f"{URL}/not-a-uuid", headers=alice).status_code == 422


def test_partial_update(client, alice):
    agent_id = create(client, alice).json()["id"]
    response = client.patch(
        f"{URL}/{agent_id}", json={"name": "Renamed", "is_active": False, "description": None}, headers=alice
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["is_active"] is False
    assert body["description"] is None
    assert body["system_prompt"] == AGENT_PAYLOAD["system_prompt"]  # untouched
    assert body["voice_config"]["voice_id"] == "v1"  # untouched


def test_update_voice_config(client, alice):
    agent_id = create(client, alice).json()["id"]
    response = client.patch(f"{URL}/{agent_id}", json={"voice_config": {"voice_id": "v2"}}, headers=alice)
    assert response.json()["voice_config"] == {"provider": None, "voice_id": "v2", "speed": 1.0}


def test_delete_agent(client, alice):
    agent_id = create(client, alice).json()["id"]
    assert client.delete(f"{URL}/{agent_id}", headers=alice).status_code == 204
    assert client.get(f"{URL}/{agent_id}", headers=alice).status_code == 404
    assert client.delete(f"{URL}/{agent_id}", headers=alice).status_code == 404


# --- ownership authorization: another user's agent must look like it does not exist ---

def test_cannot_read_other_users_agent(client, alice, mallory):
    agent_id = create(client, alice).json()["id"]
    assert client.get(f"{URL}/{agent_id}", headers=mallory).status_code == 404


def test_cannot_update_other_users_agent(client, alice, mallory):
    agent_id = create(client, alice).json()["id"]
    response = client.patch(f"{URL}/{agent_id}", json={"name": "Hacked"}, headers=mallory)
    assert response.status_code == 404
    assert client.get(f"{URL}/{agent_id}", headers=alice).json()["name"] == "Support Bot"


def test_cannot_delete_other_users_agent(client, alice, mallory):
    agent_id = create(client, alice).json()["id"]
    assert client.delete(f"{URL}/{agent_id}", headers=mallory).status_code == 404
    assert client.get(f"{URL}/{agent_id}", headers=alice).status_code == 200


def test_owner_id_in_payload_is_ignored(client, alice, mallory):
    mallory_id = client.get("/api/v1/users/me", headers=mallory).json()["id"]
    response = create(client, alice, owner_id=mallory_id)
    assert response.status_code == 201
    assert response.json()["owner_id"] != mallory_id


def test_same_name_allowed_for_different_users_but_not_same_user(client, alice, mallory):
    assert create(client, alice).status_code == 201
    assert create(client, mallory).status_code == 201
    duplicate = create(client, alice)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "agent_name_conflict"


def test_rename_to_existing_name_is_409(client, alice):
    create(client, alice, name="One")
    two = create(client, alice, name="Two").json()["id"]
    assert client.patch(f"{URL}/{two}", json={"name": "One"}, headers=alice).status_code == 409


# --- validation ---

@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"system_prompt": ""},
        {"system_prompt": "x" * 10_001},
        {"language": "not a language"},
        {"voice_config": {"speed": 5}},
        {"voice_config": {"api_key": "sk-secret"}},  # secrets cannot be stored in voice config
        {"is_active": "maybe"},
    ],
)
def test_create_validation_failures(client, alice, overrides):
    assert create(client, alice, **overrides).status_code == 422


def test_update_cannot_null_required_fields(client, alice):
    agent_id = create(client, alice).json()["id"]
    assert client.patch(f"{URL}/{agent_id}", json={"name": None}, headers=alice).status_code == 422
    assert client.patch(f"{URL}/{agent_id}", json={"system_prompt": ""}, headers=alice).status_code == 422
