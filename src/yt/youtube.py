"""YouTube integration using yt-dlp for metadata, captions, and audio download."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp


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
    
    def _get_base_opts(self) -> dict[str, Any]:
        """Get base yt-dlp options."""
        opts: dict[str, Any] = {
            "quiet": not self.verbose,
            "no_warnings": not self.verbose,
        }
        
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        
        if self.player_client:
            opts["extractor_args"] = {"youtube": {"player_client": [self.player_client]}}
        
        return opts
    
    def get_metadata(self, url: str) -> VideoMetadata:
        """Fetch video metadata including available subtitles."""
        opts = self._get_base_opts()
        opts.update({
            "skip_download": True,
            "writesubtitles": False,
            "writeautomaticsub": False,
        })
        
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
        opts = self._get_base_opts()
        opts.update({
            "skip_download": True,
            "writesubtitles": not automatic,
            "writeautomaticsub": automatic,
            "subtitleslangs": [language],
            "subtitlesformat": "vtt/srt/best",
            "outtmpl": output_template,
        })
        
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Look for the downloaded subtitle file
            for ext in ["vtt", "srt"]:
                # yt-dlp adds language code to filename
                subtitle_path = Path(f"{output_template}.{language}.{ext}")
                if subtitle_path.exists():
                    return subtitle_path
            
            return None
        except Exception:
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
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        
        # Remove extension for yt-dlp template
        base_name = output_path.stem
        output_template = str(output_dir / base_name)
        
        opts = self._get_base_opts()
        opts.update({
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": output_template + ".%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }],
        })
        
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
