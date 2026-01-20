"""Transcript fetching with intelligent fallback chain."""

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from yt.config import Config
from yt.formatter import OutputFormat, convert_format, parse_srt, parse_vtt, format_srt
from yt.translate import TranslationClient
from yt.whisper import WhisperClient, segments_to_srt
from yt.youtube import YouTubeClient, VideoMetadata
from yt.utils import format_output_filename, format_audio_filename


console = Console()


@dataclass
class TranscriptResult:
    """Result of transcript fetching."""
    content: str
    source_language: str
    format: OutputFormat
    method: str  # "official", "auto-generated", or "whisper"


class TranscriptFetcher:
    """
    Fetches transcripts using fallback chain:
    1. Official YouTube transcript
    2. Auto-generated YouTube captions
    3. Whisper transcription (download audio, transcribe via API)
    """
    
    def __init__(
        self,
        config: Config,
        youtube_client: YouTubeClient,
        verbose: bool = False,
    ):
        self.config = config
        self.youtube = youtube_client
        self.verbose = verbose
        self._whisper_client: WhisperClient | None = None
        self._translation_client: TranslationClient | None = None
    
    @property
    def whisper_client(self) -> WhisperClient:
        """Lazy-load Whisper client."""
        if self._whisper_client is None:
            api_key = self.config.transcription.api_key
            if not api_key:
                raise ValueError(
                    f"Whisper API key not found. Set {self.config.transcription.api_key_env} environment variable."
                )
            self._whisper_client = WhisperClient(
                base_url=self.config.transcription.base_url,
                api_key=api_key,
                model=self.config.transcription.model,
            )
        return self._whisper_client
    
    @property
    def translation_client(self) -> TranslationClient:
        """Lazy-load translation client."""
        if self._translation_client is None:
            api_key = self.config.llm.api_key
            if not api_key:
                raise ValueError(
                    f"LLM API key not found. Set {self.config.llm.api_key_env} environment variable."
                )
            self._translation_client = TranslationClient(
                base_url=self.config.llm.base_url,
                api_key=api_key,
                model=self.config.llm.model,
            )
        return self._translation_client
    
    def fetch_transcript(
        self,
        url: str,
        metadata: VideoMetadata,
        target_language: str,
        output_format: OutputFormat = OutputFormat.SRT,
        no_translate: bool = False,
        discard_audio: bool = False,
    ) -> TranscriptResult | None:
        """
        Fetch transcript for a video in the target language.
        
        Uses fallback chain:
        1. Try official transcript in target language
        2. Try auto-generated captions in target language
        3. Try official/auto in any language, then translate
        4. Download audio and transcribe via Whisper, then translate if needed
        
        Args:
            url: YouTube video URL
            metadata: Video metadata (pre-fetched)
            target_language: Desired output language
            output_format: Desired output format (SRT, VTT, TXT)
            no_translate: If True, skip translation step
            discard_audio: If True, delete audio file after transcription
        
        Returns:
            TranscriptResult or None if all methods fail
        """
        # Step 1: Try to get transcript directly in target language
        if self.verbose:
            console.print(f"[dim]Trying official transcript in {target_language}...[/dim]")
        
        result = self._try_youtube_transcript(url, target_language, prefer_official=True)
        if result:
            if self.verbose:
                console.print(f"[green]✓ Found official transcript in {target_language}[/green]")
            return self._format_result(result, target_language, output_format, "official")
        
        # Step 2: Try auto-generated in target language
        if self.verbose:
            console.print(f"[dim]Trying auto-generated captions in {target_language}...[/dim]")
        
        result = self._try_youtube_transcript(url, target_language, prefer_official=False)
        if result:
            if self.verbose:
                console.print(f"[green]✓ Found auto-generated captions in {target_language}[/green]")
            return self._format_result(result, target_language, output_format, "auto-generated")
        
        # Step 3: If translation is allowed, try getting transcript in source language
        if not no_translate:
            source_result = self._try_any_youtube_transcript(url, metadata)
            if source_result:
                content, source_lang, method = source_result
                if self.verbose:
                    console.print(
                        f"[yellow]Found {method} transcript in {source_lang}, translating to {target_language}...[/yellow]"
                    )
                translated = self._translate_content(content, source_lang, target_language)
                return self._format_result(translated, target_language, output_format, f"{method}+translated")
        
        # Step 4: Whisper transcription as last resort
        if self.verbose:
            console.print("[yellow]No YouTube captions available, using Whisper transcription...[/yellow]")
        
        whisper_result = self._whisper_transcribe(url, metadata, discard_audio)
        if whisper_result:
            content, source_lang = whisper_result
            
            # Translate if needed and allowed
            if source_lang != target_language and not no_translate:
                if self.verbose:
                    console.print(f"[yellow]Translating from {source_lang} to {target_language}...[/yellow]")
                content = self._translate_content(content, source_lang, target_language)
                return self._format_result(content, target_language, output_format, "whisper+translated")
            
            return self._format_result(content, source_lang, output_format, "whisper")
        
        return None
    
    def _try_youtube_transcript(
        self,
        url: str,
        language: str,
        prefer_official: bool,
    ) -> str | None:
        """Try to get YouTube transcript in specific language."""
        result = self.youtube.get_subtitle_content(url, language, prefer_official)
        if result:
            return result[0]  # Return content, ignore is_automatic flag
        return None
    
    def _try_any_youtube_transcript(
        self,
        url: str,
        metadata: VideoMetadata,
    ) -> tuple[str, str, str] | None:
        """
        Try to get any available YouTube transcript.
        
        Returns (content, language, method) or None.
        """
        # Prefer official transcripts
        for lang in metadata.subtitles.keys():
            result = self.youtube.get_subtitle_content(url, lang, prefer_official=True)
            if result:
                return (result[0], lang, "official")
        
        # Fall back to auto-generated
        for lang in metadata.automatic_captions.keys():
            result = self.youtube.get_subtitle_content(url, lang, prefer_official=False)
            if result:
                return (result[0], lang, "auto-generated")
        
        return None
    
    def _whisper_transcribe(
        self,
        url: str,
        metadata: VideoMetadata,
        discard_audio: bool,
    ) -> tuple[str, str] | None:
        """
        Download audio and transcribe via Whisper.
        
        Returns (srt_content, detected_language) or None.
        """
        try:
            # Download audio
            audio_filename = format_audio_filename(metadata.title, metadata.upload_date)
            audio_path = self.youtube.download_audio(
                url,
                self.config.storage.audio_dir,
                audio_filename,
            )
            
            if self.verbose:
                console.print(f"[dim]Downloaded audio to {audio_path}[/dim]")
            
            # Transcribe
            result = self.whisper_client.transcribe_with_timestamps(audio_path)
            
            # Convert to SRT
            if result.segments:
                srt_content = segments_to_srt(result.segments)
            else:
                # If no segments, create a single-entry SRT
                srt_content = f"1\n00:00:00,000 --> 99:59:59,999\n{result.text}\n"
            
            detected_lang = result.language or "en"
            
            # Clean up audio if requested
            if discard_audio and audio_path.exists():
                audio_path.unlink()
                if self.verbose:
                    console.print("[dim]Deleted audio file[/dim]")
            
            return (srt_content, detected_lang)
        except Exception as e:
            if self.verbose:
                console.print(f"[red]Whisper transcription failed: {e}[/red]")
            return None
    
    def _translate_content(
        self,
        content: str,
        source_language: str,
        target_language: str,
    ) -> str:
        """Translate subtitle content to target language."""
        return self.translation_client.translate_srt(content, source_language, target_language)
    
    def _format_result(
        self,
        content: str,
        language: str,
        target_format: OutputFormat,
        method: str,
    ) -> TranscriptResult:
        """Format content to the desired output format."""
        # Detect source format (usually VTT from YouTube, SRT from Whisper)
        if content.strip().startswith("WEBVTT"):
            source_format = OutputFormat.VTT
        else:
            source_format = OutputFormat.SRT
        
        # Convert if needed
        if source_format != target_format:
            content = convert_format(content, source_format, target_format)
        
        return TranscriptResult(
            content=content,
            source_language=language,
            format=target_format,
            method=method,
        )


