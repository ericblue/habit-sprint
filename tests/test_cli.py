"""Tests for the CLI adapter."""

import json
import subprocess
import sys
import tempfile
import os
from io import StringIO
from unittest import mock

from habit_sprint.cli import main


def _tmp_db():
    """Return a path to a fresh temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _tty_stdin():
    """Return a mock stdin that reports isatty=True (no pipe)."""
    m = mock.MagicMock()
    m.isatty.return_value = True
    return m


class TestJsonFlag:
    def test_valid_json_flag_returns_result(self, capsys):
        db = _tmp_db()
        action = json.dumps({"action": "list_sprints", "payload": {}})
        with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {"items": []}, "error": None}) as mock_exec:
            with mock.patch("sys.argv", ["habit-sprint", "--json", action, "--db", db]):
                with mock.patch("sys.stdin", _tty_stdin()):
                    code = main()
        mock_exec.assert_called_once()
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"

    def test_json_flag_passes_parsed_dict_to_executor(self):
        db = _tmp_db()
        action = json.dumps({"action": "create_sprint", "payload": {"name": "s1"}})
        with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {}, "error": None}) as mock_exec:
            with mock.patch("sys.argv", ["habit-sprint", "--json", action, "--db", db]):
                with mock.patch("sys.stdin", _tty_stdin()):
                    main()
        called_action = mock_exec.call_args[0][0]
        assert called_action == {"action": "create_sprint", "payload": {"name": "s1"}}


class TestStdinPipe:
    def test_stdin_pipe_reads_json(self):
        db = _tmp_db()
        action = json.dumps({"action": "list_sprints", "payload": {}})
        result = subprocess.run(
            [sys.executable, "-m", "habit_sprint.cli", "--db", db],
            input=action,
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        assert output["status"] in ("success", "error")
        assert set(output.keys()) == {"status", "data", "error"}

    def test_stdin_pipe_with_mock(self):
        db = _tmp_db()
        action = json.dumps({"action": "list_sprints"})
        mock_stdin = mock.MagicMock()
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = action
        with mock.patch("sys.argv", ["habit-sprint", "--db", db]):
            with mock.patch("sys.stdin", mock_stdin):
                with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {}, "error": None}) as mock_exec:
                    code = main()
        mock_exec.assert_called_once()
        assert code == 0


class TestDbFlag:
    def test_db_flag_passed_to_executor(self):
        db = "/tmp/custom-test.db"
        action = json.dumps({"action": "list_sprints"})
        with mock.patch("sys.argv", ["habit-sprint", "--json", action, "--db", db]):
            with mock.patch("sys.stdin", _tty_stdin()):
                with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {}, "error": None}) as mock_exec:
                    main()
        assert mock_exec.call_args[0][1] == db

    def test_default_db_path(self):
        from habit_sprint.cli import DEFAULT_DB_PATH
        action = json.dumps({"action": "list_sprints"})
        with mock.patch("sys.argv", ["habit-sprint", "--json", action]):
            with mock.patch("sys.stdin", _tty_stdin()):
                with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {}, "error": None}) as mock_exec:
                    main()
        assert mock_exec.call_args[0][1] == DEFAULT_DB_PATH


class TestInvalidJson:
    def test_invalid_json_returns_error_envelope(self, capsys):
        with mock.patch("sys.argv", ["habit-sprint", "--json", "not-json"]):
            with mock.patch("sys.stdin", _tty_stdin()):
                code = main()
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"
        assert output["data"] is None
        assert "Invalid JSON" in output["error"]
        assert code == 1

    def test_empty_json_string_returns_error(self, capsys):
        with mock.patch("sys.argv", ["habit-sprint", "--json", ""]):
            with mock.patch("sys.stdin", _tty_stdin()):
                code = main()
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"
        assert code == 1


class TestExitCodes:
    def test_success_returns_exit_code_0(self):
        action = json.dumps({"action": "list_sprints"})
        with mock.patch("sys.argv", ["habit-sprint", "--json", action]):
            with mock.patch("sys.stdin", _tty_stdin()):
                with mock.patch("habit_sprint.executor.execute", return_value={"status": "success", "data": {}, "error": None}):
                    assert main() == 0

    def test_error_returns_exit_code_1(self):
        action = json.dumps({"action": "unknown_action"})
        with mock.patch("sys.argv", ["habit-sprint", "--json", action]):
            with mock.patch("sys.stdin", _tty_stdin()):
                with mock.patch("habit_sprint.executor.execute", return_value={"status": "error", "data": None, "error": "Unknown action"}):
                    assert main() == 1

    def test_subprocess_exit_code_on_invalid_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "habit_sprint.cli", "--json", "bad-json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "error"


class TestNoInput:
    def test_no_input_returns_exit_code_1(self):
        with mock.patch("sys.argv", ["habit-sprint"]):
            with mock.patch("sys.stdin", _tty_stdin()):
                code = main()
        assert code == 1

    def test_no_input_prints_usage_to_stderr(self, capsys):
        with mock.patch("sys.argv", ["habit-sprint"]):
            with mock.patch("sys.stdin", _tty_stdin()):
                main()
        err = capsys.readouterr().err
        assert "Error" in err or "usage" in err.lower()
