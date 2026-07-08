from __future__ import annotations

from typing import Any

from app.engines.smart import (
    curate_formats,
    friendly_error,
    generic_quality_options,
    option_for_label,
    parse_playlist,
)

MB = 1024 * 1024


def _youtube_like_info() -> dict[str, Any]:
    """A trimmed-down but structurally faithful yt-dlp info dict."""
    return {
        "id": "abc123",
        "title": "Test Video",
        "formats": [
            # audio-only
            {
                "format_id": "140",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "filesize": 3 * MB,
                "ext": "m4a",
            },
            {
                "format_id": "251",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "filesize": 4 * MB,
                "ext": "webm",
            },
            # video-only (heights slightly off the ladder, as in real life)
            {
                "format_id": "248",
                "vcodec": "vp9",
                "acodec": "none",
                "height": 1088,
                "tbr": 4000,
                "filesize": 80 * MB,
                "ext": "webm",
            },
            {
                "format_id": "247",
                "vcodec": "vp9",
                "acodec": "none",
                "height": 720,
                "tbr": 2000,
                "filesize": 40 * MB,
                "ext": "webm",
            },
            # combined (already has audio)
            {
                "format_id": "18",
                "vcodec": "avc1",
                "acodec": "mp4a.40.2",
                "height": 360,
                "tbr": 700,
                "filesize": 20 * MB,
                "ext": "mp4",
            },
        ],
    }


def test_curated_labels_and_order():
    options = curate_formats(_youtube_like_info())
    assert [o.label for o in options] == ["Best", "1080p", "720p", "360p", "MP3", "M4A"]


def test_video_size_estimates_add_audio_when_needed():
    options = {o.label: o for o in curate_formats(_youtube_like_info())}
    # video-only 1080p (80 MB) + best audio (4 MB opus)
    assert options["1080p"].estimated_size == 84 * MB
    assert options["720p"].estimated_size == 44 * MB
    # the 360p format already has audio: no double counting
    assert options["360p"].estimated_size == 20 * MB
    assert options["Best"].estimated_size == 84 * MB


def test_format_specs():
    options = {o.label: o for o in curate_formats(_youtube_like_info())}
    assert options["Best"].format_spec == "bv*+ba/b"
    assert options["1080p"].format_spec == "bv*[height<=1080]+ba/b[height<=1080]"
    assert options["MP3"].format_spec == "ba/b"
    assert options["MP3"].audio_format == "mp3"
    assert options["M4A"].format_spec == "ba[ext=m4a]/ba/b"
    assert options["MP3"].estimated_size == 4 * MB


def test_audio_only_source_still_offers_audio():
    info = {
        "formats": [
            {"format_id": "0", "vcodec": "none", "acodec": "mp3", "abr": 192, "filesize": 5 * MB}
        ]
    }
    options = curate_formats(info)
    assert [o.label for o in options] == ["MP3", "M4A"]


def test_empty_formats_yield_no_options():
    assert curate_formats({"formats": []}) == ()


def test_parse_playlist_flat_listing():
    info = {
        "_type": "playlist",
        "title": "Lecture Series",
        "uploader": "Prof X",
        "webpage_url": "https://tube.example/playlist?list=1",
        "entries": [
            {"url": "https://tube.example/watch?v=a", "title": "Intro", "duration": 60},
            None,  # deleted video
            {"url": "abc123", "ie_key": "Youtube", "title": "Part 2"},
            {"url": "notaurl", "ie_key": "Other", "title": "skipped"},
        ],
    }
    playlist = parse_playlist(info)
    assert playlist is not None
    assert playlist.title == "Lecture Series"
    assert playlist.uploader == "Prof X"
    assert [entry.url for entry in playlist.entries] == [
        "https://tube.example/watch?v=a",
        "https://www.youtube.com/watch?v=abc123",
    ]
    assert playlist.entries[0].duration == 60
    # original positions survive the gaps
    assert [entry.index for entry in playlist.entries] == [1, 3]


def test_parse_playlist_returns_none_for_videos():
    assert parse_playlist({"_type": "video", "formats": []}) is None
    assert parse_playlist({"id": "x", "formats": []}) is None


def test_generic_quality_options_shape():
    options = generic_quality_options()
    labels = [option.label for option in options]
    assert labels == ["Best", "1080p", "720p", "480p", "MP3", "M4A"]
    assert options[-2].audio_format == "mp3"
    assert all(option.format_spec for option in options)


def test_option_for_label_prefers_curated_options():
    curated = curate_formats(_youtube_like_info())
    option = option_for_label("1080p", curated)
    assert option is not None and option in curated
    assert option.height == 1080


def test_option_for_label_falls_back_to_generic_tiers():
    # No curated list at all (F1.3 handoff before inspection details exist).
    option = option_for_label("720p")
    assert option is not None and option.format_spec == "bv*[height<=720]+ba/b[height<=720]"
    audio = option_for_label("mp3")
    assert audio is not None and audio.audio_format == "mp3"


def test_option_for_label_best_and_unknown():
    curated = curate_formats(_youtube_like_info())
    best = option_for_label("BEST", curated)
    assert best is not None and best.label == "Best"
    assert option_for_label("8888p", curated) is None


def test_friendly_errors():
    assert "private" in friendly_error("ERROR: [youtube] abc: Private video").lower()
    assert "age-restricted" in friendly_error("Sign in to confirm your age")
    assert "DRM" in friendly_error("This video is DRM protected")
    geo_message = "The uploader has not made this video available in your country"
    assert "region-blocked" in friendly_error(geo_message)
    assert "cookie" in friendly_error("Could not copy Chrome cookie database").lower()
    browse_404 = (
        "ERROR: [soundcloud:user] discover: Unable to download JSON metadata: "
        "HTTP Error 404: Not Found"
    )
    assert "browse" in friendly_error(browse_404)
    # unknown errors: first line, ERROR: prefix stripped, no traceback
    assert friendly_error("ERROR: something odd\nTraceback...") == "something odd"
