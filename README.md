# yt

A CLI tool to download YouTube subtitles with intelligent fallbacks and optional translation.

## Features

-   **Smart fallback chain**: Official transcripts → Auto-generated captions → Whisper transcription
-   **Whisper control**: Force Whisper for quality, or disable it to avoid API costs
-   **Multi-language support**: Request subtitles in multiple languages simultaneously
-   **Automatic translation**: Translate transcripts to target languages via LLM (OpenAI-compatible)
-   **Flexible output**: SRT, VTT, plain text, or article formats
-   **Pipe mode**: Output to stdout for piping to other tools (like [Fabric](https://github.com/danielmiessler/Fabric))
-   **Batch processing**: Process multiple URLs from command line or file
-   **Cookie support**: Bypass YouTube restrictions using browser cookies
-   **Organized storage**: Auto-naming with video title and upload date
-   **Smart caching**: Whisper results cached to disk for retry resilience

## Installation

```bash
# Install globally with uv
uv tool install .

# Or with pip
pip install .
```

### Dependencies

This tool relies on:

-   **Python 3.11+**
-   **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** – Downloads YouTube audio and extracts metadata (installed automatically)
-   **[ffmpeg](https://ffmpeg.org/)** – Required by yt-dlp for audio extraction

ffmpeg needs to be installed separately via your system package manager:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (with winget)
winget install ffmpeg
```

## Configuration

Initialize a config file:

```bash
yt config init
```

View current configuration (or defaults):

```bash
yt config show
```

The config file is located at `~/.config/yt/config.yaml`:

```yaml
# Target languages for transcripts
languages:
    - en
    - ja

# Output settings
output:
    format: srt # srt, vtt, txt, or article
    filename_date: upload # upload, request (today), or none
    pipe_mode: false # When true, output transcript to stdout for piping
    article:
        length: original # original, long, medium, short
        metadata: frontmatter # frontmatter, header, footer, none

# Output directories (~ is expanded)
storage:
    audio_dir: "~/YouTube Subtitles/Audio"
    transcript_dir: "~/YouTube Subtitles/Transcripts"
    article_dir: "~/YouTube Subtitles/Articles"
    discard_audio: false # Delete audio after Whisper transcription

# Logging
logging:
    file: "~/YouTube Subtitles/yt.log" # Log file path (omit to disable)

# YouTube/yt-dlp settings (optional)
youtube:
    cookies_from_browser: chrome # or firefox, safari, edge, brave
    # cookies_file: ~/cookies.txt   # alternative: path to cookies.txt
    # player_client: web            # force client: web, android, ios, tv

# OpenAI-compatible Whisper API (used when YouTube captions unavailable)
transcription:
    base_url: https://api.openai.com/v1/audio/transcriptions
    model: whisper-1
    api_key_env: OPENAI_API_KEY
    use_whisper: auto # auto (fallback), force (always), never (YouTube only)

# OpenAI-compatible Chat API for translation
llm:
    base_url: https://api.openai.com/v1/chat/completions
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
```

### Environment Variables

Export your API keys before running:

```bash
export OPENAI_API_KEY="your-api-key"
```

## Usage

### Basic Usage

```bash
# Single video
yt "https://www.youtube.com/watch?v=VIDEO_ID"

# Multiple videos
yt "URL1" "URL2" "URL3"

# From a file (one URL per line)
yt --input urls.txt
```

### With Browser Cookies

```bash
# From Chrome
yt "URL" --cookies-from-browser chrome

# From specific Chrome profile
yt "URL" --cookies-from-browser "chrome:Profile 1"

# From Safari or Firefox
yt "URL" --cookies-from-browser safari
yt "URL" --cookies-from-browser firefox

# Or use exported cookies.txt (Netscape format)
yt "URL" --cookies ~/Downloads/cookies.txt
```

> **Note:** If cookie-authenticated requests fail (e.g., due to YouTube's JavaScript challenges), the tool automatically retries without cookies. This provides the best of both worlds—cookies work when needed, anonymous fallback when they don't.

### Output Format

```bash
# SRT format (default)
yt "URL" --format srt

# WebVTT format
yt "URL" --format vtt

# Plain text (no timestamps)
yt "URL" --format txt

# Article format (LLM-generated article from transcript)
yt "URL" --format article

# Article with length control
yt "URL" --format article --length short    # Concise summary
yt "URL" --format article --length medium   # Standard article
yt "URL" --format article --length long     # Comprehensive article
yt "URL" --format article --length original # Full rewrite (default)
```

Articles are saved to `~/YouTube Subtitles/Articles/` as `.md` files.

#### Article Metadata

Articles can include video metadata. Configure with `output.article_metadata`:

| Value         | Description                                                    |
| ------------- | -------------------------------------------------------------- |
| `frontmatter` | YAML frontmatter (default) - works with Obsidian, Jekyll, Hugo |
| `header`      | Visible header block with title, author, links                 |
| `footer`      | Source citation at the end                                     |
| `none`        | No metadata                                                    |

Example with `frontmatter`:

```markdown
---
title: "Video Title"
author: "Channel Name"
url: https://www.youtube.com/watch?v=...
upload_date: 2024-12-13
request_date: 2026-01-21
---

Article content...
```

### Language Options

```bash
# Override config languages
yt "URL" --languages en,ja,ko

# Disable translation (save source language only)
yt "URL" --no-translate
```

### Pipe Mode

Output transcript to stdout for piping to other tools (like [Fabric](https://github.com/danielmiessler/Fabric)):

```bash
# Pipe transcript to another tool
yt "URL" --pipe | fabric --pattern summarize

# Pipe mode without saving files
yt "URL" --pipe --no-save | other-tool

# Get plain text for easier processing
yt "URL" --pipe --format txt | fabric --pattern extract_wisdom
```

In pipe mode:

-   **Only the first language** is output to stdout (for clean piping)
-   Status messages go to stderr
-   Transcript content goes to stdout
-   Files are still saved for all languages (use `--no-save` to disable)

### Whisper Transcription Control

Control when Whisper transcription is used:

```bash
# Auto mode (default): Use YouTube captions when available, fall back to Whisper
yt "URL" --use-whisper auto

# Force mode: Always use Whisper, skip YouTube captions
yt "URL" --use-whisper force

# Never mode: Only use YouTube captions, skip video if none available
yt "URL" --use-whisper never
```

| Mode    | Behavior                                             |
| ------- | ---------------------------------------------------- |
| `auto`  | Smart fallback: YouTube captions → Whisper (default) |
| `force` | Always transcribe via Whisper API (requires API key) |
| `never` | YouTube captions only, no API costs                  |

> **Note:** Whisper transcription results are cached to disk. If translation fails afterward, retrying won't re-transcribe the audio.

### Other Options

```bash
# Force overwrite existing files
yt "URL" --force

# Delete audio after transcription
yt "URL" --discard-audio

# Use specific config file
yt "URL" --config /path/to/config.yaml

# Force specific YouTube client (for compatibility)
yt "URL" --player-client android

# Enable verbose output
yt "URL" --verbose
```

## CLI Reference

### Commands

| Command          | Description                                   |
| ---------------- | --------------------------------------------- |
| `yt <urls>`      | Process YouTube URLs and download transcripts |
| `yt config show` | Display current configuration (or defaults)   |
| `yt config init` | Create a new configuration file               |

### Options

| Option                   | Description                                                                    |
| ------------------------ | ------------------------------------------------------------------------------ |
| `urls`                   | YouTube URLs (positional arguments)                                            |
| `--input`, `-i`          | File containing URLs, one per line                                             |
| `--config`               | Path to config.yaml (default: `~/.config/yt/config.yaml`)                      |
| `--format`, `-f`         | Output format: `srt`, `vtt`, `txt`, or `article`                               |
| `--length`               | Article length: `original`, `long`, `medium`, `short` (for `--format article`) |
| `--languages`, `-l`      | Comma-separated target languages (e.g., `en,ja,ko`)                            |
| `--pipe`, `-p`           | Pipe mode: output transcript to stdout                                         |
| `--no-save`              | Don't save files (only useful with `--pipe`)                                   |
| `--force`                | Overwrite existing output files                                                |
| `--no-translate`         | Skip translation; save only source language                                    |
| `--discard-audio`        | Delete audio file after Whisper transcription                                  |
| `--use-whisper`          | Whisper usage: `auto` (fallback), `force` (always), `never` (skip)             |
| `--cookies`              | Path to cookies.txt (Netscape format)                                          |
| `--cookies-from-browser` | Browser to extract cookies from                                                |
| `--player-client`        | Force YouTube client: `web`, `android`, `ios`, `tv`                            |
| `--verbose`, `-v`        | Enable verbose output for debugging                                            |

## Output Files

Files are saved with the naming pattern:

```
{YYYY-MM-DD} - {Video Title} [{language}].{ext}
```

The date prefix is controlled by the `output.filename_date` config option:

| Value     | Description                                              |
| --------- | -------------------------------------------------------- |
| `upload`  | Video upload date (default) - good for archiving         |
| `request` | Today's date - good for personal knowledge management    |
| `none`    | No date prefix - just `{Video Title} [{language}].{ext}` |

Examples with `filename_date: upload`:

-   `2024-10-26 - How AI Works [en].srt`
-   `2024-10-26 - How AI Works [ja].srt`

Examples with `filename_date: request` (assuming today is 2026-01-21):

-   `2026-01-21 - How AI Works [en].srt`
-   `2026-01-21 - How AI Works [ja].srt`

Examples with `filename_date: none`:

-   `How AI Works [en].srt`
-   `How AI Works [ja].srt`

## Acknowledgments

This project was inspired by the `yt` helper function in [Fabric](https://github.com/danielmiessler/Fabric), an open-source framework for augmenting humans using AI. While Fabric's `yt` extracts YouTube transcripts for use with AI patterns, this tool extends that concept with:

-   Multi-language support with automatic translation
-   Whisper API fallback when captions are unavailable
-   Article generation from transcripts
-   Organized file storage with configurable naming
-   Flexible output formats (SRT, VTT, TXT, article)

**Works great with Fabric!** Use `--pipe` mode to feed transcripts directly into Fabric patterns:

```bash
yt "URL" --pipe --format txt | fabric --pattern extract_wisdom
yt "URL" --pipe | fabric --pattern summarize
```

## License

MIT
