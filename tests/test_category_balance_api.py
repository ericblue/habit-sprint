"""Tests for category balance and daily scores API endpoints (task 9.5)."""

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed (optional web dependency)")
from fastapi.testclient import TestClient

from habit_sprint.web import create_app
from habit_sprint.executor import execute


def _get_sprint_id(client):
    """Helper to get the first sprint ID from the API."""
    resp = client.get("/api/sprints")
    return resp.json()["data"]["sprints"][0]["id"]


@pytest.fixture()
def seeded_client(tmp_path):
    """Client with a sprint, habits in two categories, and some logged entries."""
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)

    execute({"action": "create_sprint", "payload": {
        "start_date": "2026-03-02", "end_date": "2026-03-15",
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "exercise", "name": "Exercise", "category": "health", "target_per_week": 5,
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "reading", "name": "Read", "category": "learning", "target_per_week": 3,
    }}, db_path)
    # Log some entries
    execute({"action": "log_date", "payload": {
        "habit_id": "exercise", "date": "2026-03-02", "value": 1,
    }}, db_path)
    execute({"action": "log_date", "payload": {
        "habit_id": "exercise", "date": "2026-03-03", "value": 1,
    }}, db_path)
    execute({"action": "log_date", "payload": {
        "habit_id": "reading", "date": "2026-03-02", "value": 1,
    }}, db_path)

    return TestClient(app)


@pytest.fixture()
def two_sprint_client(tmp_path):
    """Client with two sprints for comparison testing."""
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)

    execute({"action": "create_sprint", "payload": {
        "start_date": "2026-03-02", "end_date": "2026-03-15",
    }}, db_path)
    execute({"action": "create_sprint", "payload": {
        "start_date": "2026-02-16", "end_date": "2026-03-01",
    }}, db_path)
    execute({"action": "create_habit", "payload": {
        "id": "exercise", "name": "Exercise", "category": "health", "target_per_week": 5,
    }}, db_path)
    execute({"action": "log_date", "payload": {
        "habit_id": "exercise", "date": "2026-03-02", "value": 1,
    }}, db_path)
    execute({"action": "log_date", "payload": {
        "habit_id": "exercise", "date": "2026-02-17", "value": 1,
    }}, db_path)

    return TestClient(app)


@pytest.fixture()
def empty_client(tmp_path):
    """Client with no sprints."""
    db_path = str(tmp_path / "test.db")
    app = create_app(db_path=db_path)
    return TestClient(app)


class TestCategoryBalanceAPI:
    def test_category_balance_default(self, seeded_client):
        resp = seeded_client.get("/api/reports/category-balance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        categories = data["data"]["categories"]
        assert len(categories) == 2
        cat_names = {c["category"] for c in categories}
        assert "health" in cat_names
        assert "learning" in cat_names

    def test_category_balance_with_sprint_id(self, seeded_client):
        sprint_id = _get_sprint_id(seeded_client)
        resp = seeded_client.get(f"/api/reports/category-balance?sprint_id={sprint_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["data"]["categories"]) == 2

    def test_category_balance_invalid_sprint(self, seeded_client):
        resp = seeded_client.get("/api/reports/category-balance?sprint_id=nonexistent")
        assert resp.status_code in (404, 500)
        assert resp.json()["status"] == "error"

    def test_category_balance_no_sprint(self, empty_client):
        resp = empty_client.get("/api/reports/category-balance")
        assert resp.status_code in (404, 500)
        assert resp.json()["status"] == "error"

    def test_category_balance_with_comparison(self, two_sprint_client):
        sprints_resp = two_sprint_client.get("/api/sprints")
        sprints = sprints_resp.json()["data"]["sprints"]
        s1 = sprints[0]["id"]
        s2 = sprints[1]["id"]
        resp = two_sprint_client.get(
            f"/api/reports/category-balance?sprint_id={s1}&compare_sprint_id={s2}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "comparison" in data["data"]
        assert data["data"]["comparison"] is not None
        assert "categories" in data["data"]["comparison"]

    def test_category_balance_scores_correct(self, seeded_client):
        sprint_id = _get_sprint_id(seeded_client)
        resp = seeded_client.get(f"/api/reports/category-balance?sprint_id={sprint_id}")
        data = resp.json()
        categories = {c["category"]: c for c in data["data"]["categories"]}
        assert categories["health"]["weighted_score"] >= 0
        assert categories["learning"]["weighted_score"] >= 0


class TestDailyScoresAPI:
    def test_daily_scores_default(self, seeded_client):
        resp = seeded_client.get("/api/reports/daily-scores")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "scores" in data["data"]
        assert len(data["data"]["scores"]) > 0
        first = data["data"]["scores"][0]
        assert "date" in first
        assert "completion_pct" in first

    def test_daily_scores_with_sprint_id(self, seeded_client):
        sprint_id = _get_sprint_id(seeded_client)
        resp = seeded_client.get(f"/api/reports/daily-scores?sprint_id={sprint_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["sprint_id"] == sprint_id

    def test_daily_scores_invalid_sprint(self, seeded_client):
        resp = seeded_client.get("/api/reports/daily-scores?sprint_id=nonexistent")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    def test_daily_scores_no_sprint(self, empty_client):
        resp = empty_client.get("/api/reports/daily-scores")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    def test_daily_scores_has_logged_days(self, seeded_client):
        sprint_id = _get_sprint_id(seeded_client)
        resp = seeded_client.get(f"/api/reports/daily-scores?sprint_id={sprint_id}")
        data = resp.json()
        scores = data["data"]["scores"]
        day1 = next(s for s in scores if s["date"] == "2026-03-02")
        assert day1["completion_pct"] > 0


class TestReportsPage:
    def test_category_balance_tab_renders(self, seeded_client):
        resp = seeded_client.get("/reports?tab=category-balance")
        assert resp.status_code == 200
        assert "Category Balance" in resp.text
        assert "cb-sprint-select" in resp.text

    def test_trends_tab_renders(self, seeded_client):
        resp = seeded_client.get("/reports?tab=trends")
        assert resp.status_code == 200
        assert "Daily Score Trend" in resp.text
        assert "trend-sprint-select" in resp.text

    def test_sprint_selector_populated(self, seeded_client):
        resp = seeded_client.get("/reports?tab=category-balance")
        assert resp.status_code == 200
        sprint_id = _get_sprint_id(seeded_client)
        assert sprint_id in resp.text
