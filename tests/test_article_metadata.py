"""Tests for article frontmatter parsing and enrichment."""

import pytest
from yt.article import ArticleIdentity, parse_article_frontmatter, frontmatter_identity
from yt.utils import format_article_with_metadata


class TestParseArticleFrontmatter:
    """Test parse_article_frontmatter function."""

    def test_parse_valid_frontmatter(self):
        """Test parsing valid YAML frontmatter."""
        text = """---
title: "Test Video"
video_id: abc123
language: en
profile: medium
---

Article content here.
"""
        result = parse_article_frontmatter(text)
        assert result is not None
        assert result["title"] == "Test Video"
        assert result["video_id"] == "abc123"
        assert result["language"] == "en"
        assert result["profile"] == "medium"

    def test_parse_frontmatter_with_schema_version(self):
        """Test parsing frontmatter with schema_version."""
        text = """---
schema_version: 1
title: "Test Video"
video_id: abc123
language: ja
profile: long
---

Content.
"""
        result = parse_article_frontmatter(text)
        assert result is not None
        assert result["schema_version"] == 1
        assert result["video_id"] == "abc123"

    def test_parse_frontmatter_with_special_chars(self):
        """Test parsing frontmatter with special characters requiring YAML escaping."""
        text = """---
title: 'Test: Video with "quotes" and colons'
video_id: xyz789
language: ko
profile: short
---

Content.
"""
        result = parse_article_frontmatter(text)
        assert result is not None
        assert result["title"] == 'Test: Video with "quotes" and colons'

    def test_reject_malformed_yaml(self):
        """Test rejection of malformed YAML."""
        text = """---
title: "Unclosed quote
video_id: abc123
---

Content.
"""
        result = parse_article_frontmatter(text)
        assert result is None

    def test_reject_non_mapping_yaml(self):
        """Test rejection of non-mapping YAML (e.g., list)."""
        text = """---
- item1
- item2
---

Content.
"""
        result = parse_article_frontmatter(text)
        assert result is None

    def test_reject_missing_delimiters(self):
        """Test rejection when frontmatter delimiters are missing."""
        text = """title: "Test Video"
video_id: abc123

Content without delimiters.
"""
        result = parse_article_frontmatter(text)
        assert result is None

    def test_reject_non_standalone_delimiter(self):
        """Test rejection when delimiters are not on standalone lines."""
        text = """--- extra text
title: "Test Video"
---

Content.
"""
        result = parse_article_frontmatter(text)
        assert result is None

    def test_reject_missing_closing_delimiter(self):
        """Test rejection when closing delimiter is missing."""
        text = """---
title: "Test Video"
video_id: abc123

Content without closing delimiter.
"""
        result = parse_article_frontmatter(text)
        assert result is None

    def test_ignore_frontmatter_not_at_start(self):
        """Test that frontmatter not at the start is ignored."""
        text = """Some content before.

---
title: "Test Video"
---

More content.
"""
        result = parse_article_frontmatter(text)
        assert result is None


class TestFrontmatterIdentity:
    """Test frontmatter_identity function."""

    def test_extract_complete_identity(self):
        """Test extraction of complete identity from frontmatter."""
        text = """---
title: "Test Video"
video_id: abc123
language: en
profile: medium
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is not None
        assert identity.video_id == "abc123"
        assert identity.language == "en"
        assert identity.profile == "medium"

    def test_trim_identity_strings(self):
        """Test that identity strings are trimmed."""
        text = """---
video_id: "  abc123  "
language: "  en  "
profile: "  medium  "
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is not None
        assert identity.video_id == "abc123"
        assert identity.language == "en"
        assert identity.profile == "medium"

    def test_reject_missing_video_id(self):
        """Test rejection when video_id is missing."""
        text = """---
language: en
profile: medium
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None

    def test_reject_missing_language(self):
        """Test rejection when language is missing."""
        text = """---
video_id: abc123
profile: medium
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None

    def test_reject_missing_profile(self):
        """Test rejection when profile is missing."""
        text = """---
video_id: abc123
language: en
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None

    def test_reject_empty_video_id(self):
        """Test rejection when video_id is empty after trimming."""
        text = """---
video_id: "   "
language: en
profile: medium
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None

    def test_reject_malformed_frontmatter(self):
        """Test rejection when frontmatter is malformed."""
        text = """---
malformed yaml: [unclosed
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None

    def test_reject_incomplete_frontmatter(self):
        """Test rejection when frontmatter is incomplete."""
        text = """---
video_id: abc123
---

