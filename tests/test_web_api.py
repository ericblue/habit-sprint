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


# ── Web UI tests (task 6.9) ──────────────────────────────────────────────


@pytest.fixture()
def seeded_db(tmp_path):
    """Return (db_path, app) with a sprint and habits already set up."""
    db_path = str(tmp_path / "web_ui.db")
    app = create_app(db_path=db_path)
    execute({"action": "create_sprint", "payload": {
        "id": "sprint-one", "start_date": "2026-03-02", "end_date": "2026-03-15",
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "exercise", "name": "Exercise", "category": "health",
        "target_per_week": 5, "weight": 2, "unit": "count",
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "reading", "name": "Read", "category": "learning",
        "target_per_week": 3, "weight": 1, "unit": "pages",
    }}, db_path)
    return db_path, app


@pytest.fixture()
def web_client(seeded_db):
    """TestClient backed by the seeded database."""
    _, app = seeded_db
    return TestClient(app)


class TestDashboardHTML:
    """Test the HTML dashboard (GET /)."""

    def test_dashboard_renders_with_data(self, web_client):
        resp = web_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        # Sprint header / theme or fallback title
        assert "Sprint Dashboard" in resp.text or "sprint-header" in resp.text
        # Dates should appear
        assert "2026-03-02" in resp.text or "Mar" in resp.text

    def test_dashboard_shows_categories(self, web_client):
        resp = web_client.get("/")
        assert "health" in resp.text
        assert "learning" in resp.text

    def test_dashboard_shows_checkboxes(self, web_client):
        resp = web_client.get("/")
        assert 'type="checkbox"' in resp.text

    def test_dashboard_daily_totals(self, web_client):
        resp = web_client.get("/")
        assert "Daily Total" in resp.text

    def test_dashboard_week_filter(self, web_client):
        resp = web_client.get("/?week=1")
        assert resp.status_code == 200
        # Week 1 only shows first 7 days
        assert "2026-03-02" in resp.text or "Mar" in resp.text

    def test_dashboard_no_active_sprint(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        app = create_app(db_path=db_path)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "No Active Sprint" in resp.text


class TestToggleCycle:
    """Test POST /toggle/{habit_id}/{date} toggle cycle."""

    def test_toggle_check_uncheck(self, web_client):
        # First toggle → should check
        resp = web_client.post("/toggle/exercise/2026-03-05")
        assert resp.status_code == 200
        assert "checked" in resp.text

        # Second toggle → should uncheck
        resp = web_client.post("/toggle/exercise/2026-03-05")
        assert resp.status_code == 200
        # The checkbox HTML should NOT have the checked attribute
        assert 'checked' not in resp.text or resp.text.count("checked") == 0

    def test_toggle_returns_updated_daily_total(self, web_client):
        resp = web_client.post("/toggle/exercise/2026-03-05")
        assert resp.status_code == 200
        # OOB swap for daily total should be present
        assert "total-2026-03-05" in resp.text

    def test_toggle_with_week_param(self, web_client):
        resp = web_client.post("/toggle/exercise/2026-03-05?week=1")
        assert resp.status_code == 200
        assert "week=1" in resp.text

    def test_toggle_nonexistent_habit(self, web_client):
        resp = web_client.post("/toggle/nonexistent/2026-03-05")
        # Should return 422 with HX-Trigger error header
        assert resp.status_code == 422


class TestHabitCRUDWeb:
    """Test habit management web pages."""

    def test_habits_list_page(self, web_client):
        resp = web_client.get("/habits")
        assert resp.status_code == 200
        assert "Exercise" in resp.text
        assert "Read" in resp.text

    def test_habit_new_form(self, web_client):
        resp = web_client.get("/habits/new")
        assert resp.status_code == 200
        assert "New Habit" in resp.text
        assert 'action="/habits"' in resp.text

    def test_habit_create_success(self, web_client):
        resp = web_client.post("/habits", data={
            "name": "Meditate", "id": "meditate", "category": "wellness",
            "target_per_week": "4", "weight": "1", "unit": "count",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert "/habits" in resp.headers["location"]

        # Verify it appears in the list
        list_resp = web_client.get("/habits")
        assert "Meditate" in list_resp.text

    def test_habit_create_duplicate_shows_error(self, web_client):
        resp = web_client.post("/habits", data={
            "name": "Exercise Again", "id": "exercise", "category": "health",
            "target_per_week": "3", "weight": "1", "unit": "count",
        })
        # Should re-render form with error (not redirect)
        assert resp.status_code == 200
        assert "alert-error" in resp.text or "error" in resp.text.lower()

    def test_habit_edit_form(self, web_client):
        resp = web_client.get("/habits/exercise/edit")
        assert resp.status_code == 200
        assert "Edit Habit" in resp.text
        assert "Exercise" in resp.text

    def test_habit_edit_nonexistent_redirects(self, web_client):
        resp = web_client.get("/habits/nonexistent/edit", follow_redirects=False)
        assert resp.status_code == 303

    def test_habit_update_success(self, web_client):
        resp = web_client.post("/habits/exercise/edit", data={
            "name": "Workout", "category": "fitness",
            "target_per_week": "4", "weight": "2", "unit": "count",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify update
        list_resp = web_client.get("/habits")
        assert "Workout" in list_resp.text

    def test_habit_archive(self, web_client):
        resp = web_client.post("/habits/exercise/archive", follow_redirects=False)
        assert resp.status_code == 303

        # Verify archived
        list_resp = web_client.get("/habits")
        assert "Archived" in list_resp.text or "archived" in list_resp.text


class TestSprintCRUDWeb:
    """Test sprint management web pages."""

    def test_sprints_list_page(self, web_client):
        resp = web_client.get("/sprints")
        assert resp.status_code == 200
        assert "2026-03-02" in resp.text
        assert "active" in resp.text

    def test_sprint_new_form(self, web_client):
        resp = web_client.get("/sprints/new")
        assert resp.status_code == 200
        assert "Create Sprint" in resp.text

    def test_sprint_create_success(self, seeded_db):
        # Need a fresh DB without an active sprint for this
        db_path = str(seeded_db[0]).replace("web_ui.db", "sprint_create.db")
        app = create_app(db_path=db_path)
        client = TestClient(app)

        resp = client.post("/sprints", data={
            "start_date": "2026-04-01", "end_date": "2026-04-14",
            "theme": "Focus month", "focus_goals": "Goal A\nGoal B",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert "/sprints" in resp.headers["location"]

    def test_sprint_create_invalid_dates(self, web_client):
        # Creating a second sprint while one is active should fail
        resp = web_client.post("/sprints", data={
            "start_date": "2026-04-01", "end_date": "2026-04-14",
            "theme": "", "focus_goals": "",
        })
        # Should re-render form with error
        assert resp.status_code == 200
        assert "error" in resp.text.lower() or "flash-error" in resp.text

    def test_sprint_detail_page(self, web_client):
        # Get the sprint ID
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.get(f"/sprints/{sprint_id}")
        assert resp.status_code == 200
        assert sprint_id in resp.text
        assert "2026-03-02" in resp.text

    def test_sprint_detail_not_found(self, web_client):
        resp = web_client.get("/sprints/nonexistent-sprint")
        assert resp.status_code == 404

    def test_sprint_archive(self, web_client):
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.post(f"/sprints/{sprint_id}/archive", follow_redirects=False)
        assert resp.status_code == 303

        # Verify archived
        detail_resp = web_client.get(f"/sprints/{sprint_id}")
        assert "archived" in detail_resp.text


class TestErrorCases:
    """Test error scenarios."""

    def test_dashboard_api_no_sprint(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        app = create_app(db_path=db_path)
        client = TestClient(app)
        resp = client.get("/api/dashboard")
        assert resp.status_code in (404, 500)
        assert resp.json()["status"] == "error"

    def test_toggle_invalid_habit(self, web_client):
        resp = web_client.post("/toggle/does-not-exist/2026-03-05")
        assert resp.status_code == 422

    def test_log_invalid_date(self, web_client):
        resp = web_client.post("/api/log", json={
            "habit_id": "exercise", "date": "invalid-date", "value": 1,
        })
        assert resp.status_code == 400

    def test_archive_nonexistent_habit(self, web_client):
        resp = web_client.post("/habits/no-such-habit/archive", follow_redirects=False)
        assert resp.status_code == 303  # Redirects with error message


class TestConcurrentAccess:
    """Test concurrent CLI + web access on the same database."""

    def test_cli_and_web_share_db(self, seeded_db):
        """Two TestClient instances + executor on same DB see consistent state."""
        db_path, app = seeded_db
        client1 = TestClient(app)
        client2 = TestClient(app)

        # Client 1 logs an entry via the web API
        resp = client1.post("/api/log", json={
            "habit_id": "exercise", "date": "2026-03-05", "value": 1,
        })
        assert resp.status_code == 200

        # Client 2 should see the entry in the dashboard
        resp = client2.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()["data"]
        # Find exercise habit and verify the entry exists
        found = False
        for cat in data["categories"]:
            for habit in cat["habits"]:
                if habit["habit_id"] == "exercise":
                    assert habit["daily"].get("2026-03-05", 0) > 0
                    found = True
        assert found

    def test_cli_executor_and_web_interop(self, seeded_db):
        """CLI executor writes, web reads — same database."""
        db_path, app = seeded_db
        client = TestClient(app)

        # Log via CLI executor directly
        execute({"action": "log_date", "payload": {
            "habit_id": "reading", "date": "2026-03-07", "value": 1,
        }}, db_path)

        # Web should see it
        resp = client.get("/api/dashboard")
        data = resp.json()["data"]
        found = False
        for cat in data["categories"]:
            for habit in cat["habits"]:
                if habit["habit_id"] == "reading":
                    assert habit["daily"].get("2026-03-07", 0) > 0
                    found = True
        assert found

        # Delete via web, verify via CLI
        client.request("DELETE", "/api/log", json={
            "habit_id": "reading", "date": "2026-03-07",
        })
        result = execute({"action": "sprint_dashboard", "payload": {}}, db_path)
        for cat in result["data"]["categories"]:
            for habit in cat["habits"]:
                if habit["habit_id"] == "reading":
                    assert habit["daily"].get("2026-03-07", 0) == 0

    def test_web_toggle_then_cli_read(self, seeded_db):
        """Toggle via web, read via CLI executor."""
        db_path, app = seeded_db
        client = TestClient(app)

        # Toggle on via web
        client.post("/toggle/exercise/2026-03-10")

        # CLI should see the entry
        result = execute({"action": "sprint_dashboard", "payload": {}}, db_path)
        for cat in result["data"]["categories"]:
            for habit in cat["habits"]:
                if habit["habit_id"] == "exercise":
                    assert habit["daily"].get("2026-03-10", 0) > 0
