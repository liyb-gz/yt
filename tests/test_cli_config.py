"""Tests for CLI configuration documentation."""

import pytest
from yt.cli import DEFAULT_CONFIG_CONTENT


class TestDefaultConfigContent:
    """Test that DEFAULT_CONFIG_CONTENT documents all features."""

    def test_documents_length_by_language(self):
        """Test that DEFAULT_CONFIG_CONTENT documents length_by_language."""
        assert "length_by_language" in DEFAULT_CONFIG_CONTENT
        # Should show an example with multiple languages
        assert "en:" in DEFAULT_CONFIG_CONTENT or "# en:" in DEFAULT_CONFIG_CONTENT

    def test_documents_dedup(self):
        """Test that DEFAULT_CONFIG_CONTENT documents dedup configuration."""
        assert "dedup:" in DEFAULT_CONFIG_CONTENT
        assert "enabled:" in DEFAULT_CONFIG_CONTENT

    def test_documents_recursive(self):
        """Test that DEFAULT_CONFIG_CONTENT documents recursive scanning."""
        assert "recursive:" in DEFAULT_CONFIG_CONTENT
        # Should explain what recursive does
        content_lower = DEFAULT_CONFIG_CONTENT.lower()
        assert "subdirector" in content_lower or "nested" in content_lower or "recursive" in content_lower