Content.
"""
        identity = frontmatter_identity(text)
        assert identity is None


class TestArticleIdentity:
    """Test ArticleIdentity dataclass."""

    def test_create_identity(self):
        """Test creating ArticleIdentity."""
        identity = ArticleIdentity(
            video_id="abc123",
            language="en",
            profile="medium"
        )
        assert identity.video_id == "abc123"
        assert identity.language == "en"
        assert identity.profile == "medium"

    def test_identity_equality(self):
        """Test ArticleIdentity equality."""
        id1 = ArticleIdentity("abc123", "en", "medium")
        id2 = ArticleIdentity("abc123", "en", "medium")
        id3 = ArticleIdentity("abc123", "en", "long")

        assert id1 == id2
        assert id1 != id3


class TestFormatArticleWithMetadataEnriched:
    """Test format_article_with_metadata with enriched frontmatter."""

    def test_frontmatter_includes_enriched_fields(self):
        """Test that frontmatter includes schema_version, video_id, language, and profile."""
        content = "Article content here."
        result = format_article_with_metadata(
            content=content,
            title="Test Video",
            author="Test Author",
            video_id="abc123xyz",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="medium",
            style="frontmatter",
        )

        # Parse the frontmatter
        parsed = parse_article_frontmatter(result)
        assert parsed is not None
        assert parsed["schema_version"] == 1
        assert parsed["video_id"] == "abc123xyz"
        assert parsed["language"] == "en"
        assert parsed["profile"] == "medium"
        assert parsed["title"] == "Test Video"
        assert parsed["author"] == "Test Author"

    def test_frontmatter_yaml_escaping(self):
        """Test that special characters in YAML are properly escaped."""
        content = "Content."
        result = format_article_with_metadata(
            content=content,
            title='Video: with "quotes" and colons',
            author="Author's Name",
            video_id="xyz789",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="ja",
            profile="long",
            style="frontmatter",
        )

        # Parse the frontmatter
        parsed = parse_article_frontmatter(result)
        assert parsed is not None
        assert parsed["title"] == 'Video: with "quotes" and colons'
        assert parsed["author"] == "Author's Name"

    def test_frontmatter_unicode_handling(self):
        """Test that Unicode characters are preserved (allow_unicode=True)."""
        content = "内容です。"
        result = format_article_with_metadata(
            content=content,
            title="日本語のタイトル",
            author="著者名",
            video_id="test123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="ja",
            profile="medium",
            style="frontmatter",
        )

        # Parse the frontmatter
        parsed = parse_article_frontmatter(result)
        assert parsed is not None
        assert parsed["title"] == "日本語のタイトル"
        assert parsed["author"] == "著者名"
        # Verify content is preserved
        assert "内容です。" in result

    def test_frontmatter_field_order(self):
        """Test that frontmatter fields maintain order (sort_keys=False)."""
        content = "Content."
        result = format_article_with_metadata(
            content=content,
            title="Test",
            author="Author",
            video_id="vid123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="short",
            style="frontmatter",
        )

        # Extract frontmatter text
        lines = result.split("\n")
        frontmatter_lines = []
        in_frontmatter = False
        for line in lines:
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    break
            if in_frontmatter:
                frontmatter_lines.append(line)

        # schema_version should come first
        assert frontmatter_lines[0].startswith("schema_version:")

    def test_header_style_unchanged(self):
        """Test that header style is unchanged (no language/profile in header)."""
        content = "Article content."
        result = format_article_with_metadata(
            content=content,
            title="Test Video",
            author="Test Author",
            video_id="abc123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="medium",
            style="header",
        )

        # Should still work and not break
        assert "# Test Video" in result
        assert "Test Author" in result
        assert "Article content." in result
        # Should not have frontmatter
        assert not result.startswith("---")

    def test_header_style_trailing_spaces(self):
        """Test that header style preserves trailing spaces for markdown hard line breaks."""
        content = "Article content."
        result = format_article_with_metadata(
            content=content,
            title="Test Video",
            author="Test Author",
            video_id="abc123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="medium",
            style="header",
        )

        # Check for two trailing spaces after Author line (markdown hard line break)
        assert "> **Author:** Test Author  \n" in result
        # Check for two trailing spaces after Source line
        assert "**Source:** [YouTube](https://www.youtube.com/watch?v=abc123)  \n" in result

    def test_footer_style_unchanged(self):
        """Test that footer style is unchanged."""
        content = "Article content."
        result = format_article_with_metadata(
            content=content,
            title="Test Video",
            author="Test Author",
            video_id="abc123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="medium",
            style="footer",
        )

        assert "Article content." in result
        assert "Test Video" in result
        assert "Test Author" in result
        assert not result.startswith("---")

    def test_none_style_unchanged(self):
        """Test that none style returns content unchanged."""
        content = "Article content."
        result = format_article_with_metadata(
            content=content,
            title="Test Video",
            author="Test Author",
            video_id="abc123",
            upload_date="2024-01-15",
            request_date="2024-01-20",
            language="en",
            profile="medium",
            style="none",
        )

        assert result == content

    def test_frontmatter_roundtrip(self):
        """Test that generated frontmatter can be parsed back."""
        content = "Test content."
        result = format_article_with_metadata(
            content=content,
            title="Roundtrip Test",
            author="Tester",
            video_id="round123",
            upload_date="20240115",
            request_date="2024-01-20",
            language="ko",
            profile="long",
            style="frontmatter",
        )

        # Extract identity
        identity = frontmatter_identity(result)
        assert identity is not None
        assert identity.video_id == "round123"
        assert identity.language == "ko"
        assert identity.profile == "long"
