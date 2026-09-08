"""Integration tests for article processing with profile resolution and dedup."""

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Keep tests runnable without yt_dlp
class _UnusedYoutubeDL:
    def __init__(self, *args, **kwargs):
        raise AssertionError("test must provide a YoutubeDL implementation")

sys.modules.setdefault("yt_dlp", types.SimpleNamespace(YoutubeDL=_UnusedYoutubeDL))

from yt.config import Config, ArticleConfig, ArticleDedupConfig, OutputConfig, StorageConfig
from yt.formatter import OutputFormat
from yt.transcript import process_video
from yt.youtube import VideoMetadata


def test_matching_article_skips_transcript_and_llm_calls(monkeypatch):
    """When dedup finds a match, skip both transcript fetch and LLM article generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        article_dir = Path(tmpdir)

        # Create existing article with matching identity
        existing_article = article_dir / "existing.md"
        existing_article.write_text(
            "---\nvideo_id: test123\nlanguage: en\nprofile: original\n---\nExisting content"
        )

        # Track network calls
        transcript_calls = []
        llm_calls = []

        def mock_try_any_youtube_transcript(url, metadata):
            transcript_calls.append(url)
            return ("Mock transcript content", "en", "official")

        def mock_generate_article(content, language, length):
            llm_calls.append((language, length))
            return f"Generated article in {language}"

        # Set up config with dedup enabled
        config = Config()
        config.storage = StorageConfig(article_dir=article_dir)
        config.output = OutputConfig(
            format="article",
            article=ArticleConfig(
                length="original",
                metadata="frontmatter",
                dedup=ArticleDedupConfig(enabled=True, recursive=False)
            )
        )

        # Mock YouTube client
        youtube_client = MagicMock()
        youtube_client.get_metadata.return_value = VideoMetadata(
            id="test123",
            title="Test Video",
            upload_date="20260907",
            uploader="Test Channel",
            duration=120,
            subtitles={},
            automatic_captions={}
        )

        # Monkeypatch the transcript fetcher methods
        from yt import transcript as transcript_module
        original_fetcher_init = transcript_module.TranscriptFetcher.__init__

        def patched_init(self, *args, **kwargs):
            original_fetcher_init(self, *args, **kwargs)
            self._try_any_youtube_transcript = mock_try_any_youtube_transcript
            if self._translation_client:
                self._translation_client.generate_article = mock_generate_article

        monkeypatch.setattr(transcript_module.TranscriptFetcher, "__init__", patched_init)

        # Process video
        results, transcripts = process_video(
            url="https://youtube.com/watch?v=test123",
            config=config,
            youtube_client=youtube_client,
            languages=["en"],
            output_format=OutputFormat.ARTICLE,
            article_length="original",
            force=False,
            save_files=True,
            pipe_mode=True,
        )

        # Verify no network calls were made (dedup found existing article)
        assert len(transcript_calls) == 0, "Should skip transcript fetch when duplicate found"
        assert len(llm_calls) == 0, "Should skip LLM call when duplicate found"
        assert "en" in results
        assert results["en"] == existing_article


def test_multiple_languages_with_different_profiles_generate_distinct_filenames(monkeypatch):
    """zh-TW original and ko short should produce separate files with profile in filename."""
    with tempfile.TemporaryDirectory() as tmpdir:
        article_dir = Path(tmpdir)

        # Track LLM calls to verify different length arguments
        llm_calls = []

        def mock_try_any_youtube_transcript(url, metadata):
            return ("Mock transcript content", "en", "official")

        def mock_generate_article(content, language, length):
            llm_calls.append((language, length))
            return f"Generated article in {language} with length {length}"

        # Set up config with per-language profiles
        config = Config()
        config.storage = StorageConfig(article_dir=article_dir)
        config.output = OutputConfig(
            format="article",
            article=ArticleConfig(
                length="original",  # Global default
                metadata="frontmatter",
                length_by_language={
                    "ko": "short"  # Korean override
                },
                dedup=ArticleDedupConfig(enabled=False, recursive=False)
            )
        )

        # Mock YouTube client
        youtube_client = MagicMock()
        youtube_client.get_metadata.return_value = VideoMetadata(
            id="test456",
            title="Test Video",
            upload_date="20260907",
            uploader="Test Channel",
            duration=120,
            subtitles={},
            automatic_captions={}
        )

        # Monkeypatch the transcript fetcher
        from yt import transcript as transcript_module
        original_fetcher_init = transcript_module.TranscriptFetcher.__init__

        def patched_init(self, *args, **kwargs):
            original_fetcher_init(self, *args, **kwargs)
            self._try_any_youtube_transcript = mock_try_any_youtube_transcript
            # Ensure translation client exists
            if not self._translation_client:
                self._translation_client = MagicMock()
            self._translation_client.generate_article = mock_generate_article
            self._translation_client.model = "gpt-4o"

        monkeypatch.setattr(transcript_module.TranscriptFetcher, "__init__", patched_init)

        # Process video for multiple languages
        results, transcripts = process_video(
            url="https://youtube.com/watch?v=test456",
            config=config,
            youtube_client=youtube_client,
            languages=["zh-TW", "ko"],
            output_format=OutputFormat.ARTICLE,
            article_length=None,  # Use config-based resolution
            force=False,
            save_files=True,
            pipe_mode=True,
        )

        # Verify LLM was called with correct lengths
        assert len(llm_calls) == 2
        assert ("zh-TW", "original") in llm_calls, "zh-TW should use global 'original'"
        assert ("ko", "short") in llm_calls, "ko should use overridden 'short'"

        # Verify filenames
        assert "zh-TW" in results
        assert "ko" in results

        zh_tw_path = results["zh-TW"]
        ko_path = results["ko"]

        # zh-TW with original profile should NOT have profile in filename
        assert "[original]" not in zh_tw_path.name, "Original profile should not appear in filename"
        assert "[zh-TW]" in zh_tw_path.name, "Language should appear in filename"

        # ko with short profile SHOULD have profile in filename
        assert "[ko]" in ko_path.name, "Language should appear in filename"
        assert "[short]" in ko_path.name, "Non-original profile should appear in filename"

        # Verify files were created and contain correct content
        assert zh_tw_path.exists()
        assert ko_path.exists()

        zh_tw_content = zh_tw_path.read_text()
        ko_content = ko_path.read_text()

        # Check frontmatter has correct profile
        assert "profile: original" in zh_tw_content
        assert "profile: short" in ko_content


def test_cli_override_takes_precedence_over_config(monkeypatch):
    """CLI --length override should take precedence over config profiles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        article_dir = Path(tmpdir)

        llm_calls = []

        def mock_try_any_youtube_transcript(url, metadata):
            return ("Mock transcript", "en", "official")

        def mock_generate_article(content, language, length):
            llm_calls.append((language, length))
            return f"Article in {language} with {length}"

        # Config says "original" globally and "short" for en
        config = Config()
        config.storage = StorageConfig(article_dir=article_dir)
        config.output = OutputConfig(
            format="article",
            article=ArticleConfig(
                length="original",
                metadata="frontmatter",
                length_by_language={
                    "en": "short"
                },
                dedup=ArticleDedupConfig(enabled=False)
            )
        )

        youtube_client = MagicMock()
        youtube_client.get_metadata.return_value = VideoMetadata(
            id="test789",
            title="Test",
            upload_date="20260907",
            uploader="Channel",
            duration=60,
            subtitles={},
            automatic_captions={}
        )

        from yt import transcript as transcript_module
        original_fetcher_init = transcript_module.TranscriptFetcher.__init__

        def patched_init(self, *args, **kwargs):
            original_fetcher_init(self, *args, **kwargs)
            self._try_any_youtube_transcript = mock_try_any_youtube_transcript
            if not self._translation_client:
                self._translation_client = MagicMock()
            self._translation_client.generate_article = mock_generate_article
            self._translation_client.model = "gpt-4o"

        monkeypatch.setattr(transcript_module.TranscriptFetcher, "__init__", patched_init)

        # Process with CLI override to "medium"
        results, transcripts = process_video(
            url="https://youtube.com/watch?v=test789",
            config=config,
            youtube_client=youtube_client,
            languages=["en"],
            output_format=OutputFormat.ARTICLE,
            article_length="medium",  # CLI override
            force=False,
            save_files=True,
            pipe_mode=True,
        )

        # CLI override should take precedence
        assert len(llm_calls) == 1
        assert llm_calls[0] == ("en", "medium")

        # Filename should reflect medium profile
        en_path = results["en"]
        assert "[medium]" in en_path.name


