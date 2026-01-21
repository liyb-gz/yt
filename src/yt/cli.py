"""Command-line interface for yt."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.syntax import Syntax

from yt import __version__
from yt.config import Config, DEFAULT_CONFIG_PATH
from yt.formatter import OutputFormat
from yt.transcript import process_video
from yt.utils import parse_language_codes, expand_path
from yt.youtube import YouTubeClient


console = Console()
logger = logging.getLogger("yt")


def setup_logging(log_file: Path | None, verbose: bool = False) -> None:
    """
    Set up logging to file and console.
    
    Args:
        log_file: Path to log file (None = no file logging)
        verbose: Enable verbose console output
    """
    # Set root logger level
    logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # File handler (always verbose if configured)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Log session start
        logger.info("=" * 60)
        logger.info(f"yt v{__version__} - Session started")
        logger.info(f"Command: {' '.join(sys.argv)}")
        logger.info("=" * 60)


class LoggingConsole(Console):
    """Console wrapper that also logs output to file."""
    
    def print(self, *objects, **kwargs) -> None:
        """Print to console and log to file."""
        super().print(*objects, **kwargs)
        
        # Also log to file (strip rich markup for clean logs)
        if logger.handlers:
            # Convert objects to plain text
            from io import StringIO
            temp_console = Console(file=StringIO(), force_terminal=False, no_color=True)
            temp_console.print(*objects, **kwargs)
            text = temp_console.file.getvalue().strip()
            if text:
                logger.info(text)


DEFAULT_CONFIG_CONTENT = """\
# yt configuration file
# See: https://github.com/your-repo/yt for documentation

# Target languages for transcripts (will try to fetch or translate to these)
languages:
  - en
  - ja

# Output settings
output:
  format: srt          # srt, vtt, or txt
  pipe_mode: false     # When true, output transcript to stdout for piping
  # log_file: "~/YouTube Subtitles/yt.log"  # Log file path (verbose logs always written here)

# Output directories (~ is expanded)
storage:
  audio_dir: "~/YouTube Subtitles/Audio"
  transcript_dir: "~/YouTube Subtitles/Transcripts"
  article_dir: "~/YouTube Subtitles/Articles"

# YouTube/yt-dlp settings
youtube:
  # cookies_from_browser: chrome    # Browser to extract cookies from (chrome, firefox, safari, etc.)
  # cookies_file: ~/cookies.txt     # Path to cookies.txt (Netscape format)
  # player_client: web              # Force YouTube client: web, android, ios, tv

# OpenAI-compatible Whisper API (used when YouTube captions unavailable)
transcription:
  base_url: https://api.openai.com/v1/audio/transcriptions
  model: whisper-1
  api_key_env: OPENAI_API_KEY

# OpenAI-compatible Chat API for translation (used when source != target language)
llm:
  base_url: https://api.openai.com/v1/chat/completions
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
"""


def build_main_parser() -> argparse.ArgumentParser:
    """Build the main argument parser for URL processing."""
    parser = argparse.ArgumentParser(
        prog="yt",
        description="Download YouTube subtitles with intelligent fallbacks and optional translation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yt "https://www.youtube.com/watch?v=VIDEO_ID"
  yt "URL1" "URL2" "URL3"
  yt --input urls.txt
  yt "URL" --languages en,ja,ko
  yt "URL" --pipe | other-tool
  yt config show
  yt config init
        """,
    )
    
    parser.add_argument(
        "urls",
        nargs="*",
        help="YouTube URLs to process",
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    
    parser.add_argument(
        "--input", "-i",
        dest="input_file",
        type=Path,
        help="File containing URLs, one per line",
    )
    
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.yaml (default: ~/.config/yt/config.yaml)",
    )
    
    parser.add_argument(
        "--format", "-f",
        dest="output_format",
        choices=["srt", "vtt", "txt", "article"],
        help="Output format: srt, vtt, txt, or article (default: from config or srt)",
    )
    
    parser.add_argument(
        "--length",
        choices=["original", "long", "medium", "short"],
        default="original",
        help="Article length (only used with --format article): original, long, medium, short",
    )
    
    parser.add_argument(
        "--languages", "-l",
        help="Comma-separated target languages (e.g., en,ja,ko)",
    )
    
    parser.add_argument(
        "--pipe", "-p",
        action="store_true",
        help="Pipe mode: output transcript to stdout (for piping to other tools)",
    )
    
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save transcript files (only useful with --pipe)",
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files",
    )
    
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Skip translation; save only source language",
    )
    
    parser.add_argument(
        "--discard-audio",
        action="store_true",
        help="Delete audio file after Whisper transcription",
    )
    
    parser.add_argument(
        "--cookies",
        type=Path,
        help="Path to cookies.txt (Netscape format)",
    )
    
    parser.add_argument(
        "--cookies-from-browser",
        help="Browser to extract cookies from (e.g., chrome, firefox, safari)",
    )
    
    parser.add_argument(
        "--player-client",
        choices=["web", "android", "ios", "tv"],
        help="Force YouTube client: web, android, ios, tv",
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output for debugging",
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (reserved for future)",
    )
    
    return parser


