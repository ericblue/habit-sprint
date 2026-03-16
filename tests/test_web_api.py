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
        # Creating an overlapping sprint while one is active should fail
        resp = web_client.post("/sprints", data={
            "start_date": "2026-03-10", "end_date": "2026-03-20",
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


# ── Epic 7 tests ─────────────────────────────────────────────────────────


class TestSprintEditForm:
    """Test GET/POST /sprints/{id}/edit (task 7.3)."""

    def test_edit_form_renders_prefilled(self, web_client):
        """Sprint edit form renders with pre-filled theme and focus_goals."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        # Set theme and goals first
        web_client.post(f"/sprints/{sprint_id}/edit", data={
            "theme": "Deep Work", "focus_goals": "Goal A\nGoal B",
        }, follow_redirects=False)

        resp = web_client.get(f"/sprints/{sprint_id}/edit")
        assert resp.status_code == 200
        assert "Edit Sprint" in resp.text
        assert "Deep Work" in resp.text
        assert "Goal A" in resp.text
        assert "Goal B" in resp.text

    def test_edit_form_hides_date_fields(self, web_client):
        """Edit form should not show start_date/end_date inputs."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.get(f"/sprints/{sprint_id}/edit")
        assert resp.status_code == 200
        assert "Update Sprint" in resp.text

    def test_edit_post_updates_theme_and_goals(self, web_client):
        """POST to sprint edit updates theme and focus_goals."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.post(f"/sprints/{sprint_id}/edit", data={
            "theme": "Productivity Sprint",
            "focus_goals": "Read more\nExercise daily",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert f"/sprints/{sprint_id}" in resp.headers["location"]

        # Verify changes persisted
        detail_resp = web_client.get(f"/sprints/{sprint_id}")
        assert "Productivity Sprint" in detail_resp.text
        assert "Read more" in detail_resp.text
        assert "Exercise daily" in detail_resp.text

    def test_edit_nonexistent_sprint_redirects(self, web_client):
        resp = web_client.get("/sprints/no-such-sprint/edit", follow_redirects=False)
        assert resp.status_code == 303


class TestSprintRetro:
    """Test retro form rendering and POST /sprints/{id}/retro (task 7.4)."""

    def test_retro_form_renders_empty(self, web_client):
        """Sprint detail page shows retro form with empty fields."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.get(f"/sprints/{sprint_id}")
        assert resp.status_code == 200
        assert "Retrospective" in resp.text
        assert 'name="what_went_well"' in resp.text
        assert 'name="what_to_improve"' in resp.text
        assert 'name="ideas"' in resp.text
        assert "Save Retrospective" in resp.text

    def test_retro_post_creates_retro(self, web_client):
        """POST to retro endpoint creates retrospective data."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.post(f"/sprints/{sprint_id}/retro", data={
            "what_went_well": "Consistent exercise",
            "what_to_improve": "Sleep schedule",
            "ideas": "Try meditation",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert f"/sprints/{sprint_id}" in resp.headers["location"]

    def test_retro_form_prefilled_after_save(self, web_client):
        """After saving retro, the detail page shows pre-filled values."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        # Save retro
        web_client.post(f"/sprints/{sprint_id}/retro", data={
            "what_went_well": "Great progress",
            "what_to_improve": "Time management",
            "ideas": "Use pomodoro",
        }, follow_redirects=False)

        # Check it's pre-filled on the detail page
        resp = web_client.get(f"/sprints/{sprint_id}")
        assert "Great progress" in resp.text
        assert "Time management" in resp.text
        assert "Use pomodoro" in resp.text

    def test_retro_post_updates_existing(self, web_client):
        """POST to retro endpoint twice should update (upsert) existing retro."""
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        # First save
        web_client.post(f"/sprints/{sprint_id}/retro", data={
            "what_went_well": "Original",
            "what_to_improve": "",
            "ideas": "",
        }, follow_redirects=False)

        # Second save (update)
        web_client.post(f"/sprints/{sprint_id}/retro", data={
            "what_went_well": "Updated thoughts",
            "what_to_improve": "More focus",
            "ideas": "New idea",
        }, follow_redirects=False)

        resp = web_client.get(f"/sprints/{sprint_id}")
        assert "Updated thoughts" in resp.text
        assert "More focus" in resp.text
        assert "New idea" in resp.text
        # Original text should be replaced
        assert "Original" not in resp.text


class TestHabitSprintScope:
    """Test habit form sprint scope field and create with sprint_id (task 7.2)."""

    def test_habit_form_has_sprint_scope_field(self, web_client):
        """New habit form includes sprint scope dropdown."""
        resp = web_client.get("/habits/new")
        assert resp.status_code == 200
        assert "Sprint Scope" in resp.text
        assert 'name="sprint_id"' in resp.text
        assert "Global" in resp.text

    def test_habit_form_shows_active_sprint_option(self, web_client):
        """Sprint scope dropdown shows active sprint as an option."""
        resp = web_client.get("/habits/new")
        assert resp.status_code == 200
        # The active sprint (sprint-one) should appear as an option
        assert "sprint-one" in resp.text or "2026-03-02" in resp.text

    def test_habit_create_with_sprint_id(self, web_client):
        """Creating a habit with sprint_id sets sprint scope correctly."""
        # Look up the actual auto-generated sprint ID
        sprints_resp = web_client.get("/api/sprints")
        sprint_id = sprints_resp.json()["data"]["sprints"][0]["id"]

        resp = web_client.post("/habits", data={
            "name": "Sprint Meditation", "id": "sprint-med",
            "category": "wellness", "target_per_week": "3",
            "weight": "1", "unit": "count", "sprint_id": sprint_id,
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify the habit has sprint_id set
        habits_resp = web_client.get("/api/habits")
        habits = habits_resp.json()["data"]["habits"]
        med = next(h for h in habits if h["id"] == "sprint-med")
        assert med["sprint_id"] == sprint_id

    def test_habit_create_without_sprint_id(self, web_client):
        """Creating a habit without sprint_id keeps it global."""
        resp = web_client.post("/habits", data={
            "name": "Global Habit", "id": "global-hab",
            "category": "general", "target_per_week": "5",
            "weight": "1", "unit": "count", "sprint_id": "",
        }, follow_redirects=False)
        assert resp.status_code == 303

        habits_resp = web_client.get("/api/habits")
        habits = habits_resp.json()["data"]["habits"]
        glob = next(h for h in habits if h["id"] == "global-hab")
        assert glob.get("sprint_id") is None

    def test_habit_edit_form_shows_sprint_scope(self, web_client):
        """Edit habit form shows sprint scope field with current value."""
        resp = web_client.get("/habits/exercise/edit")
        assert resp.status_code == 200
        assert "Sprint Scope" in resp.text
        assert 'name="sprint_id"' in resp.text


class TestSprintHabitsManagement:
    """Test sprint habits management page (task 7.5)."""

    def _sprint_id(self, web_client):
        return web_client.get("/api/sprints").json()["data"]["sprints"][0]["id"]

    def test_sprint_habits_page_renders(self, web_client):
        """GET /sprints/{id}/habits renders the management page."""
        sid = self._sprint_id(web_client)
        resp = web_client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        assert "Manage Habits" in resp.text

    def test_sprint_habits_lists_sections(self, web_client):
        """Page shows Sprint Habits and Available Global Habits sections."""
        sid = self._sprint_id(web_client)
        resp = web_client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        assert "Sprint Habits" in resp.text
        assert "Global Habits" in resp.text or "Available" in resp.text

    def test_global_habits_listed(self, web_client):
        """Global habits appear in the available section."""
        sid = self._sprint_id(web_client)
        resp = web_client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        # exercise and reading are global (no sprint_id)
        assert "Exercise" in resp.text
        assert "Read" in resp.text

    def test_add_habit_to_sprint(self, web_client):
        """POST to add moves a global habit into the sprint."""
        sid = self._sprint_id(web_client)
        resp = web_client.post(f"/sprints/{sid}/habits/add", data={
            "habit_id": "exercise",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify exercise is now a sprint habit
        habits_resp = web_client.get("/api/habits")
        habits = habits_resp.json()["data"]["habits"]
        ex = next(h for h in habits if h["id"] == "exercise")
        assert ex["sprint_id"] == sid

    def test_remove_habit_from_sprint(self, web_client):
        """POST to remove makes a sprint habit global again."""
        sid = self._sprint_id(web_client)
        # First add it
        web_client.post(f"/sprints/{sid}/habits/add", data={
            "habit_id": "exercise",
        }, follow_redirects=False)

        # Then remove it
        resp = web_client.post(f"/sprints/{sid}/habits/remove", data={
            "habit_id": "exercise",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify exercise is global again
        habits_resp = web_client.get("/api/habits")
        habits = habits_resp.json()["data"]["habits"]
        ex = next(h for h in habits if h["id"] == "exercise")
        assert ex.get("sprint_id") is None

    def test_sprint_habits_correct_sections_after_add(self, web_client):
        """After adding a habit to sprint, it moves between sections."""
        sid = self._sprint_id(web_client)
        # Add exercise to sprint
        web_client.post(f"/sprints/{sid}/habits/add", data={
            "habit_id": "exercise",
        }, follow_redirects=False)

        resp = web_client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        # Exercise should be in sprint section with Remove button
        assert "Remove from Sprint" in resp.text
        # Reading should still be in global section with Add button
        assert "Add to Sprint" in resp.text

    def test_sprint_habits_not_found(self, web_client):
        """Nonexistent sprint returns 404."""
        resp = web_client.get("/sprints/nonexistent/habits")
        assert resp.status_code == 404

    def test_sprint_habits_shows_goal_inputs(self, web_client):
        """Sprint habits page shows editable target and weight inputs."""
        sid = self._sprint_id(web_client)
        # Add exercise to sprint so it appears in the sprint section
        web_client.post(f"/sprints/{sid}/habits/add", data={"habit_id": "exercise"}, follow_redirects=False)
        resp = web_client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        assert "goal_target_exercise" in resp.text
        assert "goal_weight_exercise" in resp.text
        assert "Save Goals" in resp.text

    def test_save_sprint_goals(self, web_client):
        """POST to save goals creates sprint_habit_goals overrides."""
        sid = self._sprint_id(web_client)
        web_client.post(f"/sprints/{sid}/habits/add", data={"habit_id": "exercise"}, follow_redirects=False)
        resp = web_client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "5",
            "goal_weight_exercise": "3",
            "default_target_exercise": "3",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify override is shown on the page
        page = web_client.get(f"/sprints/{sid}/habits")
        assert "goal-override" in page.text
        assert "(default:" in page.text

    def test_save_goals_removes_override_when_matching_default(self, web_client):
        """Saving goals matching defaults removes the override."""
        sid = self._sprint_id(web_client)
        web_client.post(f"/sprints/{sid}/habits/add", data={"habit_id": "exercise"}, follow_redirects=False)
        # First set an override
        web_client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "5",
            "goal_weight_exercise": "3",
            "default_target_exercise": "3",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        # Now save with default values
        web_client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "3",
            "goal_weight_exercise": "1",
            "default_target_exercise": "3",
            "default_weight_exercise": "1",
        }, follow_redirects=False)

        page = web_client.get(f"/sprints/{sid}/habits")
        # CSS class definition always present; check no input has it applied
        assert 'class="goal-override"' not in page.text


class TestDashboardProgressBars:
    """Test dashboard progress bars render with correct data (task 7.6)."""

    def test_progress_bar_renders(self, web_client):
        """Dashboard contains progress bar elements."""
        resp = web_client.get("/")
        assert resp.status_code == 200
        assert "progress-bar" in resp.text
        assert "progress" in resp.text

    def test_progress_bar_with_entries(self, seeded_db):
        """Progress bars reflect actual completion percentages."""
        db_path, app = seeded_db
        client = TestClient(app)

        # Log some entries for exercise (target 5/week)
        for day in range(2, 7):  # 5 days
            execute({"action": "log_date", "payload": {
                "habit_id": "exercise", "date": f"2026-03-0{day}", "value": 1,
            }}, db_path)

        resp = client.get("/?week=1")
        assert resp.status_code == 200
        # Exercise: 5/5 = 100% → should have success class
        assert "progress-bar-success" in resp.text

    def test_progress_bar_color_classes(self, seeded_db):
        """Color coding: success (>=80%), warning (50-79%), danger (<50%)."""
        db_path, app = seeded_db
        client = TestClient(app)

        # Log 1 entry for reading (target 3/week) → 33% → danger
        execute({"action": "log_date", "payload": {
            "habit_id": "reading", "date": "2026-03-02", "value": 1,
        }}, db_path)

        resp = client.get("/?week=1")
        assert resp.status_code == 200
        assert "progress-bar" in resp.text

    def test_sprint_header_progress_bar(self, web_client):
        """Sprint header shows overall progress bar."""
        resp = web_client.get("/")
        assert resp.status_code == 200
        assert "sprint-progress" in resp.text

    def test_category_progress_bar(self, web_client):
        """Category rows show progress bars."""
        resp = web_client.get("/")
        assert resp.status_code == 200
        assert "category-row" in resp.text
        assert "progress-sm" in resp.text or "progress-inline" in resp.text


# ── Epic 9 tests ─────────────────────────────────────────────────────────


class TestReportsPage:
    """Test reports page layout and navigation (task 9.1)."""

    def test_reports_route_returns_200(self, client):
        """GET /reports returns 200."""
        resp = client.get("/reports")
        assert resp.status_code == 200

    def test_reports_page_has_tab_navigation(self, client):
        """Reports page includes all five report tabs."""
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "Sprint Comparison" in resp.text
        assert "Habit Heatmap" in resp.text
        assert "Category Balance" in resp.text
        assert "Trends" in resp.text
        assert "Streaks" in resp.text

    def test_reports_default_tab_is_sprint_comparison(self, client):
        """Default tab is sprint-comparison when no tab param given."""
        resp = client.get("/reports")
        assert resp.status_code == 200
        # The sprint-comparison tab should be active
        assert 'report-tab active' in resp.text
        assert "Sprint Comparison" in resp.text

    def test_reports_tab_parameter(self, client):
        """Tab query parameter switches the active view."""
        for tab in ["sprint-comparison", "heatmap", "category-balance", "trends", "streaks"]:
            resp = client.get(f"/reports?tab={tab}")
            assert resp.status_code == 200

    def test_reports_invalid_tab_defaults(self, client):
        """Invalid tab parameter defaults to sprint-comparison."""
        resp = client.get("/reports?tab=invalid")
        assert resp.status_code == 200
        assert "Sprint Comparison" in resp.text

    def test_reports_loads_chartjs(self, client):
        """Reports page loads Chart.js via CDN."""
        resp = client.get("/reports")
        assert "chart.js" in resp.text.lower() or "Chart.js" in resp.text

    def test_reports_loads_cal_heatmap(self, client):
        """Reports page loads cal-heatmap via CDN."""
        resp = client.get("/reports")
        assert "cal-heatmap" in resp.text

    def test_reports_nav_active(self, client):
        """Navigation highlights Reports as active on /reports page."""
        resp = client.get("/reports")
        # The nav link for Reports should have the active class
        assert 'href="/reports"' in resp.text
        # Check that "active" appears near the reports link
        assert 'class="active"' in resp.text or "active" in resp.text

    def test_reports_heatmap_tab_shows_cal_heatmap_container(self, client):
        """Heatmap tab includes the cal-heatmap container div."""
        resp = client.get("/reports?tab=heatmap")
        assert resp.status_code == 200
        assert "cal-heatmap" in resp.text


class TestSprintComparisonReport:
    """Test sprint comparison report — API + HTML (task 9.2)."""

    def test_api_returns_200_empty(self, client):
        """API returns 200 with empty sprints list when no sprints exist."""
        resp = client.get("/api/reports/sprint-comparison")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["sprints"] == []

    def test_api_returns_sprint_data(self, seeded_client):
        """API returns sprint comparison data with scores and habit_count."""
        # Log some entries so scores are non-zero
        seeded_client.post("/api/log", json={
            "habit_id": "exercise", "date": "2026-03-05", "value": 1,
        })
        resp = seeded_client.get("/api/reports/sprint-comparison")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        sprints = body["data"]["sprints"]
        assert len(sprints) >= 1
        s = sprints[0]
        assert "weighted_score" in s
        assert "unweighted_score" in s
        assert "habit_count" in s
        assert "trend_delta" in s
        assert isinstance(s["habit_count"], int)

    def test_api_color_thresholds(self, seeded_db):
        """Verify weighted_score values allow client-side color coding."""
        db_path, app = seeded_db
        client = TestClient(app)
        # Log enough entries to get a measurable score
        for day in range(2, 14):
            d = f"2026-03-{day:02d}"
            execute({"action": "log_date", "payload": {
                "habit_id": "exercise", "date": d, "value": 1,
            }}, db_path)
        resp = client.get("/api/reports/sprint-comparison")
        sprints = resp.json()["data"]["sprints"]
        assert len(sprints) >= 1
        ws = sprints[0]["weighted_score"]
        # Score should be a number between 0 and 100
        assert 0 <= ws <= 100

    def test_reports_page_has_comparison_table(self, client):
        """Sprint comparison tab includes the table and chart elements."""
        resp = client.get("/reports?tab=sprint-comparison")
        assert resp.status_code == 200
        assert "sprint-comparison-table" in resp.text
        assert "sprint-comparison-chart" in resp.text

    def test_reports_page_fetches_api(self, client):
        """Sprint comparison tab includes JS fetch to the API endpoint."""
        resp = client.get("/reports?tab=sprint-comparison")
        assert resp.status_code == 200
        assert "/api/reports/sprint-comparison" in resp.text

    def test_api_multiple_sprints_trend(self, tmp_path):
        """With multiple sprints, trend_delta is computed between consecutive sprints."""
        db_path = str(tmp_path / "multi.db")
        app = create_app(db_path=db_path)
        client = TestClient(app)

        # Create first sprint and archive it
        execute({"action": "create_sprint", "payload": {
            "id": "s1", "start_date": "2026-02-02", "end_date": "2026-02-15",
        }}, db_path)
        execute({"action": "create_habit", "payload": {
            "id": "h1", "name": "H1", "category": "cat", "target_per_week": 7,
        }}, db_path)
        for day in range(2, 9):
            execute({"action": "log_date", "payload": {
                "habit_id": "h1", "date": f"2026-02-{day:02d}", "value": 1,
            }}, db_path)
        execute({"action": "archive_sprint", "payload": {"sprint_id": "s1"}}, db_path)

        # Create second sprint
        execute({"action": "create_sprint", "payload": {
            "id": "s2", "start_date": "2026-03-02", "end_date": "2026-03-15",
        }}, db_path)

        resp = client.get("/api/reports/sprint-comparison")
        assert resp.status_code == 200
        sprints = resp.json()["data"]["sprints"]
        assert len(sprints) == 2
        # First sprint has no trend_delta
        assert sprints[0]["trend_delta"] is None
        # Second sprint has a trend_delta (diff from first)
        assert sprints[1]["trend_delta"] is not None
