"""Tests for article configuration with per-language length profiles and deduplication."""

import pytest
from yt.config import ArticleConfig, ArticleDedupConfig, Config


class TestArticleDedupConfig:
    """Test ArticleDedupConfig dataclass."""

    def test_defaults(self):
        """Test default values for ArticleDedupConfig."""
        dedup = ArticleDedupConfig()
        assert dedup.enabled is False
        assert dedup.recursive is False

    def test_custom_values(self):
        """Test setting custom values."""
        dedup = ArticleDedupConfig(enabled=True, recursive=True)
        assert dedup.enabled is True
        assert dedup.recursive is True


class TestArticleConfigLengthByLanguage:
    """Test ArticleConfig with length_by_language."""

    def test_length_by_language_default(self):
        """Test that length_by_language defaults to empty dict."""
        article = ArticleConfig()
        assert article.length_by_language == {}

    def test_length_by_language_custom(self):
        """Test setting length_by_language."""
        article = ArticleConfig(length_by_language={"en": "long", "ja": "medium"})
        assert article.length_by_language == {"en": "long", "ja": "medium"}


class TestArticleConfigResolveLength:
    """Test ArticleConfig.resolve_length method."""

    def test_cli_override_takes_precedence(self):
        """CLI --length takes precedence over everything."""
        article = ArticleConfig(
            length="original",
            length_by_language={"en": "long"}
        )
        assert article.resolve_length("en", cli_override="short") == "short"
        assert article.resolve_length("ja", cli_override="medium") == "medium"

    def test_exact_language_match(self):
        """Exact language match in length_by_language."""
        article = ArticleConfig(
            length="original",
            length_by_language={"en": "long", "ja": "medium"}
        )
        assert article.resolve_length("en", cli_override=None) == "long"
        assert article.resolve_length("ja", cli_override=None) == "medium"

    def test_fallback_to_global_length(self):
        """Fall back to global length when language not in length_by_language."""
        article = ArticleConfig(
            length="short",
            length_by_language={"en": "long"}
        )
        assert article.resolve_length("ko", cli_override=None) == "short"
        assert article.resolve_length("zh", cli_override=None) == "short"

    def test_precedence_order(self):
        """Test full precedence: CLI > exact language > global."""
        article = ArticleConfig(
            length="original",
            length_by_language={"en": "medium"}
        )
        # CLI override wins
        assert article.resolve_length("en", cli_override="short") == "short"
        # Exact language match wins over global
        assert article.resolve_length("en", cli_override=None) == "medium"
        # Global fallback
        assert article.resolve_length("ja", cli_override=None) == "original"


class TestConfigFromDictLengthByLanguage:
    """Test Config.from_dict parsing of length_by_language."""

    def test_parse_length_by_language(self):
        """Test parsing length_by_language from dict."""
        data = {
            "output": {
                "article": {
                    "length": "original",
                    "length_by_language": {
                        "en": "long",
                        "ja": "medium"
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.length_by_language == {"en": "long", "ja": "medium"}

    def test_empty_length_by_language(self):
        """Test that missing length_by_language defaults to empty dict."""
        data = {
            "output": {
                "article": {
                    "length": "original"
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.length_by_language == {}

    def test_validate_language_profiles(self):
        """Test validation of language profiles (valid lengths)."""
        # Valid lengths
        data = {
            "output": {
                "article": {
                    "length_by_language": {
                        "en": "original",
                        "ja": "long",
                        "ko": "medium",
                        "zh": "short"
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert len(config.output.article.length_by_language) == 4

    def test_reject_invalid_language_length(self):
        """Test rejection of invalid length in length_by_language."""
        data = {
            "output": {
                "article": {
                    "length_by_language": {
                        "en": "invalid_length"
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="must be 'original', 'long', 'medium', or 'short'"):
            Config.from_dict(data)

    def test_reject_empty_string_language_key(self):
        """Test rejection of empty string as language key."""
        data = {
            "output": {
                "article": {
                    "length_by_language": {
                        "": "long"
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Language keys in length_by_language must be non-empty strings"):
            Config.from_dict(data)

    def test_reject_non_string_language_key(self):
        """Test rejection of non-string language keys."""
        data = {
            "output": {
                "article": {
                    "length_by_language": {
                        123: "long"
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Language keys in length_by_language must be non-empty strings"):
            Config.from_dict(data)


class TestConfigFromDictDedup:
    """Test Config.from_dict parsing of dedup configuration."""

    def test_parse_dedup_disabled(self):
        """Test parsing dedup with enabled=false."""
        data = {
            "output": {
                "article": {
                    "dedup": {
                        "enabled": False
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.dedup.enabled is False
        assert config.output.article.dedup.recursive is False

    def test_parse_dedup_enabled_with_frontmatter(self):
        """Test parsing dedup with enabled=true when metadata is frontmatter."""
        data = {
            "output": {
                "article": {
                    "metadata": "frontmatter",
                    "dedup": {
                        "enabled": True,
                        "recursive": False
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.dedup.enabled is True
        assert config.output.article.dedup.recursive is False

    def test_parse_dedup_enabled_recursive(self):
        """Test parsing dedup with both enabled and recursive true."""
        data = {
            "output": {
                "article": {
                    "metadata": "frontmatter",
                    "dedup": {
                        "enabled": True,
                        "recursive": True
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.dedup.enabled is True
        assert config.output.article.dedup.recursive is True

    def test_reject_dedup_without_frontmatter_header(self):
        """Test rejection of dedup when metadata is header."""
        data = {
            "output": {
                "article": {
                    "metadata": "header",
                    "dedup": {
                        "enabled": True
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Deduplication requires output.article.metadata: frontmatter"):
            Config.from_dict(data)

    def test_reject_dedup_without_frontmatter_footer(self):
        """Test rejection of dedup when metadata is footer."""
        data = {
            "output": {
                "article": {
                    "metadata": "footer",
                    "dedup": {
                        "enabled": True
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Deduplication requires output.article.metadata: frontmatter"):
            Config.from_dict(data)

    def test_reject_dedup_without_frontmatter_none(self):
        """Test rejection of dedup when metadata is none."""
        data = {
            "output": {
                "article": {
                    "metadata": "none",
                    "dedup": {
                        "enabled": True
                    }
                }
            }
        }
        with pytest.raises(ValueError, match="Deduplication requires output.article.metadata: frontmatter"):
            Config.from_dict(data)

    def test_dedup_defaults_when_not_specified(self):
        """Test that dedup defaults to disabled when not in config."""
        data = {
            "output": {
                "article": {
                    "length": "original"
                }
            }
        }
        config = Config.from_dict(data)
        assert config.output.article.dedup.enabled is False
        assert config.output.article.dedup.recursive is False
