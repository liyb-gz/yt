# yt

A CLI tool to download YouTube subtitles with intelligent fallbacks and optional translation.

## Features

- **Smart fallback chain**: Official transcripts → Auto-generated captions → Whisper transcription
- **Multi-language support**: Request subtitles in multiple languages simultaneously
- **Automatic translation**: Translate transcripts to target languages via LLM (OpenAI-compatible)
- **Flexible output**: SRT, VTT, or plain text formats
- **Pipe mode**: Output to stdout for piping to other tools (like [Fabric](https://github.com/danielmiessler/Fabric))
- **Batch processing**: Process multiple URLs from command line or file
- **Cookie support**: Bypass YouTube restrictions using browser cookies
- **Organized storage**: Auto-naming with video title and upload date

## Installation

```bash
# Install globally with uv
uv tool install .

# Or with pip
pip install .
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
  format: srt          # srt, vtt, or txt
  pipe_mode: false     # When true, output transcript to stdout for piping

# Output directories (~ is expanded)
storage:
  audio_dir: "~/YouTube Subtitles/Audio"
  transcript_dir: "~/YouTube Subtitles/Transcripts"

# YouTube/yt-dlp settings (optional)
youtube:
  cookies_from_browser: chrome  # or firefox, safari, edge, brave
  # cookies_file: ~/cookies.txt   # alternative: path to cookies.txt
  # player_client: web            # force client: web, android, ios, tv

# OpenAI-compatible Whisper API (used when YouTube captions unavailable)
transcription:
  base_url: https://api.openai.com/v1/audio/transcriptions
  model: whisper-1
  api_key_env: OPENAI_API_KEY

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
- **Only the first language** is output to stdout (for clean piping)
- Status messages go to stderr
- Transcript content goes to stdout
- Files are still saved for all languages (use `--no-save` to disable)

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

| Command | Description |
|---------|-------------|
| `yt <urls>` | Process YouTube URLs and download transcripts |
| `yt config show` | Display current configuration (or defaults) |
| `yt config init` | Create a new configuration file |

### Options

| Option | Description |
|--------|-------------|
| `urls` | YouTube URLs (positional arguments) |
| `--input`, `-i` | File containing URLs, one per line |
| `--config` | Path to config.yaml (default: `~/.config/yt/config.yaml`) |
| `--format`, `-f` | Output format: `srt`, `vtt`, or `txt` |
| `--languages`, `-l` | Comma-separated target languages (e.g., `en,ja,ko`) |
| `--pipe`, `-p` | Pipe mode: output transcript to stdout |
| `--no-save` | Don't save files (only useful with `--pipe`) |
| `--force` | Overwrite existing output files |
| `--no-translate` | Skip translation; save only source language |
| `--discard-audio` | Delete audio file after Whisper transcription |
| `--cookies` | Path to cookies.txt (Netscape format) |
| `--cookies-from-browser` | Browser to extract cookies from |
| `--player-client` | Force YouTube client: `web`, `android`, `ios`, `tv` |
| `--verbose`, `-v` | Enable verbose output for debugging |

## Output Files

Files are saved with the naming pattern:

```
{YYYY-MM-DD} - {Video Title} [{language}].{ext}
```

Examples:
- `2025-10-26 - How AI Works [en].srt`
- `2025-10-26 - How AI Works [ja].srt`
- `2025-10-26 - How AI Works [audio].m4a` (if Whisper was used)

## License

MIT
