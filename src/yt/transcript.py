"""Transcript fetching with intelligent fallback chain."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rich.console import Console

from yt.config import Config
from yt.formatter import OutputFormat, convert_format, parse_srt, parse_vtt, format_srt
from yt.translate import TranslationClient, TranslationError
from yt.whisper import WhisperClient, segments_to_srt
from yt.youtube import YouTubeClient, VideoMetadata
from yt.utils import format_output_filename, format_audio_filename, format_article_with_metadata


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
        status_console: Console | None = None,
    ):
        self.config = config
        self.youtube = youtube_client
        self.verbose = verbose
        self.status_console = status_console or console
        self._whisper_client: WhisperClient | None = None
        self._translation_client: TranslationClient | None = None
        # Cache for Whisper transcription results (keyed by video ID)
        self._whisper_cache: dict[str, tuple[str, str]] = {}  # video_id -> (srt_content, language)
    
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
        # Step 1: Try to get transcript directly in target language (prefer official)
        if self.verbose:
            console.print(f"[dim]Trying transcript in {target_language}...[/dim]")
        
        result = self._try_youtube_transcript(url, target_language, prefer_official=True)
        if result:
            content, is_automatic = result
            method = "auto-generated" if is_automatic else "official"
            if self.verbose:
                console.print(f"[green]✓ Found {method} transcript in {target_language}[/green]")
            return self._format_result(content, target_language, output_format, method)
        
        # Step 3: If translation is allowed, try getting transcript in source language
        if not no_translate:
            source_result = self._try_any_youtube_transcript(url, metadata)
            if source_result:
                content, source_lang, method = source_result
                self.status_console.print(
                    f"[yellow]🌐 Found {method} transcript in {source_lang}, translating to {target_language}...[/yellow]"
                )
                try:
                    translated = self._translate_content(content, source_lang, target_language)
                    self.status_console.print(f"[green]✓ Translation complete[/green]")
                    return self._format_result(translated, target_language, output_format, f"{method}+translated")
                except TranslationError as e:
                    self.status_console.print(f"[red]✗ Translation failed: {e}[/red]")
                    # Fall through to Whisper as last resort
        
        # Step 4: Whisper transcription as last resort
        if self.verbose:
            console.print("[yellow]No YouTube captions available, using Whisper transcription...[/yellow]")
        
        whisper_result = self._whisper_transcribe(url, metadata, discard_audio)
        if whisper_result:
            content, source_lang = whisper_result
            
            # Translate if needed and allowed
            if source_lang != target_language and not no_translate:
                self.status_console.print(f"[yellow]🌐 Translating from {source_lang} to {target_language}...[/yellow]")
                try:
                    content = self._translate_content(content, source_lang, target_language)
                    self.status_console.print(f"[green]✓ Translation complete[/green]")
                    return self._format_result(content, target_language, output_format, "whisper+translated")
                except TranslationError as e:
                    self.status_console.print(f"[red]✗ Translation failed: {e}[/red]")
                    return None
            
            return self._format_result(content, source_lang, output_format, "whisper")
        
        return None
    
    def _try_youtube_transcript(
        self,
        url: str,
        language: str,
        prefer_official: bool,
    ) -> tuple[str, bool] | None:
        """
        Try to get YouTube transcript in specific language.
        
        Returns (content, is_automatic) or None.
        """
        result = self.youtube.get_subtitle_content(url, language, prefer_official)
        if result:
            return result  # (content, is_automatic)
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
        
        # Fall back to auto-generated, but only try common languages to avoid rate limiting
        # YouTube auto-generates captions in many languages; we prioritize widely-used ones
        preferred_auto_langs = ["en", "en-US", "en-GB",  "zh", "zh-Hans", "zh-Hant", "ja", "ko", "es", "fr", "de", "pt",]
        available_auto = list(metadata.automatic_captions.keys())
        
        # Try preferred languages first, then fall back to first available
        langs_to_try = [l for l in preferred_auto_langs if l in available_auto]
        if not langs_to_try and available_auto:
            langs_to_try = available_auto[:1]  # Just try the first one
        
        for lang in langs_to_try:
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
        
        Uses cache to avoid re-transcribing the same video for multiple languages.
        
        Returns (srt_content, detected_language) or None.
        """
        # Check cache first (avoid re-transcribing for multiple languages)
        if metadata.id in self._whisper_cache:
            if self.verbose:
                self.status_console.print("[dim]Using cached Whisper transcription[/dim]")
            return self._whisper_cache[metadata.id]
        
        try:
            # Download audio
            self.status_console.print("[yellow]⬇ Downloading audio for Whisper transcription...[/yellow]")
            
            # Determine audio filename date prefix
            filename_date_mode = self.config.output.filename_date
            if filename_date_mode == "upload":
                audio_date_prefix: str | None = metadata.upload_date
            elif filename_date_mode == "request":
                audio_date_prefix = date.today().strftime("%Y-%m-%d")
            else:  # "none"
                audio_date_prefix = None
            
            audio_filename = format_audio_filename(
                metadata.title,
                date_prefix=audio_date_prefix,
            )
            audio_path = self.youtube.download_audio(
                url,
                self.config.storage.audio_dir,
                audio_filename,
            )
            
            if self.verbose:
                self.status_console.print(f"[dim]Downloaded audio to {audio_path}[/dim]")
            
            # Transcribe via Whisper API
            self.status_console.print("[yellow]🎤 Sending audio to Whisper API for transcription...[/yellow]")
            result = self.whisper_client.transcribe_with_timestamps(audio_path)
            
            # Convert to SRT
            if result.segments:
                srt_content = segments_to_srt(result.segments)
            else:
                # If no segments, create a single-entry SRT
                srt_content = f"1\n00:00:00,000 --> 99:59:59,999\n{result.text}\n"
            
            detected_lang = result.language or "en"
            self.status_console.print(f"[green]✓ Whisper transcription complete (detected: {detected_lang})[/green]")
            
            # Cache the result for other languages
            self._whisper_cache[metadata.id] = (srt_content, detected_lang)
            
            # Clean up audio if requested
            if discard_audio and audio_path.exists():
                audio_path.unlink()
                if self.verbose:
                    self.status_console.print("[dim]Deleted audio file[/dim]")
            
            return (srt_content, detected_lang)
        except Exception as e:
            self.status_console.print(f"[red]✗ Whisper transcription failed: {e}[/red]")
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
    article_length: str = "original",
    no_translate: bool = False,
    discard_audio: bool = False,
    force: bool = False,
    verbose: bool = False,
    pipe_mode: bool = False,
    save_files: bool = True,
    status_console: Console | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """
    Process a single video: fetch transcripts for all target languages.
    
    Args:
        url: YouTube video URL
        config: Configuration
        youtube_client: YouTube client
        languages: Target languages
        output_format: Output format
        article_length: Article length (for article format): original, long, medium, short
        no_translate: Skip translation
        discard_audio: Delete audio after Whisper
        force: Overwrite existing files
        verbose: Enable verbose output
        pipe_mode: If True, suppress status output (for piping)
        save_files: If True, save transcript files
        status_console: Optional console for output (with logging support)
    
    Returns:
        Tuple of (dict mapping language to output file path, list of transcript contents)
    """
    from rich.console import Console
    
    # Use provided console, or create one based on mode
    if status_console is None:
        if pipe_mode:
            status_console = Console(stderr=True, quiet=True)
        else:
            status_console = console
    
    fetcher = TranscriptFetcher(
        config,
        youtube_client,
        verbose=verbose and not pipe_mode,
        status_console=status_console,
    )
    
    # Get video metadata
    if verbose and not pipe_mode:
        status_console.print(f"[bold]Fetching metadata for {url}[/bold]")
    metadata = youtube_client.get_metadata(url)
    
    if not pipe_mode:
        status_console.print(f"[bold]{metadata.title}[/bold]")
        status_console.print(f"[dim]Uploaded: {metadata.upload_date}, Duration: {metadata.duration}s[/dim]")
    
    # Determine filename date prefix based on config
    filename_date_mode = config.output.filename_date
    if filename_date_mode == "upload":
        date_prefix: str | None = metadata.upload_date
    elif filename_date_mode == "request":
        date_prefix = date.today().strftime("%Y-%m-%d")
    else:  # "none"
        date_prefix = None
    
    results: dict[str, Path] = {}
    transcripts: list[str] = []  # For pipe mode output
    
    # Determine if this is article mode
    is_article_mode = output_format == OutputFormat.ARTICLE
    
    for lang in languages:
        # For article mode, use .md extension and article_dir
        if is_article_mode:
            output_filename = format_output_filename(
                metadata.title,
                lang,
                "md",
                date_prefix=date_prefix,
            )
            output_path = config.storage.article_dir / output_filename
        else:
            output_filename = format_output_filename(
                metadata.title,
                lang,
                output_format.value,
                date_prefix=date_prefix,
            )
            output_path = config.storage.transcript_dir / output_filename
        
        # Check if file already exists (only matters if saving)
        if save_files and output_path.exists() and not force:
            if not pipe_mode:
                safe_name = output_path.name.replace("[", r"\[")
                status_console.print(f"[yellow]Skipping {lang}: {safe_name} already exists[/yellow]")
            # Still read content for pipe mode (only first language)
            if pipe_mode and not transcripts:
                transcripts.append(output_path.read_text(encoding="utf-8"))
            results[lang] = output_path
            continue
        
        # Fetch transcript
        if not pipe_mode:
            if is_article_mode:
                status_console.print(f"[cyan]Fetching transcript for article in {lang}...[/cyan]")
            else:
                status_console.print(f"[cyan]Fetching transcript in {lang}...[/cyan]")
        
        # For article mode: get source transcript without translation, then generate article in target language
        # This uses 1 LLM call instead of 2 (translate + article → just article with language instruction)
        if is_article_mode:
            # First try to get any available YouTube transcript (without translation)
            source_result = fetcher._try_any_youtube_transcript(url, metadata)
            
            if source_result:
                raw_content, source_lang, method = source_result
                # Convert to plain text format
                source_content = fetcher._format_result(raw_content, source_lang, OutputFormat.TXT, method).content
            else:
                # Fall back to Whisper if no YouTube captions available
                if not pipe_mode:
                    status_console.print("[yellow]No YouTube captions, falling back to Whisper...[/yellow]")
                whisper_result = fetcher._whisper_transcribe(url, metadata, discard_audio)
                if whisper_result:
                    raw_content, source_lang = whisper_result
                    source_content = fetcher._format_result(raw_content, source_lang, OutputFormat.TXT, "whisper").content
                    method = "whisper"
                else:
                    if not pipe_mode:
                        status_console.print(f"[red]✗ Failed to get transcript for article[/red]")
                    continue
            
            # Generate article in target language (1 LLM call handles both translation + article)
            if not pipe_mode:
                length_info = "" if article_length == "original" else f", length: {article_length}"
                if source_lang != lang:
                    status_console.print(f"[yellow]📝 Generating {lang} article from {source_lang} {method} transcript{length_info}...[/yellow]")
                else:
                    status_console.print(f"[yellow]📝 Generating article from {method} transcript{length_info}...[/yellow]")
            try:
                content = fetcher.translation_client.generate_article(
                    source_content,
                    language=lang,
                    length=article_length,
                )
                
                # Add metadata based on config setting
                content = format_article_with_metadata(
                    content=content,
                    title=metadata.title,
                    author=metadata.uploader,
                    video_id=metadata.id,
                    upload_date=metadata.upload_date,
                    request_date=date.today().strftime("%Y-%m-%d"),
                    style=config.output.article.metadata,
                )
                
                if source_lang != lang:
                    method = f"{method}+article({source_lang}→{lang})"
                else:
                    method = f"{method}+article"
                if not pipe_mode:
                    status_console.print(f"[green]✓ Article generated[/green]")
            except Exception as e:
                if not pipe_mode:
                    status_console.print(f"[red]✗ Article generation failed: {e}[/red]")
                continue
        else:
            # Normal mode: fetch transcript with translation if needed
            result = fetcher.fetch_transcript(
                url,
                metadata,
                lang,
                output_format,
                no_translate,
                discard_audio,
            )
            
            if not result:
                if not pipe_mode:
                    status_console.print(f"[red]✗ Failed to get transcript in {lang}[/red]")
                continue
            
            content = result.content
            method = result.method
        
        # Collect for pipe mode (only first language)
        if pipe_mode and not transcripts:
            transcripts.append(content)
        
        # Save file (if enabled)
        if save_files:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            if not pipe_mode:
                # Escape brackets in filename to prevent Rich from interpreting [en] as markup
                safe_name = output_path.name.replace("[", r"\[")
                status_console.print(f"[green]✓ Saved: {safe_name} ({method})[/green]")
        results[lang] = output_path
    
    return results, transcripts
