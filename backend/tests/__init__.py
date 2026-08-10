from fastapi.testclient import TestClient


def auth_headers(client: TestClient, user_id: str = "1", password: str = "1") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"id": user_id, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
