from __future__ import annotations

from pathlib import Path

from app.core import naming
from app.core.naming import (
    filename_from_url,
    improved_filename,
    is_ugly_name,
    sanitize_filename,
    unique_path,
)


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


def test_is_ugly_name():
    assert is_ugly_name("videoplayback.mp4")
    assert is_ugly_name("index.html")
    assert is_ugly_name("download")
    assert is_ugly_name("123456.mp4")
    assert is_ugly_name("f.bin")
    assert not is_ugly_name("My Vacation 2026.mp4")
    assert not is_ugly_name("lecture-03-recursion.pdf")


def test_improved_filename_rescues_ugly_names():
    fixed = improved_filename(
        "https://cdn.example/videoplayback.mp4", "Amazing Talk - Conference 2026"
    )
    assert fixed == "Amazing Talk - Conference 2026.mp4"


def test_improved_filename_keeps_good_names():
    kept = improved_filename("https://cdn.example/great-talk.mp4", "Some Page Title")
    assert kept == "great-talk.mp4"


def test_improved_filename_without_title_keeps_url_name():
    assert improved_filename("https://cdn.example/videoplayback.mp4", None) == ("videoplayback.mp4")


def test_improved_filename_guesses_extension_from_content_type():
    fixed = improved_filename("https://cdn.example/get", "A Nice Song", "audio/mpeg")
    assert fixed == "A Nice Song.mp3"


def test_unique_path_never_overwrites(tmp_path: Path):
    target = tmp_path / "file.bin"
    assert unique_path(target) == target
    target.write_bytes(b"x")
    assert unique_path(target) == tmp_path / "file (1).bin"
    (tmp_path / "file (1).bin").write_bytes(b"y")
    assert unique_path(target) == tmp_path / "file (2).bin"


# ------------------------------------------------------------- rename rules


def test_rename_rules_replace_in_order_and_keep_extension():
    rules = [("[SPONSORED] ", ""), ("Draft", "Final")]
    assert naming.apply_rename_rules("[SPONSORED] Draft Report.pdf", rules) == "Final Report.pdf"


def test_rename_rules_never_touch_the_extension():
    assert naming.apply_rename_rules("notes.txt", [("txt", "md")]) == "notes.txt"


def test_rename_rules_result_is_sanitized():
    # A rule can't inject path separators or empty the name out.
    assert "/" not in naming.apply_rename_rules("report.pdf", [("report", "a/b")])
    assert naming.apply_rename_rules("junk.bin", [("junk", "")]) == "download.bin"


def test_no_rules_is_a_no_op():
    assert naming.apply_rename_rules("as-is.zip", []) == "as-is.zip"
