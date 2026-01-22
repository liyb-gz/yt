"""YouTube integration using yt-dlp for metadata, captions, and audio download."""

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp


# Errors that suggest cookie/auth issues - should trigger fallback to anonymous
COOKIE_FALLBACK_ERRORS = [
    "Requested format is not available",
    "n challenge solving failed",
    "Only images are available",
    "Sign in to confirm your age",
]


@dataclass
class VideoMetadata:
    """Container for YouTube video metadata."""
    id: str
    title: str
    upload_date: str  # YYYYMMDD format
    uploader: str
    duration: int  # seconds
    subtitles: dict[str, list[dict[str, str]]]  # Official subtitles
    automatic_captions: dict[str, list[dict[str, str]]]  # Auto-generated


@dataclass
class SubtitleInfo:
    """Information about an available subtitle track."""
    language: str
    ext: str
    url: str | None = None
    is_automatic: bool = False


@dataclass
class PlaylistInfo:
    """Container for playlist/channel metadata."""
    id: str
    title: str
    uploader: str
    video_urls: list[str]


class YouTubeClient:
    """yt-dlp wrapper for YouTube operations."""
    
    def __init__(
        self,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        player_client: str | None = None,
        verbose: bool = False,
    ):
        self.cookies_file = cookies_file
        self.cookies_from_browser = cookies_from_browser
        self.player_client = player_client
        self.verbose = verbose
    
    @property
    def _has_cookies(self) -> bool:
        """Check if cookies are configured."""
        return bool(self.cookies_file or self.cookies_from_browser)
    
    def _get_base_opts(self, use_cookies: bool = True) -> dict[str, Any]:
        """
        Get base yt-dlp options.
        
        Args:
            use_cookies: Whether to include cookie options (set False for fallback)
        """
        opts: dict[str, Any] = {
            "quiet": not self.verbose,
            "no_warnings": not self.verbose,
        }
        
        if use_cookies:
            if self.cookies_file:
                opts["cookiefile"] = self.cookies_file
            
            if self.cookies_from_browser:
                opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        
        if self.player_client:
            opts["extractor_args"] = {"youtube": {"player_client": [self.player_client]}}
        
        return opts
    
    def _should_fallback(self, error: Exception) -> bool:
        """Check if error suggests we should retry without cookies."""
        error_str = str(error)
        return any(msg in error_str for msg in COOKIE_FALLBACK_ERRORS)
    
    def is_playlist_or_channel(self, url: str) -> bool:
        """
        Check if URL is a playlist or channel (not a single video).
        
        Detects:
        - Playlist URLs: /playlist?list=...
        - Channel URLs: /@username, /channel/..., /c/..., /user/...
        - Channel tabs: /@username/videos, /channel/.../videos
        """
        # Playlist URL patterns
        if "/playlist?" in url or "list=" in url:
            # But if it's a video URL with a playlist, it's a single video
            # e.g., /watch?v=xxx&list=yyy should be treated as single video
            if "/watch?" in url and "v=" in url:
                return False
            return True
        
        # Channel URL patterns
        channel_patterns = [
            r"youtube\.com/@[\w-]+(/videos)?/?$",
            r"youtube\.com/channel/[\w-]+(/videos)?/?$",
            r"youtube\.com/c/[\w-]+(/videos)?/?$",
            r"youtube\.com/user/[\w-]+(/videos)?/?$",
        ]
        for pattern in channel_patterns:
            if re.search(pattern, url):
                return True
        
        return False
    
    def expand_playlist_or_channel(self, url: str) -> PlaylistInfo | None:
        """
        Extract all video URLs from a playlist or channel.
        
        Args:
            url: Playlist or channel URL
        
        Returns:
            PlaylistInfo with video URLs, or None if extraction fails
        """
        opts = self._get_base_opts()
        opts.update({
            "skip_download": True,
            "extract_flat": True,  # Don't download individual video info
            "quiet": not self.verbose,
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    return None
                
                # Check if this is a playlist/channel (has entries)
                entries = info.get("entries", [])
                if not entries:
                    return None
                
                # Extract video URLs from entries
                video_urls = []
                for entry in entries:
                    if entry is None:
                        continue
                    # entry can be a dict with 'id' or 'url'
                    video_id = entry.get("id")
                    video_url = entry.get("url")
                    
                    if video_url:
                        video_urls.append(video_url)
                    elif video_id:
                        video_urls.append(f"https://www.youtube.com/watch?v={video_id}")
                
                return PlaylistInfo(
                    id=info.get("id", ""),
                    title=info.get("title", "Unknown Playlist"),
                    uploader=info.get("uploader", info.get("channel", "Unknown")),
                    video_urls=video_urls,
                )
        except Exception as e:
            if self.verbose:
                print(f"Failed to expand playlist/channel: {e}", file=sys.stderr)
            return None
    
    def get_metadata(self, url: str) -> VideoMetadata:
        """Fetch video metadata including available subtitles."""
        return self._get_metadata_impl(url, use_cookies=True)
    
    def _get_metadata_impl(self, url: str, use_cookies: bool) -> VideoMetadata:
        """Internal metadata fetch with cookie control."""
        opts = self._get_base_opts(use_cookies=use_cookies)
        opts.update({
            "skip_download": True,
            "writesubtitles": False,
            "writeautomaticsub": False,
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise ValueError(f"Could not extract info from {url}")
            
            return VideoMetadata(
                id=info.get("id", ""),
                title=info.get("title", "Unknown"),
                upload_date=info.get("upload_date", ""),
                uploader=info.get("uploader", "Unknown"),
                duration=info.get("duration", 0),
                subtitles=info.get("subtitles", {}),
                automatic_captions=info.get("automatic_captions", {}),
            )
        except Exception as e:
            # If cookies are enabled and error suggests auth issues, retry without cookies
            if use_cookies and self._has_cookies and self._should_fallback(e):
                print(
                    f"[yellow]Warning: Cookie-authenticated request failed, retrying without cookies...[/yellow]",
                    file=sys.stderr,
                )
                return self._get_metadata_impl(url, use_cookies=False)
            raise
    
    def list_available_subtitles(self, metadata: VideoMetadata) -> list[SubtitleInfo]:
        """List all available subtitle tracks for a video."""
        subtitles = []
        
        # Official subtitles first
        for lang, formats in metadata.subtitles.items():
            for fmt in formats:
                subtitles.append(SubtitleInfo(
                    language=lang,
                    ext=fmt.get("ext", "vtt"),
                    url=fmt.get("url"),
                    is_automatic=False,
                ))
        
        # Then automatic captions
        for lang, formats in metadata.automatic_captions.items():
            for fmt in formats:
                subtitles.append(SubtitleInfo(
                    language=lang,
                    ext=fmt.get("ext", "vtt"),
                    url=fmt.get("url"),
                    is_automatic=True,
                ))
        
        return subtitles
    
    def download_subtitles(
        self,
        url: str,
        language: str,
        output_dir: Path,
        filename_base: str,
        prefer_official: bool = True,
    ) -> Path | None:
        """
        Download subtitles for a specific language.
        
        Args:
            url: YouTube video URL
            language: Language code (e.g., 'en', 'ja')
            output_dir: Directory to save subtitle file
            filename_base: Base filename without extension
            prefer_official: Try official subtitles before auto-generated
        
        Returns:
            Path to downloaded subtitle file, or None if not available
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / filename_base)
        
        # Try official subtitles first
        if prefer_official:
            result = self._try_download_subtitles(
                url, language, output_template, automatic=False
            )
            if result:
                return result
        
        # Fall back to automatic captions
        result = self._try_download_subtitles(
            url, language, output_template, automatic=True
        )
        if result:
            return result
        
        # If prefer_official was True and we got here, official wasn't available
        # and neither was automatic. If prefer_official was False, try official now
        if not prefer_official:
            result = self._try_download_subtitles(
                url, language, output_template, automatic=False
            )
            if result:
                return result
        
        return None
    
    def _try_download_subtitles(
        self,
        url: str,
        language: str,
        output_template: str,
        automatic: bool,
    ) -> Path | None:
        """Attempt to download subtitles with specific settings."""
        # Try with FFmpeg converter first, then without
        for use_converter in [True, False]:
            opts = self._get_base_opts()
            opts.update({
                "skip_download": True,
                "writesubtitles": not automatic,
                "writeautomaticsub": automatic,
                "subtitleslangs": [language],
                # Prefer vtt/srt over json3/srv3 which have word-level timing
                "subtitlesformat": "vtt/srt/best",
                "outtmpl": output_template,
            })
            
            if use_converter:
                # Convert subtitles to SRT format (removes word-level timing from json3/srv3)
                opts["postprocessors"] = [{
                    "key": "FFmpegSubtitlesConvertor",
                    "format": "srt",
                }]
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                
                # Look for the downloaded subtitle file
                for ext in ["srt", "vtt", "json3", "srv3"]:
                    subtitle_path = Path(f"{output_template}.{language}.{ext}")
                    if subtitle_path.exists():
                        # Clean up any remaining artifacts
                        content = subtitle_path.read_text(encoding="utf-8")
                        cleaned = _clean_subtitle_content(content)
                        subtitle_path.write_text(cleaned, encoding="utf-8")
                        return subtitle_path
                
                # If we got here without finding a file, try next approach
                if use_converter:
                    continue
                return None
            except Exception as e:
                # If converter failed, try without it
                if use_converter:
                    continue
                return None
        
        return None
    
    def download_audio(
        self,
        url: str,
        output_dir: Path,
        filename: str,
    ) -> Path:
        """
        Download audio from a YouTube video.
        
        Args:
            url: YouTube video URL
            output_dir: Directory to save audio file
            filename: Output filename (should include extension like .m4a)
        
        Returns:
            Path to downloaded audio file
        """
        return self._download_audio_impl(url, output_dir, filename, use_cookies=True)
    
    def _download_audio_impl(
        self,
        url: str,
        output_dir: Path,
        filename: str,
        use_cookies: bool,
    ) -> Path:
        """Internal audio download with cookie control."""
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        
        # Remove extension for yt-dlp template
        base_name = output_path.stem
        output_template = str(output_dir / base_name)
        
        opts = self._get_base_opts(use_cookies=use_cookies)
        opts.update({
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": output_template + ".%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }],
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            for ext in ["m4a", "mp3", "opus", "webm"]:
                audio_path = output_dir / f"{base_name}.{ext}"
                if audio_path.exists():
                    return audio_path
            
            # If post-processing happened, look for m4a specifically
            if output_path.exists():
                return output_path
            
            raise FileNotFoundError(f"Audio download failed for {url}")
        except Exception as e:
            # If cookies are enabled and error suggests auth issues, retry without cookies
            if use_cookies and self._has_cookies and self._should_fallback(e):
                print(
                    f"[yellow]Warning: Cookie-authenticated request failed, retrying without cookies...[/yellow]",
                    file=sys.stderr,
                )
                return self._download_audio_impl(url, output_dir, filename, use_cookies=False)
            raise
    
    def get_subtitle_content(
        self,
        url: str,
        language: str,
        prefer_official: bool = True,
    ) -> tuple[str, bool] | None:
        """
        Get subtitle content directly without saving to file.
        
        Args:
            url: YouTube video URL
            language: Language code
            prefer_official: Try official subtitles first
        
        Returns:
            Tuple of (content, is_automatic) or None if not available
        """
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            result = self.download_subtitles(
                url, language, tmppath, "temp", prefer_official
            )
            if result and result.exists():
                content = result.read_text(encoding="utf-8")
                is_automatic = ".auto." in result.name or "auto" in result.stem.lower()
                return (content, is_automatic)
        
        return None


def _clean_subtitle_content(content: str) -> str:
    """
    Clean up subtitle content by removing word-level timing artifacts.
    
    YouTube's auto-generated captions sometimes include artifacts like:
    - <00:00:02.840><c> word</c>
    - Duplicate lines
    - Extra whitespace
    - JSON3 format with embedded timing
    """
    # Check if this is JSON3 format (starts with { or [)
    stripped_content = content.strip()
    if stripped_content.startswith('{') or stripped_content.startswith('['):
        return _convert_json3_to_srt(content)
    
    # Remove word-level timing tags: <00:00:02.840><c> and </c>
    content = re.sub(r'<[\d:.]+><c>', '', content)
    content = re.sub(r'</c>', '', content)
    
    # Remove any remaining timing-like tags
    content = re.sub(r'<[\d:.]+>', '', content)
    
    # Remove VTT positioning/styling tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Remove duplicate consecutive lines (common in auto-generated captions)
    lines = content.split('\n')
    cleaned_lines = []
    prev_line = None
    
    for line in lines:
        stripped = line.strip()
        # Keep timing lines and non-duplicate text lines
        if re.match(r'^\d+$', stripped):  # Subtitle index
            cleaned_lines.append(line)
            prev_line = None
        elif re.match(r'^\d{2}:\d{2}:\d{2}', stripped):  # Timestamp line
            cleaned_lines.append(line)
            prev_line = None
        elif stripped.upper() == 'WEBVTT':  # VTT header
            cleaned_lines.append(line)
            prev_line = None
        elif stripped and stripped != prev_line:  # Non-empty, non-duplicate
            cleaned_lines.append(line)
            prev_line = stripped
        elif not stripped:  # Keep empty lines for structure
            cleaned_lines.append(line)
            prev_line = None
    
    return '\n'.join(cleaned_lines)


def _convert_json3_to_srt(content: str) -> str:
    """Convert YouTube's JSON3 caption format to SRT."""
    import json
    
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content  # Return as-is if not valid JSON
    
    # Handle YouTube's JSON3 format
    events = data.get("events", [])
    if not events:
        return content
    
    srt_entries = []
    index = 1
    
    for event in events:
        # Skip events without segments (usually window positioning)
        if "segs" not in event:
            continue
        
        start_ms = event.get("tStartMs", 0)
        duration_ms = event.get("dDurationMs", 0)
        end_ms = start_ms + duration_ms
        
        # Combine all segments into one line
        text_parts = []
        for seg in event.get("segs", []):
            text = seg.get("utf8", "")
            if text and text.strip():
                text_parts.append(text)
        
        text = "".join(text_parts).strip()
        if not text or text == "\n":
            continue
        
        # Format timestamps
        start_time = _format_srt_timestamp(start_ms)
        end_time = _format_srt_timestamp(end_ms)
        
        srt_entries.append(f"{index}\n{start_time} --> {end_time}\n{text}\n")
        index += 1
    
    return "\n".join(srt_entries)


def _format_srt_timestamp(ms: int) -> str:
    """Format milliseconds to SRT timestamp (HH:MM:SS,mmm)."""
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
