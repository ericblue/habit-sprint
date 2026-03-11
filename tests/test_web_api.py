"""Tests for the web API endpoints (task 6.2)."""

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed (optional web dependency)")
from fastapi.testclient import TestClient

from habit_sprint.web import create_app
from habit_sprint.executor import execute


@pytest.fixture()
def client(tmp_path):
    """Create a test client with a temporary database."""
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)
    return TestClient(app)


@pytest.fixture()
def seeded_client(tmp_path):
    """Create a test client with a sprint and habits already set up."""
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)

    # Seed data via executor
    execute({"action": "create_sprint", "payload": {
        "id": "sprint-one", "start_date": "2026-03-02", "end_date": "2026-03-15",
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "exercise", "name": "Exercise", "category": "health", "target_per_week": 5,
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "reading", "name": "Read", "category": "learning", "target_per_week": 3,
    }}, db_path)

    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestDashboard:
    def test_dashboard_no_sprint(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code in (404, 500)
        assert resp.json()["status"] == "error"

    def test_dashboard_with_sprint(self, seeded_client):
        resp = seeded_client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"] is not None

    def test_dashboard_with_sprint_id(self, seeded_client):
        # Get the actual sprint ID (auto-generated)
        sprints_resp = seeded_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]
        resp = seeded_client.get(f"/api/dashboard?sprint_id={sprint_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


class TestLogEndpoint:
    def test_log_success(self, seeded_client):
        resp = seeded_client.post("/api/log", json={
            "habit_id": "exercise", "date": "2026-03-05", "value": 1,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_log_missing_field(self, seeded_client):
        resp = seeded_client.post("/api/log", json={"habit_id": "exercise"})
        assert resp.status_code == 422  # Pydantic validation

    def test_log_default_value(self, seeded_client):
        resp = seeded_client.post("/api/log", json={
            "habit_id": "exercise", "date": "2026-03-06",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


class TestDeleteLog:
    def test_delete_log(self, seeded_client):
        # First log an entry
        seeded_client.post("/api/log", json={
            "habit_id": "exercise", "date": "2026-03-05", "value": 1,
        })
        # Then delete it
        resp = seeded_client.request("DELETE", "/api/log", json={
            "habit_id": "exercise", "date": "2026-03-05",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_delete_log_missing_field(self, seeded_client):
        resp = seeded_client.request("DELETE", "/api/log", json={
            "habit_id": "exercise",
        })
        assert resp.status_code == 422


class TestHabits:
    def test_list_habits(self, seeded_client):
        resp = seeded_client.get("/api/habits")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["data"]["habits"]) == 2

    def test_list_habits_include_archived(self, seeded_client):
        # Archive one habit
        execute({"action": "archive_habit", "payload": {"id": "reading"}},
                seeded_client.app.state.db_path)

        resp = seeded_client.get("/api/habits?include_archived=false")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["habits"]) == 1

        resp = seeded_client.get("/api/habits?include_archived=true")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["habits"]) == 2


class TestSprints:
    def test_list_sprints(self, seeded_client):
        resp = seeded_client.get("/api/sprints")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["data"]["sprints"]) == 1

    def test_list_sprints_with_status_filter(self, seeded_client):
        resp = seeded_client.get("/api/sprints?status=active")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_list_sprints_archived(self, seeded_client):
        resp = seeded_client.get("/api/sprints?status=archived")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["sprints"]) == 0


class TestActiveSprint:
    def test_active_sprint(self, seeded_client):
        resp = seeded_client.get("/api/sprint/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["id"] is not None

    def test_no_active_sprint(self, client):
        resp = client.get("/api/sprint/active")
        assert resp.status_code in (404, 500)
        assert resp.json()["status"] == "error"


class TestErrorMapping:
    def test_validation_error_returns_400(self, seeded_client):
        resp = seeded_client.post("/api/log", json={
            "habit_id": "exercise", "date": "not-a-date", "value": 1,
        })
        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_all_endpoints_return_envelope(self, seeded_client):
        """All responses should have status, data, and error keys."""
        responses = [
            seeded_client.get("/api/dashboard"),
            seeded_client.get("/api/habits"),
            seeded_client.get("/api/sprints"),
            seeded_client.get("/api/sprint/active"),
            seeded_client.post("/api/log", json={
                "habit_id": "exercise", "date": "2026-03-05", "value": 1,
            }),
        ]
        for resp in responses:
            body = resp.json()
            assert "status" in body
            assert "data" in body
            assert "error" in body