def test_force_bypasses_both_exact_path_and_metadata_dedup(monkeypatch):
    """--force should bypass both exact path check and metadata dedup check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        article_dir = Path(tmpdir)

        # Create existing article at exact path with matching identity
        existing_path = article_dir / "2026-09-07 - Test Video [en].md"
        existing_path.write_text(
            "---\nvideo_id: test999\nlanguage: en\nprofile: original\n---\nOld content"
        )

        llm_calls = []

        def mock_try_any_youtube_transcript(url, metadata):
            return ("New transcript", "en", "official")

        def mock_generate_article(content, language, length):
            llm_calls.append((language, length))
            return "New article content"

        config = Config()
        config.storage = StorageConfig(article_dir=article_dir)
        config.output = OutputConfig(
            format="article",
            filename_date="upload",
            article=ArticleConfig(
                length="original",
                metadata="frontmatter",
                dedup=ArticleDedupConfig(enabled=True, recursive=False)
            )
        )

        youtube_client = MagicMock()
        youtube_client.get_metadata.return_value = VideoMetadata(
            id="test999",
            title="Test Video",
            upload_date="20260907",
            uploader="Channel",
            duration=90,
            subtitles={},
            automatic_captions={}
        )

        from yt import transcript as transcript_module
        original_fetcher_init = transcript_module.TranscriptFetcher.__init__

        def patched_init(self, *args, **kwargs):
            original_fetcher_init(self, *args, **kwargs)
            self._try_any_youtube_transcript = mock_try_any_youtube_transcript
            if not self._translation_client:
                self._translation_client = MagicMock()
            self._translation_client.generate_article = mock_generate_article
            self._translation_client.model = "gpt-4o"

        monkeypatch.setattr(transcript_module.TranscriptFetcher, "__init__", patched_init)

        # Process with force=True
        results, transcripts = process_video(
            url="https://youtube.com/watch?v=test999",
            config=config,
            youtube_client=youtube_client,
            languages=["en"],
            output_format=OutputFormat.ARTICLE,
            article_length="original",
            force=True,  # Force should bypass all checks
            save_files=True,
            pipe_mode=True,
        )

        # Should have made LLM call despite existing file
        assert len(llm_calls) == 1

        # Should have overwritten the file
        content = existing_path.read_text()
        assert "New article content" in content
        assert "Old content" not in content
