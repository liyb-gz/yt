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
class Config:
    """Main configuration container."""
    languages: list[str] = field(default_factory=lambda: ["en"])
    storage: StorageConfig = field(default_factory=StorageConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from a dictionary (parsed YAML)."""
        languages = data.get("languages", ["en"])
        
        # Parse storage config
        storage_data = data.get("storage", {})
        storage = StorageConfig(
            audio_dir=expand_path(storage_data.get("audio_dir", "~/YouTube Subtitles/Audio")),
            transcript_dir=expand_path(storage_data.get("transcript_dir", "~/YouTube Subtitles/Transcripts")),
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
        
        return cls(
            languages=languages,
            storage=storage,
            transcription=transcription,
            llm=llm,
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
