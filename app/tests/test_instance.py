from __future__ import annotations

from pathlib import Path

from app.core.instance import app_is_running, clear_pid, running_marker, write_pid


def test_pid_lifecycle(tmp_path: Path):
    pid_path = tmp_path / "grabline.pid"
    assert not app_is_running(pid_path)
    write_pid(pid_path)
    assert app_is_running(pid_path)  # we are that process
    clear_pid(pid_path)
    assert not app_is_running(pid_path)
    clear_pid(pid_path)  # idempotent


def test_stale_pid_is_not_running(tmp_path: Path):
    pid_path = tmp_path / "grabline.pid"
    pid_path.write_text("99999999")  # far beyond pid_max: provably no such process
    assert not app_is_running(pid_path)


def test_garbage_pid_file(tmp_path: Path):
    pid_path = tmp_path / "grabline.pid"
    pid_path.write_text("not a pid")
    assert not app_is_running(pid_path)
    pid_path.write_text("-5")
    assert not app_is_running(pid_path)


def test_running_marker_context(tmp_path: Path):
    pid_path = tmp_path / "grabline.pid"
    with running_marker(pid_path):
        assert app_is_running(pid_path)
    assert not app_is_running(pid_path)
