from fastapi.testclient import TestClient

from polis.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "Polis"
    assert set(body) == {"status", "service", "env", "version"}
