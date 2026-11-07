from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_liveness():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_validates_query():
    response = client.post("/api/get_response", json={"query": ""})
    assert response.status_code == 422


def test_chat_reports_backend_not_configured():
    response = client.post("/api/get_response", json={"query": "Where is deployment documented?"})
    assert response.status_code == 503
