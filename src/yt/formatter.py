"""Output formatters for SRT, VTT, and plain text."""

import re
from dataclasses import dataclass
from enum import Enum


class OutputFormat(Enum):
    """Supported output formats."""
    SRT = "srt"
    VTT = "vtt"
    TXT = "txt"
    
    @classmethod
    def from_string(cls, s: str) -> "OutputFormat":
        """Parse format from string."""
        s = s.lower().strip()
        for fmt in cls:
            if fmt.value == s:
                return fmt
        raise ValueError(f"Unknown format: {s}. Supported: srt, vtt, txt")


@dataclass
class SubtitleEntry:
    """A single subtitle entry with timing and text."""
    index: int
    start_time: float  # seconds
    end_time: float    # seconds
    text: str


def parse_srt(content: str) -> list[SubtitleEntry]:
    """Parse SRT content into subtitle entries."""
    entries = []
    blocks = re.split(r'\n\n+', content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        
        # Parse timestamp line
        timestamp_match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            lines[1].strip()
        )
        if not timestamp_match:
            continue
        
        start_time = _parse_timestamp(*timestamp_match.groups()[:4])
        end_time = _parse_timestamp(*timestamp_match.groups()[4:])
        text = '\n'.join(lines[2:])
        
        entries.append(SubtitleEntry(
            index=index,
            start_time=start_time,
            end_time=end_time,
            text=text,
        ))
    
    return entries


def parse_vtt(content: str) -> list[SubtitleEntry]:
    """Parse VTT content into subtitle entries."""
    entries = []
    lines = content.strip().split('\n')
    
    # Skip WEBVTT header and any metadata
    i = 0
    while i < len(lines) and not re.match(r'\d{2}:\d{2}', lines[i]):
        i += 1
    
    index = 1
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for timestamp line
        timestamp_match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})',
            line
        )
        if not timestamp_match:
            # Also try without hours (MM:SS.mmm format)
            timestamp_match = re.match(
                r'(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2})\.(\d{3})',
                line
            )
            if timestamp_match:
                # Convert to full format
                g = timestamp_match.groups()
                start_time = _parse_timestamp("00", g[0], g[1], g[2])
                end_time = _parse_timestamp("00", g[3], g[4], g[5])
            else:
                i += 1
                continue
        else:
            start_time = _parse_timestamp(*timestamp_match.groups()[:4])
            end_time = _parse_timestamp(*timestamp_match.groups()[4:])
        
        # Collect text lines until empty line or next timestamp
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            if re.match(r'\d{2}:\d{2}', lines[i]):
                break
            text_lines.append(lines[i])
            i += 1
        
        if text_lines:
            entries.append(SubtitleEntry(
                index=index,
                start_time=start_time,
                end_time=end_time,
                text='\n'.join(text_lines),
            ))
            index += 1
        
        # Skip empty lines
        while i < len(lines) and not lines[i].strip():
            i += 1
    
    return entries


def _parse_timestamp(hours: str, minutes: str, seconds: str, millis: str) -> float:
    """Parse timestamp components to seconds."""
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def format_srt(entries: list[SubtitleEntry]) -> str:
    """Format subtitle entries as SRT."""
    lines = []
    for entry in entries:
        lines.append(str(entry.index))
        lines.append(f"{_format_time_srt(entry.start_time)} --> {_format_time_srt(entry.end_time)}")
        lines.append(entry.text)
        lines.append("")
    return '\n'.join(lines)


def format_vtt(entries: list[SubtitleEntry]) -> str:
    """Format subtitle entries as VTT."""
    lines = ["WEBVTT", ""]
    for entry in entries:
        lines.append(f"{_format_time_vtt(entry.start_time)} --> {_format_time_vtt(entry.end_time)}")
        lines.append(entry.text)
        lines.append("")
    return '\n'.join(lines)


def format_txt(entries: list[SubtitleEntry]) -> str:
    """Format subtitle entries as plain text (no timestamps)."""
    return '\n'.join(entry.text for entry in entries)


def _format_time_srt(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_time_vtt(seconds: float) -> str:
    """Format seconds as VTT timestamp (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def convert_format(content: str, source_format: OutputFormat, target_format: OutputFormat) -> str:
    """Convert subtitle content between formats."""
    if source_format == target_format:
        return content
    
    # Parse source
    if source_format == OutputFormat.SRT:
        entries = parse_srt(content)
    elif source_format == OutputFormat.VTT:
        entries = parse_vtt(content)
    else:
        # TXT has no timestamps, can't convert to other formats
        raise ValueError("Cannot convert from TXT format (no timestamps)")
    
    # Format target
    if target_format == OutputFormat.SRT:
        return format_srt(entries)
    elif target_format == OutputFormat.VTT:
        return format_vtt(entries)
    else:
        return format_txt(entries)


def srt_to_vtt(srt_content: str) -> str:
    """Convert SRT to VTT format."""
    return convert_format(srt_content, OutputFormat.SRT, OutputFormat.VTT)


def vtt_to_srt(vtt_content: str) -> str:
    """Convert VTT to SRT format."""
    return convert_format(vtt_content, OutputFormat.VTT, OutputFormat.SRT)


def extract_plain_text(content: str, source_format: OutputFormat) -> str:
    """Extract plain text from subtitle content."""
    if source_format == OutputFormat.TXT:
        return content
    elif source_format == OutputFormat.SRT:
        entries = parse_srt(content)
    else:
        entries = parse_vtt(content)
    return format_txt(entries)
