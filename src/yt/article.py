"""Article frontmatter parsing and identity extraction."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ArticleIdentity:
    """Identity tuple for article deduplication."""
    video_id: str
    language: str
    profile: str


def parse_article_frontmatter(text: str) -> dict[str, object] | None:
    """
    Parse YAML frontmatter from article text.

    Returns the parsed frontmatter as a dictionary, or None if:
    - Frontmatter is not present at the start of the text
    - YAML is malformed
    - Result is not a mapping (dict)

    Args:
        text: Article text potentially containing frontmatter

    Returns:
        Parsed frontmatter dictionary or None
    """
    # Check if text starts with frontmatter delimiter
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None

    # Find the closing delimiter
    # Must be on a standalone line (---\n or ---\r\n)
    lines = text.split("\n")

    # Skip the opening --- line
    closing_idx = None
    for i in range(1, len(lines)):
        line = lines[i].rstrip("\r")
        if line == "---":
            closing_idx = i
            break

    if closing_idx is None:
        return None

    # Extract YAML content between delimiters
    yaml_lines = lines[1:closing_idx]
    yaml_content = "\n".join(yaml_lines)

    # Parse YAML
    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        return None

    # Ensure result is a mapping
    if not isinstance(parsed, dict):
        return None

    return parsed


def frontmatter_identity(text: str) -> ArticleIdentity | None:
    """
    Extract article identity from frontmatter.

    Returns ArticleIdentity if all required fields are present and non-empty
    (after trimming), otherwise None.

    Required fields: video_id, language, profile

    Args:
        text: Article text with frontmatter

    Returns:
        ArticleIdentity or None
    """
    frontmatter = parse_article_frontmatter(text)
    if frontmatter is None:
        return None

    # Extract and validate required fields
    video_id = frontmatter.get("video_id")
    language = frontmatter.get("language")
    profile = frontmatter.get("profile")

    # Check all fields exist
    if video_id is None or language is None or profile is None:
        return None

    # Convert to strings and trim
    video_id_str = str(video_id).strip()
    language_str = str(language).strip()
    profile_str = str(profile).strip()

    # Check all fields are non-empty after trimming
    if not video_id_str or not language_str or not profile_str:
        return None

    return ArticleIdentity(
        video_id=video_id_str,
        language=language_str,
        profile=profile_str,
    )


def find_duplicate_articles(
    root: Path,
    identity: ArticleIdentity,
    recursive: bool = False,
) -> list[Path]:
    """
    Find all articles with matching identity in a directory.

    Scans markdown files in root directory (and descendants if recursive=True)
    for articles whose frontmatter matches the given identity.

    Files with malformed, incomplete, or unreadable frontmatter are silently
    ignored and do not abort processing.

    Args:
        root: Directory to scan for articles
        identity: Article identity to match against
        recursive: If True, scan all descendant directories; if False, only
                   scan direct children

    Returns:
        Sorted list of paths to articles with matching identity.
        Empty list if root does not exist.
    """
    # Return empty list if root doesn't exist
    if not root.exists():
        return []

    # Choose glob pattern based on recursive flag
    pattern = root.rglob("*.md") if recursive else root.glob("*.md")

    matches = []

    for path in pattern:
        # Skip if not a regular file (e.g., directories)
        if not path.is_file():
            continue

        try:
            # Read file content as UTF-8
            text = path.read_text(encoding="utf-8")

            # Extract identity from frontmatter
            article_identity = frontmatter_identity(text)

            # Check if identity matches
            if article_identity == identity:
                matches.append(path)

        except (OSError, UnicodeDecodeError):
            # Silently ignore files that cannot be read
            continue
        except Exception:
            # Catch any other errors (e.g., from YAML parsing)
            # and continue processing
            continue

    # Return sorted list
    return sorted(matches)

