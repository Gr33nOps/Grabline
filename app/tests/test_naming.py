from __future__ import annotations

from pathlib import Path

from app.core.naming import filename_from_url, sanitize_filename, unique_path


def test_sanitize_strips_invalid_characters():
    assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j.mp4') == "a_b_c_d_e_f_g_h_i_j.mp4"


def test_sanitize_control_chars_and_dots():
    assert sanitize_filename("..\x00\x1fmovie.mkv..") == "__movie.mkv"


def test_sanitize_empty_becomes_fallback():
    assert sanitize_filename("   ") == "download"
    assert sanitize_filename("...") == "download"


def test_sanitize_windows_reserved_names():
    assert sanitize_filename("CON.txt") == "_CON.txt"
    assert sanitize_filename("com1.tar.gz") == "_com1.tar.gz"


def test_sanitize_caps_length_but_keeps_extension():
    name = sanitize_filename("x" * 400 + ".mp4")
    assert len(name) <= 150
    assert name.endswith(".mp4")


def test_filename_from_url():
    assert filename_from_url("http://x.test/a/My%20Video.mp4?token=1") == "My Video.mp4"
    assert filename_from_url("http://x.test/") == "download"


def test_unique_path_never_overwrites(tmp_path: Path):
    target = tmp_path / "file.bin"
    assert unique_path(target) == target
    target.write_bytes(b"x")
    assert unique_path(target) == tmp_path / "file (1).bin"
    (tmp_path / "file (1).bin").write_bytes(b"y")
    assert unique_path(target) == tmp_path / "file (2).bin"
