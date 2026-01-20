"""OpenAI-compatible Whisper transcription API client."""

from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class TranscriptionResult:
    """Result from Whisper transcription."""
    text: str
    language: str | None = None
    segments: list[dict] | None = None


class WhisperClient:
    """
    Generic OpenAI-compatible Whisper transcription client.
    
    Works with:
    - OpenAI's Whisper API
    - Fireworks AI
    - Groq
    - Any OpenAI-compatible audio transcription endpoint
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "whisper-1",
        timeout: float = 300.0,  # 5 minutes for large files
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
    
    def transcribe(
        self,
        audio_path: Path,
        response_format: str = "verbose_json",
        language: str | None = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.
        
        Args:
            audio_path: Path to the audio file
            response_format: Output format ('json', 'text', 'srt', 'vtt', 'verbose_json')
            language: Optional language hint (ISO 639-1 code)
        
        Returns:
            TranscriptionResult with text and optional segments
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        # Build form data
        data = {
            "model": self.model,
            "response_format": response_format,
        }
        
        if language:
            data["language"] = language
        
        # Read audio file
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, self._get_mime_type(audio_path))}
            
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.base_url,
                    headers=headers,
                    data=data,
                    files=files,
                )
        
        response.raise_for_status()
        
        # Parse response based on format
        if response_format == "text":
            return TranscriptionResult(text=response.text)
        elif response_format in ("srt", "vtt"):
            return TranscriptionResult(text=response.text)
        else:
            # JSON or verbose_json
            result = response.json()
            return TranscriptionResult(
                text=result.get("text", ""),
                language=result.get("language"),
                segments=result.get("segments"),
            )
    
    def transcribe_to_srt(self, audio_path: Path, language: str | None = None) -> str:
        """Transcribe audio file and return SRT format."""
        result = self.transcribe(audio_path, response_format="srt", language=language)
        return result.text
    
    def transcribe_to_vtt(self, audio_path: Path, language: str | None = None) -> str:
        """Transcribe audio file and return VTT format."""
        result = self.transcribe(audio_path, response_format="vtt", language=language)
        return result.text
    
    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe audio file with detailed timestamp segments."""
        return self.transcribe(audio_path, response_format="verbose_json", language=language)
    
    @staticmethod
    def _get_mime_type(path: Path) -> str:
        """Get MIME type for audio file."""
        mime_types = {
            ".mp3": "audio/mpeg",
            ".mp4": "audio/mp4",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".opus": "audio/opus",
        }
        return mime_types.get(path.suffix.lower(), "audio/mpeg")


def segments_to_srt(segments: list[dict]) -> str:
    """Convert Whisper segments to SRT format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_timestamp_srt(seg["start"])
        end = _format_timestamp_srt(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def segments_to_vtt(segments: list[dict]) -> str:
    """Convert Whisper segments to VTT format."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = _format_timestamp_vtt(seg["start"])
        end = _format_timestamp_vtt(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _format_timestamp_srt(seconds: float) -> str:
    """Format seconds to SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Format seconds to VTT timestamp (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