def process_video(
    url: str,
    config: Config,
    youtube_client: YouTubeClient,
    languages: list[str],
    output_format: OutputFormat = OutputFormat.SRT,
    no_translate: bool = False,
    discard_audio: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> dict[str, Path]:
    """
    Process a single video: fetch transcripts for all target languages.
    
    Args:
        url: YouTube video URL
        config: Configuration
        youtube_client: YouTube client
        languages: Target languages
        output_format: Output format
        no_translate: Skip translation
        discard_audio: Delete audio after Whisper
        force: Overwrite existing files
        verbose: Enable verbose output
    
    Returns:
        Dict mapping language to output file path
    """
    fetcher = TranscriptFetcher(config, youtube_client, verbose)
    
    # Get video metadata
    if verbose:
        console.print(f"[bold]Fetching metadata for {url}[/bold]")
    metadata = youtube_client.get_metadata(url)
    
    console.print(f"[bold]{metadata.title}[/bold]")
    console.print(f"[dim]Uploaded: {metadata.upload_date}, Duration: {metadata.duration}s[/dim]")
    
    results: dict[str, Path] = {}
    
    for lang in languages:
        output_filename = format_output_filename(
            metadata.title,
            metadata.upload_date,
            lang,
            output_format.value,
        )
        output_path = config.storage.transcript_dir / output_filename
        
        # Check if file already exists
        if output_path.exists() and not force:
            console.print(f"[yellow]Skipping {lang}: {output_path.name} already exists[/yellow]")
            results[lang] = output_path
            continue
        
        # Fetch transcript
        console.print(f"[cyan]Fetching transcript in {lang}...[/cyan]")
        result = fetcher.fetch_transcript(
            url,
            metadata,
            lang,
            output_format,
            no_translate,
            discard_audio,
        )
        
        if result:
            # Save transcript
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result.content, encoding="utf-8")
            console.print(f"[green]✓ Saved: {output_path.name} ({result.method})[/green]")
            results[lang] = output_path
        else:
            console.print(f"[red]✗ Failed to get transcript in {lang}[/red]")
    
    return results
