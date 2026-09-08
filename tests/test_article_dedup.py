"""Tests for article duplicate detection."""

import tempfile
from pathlib import Path

import pytest

from yt.article import ArticleIdentity, find_duplicate_articles


def test_find_duplicates_filename_independent():
    """Matches articles with same identity regardless of filename."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create articles with same identity but different filenames
        identity = ArticleIdentity(
            video_id="abc123",
            language="en",
            profile="default"
        )

        article1 = root / "random-name-1.md"
        article1.write_text(
            "---\nvideo_id: abc123\nlanguage: en\nprofile: default\n---\nContent 1"
        )

        article2 = root / "different-name.md"
        article2.write_text(
            "---\nvideo_id: abc123\nlanguage: en\nprofile: default\n---\nContent 2"
        )

        # Different identity should not match
        article3 = root / "other.md"
        article3.write_text(
            "---\nvideo_id: xyz789\nlanguage: en\nprofile: default\n---\nContent 3"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 2
        assert article1 in results
        assert article2 in results
        assert article3 not in results


def test_find_duplicates_non_recursive_only_direct_children():
    """Non-recursive mode only scans direct children, not subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        subdir = root / "subdir"
        subdir.mkdir()

        identity = ArticleIdentity(
            video_id="test123",
            language="fr",
            profile="technical"
        )

        # Direct child - should be found
        direct_child = root / "article.md"
        direct_child.write_text(
            "---\nvideo_id: test123\nlanguage: fr\nprofile: technical\n---\nDirect"
        )

        # In subdirectory - should NOT be found in non-recursive mode
        nested_article = subdir / "nested.md"
        nested_article.write_text(
            "---\nvideo_id: test123\nlanguage: fr\nprofile: technical\n---\nNested"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 1
        assert direct_child in results
        assert nested_article not in results


def test_find_duplicates_recursive_scans_all_descendants():
    """Recursive mode scans all descendant directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        subdir1 = root / "sub1"
        subdir1.mkdir()
        subdir2 = root / "sub1" / "sub2"
        subdir2.mkdir()

        identity = ArticleIdentity(
            video_id="video99",
            language="es",
            profile="casual"
        )

        # Direct child
        direct = root / "direct.md"
        direct.write_text(
            "---\nvideo_id: video99\nlanguage: es\nprofile: casual\n---\nDirect"
        )

        # One level deep
        level1 = subdir1 / "level1.md"
        level1.write_text(
            "---\nvideo_id: video99\nlanguage: es\nprofile: casual\n---\nLevel 1"
        )

        # Two levels deep
        level2 = subdir2 / "level2.md"
        level2.write_text(
            "---\nvideo_id: video99\nlanguage: es\nprofile: casual\n---\nLevel 2"
        )

        results = find_duplicate_articles(root, identity, recursive=True)

        assert len(results) == 3
        assert direct in results
        assert level1 in results
        assert level2 in results


def test_find_duplicates_ignores_malformed_frontmatter():
    """Articles with malformed frontmatter are ignored, not errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="valid123",
            language="de",
            profile="standard"
        )

        # Valid article
        valid = root / "valid.md"
        valid.write_text(
            "---\nvideo_id: valid123\nlanguage: de\nprofile: standard\n---\nValid"
        )

        # Malformed YAML
        malformed_yaml = root / "malformed.md"
        malformed_yaml.write_text(
            "---\nvideo_id: valid123\n  language: de\n    bad_indent: yes\n---\n"
        )

        # Missing closing delimiter
        no_closing = root / "no-closing.md"
        no_closing.write_text(
            "---\nvideo_id: valid123\nlanguage: de\nprofile: standard\n"
        )

        # Not a dict (just a string)
        not_dict = root / "not-dict.md"
        not_dict.write_text("---\njust a string\n---\n")

        results = find_duplicate_articles(root, identity, recursive=False)

        # Should only find the valid one
        assert len(results) == 1
        assert valid in results