def build_config_parser() -> argparse.ArgumentParser:
    """Build the config subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="yt config",
        description="Manage yt configuration",
    )
    
    subparsers = parser.add_subparsers(dest="config_command", help="Config commands")
    
    # config show
    show_parser = subparsers.add_parser(
        "show",
        help="Display current configuration (or defaults if not configured)",
    )
    show_parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.yaml",
    )
    
    # config init
    init_parser = subparsers.add_parser(
        "init",
        help="Create a new configuration file with defaults",
    )
    init_parser.add_argument(
        "--config",
        type=Path,
        help="Path to create config.yaml (default: ~/.config/yt/config.yaml)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config file",
    )
    
    return parser


def cmd_config_show(args: argparse.Namespace) -> int:
    """Handle 'config show' command."""
    config_path = expand_path(str(args.config)) if args.config else expand_path(str(DEFAULT_CONFIG_PATH))
    
    if config_path.exists():
        console.print(f"[bold green]Configuration file:[/bold green] {config_path}")
        console.print()
        content = config_path.read_text()
        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
        console.print(syntax)
    else:
        console.print(f"[yellow]No configuration file found at:[/yellow] {config_path}")
        console.print()
        console.print("[bold]Using default configuration:[/bold]")
        console.print()
        
        # Display defaults as YAML
        config = Config()
        defaults = {
            "languages": config.languages,
            "output": {
                "format": config.output.format,
                "pipe_mode": config.output.pipe_mode,
                "log_file": str(config.output.log_file) if config.output.log_file else None,
            },
            "storage": {
                "audio_dir": str(config.storage.audio_dir),
                "transcript_dir": str(config.storage.transcript_dir),
                "article_dir": str(config.storage.article_dir),
            },
            "youtube": {
                "cookies_from_browser": config.youtube.cookies_from_browser,
                "cookies_file": config.youtube.cookies_file,
                "player_client": config.youtube.player_client,
            },
            "transcription": {
                "base_url": config.transcription.base_url,
                "model": config.transcription.model,
                "api_key_env": config.transcription.api_key_env,
            },
            "llm": {
                "base_url": config.llm.base_url,
                "model": config.llm.model,
                "api_key_env": config.llm.api_key_env,
            },
        }
        yaml_content = yaml.dump(defaults, default_flow_style=False, sort_keys=False)
        syntax = Syntax(yaml_content, "yaml", theme="monokai", line_numbers=True)
        console.print(syntax)
        
        console.print()
        console.print(f"[dim]Run 'yt config init' to create a config file at {DEFAULT_CONFIG_PATH}[/dim]")
    
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    """Handle 'config init' command."""
    config_path = expand_path(str(args.config)) if args.config else expand_path(str(DEFAULT_CONFIG_PATH))
    
    if config_path.exists() and not args.force:
        console.print(f"[yellow]Configuration file already exists:[/yellow] {config_path}")
        console.print("[dim]Use --force to overwrite[/dim]")
        return 1
    
    # Create parent directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write default config
    config_path.write_text(DEFAULT_CONFIG_CONTENT)
    
    console.print(f"[bold green]Created configuration file:[/bold green] {config_path}")
    console.print()
    console.print("Edit this file to customize your settings:")
    console.print()
    syntax = Syntax(DEFAULT_CONFIG_CONTENT, "yaml", theme="monokai", line_numbers=True)
    console.print(syntax)
    
    return 0


def collect_urls(args: argparse.Namespace) -> list[str]:
    """Collect URLs from arguments and input file."""
    urls: list[str] = list(args.urls) if args.urls else []
    
    if args.input_file:
        if not args.input_file.exists():
            console.print(f"[red]Error: Input file not found: {args.input_file}[/red]")
            sys.exit(1)
        
        with open(args.input_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    
    return urls


def cmd_process_urls(args: argparse.Namespace) -> int:
    """Handle URL processing (main command)."""
    # Load config first (needed for defaults)
    try:
        config = Config.load(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return 1
    
    # Set up logging (file logging if configured)
    setup_logging(config.output.log_file, verbose=args.verbose)
    
    # Determine pipe mode (flag wins over config)
    pipe_mode = args.pipe if args.pipe else config.output.pipe_mode
    save_files = not args.no_save
    
    # Create console with logging support
    # In pipe mode: stderr + quiet (no output), file logging still works
    # Normal mode: LoggingConsole that writes to both console and log file
    if pipe_mode:
        status_console = Console(stderr=True, quiet=True)
    elif config.output.log_file:
        status_console = LoggingConsole()
    else:
        status_console = console
    
    # Collect URLs
    urls = collect_urls(args)
    if not urls:
        status_console.print("[red]Error: No URLs provided. Use positional arguments or --input file.[/red]")
        if not pipe_mode:
            status_console.print("[dim]Run 'yt --help' for usage information.[/dim]")
        return 1
    
    # Override languages if specified (flag wins over config)
    if args.languages:
        languages = parse_language_codes(args.languages)
    else:
        languages = config.languages
    
    if not languages:
        status_console.print("[red]Error: No target languages specified.[/red]")
        return 1
    
    # Ensure output directories exist (only if saving files)
    if save_files:
        config.ensure_directories()
    
    # Parse output format (flag wins over config)
    format_str = args.output_format if args.output_format else config.output.format
    output_format = OutputFormat.from_string(format_str)
    
    # Create YouTube client (CLI flags override config)
    cookies_file = str(args.cookies) if args.cookies else config.youtube.cookies_file
    cookies_from_browser = args.cookies_from_browser or config.youtube.cookies_from_browser
    player_client = args.player_client or config.youtube.player_client
    
    youtube = YouTubeClient(
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        player_client=player_client,
        verbose=args.verbose and not pipe_mode,  # Suppress verbose in pipe mode
    )
    
    # Process each URL
    success_count = 0
    error_count = 0
    all_transcripts: list[str] = []  # Collect transcripts for pipe mode
    
    for i, url in enumerate(urls, 1):
        if not pipe_mode:
            status_console.print()
            status_console.print(f"[bold blue]Processing {i}/{len(urls)}:[/bold blue] {url}")
            status_console.print("-" * 60)
        
        try:
            results, transcripts = process_video(
                url=url,
                config=config,
                youtube_client=youtube,
                languages=languages,
                output_format=output_format,
                article_length=args.length,
                no_translate=args.no_translate,
                discard_audio=args.discard_audio,
                force=args.force,
                verbose=args.verbose and not pipe_mode,
                pipe_mode=pipe_mode,
                save_files=save_files,
                status_console=status_console,
            )
            
            if results or transcripts:
                success_count += 1
                if pipe_mode and transcripts:
                    all_transcripts.extend(transcripts)
            else:
                error_count += 1
        except Exception as e:
            status_console.print(f"[red]Error processing {url}: {e}[/red]")
            if args.verbose and not pipe_mode:
                status_console.print_exception()
            error_count += 1
    
    # Output transcripts to stdout in pipe mode
    if pipe_mode and all_transcripts:
        # Join multiple transcripts with separator
        print("\n".join(all_transcripts))
    
    # Summary (only in non-pipe mode)
    if not pipe_mode:
        status_console.print()
        status_console.print("-" * 60)
        status_console.print(f"[bold]Done![/bold] {success_count} succeeded, {error_count} failed")
    
    return 0 if error_count == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]
    
    # Check if this is a config command (handle separately to avoid argparse conflicts)
    if argv and argv[0] == "config":
        config_parser = build_config_parser()
        args = config_parser.parse_args(argv[1:])  # Skip "config"
        
        if args.config_command == "show":
            return cmd_config_show(args)
        elif args.config_command == "init":
            return cmd_config_init(args)
        else:
            # No config subcommand specified
            console.print("[yellow]Usage: yt config {show|init}[/yellow]")
            console.print()
            console.print("  show  - Display current configuration (or defaults)")
            console.print("  init  - Create a new configuration file")
            return 1
    else:
        # Main command: process URLs
        main_parser = build_main_parser()
        args = main_parser.parse_args(argv)
        return cmd_process_urls(args)


if __name__ == "__main__":
    sys.exit(main())
