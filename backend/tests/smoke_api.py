"""Run a local API smoke test without starting a TCP server."""

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from tests import auth_headers


def main() -> None:
    client = TestClient(app)
    headers = auth_headers(client)
    project = Path(__file__).resolve().parents[2] / "frontend"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["python"].startswith("3.10."), health.json()

    opened = client.post("/api/project/open", json={"path": str(project)}, headers=headers)
    assert opened.status_code == 200, opened.text
    assert opened.json()["name"] == "frontend"

    file_response = client.get("/api/file", params={"path": "src/App.tsx"}, headers=headers)
    assert file_response.status_code == 200, file_response.text
    assert "Local only" in file_response.json()["content"]

    search = client.post("/api/search", json={"query": "Local only"}, headers=headers)
    assert search.status_code == 200, search.text
    assert search.json()["results"]

    models = client.get("/api/ollama/models", headers=headers)
    assert models.status_code == 200, models.text

    build = client.post("/api/build", headers=headers)
    assert build.status_code == 200, build.text
    assert build.json()["return_code"] == 0, build.json()

    print("API smoke test passed")
    print(f"Python runtime: {health.json()['python']}")
    model_names = [item["name"] for item in models.json()["models"]]
    print(f"Ollama models: {', '.join(model_names) or 'unavailable'}")


if __name__ == "__main__":
    main()
