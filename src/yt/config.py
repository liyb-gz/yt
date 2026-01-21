"""Configuration loading and management."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from yt.utils import expand_path


DEFAULT_CONFIG_PATH = Path("~/.config/yt/config.yaml")


@dataclass
class StorageConfig:
    """Storage directory configuration."""
    audio_dir: Path = field(default_factory=lambda: expand_path("~/YouTube Subtitles/Audio"))
    transcript_dir: Path = field(default_factory=lambda: expand_path("~/YouTube Subtitles/Transcripts"))
    article_dir: Path = field(default_factory=lambda: expand_path("~/YouTube Subtitles/Articles"))


@dataclass
class TranscriptionConfig:
    """Whisper transcription API configuration."""
    base_url: str = "https://api.openai.com/v1/audio/transcriptions"
    model: str = "whisper-1"
    api_key_env: str = "OPENAI_API_KEY"
    
    @property
    def api_key(self) -> str | None:
        """Get API key from environment variable."""
        return os.environ.get(self.api_key_env)


@dataclass
class LLMConfig:
    """LLM translation API configuration."""
    base_url: str = "https://api.openai.com/v1/chat/completions"
    model: str = "gpt-4o"
    api_key_env: str = "OPENAI_API_KEY"
    
    @property
    def api_key(self) -> str | None:
        """Get API key from environment variable."""
        return os.environ.get(self.api_key_env)


@dataclass
class OutputConfig:
    """Output configuration."""
    format: str = "srt"  # srt, vtt, or txt
    pipe_mode: bool = False  # When True, output transcript to stdout for piping
    log_file: Path | None = None  # Path to log file (None = no file logging)
    filename_date: str = "upload"  # "upload" = video upload date, "request" = today's date, "none" = no date prefix
    article_metadata: str = "frontmatter"  # "frontmatter", "header", "footer", or "none"


@dataclass
class YouTubeConfig:
    """YouTube/yt-dlp configuration."""
    cookies_from_browser: str | None = None  # e.g., "chrome", "firefox", "safari"
    cookies_file: str | None = None  # Path to cookies.txt (Netscape format)
    player_client: str | None = None  # e.g., "web", "android", "ios", "tv"


@dataclass
class Config:
    """Main configuration container."""
    languages: list[str] = field(default_factory=lambda: ["en"])
    output: OutputConfig = field(default_factory=OutputConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from a dictionary (parsed YAML)."""
        languages = data.get("languages", ["en"])
        
        # Parse output config
        output_data = data.get("output", {})
        log_file_str = output_data.get("log_file")
        log_file = expand_path(log_file_str) if log_file_str else None
        filename_date = output_data.get("filename_date", "upload")
        if filename_date not in ("upload", "request", "none"):
            raise ValueError(
                f"output.filename_date must be 'upload', 'request', or 'none', got '{filename_date}'"
            )
        article_metadata = output_data.get("article_metadata", "frontmatter")
        if article_metadata not in ("frontmatter", "header", "footer", "none"):
            raise ValueError(
                f"output.article_metadata must be 'frontmatter', 'header', 'footer', or 'none', got '{article_metadata}'"
            )
        output = OutputConfig(
            format=output_data.get("format", "srt"),
            pipe_mode=output_data.get("pipe_mode", False),
            log_file=log_file,
            filename_date=filename_date,
            article_metadata=article_metadata,
        )
        
        # Parse storage config
        storage_data = data.get("storage", {})
        storage = StorageConfig(
            audio_dir=expand_path(storage_data.get("audio_dir", "~/YouTube Subtitles/Audio")),
            transcript_dir=expand_path(storage_data.get("transcript_dir", "~/YouTube Subtitles/Transcripts")),
            article_dir=expand_path(storage_data.get("article_dir", "~/YouTube Subtitles/Articles")),
        )
        
        # Parse transcription config
        transcription_data = data.get("transcription", {})
        transcription = TranscriptionConfig(
            base_url=transcription_data.get("base_url", "https://api.openai.com/v1/audio/transcriptions"),
            model=transcription_data.get("model", "whisper-1"),
            api_key_env=transcription_data.get("api_key_env", "OPENAI_API_KEY"),
        )
        
        # Parse LLM config
        llm_data = data.get("llm", {})
        llm = LLMConfig(
            base_url=llm_data.get("base_url", "https://api.openai.com/v1/chat/completions"),
            model=llm_data.get("model", "gpt-4o"),
            api_key_env=llm_data.get("api_key_env", "OPENAI_API_KEY"),
        )
        
        # Parse YouTube config
        youtube_data = data.get("youtube", {})
        cookies_from_browser = youtube_data.get("cookies_from_browser")
        
        # Validate cookies_from_browser is a browser name, not a boolean
        if cookies_from_browser is True:
            raise ValueError(
                "youtube.cookies_from_browser must be a browser name (e.g., 'chrome', 'firefox', 'safari'), "
                "not 'true'. Example: cookies_from_browser: chrome"
            )
        if cookies_from_browser is not None and not isinstance(cookies_from_browser, str):
            raise ValueError(
                f"youtube.cookies_from_browser must be a string, got {type(cookies_from_browser).__name__}"
            )
        
        youtube = YouTubeConfig(
            cookies_from_browser=cookies_from_browser,
            cookies_file=youtube_data.get("cookies_file"),
            player_client=youtube_data.get("player_client"),
        )
        
        return cls(
            languages=languages,
            output=output,
            storage=storage,
            transcription=transcription,
            llm=llm,
            youtube=youtube,
        )
    
    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "Config":
        """
        Load configuration from a YAML file.
        
        Falls back to defaults if the file doesn't exist.
        """
        if config_path is None:
            config_path = expand_path(str(DEFAULT_CONFIG_PATH))
        else:
            config_path = expand_path(str(config_path))
        
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            return cls.from_dict(data)
        
        # Return default config if file doesn't exist
        return cls()
    
    def ensure_directories(self) -> None:
        """Create storage directories if they don't exist."""
        self.storage.audio_dir.mkdir(parents=True, exist_ok=True)
        self.storage.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.storage.article_dir.mkdir(parents=True, exist_ok=True)