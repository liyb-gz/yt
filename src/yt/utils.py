"""Utility functions for file naming, path expansion, and helpers."""

import os
import re
from pathlib import Path


def expand_path(path: str) -> Path:
    """Expand ~ and environment variables in a path."""
    return Path(os.path.expandvars(os.path.expanduser(path)))


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    # Replace characters that are problematic in filenames
    replacements = {
        "/": "-",
        "\\": "-",
        ":": " -",
        "*": "",
        "?": "",
        '"': "'",
        "<": "",
        ">": "",
        "|": "-",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    # Remove leading/trailing whitespace and dots
    name = name.strip().strip(".")
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)
    return name


def format_output_filename(
    title: str,
    language: str,
    extension: str,
    date_prefix: str | None = None,
) -> str:
    """
    Format output filename according to the pattern:
    {YYYY-MM-DD} - {Video Title} [{language}].{ext}
    
    Args:
        title: Video title
        language: Language code (e.g., 'en', 'ja')
        extension: File extension without dot (e.g., 'srt', 'vtt', 'txt')
        date_prefix: Date in YYYYMMDD or YYYY-MM-DD format, or None to omit date prefix
    
    Returns:
        Formatted filename
    """
    safe_title = sanitize_filename(title)
    
    if date_prefix is None:
        return f"{safe_title} [{language}].{extension}"
    
    # Parse YYYYMMDD to YYYY-MM-DD if needed
    if len(date_prefix) == 8 and date_prefix.isdigit():
        formatted_date = f"{date_prefix[:4]}-{date_prefix[4:6]}-{date_prefix[6:8]}"
    else:
        formatted_date = date_prefix
    
    return f"{formatted_date} - {safe_title} [{language}].{extension}"


def format_audio_filename(
    title: str,
    extension: str = "m4a",
    date_prefix: str | None = None,
) -> str:
    """
    Format audio filename according to the pattern:
    {YYYY-MM-DD} - {Video Title} [audio].{ext}
    
    Args:
        title: Video title
        extension: File extension without dot (default: 'm4a')
        date_prefix: Date in YYYYMMDD or YYYY-MM-DD format, or None to omit date prefix
    """
    safe_title = sanitize_filename(title)
    
    if date_prefix is None:
        return f"{safe_title} [audio].{extension}"
    
    # Parse YYYYMMDD to YYYY-MM-DD if needed
    if len(date_prefix) == 8 and date_prefix.isdigit():
        formatted_date = f"{date_prefix[:4]}-{date_prefix[4:6]}-{date_prefix[6:8]}"
    else:
        formatted_date = date_prefix
    
    return f"{formatted_date} - {safe_title} [audio].{extension}"


def parse_language_codes(lang_string: str) -> list[str]:
    """Parse comma-separated language codes into a list."""
    return [lang.strip() for lang in lang_string.split(",") if lang.strip()]


def get_language_name(code: str) -> str:
    """Get human-readable language name from ISO 639-1 code."""
    language_names = {
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
        "zh-TW": "Traditional Chinese",
        "zh-CN": "Simplified Chinese",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ru": "Russian",
        "ar": "Arabic",
        "hi": "Hindi",
        "th": "Thai",
        "vi": "Vietnamese",
        "id": "Indonesian",
        "ms": "Malay",
        "nl": "Dutch",
        "pl": "Polish",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "cs": "Czech",
        "sv": "Swedish",
        "da": "Danish",
        "fi": "Finnish",
        "no": "Norwegian",
        "el": "Greek",
        "he": "Hebrew",
        "ro": "Romanian",
        "hu": "Hungarian",
        "bg": "Bulgarian",
        "hr": "Croatian",
        "sk": "Slovak",
        "sl": "Slovenian",
        "et": "Estonian",
        "lv": "Latvian",
        "lt": "Lithuanian",
    }
    return language_names.get(code, code)


def format_article_with_metadata(
    content: str,
    title: str,
    author: str,
    video_id: str,
    upload_date: str,
    request_date: str,
    style: str,
) -> str:
    """
    Add metadata to article content based on the specified style.
    
    Args:
        content: The article content (markdown)
        title: Video title
        author: Channel/uploader name
        video_id: YouTube video ID
        upload_date: Video upload date (YYYYMMDD or YYYY-MM-DD)
        request_date: Date the article was requested (YYYY-MM-DD)
        style: Metadata style: "frontmatter", "header", "footer", or "none"
    
    Returns:
        Article content with metadata added
    """
    if style == "none":
        return content
    
    # Format upload date if in YYYYMMDD format
    if len(upload_date) == 8 and upload_date.isdigit():
        formatted_upload = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    else:
        formatted_upload = upload_date
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    if style == "frontmatter":
        # YAML frontmatter
        frontmatter = f'''---
title: "{title}"
author: "{author}"
url: {url}
upload_date: {formatted_upload}
request_date: {request_date}
---

'''
        return frontmatter + content
    
    elif style == "header":
        # Visible header block
        header = f'''# {title}

> **Author:** {author}  
> **Source:** [YouTube]({url})  
> **Uploaded:** {formatted_upload} | **Requested:** {request_date}

---

'''
        return header + content
    
    elif style == "footer":
        # Footer with source info
        footer = f'''

---
*Source: [{title}]({url}) by {author} (uploaded {formatted_upload})*
'''
        return content + footer
    
    return content
