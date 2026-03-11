"""End-to-end integration tests for the CLI adapter.

These tests exercise the full stack: CLI -> executor -> engine/reporting -> SQLite.
No mocking of the executor or engine layers; we use real temp databases and
subprocess calls to ensure the entire pipeline works correctly.
"""

import json
import os
import pty
import subprocess
import sys
import tempfile
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    """Return a path to a fresh temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _run_cli_stdin(
    input_json: str,
    *extra_args: str,
    db: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the CLI piping *input_json* via stdin (full end-to-end)."""
    cmd = [sys.executable, "-m", "habit_sprint.cli"]
    if db is not None:
        cmd += ["--db", db]
    cmd += list(extra_args)
    return subprocess.run(
        cmd,
        input=input_json,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_cli_json_flag(
    json_str: str,
    *extra_args: str,
    db: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the CLI using the --json flag with a pseudo-TTY for stdin.

    This ensures ``sys.stdin.isatty()`` returns True inside the child process
    so the CLI reads from the ``--json`` argument instead of stdin.
    """
    cmd = [sys.executable, "-m", "habit_sprint.cli", "--json", json_str]
    if db is not None:
        cmd += ["--db", db]
    cmd += list(extra_args)

    # Create a pseudo-TTY so the child's stdin.isatty() returns True
    master_fd, slave_fd = pty.openpty()
    try:
        result = subprocess.run(
            cmd,
            stdin=slave_fd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        os.close(slave_fd)
        os.close(master_fd)
    return result


def _parse_envelope(result: subprocess.CompletedProcess) -> dict:
    """Parse the JSON envelope from subprocess stdout."""
    return json.loads(result.stdout)


def _create_sprint_payload(
    start_date: str = "2026-03-02",
    end_date: str = "2026-03-15",
    theme: str | None = None,
    focus_goals: list[str] | None = None,
) -> dict:
    """Build a create_sprint action dict."""
    payload: dict = {
        "start_date": start_date,
        "end_date": end_date,
    }
    if theme is not None:
        payload["theme"] = theme
    if focus_goals is not None:
        payload["focus_goals"] = focus_goals
    return {"action": "create_sprint", "payload": payload}


def _create_habit_payload(
    habit_id: str,
    name: str,
    category: str = "health",
    target_per_week: int = 5,
    weight: int = 1,
    sprint_id: str | None = None,
) -> dict:
    """Build a create_habit action dict."""
    payload: dict = {
        "id": habit_id,
        "name": name,
        "category": category,
        "target_per_week": target_per_week,
        "weight": weight,
    }
    if sprint_id is not None:
        payload["sprint_id"] = sprint_id
    return {"action": "create_habit", "payload": payload}


def _log_date_payload(habit_id: str, entry_date: str, value: int = 1) -> dict:
    """Build a log_date action dict."""
    return {
        "action": "log_date",
        "payload": {
            "habit_id": habit_id,
            "date": entry_date,
            "value": value,
        },
    }


# ---------------------------------------------------------------------------
# 1. Stdin pipe end-to-end
# ---------------------------------------------------------------------------

class TestStdinPipeEndToEnd:
    """Test piping valid JSON to stdin through the full stack."""

    def test_create_sprint_via_stdin(self):
        db = _tmp_db()
        try:
            action = _create_sprint_payload()
            result = _run_cli_stdin(json.dumps(action), db=db)

            assert result.returncode == 0
            envelope = _parse_envelope(result)
            assert envelope["status"] == "success"
            assert envelope["error"] is None
            assert envelope["data"]["start_date"] == "2026-03-02"
            assert envelope["data"]["end_date"] == "2026-03-15"
            assert envelope["data"]["status"] == "active"
            # Auto-generated ID should follow YYYY-S## pattern
            assert envelope["data"]["id"].startswith("2026-S")
        finally:
            os.unlink(db)

    def test_list_sprints_via_stdin_returns_empty_list(self):
        db = _tmp_db()
        try:
            action = {"action": "list_sprints", "payload": {}}
            result = _run_cli_stdin(json.dumps(action), db=db)

            assert result.returncode == 0
            envelope = _parse_envelope(result)
            assert envelope["status"] == "success"
            assert envelope["data"]["sprints"] == []
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 2. --json flag end-to-end
# ---------------------------------------------------------------------------

class TestJsonFlagEndToEnd:
    """Test the --json flag through the full stack."""

    def test_create_then_list_sprints(self):
        db = _tmp_db()
        try:
            # Create a sprint via --json flag
            create_action = json.dumps(_create_sprint_payload(theme="Test Theme"))
            result = _run_cli_json_flag(create_action, db=db)
            assert result.returncode == 0
            created = _parse_envelope(result)
            assert created["status"] == "success"
            sprint_id = created["data"]["id"]

            # List sprints via --json flag and verify
            list_action = json.dumps({"action": "list_sprints", "payload": {}})
            result = _run_cli_json_flag(list_action, db=db)
            assert result.returncode == 0
            listed = _parse_envelope(result)
            assert listed["status"] == "success"
            sprints = listed["data"]["sprints"]
            assert len(sprints) == 1
            assert sprints[0]["id"] == sprint_id
            assert sprints[0]["theme"] == "Test Theme"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 3. Chained operations
# ---------------------------------------------------------------------------

class TestChainedOperations:
    """Test create sprint -> create habit -> log entry -> verify via list."""

    def test_full_chain(self):
        db = _tmp_db()
        try:
            # Step 1: Create sprint
            create_sprint = _create_sprint_payload(
                start_date="2026-03-02",
                end_date="2026-03-15",
            )
            result = _run_cli_stdin(json.dumps(create_sprint), db=db)
            assert result.returncode == 0
            sprint_id = _parse_envelope(result)["data"]["id"]

            # Step 2: Create habit
            create_habit = _create_habit_payload(
                habit_id="reading",
                name="Reading",
                category="cognitive",
                target_per_week=5,
                weight=2,
                sprint_id=sprint_id,
            )
            result = _run_cli_stdin(json.dumps(create_habit), db=db)
            assert result.returncode == 0
            habit_data = _parse_envelope(result)["data"]
            assert habit_data["id"] == "reading"
            assert habit_data["name"] == "Reading"
            assert habit_data["weight"] == 2

            # Step 3: Log entry
            log = _log_date_payload("reading", "2026-03-02", value=1)
            result = _run_cli_stdin(json.dumps(log), db=db)
            assert result.returncode == 0
            log_data = _parse_envelope(result)["data"]
            assert log_data["habit_id"] == "reading"
            assert log_data["date"] == "2026-03-02"
            assert log_data["created"] is True

            # Step 4: List habits and verify
            list_habits = {"action": "list_habits", "payload": {"sprint_id": sprint_id}}
            result = _run_cli_stdin(json.dumps(list_habits), db=db)
            assert result.returncode == 0
            habits = _parse_envelope(result)["data"]["habits"]
            assert len(habits) == 1
            assert habits[0]["id"] == "reading"
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 4. --db flag creates DB
# ---------------------------------------------------------------------------

class TestDbFlagCreatesDb:
    """Test that --db creates a database file at the specified path."""

    def test_db_file_created(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(db_path)  # remove so we can verify it gets created
        try:
            assert not os.path.exists(db_path)
            action = json.dumps({"action": "list_sprints", "payload": {}})
            result = _run_cli_stdin(action, db=db_path)
            assert result.returncode == 0
            assert os.path.exists(db_path)
            # Verify it is a valid database by checking the envelope
            envelope = _parse_envelope(result)
            assert envelope["status"] == "success"
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ---------------------------------------------------------------------------
# 5. --format markdown for sprint_dashboard
# ---------------------------------------------------------------------------

class TestFormatMarkdownSprintDashboard:
    """Test --format markdown produces expected ASCII output for sprint_dashboard."""

    def test_sprint_dashboard_markdown_sections(self):
        db = _tmp_db()
        try:
            # Create sprint
            create_sprint = _create_sprint_payload(
                start_date="2026-03-02",
                end_date="2026-03-15",
                theme="Integration Test Sprint",
                focus_goals=["Testing", "Quality"],
            )
            result = _run_cli_stdin(json.dumps(create_sprint), db=db)
            assert result.returncode == 0
            sprint_id = _parse_envelope(result)["data"]["id"]

            # Create habits in two categories
            for habit in [
                _create_habit_payload("exercise", "Exercise", "health", 5, 2, sprint_id),
                _create_habit_payload("reading", "Reading", "cognitive", 3, 1, sprint_id),
            ]:
                result = _run_cli_stdin(json.dumps(habit), db=db)
                assert result.returncode == 0

            # Log some entries
            for entry in [
                _log_date_payload("exercise", "2026-03-02"),
                _log_date_payload("exercise", "2026-03-03"),
                _log_date_payload("reading", "2026-03-02"),
            ]:
                result = _run_cli_stdin(json.dumps(entry), db=db)
                assert result.returncode == 0

            # Request sprint_dashboard with --format markdown
            dashboard_action = json.dumps({
                "action": "sprint_dashboard",
                "payload": {"sprint_id": sprint_id},
            })
            result = _run_cli_stdin(
                dashboard_action,
                "--format", "markdown",
                db=db,
            )
            assert result.returncode == 0
            output = result.stdout

            # Verify expected sections are present
            assert "SPRINT:" in output
            assert "CATEGORY:" in output
            assert "DAILY TOTALS" in output
            assert "SPRINT SUMMARY" in output
            assert "SPRINT REFLECTION" in output

            # Verify theme and focus goals appear
            assert "Integration Test Sprint" in output
            assert "Testing" in output
            assert "Quality" in output

            # Verify habit names appear
            assert "Exercise" in output
            assert "Reading" in output

            # Output should NOT be valid JSON (it is markdown/ASCII)
            with pytest.raises(json.JSONDecodeError):
                json.loads(output)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 6. --format markdown for daily_score and sprint_report
# ---------------------------------------------------------------------------

class TestFormatMarkdownOtherActions:
    """Test --format markdown for daily_score and sprint_report."""

    def _setup_sprint_with_data(self, db: str) -> str:
        """Create a sprint with habits and entries, return sprint_id."""
        create_sprint = _create_sprint_payload(
            start_date="2026-03-02",
            end_date="2026-03-15",
            theme="Test Sprint",
        )
        result = _run_cli_stdin(json.dumps(create_sprint), db=db)
        sprint_id = _parse_envelope(result)["data"]["id"]

        create_habit = _create_habit_payload(
            "meditation", "Meditation", "health", 5, 1, sprint_id,
        )
        _run_cli_stdin(json.dumps(create_habit), db=db)

        log = _log_date_payload("meditation", "2026-03-02", value=1)
        _run_cli_stdin(json.dumps(log), db=db)

        return sprint_id

    def test_daily_score_markdown(self):
        db = _tmp_db()
        try:
            sprint_id = self._setup_sprint_with_data(db)

            action = json.dumps({
                "action": "daily_score",
                "payload": {"date": "2026-03-02", "sprint_id": sprint_id},
            })
            result = _run_cli_stdin(
                action,
                "--format", "markdown",
                db=db,
            )
            assert result.returncode == 0
            output = result.stdout

            assert "DAILY SCORE" in output
            assert "2026-03-02" in output
            # Should contain COMPLETED section since we logged an entry
            assert "COMPLETED" in output
            assert "Meditation" in output

            # Not JSON
            with pytest.raises(json.JSONDecodeError):
                json.loads(output)
        finally:
            os.unlink(db)

    def test_sprint_report_markdown(self):
        db = _tmp_db()
        try:
            sprint_id = self._setup_sprint_with_data(db)

            action = json.dumps({
                "action": "sprint_report",
                "payload": {"sprint_id": sprint_id},
            })
            result = _run_cli_stdin(
                action,
                "--format", "markdown",
                db=db,
            )
            assert result.returncode == 0
            output = result.stdout

            assert "SPRINT REPORT" in output
            assert "2026-03-02" in output
            assert "2026-03-15" in output
            assert "Test Sprint" in output
            assert "Meditation" in output

            # Not JSON
            with pytest.raises(json.JSONDecodeError):
                json.loads(output)
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 7. Invalid JSON via stdin pipe
# ---------------------------------------------------------------------------

class TestInvalidJsonStdinPipe:
    """Test that malformed JSON piped via stdin produces an error envelope."""

    def test_malformed_json_stdin(self):
        db = _tmp_db()
        try:
            result = _run_cli_stdin("this is not json{{{", db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert envelope["data"] is None
            assert "Invalid JSON" in envelope["error"]
        finally:
            os.unlink(db)

    def test_empty_string_stdin(self):
        db = _tmp_db()
        try:
            result = _run_cli_stdin("", db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert "Invalid JSON" in envelope["error"]
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 8. Invalid JSON via --json flag
# ---------------------------------------------------------------------------

class TestInvalidJsonFlag:
    """Test that malformed JSON via --json produces error envelope and exit code 1."""

    def test_malformed_json_flag(self):
        db = _tmp_db()
        try:
            result = _run_cli_json_flag("not-valid-json", db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert envelope["data"] is None
            assert "Invalid JSON" in envelope["error"]
        finally:
            os.unlink(db)

    def test_truncated_json_flag(self):
        db = _tmp_db()
        try:
            result = _run_cli_json_flag('{"action": "list_sprints"', db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert "Invalid JSON" in envelope["error"]
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 9. Unknown action
# ---------------------------------------------------------------------------

class TestUnknownAction:
    """Test that an unknown action returns error envelope."""

    def test_unknown_action_error(self):
        db = _tmp_db()
        try:
            action = json.dumps({"action": "nonexistent_action", "payload": {}})
            result = _run_cli_stdin(action, db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert envelope["data"] is None
            assert "Unknown action" in envelope["error"]
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 10. Validation error
# ---------------------------------------------------------------------------

class TestValidationError:
    """Test that invalid payloads (missing required fields) return error."""

    def test_missing_required_field(self):
        db = _tmp_db()
        try:
            # create_habit requires 'id', 'name', 'category', 'target_per_week'
            # Omit 'name' to trigger validation error
            action = json.dumps({
                "action": "create_habit",
                "payload": {
                    "id": "test-habit",
                    "category": "health",
                    "target_per_week": 5,
                },
            })
            result = _run_cli_stdin(action, db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert envelope["data"] is None
            assert "name" in envelope["error"].lower()
        finally:
            os.unlink(db)

    def test_invalid_field_type(self):
        db = _tmp_db()
        try:
            # target_per_week must be an int, pass a string
            action = json.dumps({
                "action": "create_habit",
                "payload": {
                    "id": "test-habit",
                    "name": "Test",
                    "category": "health",
                    "target_per_week": "not-a-number",
                },
            })
            result = _run_cli_stdin(action, db=db)

            assert result.returncode == 1
            envelope = _parse_envelope(result)
            assert envelope["status"] == "error"
            assert "target_per_week" in envelope["error"]
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# 11. No input
# ---------------------------------------------------------------------------

class TestNoInput:
    """Test that no stdin and no --json flag returns exit code 1."""

    def test_no_input_exits_with_error(self):
        """When stdin is a tty and no --json is given, exit code should be 1.

        We mock sys.stdin.isatty because subprocess cannot easily provide
        a real TTY with no data for the child process.
        """
        from habit_sprint.cli import main

        tty_mock = mock.MagicMock()
        tty_mock.isatty.return_value = True

        with mock.patch("sys.argv", ["habit-sprint"]):
            with mock.patch("sys.stdin", tty_mock):
                code = main()
        assert code == 1

    def test_no_input_prints_error_to_stderr(self, capsys):
        """When no input is provided, an error message goes to stderr."""
        from habit_sprint.cli import main

        tty_mock = mock.MagicMock()
        tty_mock.isatty.return_value = True

        with mock.patch("sys.argv", ["habit-sprint"]):
            with mock.patch("sys.stdin", tty_mock):
                main()

        err = capsys.readouterr().err
        assert "Error" in err or "usage" in err.lower()


# ---------------------------------------------------------------------------
# 12. Markdown fallback to JSON
# ---------------------------------------------------------------------------

class TestMarkdownFallbackToJson:
    """When --format markdown is used with an action without a formatter,
    the output should fall back to JSON."""

    def test_list_sprints_with_markdown_flag_returns_json(self):
        db = _tmp_db()
        try:
            action = json.dumps({"action": "list_sprints", "payload": {}})
            result = _run_cli_stdin(
                action,
                "--format", "markdown",
                db=db,
            )
            assert result.returncode == 0
            # Should still be valid JSON since list_sprints has no formatter
            envelope = _parse_envelope(result)
            assert envelope["status"] == "success"
            assert "sprints" in envelope["data"]
        finally:
            os.unlink(db)

    def test_create_sprint_with_markdown_flag_returns_json(self):
        db = _tmp_db()
        try:
            action = json.dumps(_create_sprint_payload())
            result = _run_cli_stdin(
                action,
                "--format", "markdown",
                db=db,
            )
            assert result.returncode == 0
            # create_sprint has no formatter, should fall back to JSON
            envelope = _parse_envelope(result)
            assert envelope["status"] == "success"
            assert envelope["data"]["start_date"] == "2026-03-02"
        finally:
            os.unlink(db)
