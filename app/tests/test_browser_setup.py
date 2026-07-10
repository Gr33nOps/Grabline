"""Browser Setup core: staging the extension to a stable path, detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core import browser_setup


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


def test_source_extension_has_a_manifest():
    manifest = browser_setup._source_extension_dir() / "manifest.json"
    assert manifest.is_file(), "the extension must ship with the app"


def test_install_extension_files_stages_a_usable_copy():
    target = browser_setup.install_extension_files()
    assert target == browser_setup.stable_extension_dir()
    assert (target / "manifest.json").is_file()
    assert (target / "background.js").is_file()
    assert (target / "content").is_dir()


def test_install_extension_files_refreshes_on_reinstall():
    first = browser_setup.install_extension_files()
    stale = first / "stale-leftover.txt"
    stale.write_text("old")
    browser_setup.install_extension_files()  # a second run (app update)
    assert not stale.exists()  # stale files are cleared
    assert (first / "manifest.json").is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="posix browser roots")
def test_detect_browsers_marks_installed(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".config" / "google-chrome").mkdir(parents=True)
    (home / ".mozilla").mkdir(parents=True)
    steps = {s.name: s for s in browser_setup.detect_browsers("linux", home=home)}
    assert steps["Chrome"].installed is True
    assert steps["Firefox"].installed is True
    assert steps["Brave"].installed is False
    # Firefox and Edge are the free-auto path; Chrome/Brave are load-unpacked.
    assert steps["Firefox"].method == "auto"
    assert steps["Microsoft Edge"].method == "auto"
    assert steps["Chrome"].method == "unpacked"


def test_detect_cookie_browser_prefers_firefox_over_edge(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".mozilla" / "firefox").mkdir(parents=True)
    (home / ".config" / "microsoft-edge").mkdir(parents=True)  # present but unused
    assert browser_setup.detect_cookie_browser("linux", home=home) == "firefox"


def test_detect_cookie_browser_falls_back_to_installed(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".config" / "google-chrome").mkdir(parents=True)
    assert browser_setup.detect_cookie_browser("linux", home=home) == "chrome"


def test_detect_cookie_browser_none_when_nothing_present(tmp_path: Path):
    assert browser_setup.detect_cookie_browser("linux", home=tmp_path / "empty") is None
