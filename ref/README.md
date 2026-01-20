# yt

A CLI tool to download YouTube subtitles with intelligent fallbacks and optional translation.

## Features

- **Smart fallback chain**: Official transcripts → Auto-generated captions → Whisper transcription
- **Multi-language support**: Request subtitles in multiple languages simultaneously
- **Automatic translation**: Translate transcripts to target languages via LLM (OpenRouter)
- **Flexible output**: SRT, VTT, or plain text formats
- **Batch processing**: Process multiple URLs from command line or file
- **Cookie support**: Bypass YouTube restrictions using browser cookies
- **Organized storage**: Auto-naming with video title and upload date

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                          yt workflow                            │
├─────────────────────────────────────────────────────────────────┤
│  1. Fetch video metadata (title, upload date, ID)               │
│                           ↓                                     │
│  2. Try official YouTube transcript (manually created)          │
│                           ↓ (if unavailable)                    │
│  3. Try auto-generated YouTube captions                         │
│                           ↓ (if unavailable)                    │
│  4. Download audio → Transcribe via Whisper (e.g., Fireworks API)     │
│                           ↓                                     │
│  5. If source language ≠ target language(s) → Translate via LLM │
│                           ↓                                     │
│  6. Save transcripts as SRT/VTT/TXT                             │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration

Create a config file at `~/.config/yt/config.yaml`:

```yaml
# Target languages for transcripts (will try to fetch or translate to these)
languages:
  - en
  - ja
  - ko
  - zh-TW

# Output directories (~ is expanded)
storage:
  audio_dir: "~/YouTube Subtitles/Audio"
  transcript_dir: "~/YouTube Subtitles/Transcripts"

# Whisper transcription service (used when YouTube captions unavailable)
transcription:
  provider: fireworks
  model: whisper-v3
  base_url: https://audio-prod.us-virginia-1.direct.fireworks.ai/v1/audio/transcriptions

# LLM for translation (used when source language differs from targets)
llm:
  provider: openrouter
  model: google/gemini-2.5-pro
  base_url: https://openrouter.ai/api/v1/chat/completions

# Environment variable names for API keys
secrets:
  transcriber_api_key_env: FIREWORKS_API_KEY
  llm_api_key_env: OPENROUTER_API_KEY
```

### Environment Variables

Export your API keys before running:

```bash
export FIREWORKS_API_KEY="your-fireworks-api-key"
export OPENROUTER_API_KEY="your-openrouter-api-key"
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

YouTube may require authentication for some videos. Use cookies from your browser:

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

| Option | Description |
|--------|-------------|
| `urls` | YouTube URLs (positional arguments) |
| `--input`, `-i` | File containing URLs, one per line |
| `--config` | Path to config.yaml (default: `~/.config/yt/config.yaml`) |
| `--format`, `-f` | Output format: `srt`, `vtt`, or `txt` |
| `--languages`, `-l` | Comma-separated target languages (e.g., `en,ja,ko`) |
| `--force` | Overwrite existing output files |
| `--no-translate` | Skip translation; save only source language |
| `--discard-audio` | Delete audio file after Whisper transcription |
| `--cookies` | Path to cookies.txt (Netscape format) |
| `--cookies-from-browser` | Browser to extract cookies from |
| `--player-client` | Force YouTube client: `web`, `android`, `ios`, `tv` |
| `--verbose`, `-v` | Enable verbose output for debugging |
| `--workers` | Number of parallel workers (reserved for future) |

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