def test_find_duplicates_ignores_incomplete_frontmatter():
    """Articles with incomplete frontmatter (missing required fields) are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="complete123",
            language="ja",
            profile="detailed"
        )

        # Complete and matching
        complete = root / "complete.md"
        complete.write_text(
            "---\nvideo_id: complete123\nlanguage: ja\nprofile: detailed\n---\nOK"
        )

        # Missing video_id
        missing_video = root / "missing-video.md"
        missing_video.write_text(
            "---\nlanguage: ja\nprofile: detailed\n---\nMissing video_id"
        )

        # Missing language
        missing_lang = root / "missing-lang.md"
        missing_lang.write_text(
            "---\nvideo_id: complete123\nprofile: detailed\n---\nMissing language"
        )

        # Missing profile
        missing_profile = root / "missing-profile.md"
        missing_profile.write_text(
            "---\nvideo_id: complete123\nlanguage: ja\n---\nMissing profile"
        )

        # Empty string after trimming
        empty_field = root / "empty.md"
        empty_field.write_text(
            "---\nvideo_id: complete123\nlanguage: '  '\nprofile: detailed\n---\nEmpty"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 1
        assert complete in results


def test_find_duplicates_returns_empty_list_when_root_absent():
    """Returns empty list when root directory does not exist."""
    nonexistent_root = Path("/tmp/this-does-not-exist-12345678")

    identity = ArticleIdentity(
        video_id="any",
        language="any",
        profile="any"
    )

    results = find_duplicate_articles(nonexistent_root, identity, recursive=False)

    assert results == []


def test_find_duplicates_ignores_non_markdown_files():
    """Only processes .md files, ignores other files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="md123",
            language="en",
            profile="default"
        )

        # Valid markdown file
        md_file = root / "article.md"
        md_file.write_text(
            "---\nvideo_id: md123\nlanguage: en\nprofile: default\n---\nContent"
        )

        # Text file with same content
        txt_file = root / "article.txt"
        txt_file.write_text(
            "---\nvideo_id: md123\nlanguage: en\nprofile: default\n---\nContent"
        )

        # Python file
        py_file = root / "script.py"
        py_file.write_text("# Not markdown")

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 1
        assert md_file in results


def test_find_duplicates_ignores_directories():
    """Ignores directories, only processes regular files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="dir123",
            language="en",
            profile="default"
        )

        # Create a directory that ends with .md (edge case)
        weird_dir = root / "looks-like-file.md"
        weird_dir.mkdir()

        # Create a real file
        real_file = root / "real-file.md"
        real_file.write_text(
            "---\nvideo_id: dir123\nlanguage: en\nprofile: default\n---\nReal"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 1
        assert real_file in results


def test_find_duplicates_returns_sorted_paths():
    """Results are returned in sorted order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="sort123",
            language="en",
            profile="default"
        )

        # Create files in non-alphabetical order
        file_c = root / "c-file.md"
        file_c.write_text(
            "---\nvideo_id: sort123\nlanguage: en\nprofile: default\n---\nC"
        )

        file_a = root / "a-file.md"
        file_a.write_text(
            "---\nvideo_id: sort123\nlanguage: en\nprofile: default\n---\nA"
        )

        file_b = root / "b-file.md"
        file_b.write_text(
            "---\nvideo_id: sort123\nlanguage: en\nprofile: default\n---\nB"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 3
        assert results == sorted(results)
        assert results == [file_a, file_b, file_c]


def test_find_duplicates_handles_utf8_content():
    """Correctly reads files with UTF-8 content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="utf8_test",
            language="zh",
            profile="chinese"
        )

        # Chinese content
        chinese_file = root / "chinese.md"
        chinese_file.write_text(
            "---\nvideo_id: utf8_test\nlanguage: zh\nprofile: chinese\n---\n你好世界",
            encoding="utf-8"
        )

        # Emoji content
        emoji_file = root / "emoji.md"
        emoji_file.write_text(
            "---\nvideo_id: utf8_test\nlanguage: zh\nprofile: chinese\n---\n😀🎉",
            encoding="utf-8"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        assert len(results) == 2
        assert chinese_file in results
        assert emoji_file in results


def test_find_duplicates_continues_on_read_errors():
    """Continues processing if a file cannot be read."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        identity = ArticleIdentity(
            video_id="error123",
            language="en",
            profile="default"
        )

        # Valid file
        valid_file = root / "valid.md"
        valid_file.write_text(
            "---\nvideo_id: error123\nlanguage: en\nprofile: default\n---\nValid"
        )

        # Create an unreadable file (simulate by creating a file then making it a directory)
        # This is tricky to test portably - we'll create a file with invalid UTF-8 instead
        invalid_utf8 = root / "invalid.md"
        invalid_utf8.write_bytes(b"---\nvideo_id: error123\n\xff\xfe---\n")

        # Another valid file
        valid_file2 = root / "valid2.md"
        valid_file2.write_text(
            "---\nvideo_id: error123\nlanguage: en\nprofile: default\n---\nValid 2"
        )

        results = find_duplicate_articles(root, identity, recursive=False)

        # Should find the valid files despite the error
        assert len(results) == 2
        assert valid_file in results
        assert valid_file2 in results
