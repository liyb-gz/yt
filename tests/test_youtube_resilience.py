import sys
import types
from pathlib import Path


class _UnusedYoutubeDL:
    def __init__(self, *args, **kwargs):
        raise AssertionError("test must provide a YoutubeDL implementation")


# Keep the tests runnable in the lightweight system Python used by this repo.
sys.modules.setdefault("yt_dlp", types.SimpleNamespace(YoutubeDL=_UnusedYoutubeDL))

from yt.youtube import VideoMetadata, YouTubeClient


def test_audio_client_candidates_include_android_fallback():
    assert YouTubeClient()._get_audio_player_clients() == [None, "android"]
    assert YouTubeClient(player_client="web")._get_audio_player_clients() == ["web"]


def test_metadata_retries_with_android_when_default_has_no_captions(monkeypatch):
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            if len(calls) == 1:
                return {
                    "id": "video",
                    "title": "Example",
                    "upload_date": "20260907",
                    "uploader": "Channel",
                    "duration": 12,
                }
            return {
                "id": "video",
                "title": "Example",
                "upload_date": "20260907",
                "uploader": "Channel",
                "duration": 12,
                "automatic_captions": {"en-US": [{"ext": "srt", "url": "https://captions"}]},
            }

    monkeypatch.setattr("yt.youtube.yt_dlp.YoutubeDL", FakeYoutubeDL)
    metadata = YouTubeClient().get_metadata("https://youtube.test/watch?v=video")

    assert list(metadata.automatic_captions) == ["en-US"]
    assert calls[1]["extractor_args"] == {"youtube": {"player_client": ["android"]}}


def test_subtitle_content_uses_metadata_track_without_reextracting(monkeypatch):
    calls = {"extract": 0, "urls": []}

    class FakeResponse:
        def read(self):
            return b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"

    class FakeYoutubeDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            calls["extract"] += 1
            raise AssertionError("metadata-backed subtitle lookup must not re-extract the video")

        def urlopen(self, url):
            calls["urls"].append(url)
            return FakeResponse()

    monkeypatch.setattr("yt.youtube.yt_dlp.YoutubeDL", FakeYoutubeDL)
    metadata = VideoMetadata(
        id="video",
        title="Example",
        upload_date="20260907",
        uploader="Channel",
        duration=12,
        subtitles={},
        automatic_captions={
            "en-US": [
                {"ext": "json3", "url": "https://captions/json3"},
                {"ext": "srt", "url": "https://captions/srt"},
            ]
        },
    )

    result = YouTubeClient().get_subtitle_content(
        "https://youtube.test/watch?v=video",
        "en-US",
        prefer_official=False,
        metadata=metadata,
    )

    assert result == ("1\n00:00:00,000 --> 00:00:01,000\nHello\n", True)
    assert calls == {"extract": 0, "urls": ["https://captions/srt"]}


def test_audio_download_retries_android_after_http_403(monkeypatch, tmp_path):
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            calls.append(opts)
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            if len(calls) == 1:
                raise RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
            output_template = self.opts["outtmpl"].replace("%(ext)s", "m4a")
            Path(output_template).write_bytes(b"audio")

    monkeypatch.setattr("yt.youtube.yt_dlp.YoutubeDL", FakeYoutubeDL)
    result = YouTubeClient().download_audio(
        "https://youtube.test/watch?v=video",
        tmp_path,
        "example.m4a",
    )

    assert result == tmp_path / "example.m4a"
    assert calls[0].get("extractor_args") is None
    assert calls[1]["extractor_args"] == {"youtube": {"player_client": ["android"]}}
