"""Utilities for reading/writing SRT and converting to transcript JSON records."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_TIME_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)
_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+\s*\n)?"
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?:[^\n]*)\n"
    r"(?P<text>.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def parse_srt_time(value: str) -> float:
    """Parse an SRT timestamp into seconds."""
    match = _TIME_RE.search(value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    h = int(match.group("h"))
    m = int(match.group("m"))
    s = int(match.group("s"))
    ms = int(match.group("ms").ljust(3, "0")[:3])
    return h * 3600 + m * 60 + s + ms / 1000


def format_srt_time(seconds: float) -> str:
    """Format seconds as an SRT timestamp."""
    seconds = max(0.0, float(seconds or 0.0))
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_content(content: str) -> List[Dict]:
    """Parse SRT text into records: id/start/end/text."""
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    records: List[Dict] = []
    for idx, match in enumerate(_BLOCK_RE.finditer(content), 1):
        text = re.sub(r"\n+", " ", match.group("text")).strip()
        records.append(
            {
                "id": idx,
                "start": round(parse_srt_time(match.group("start")), 3),
                "end": round(parse_srt_time(match.group("end")), 3),
                "text": text,
            }
        )
    return records


def parse_srt_file(path: str | Path) -> List[Dict]:
    return parse_srt_content(Path(path).read_text(encoding="utf-8-sig"))


def write_srt(segments: Iterable[Dict], output_path: str | Path, text_key: str = "text_vi") -> None:
    """Write transcript-like records into an SRT file."""
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        text = str(seg.get(text_key) or seg.get("text") or seg.get("text_zh") or "").strip()
        if not text:
            continue
        lines.extend(
            [
                str(idx),
                f"{format_srt_time(seg.get('start', 0))} --> {format_srt_time(seg.get('end', 0))}",
                text,
                "",
            ]
        )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def merge_origin_target_srt(
    target_srt: str | Path,
    origin_srt: Optional[str | Path] = None,
) -> List[Dict]:
    """Convert KrillinAI-style target/origin SRT files to tool transcript records."""
    target = parse_srt_file(target_srt)
    origin = parse_srt_file(origin_srt) if origin_srt else []
    merged: List[Dict] = []
    for idx, item in enumerate(target, 1):
        origin_text = origin[idx - 1]["text"] if idx - 1 < len(origin) else ""
        merged.append(
            {
                "id": idx,
                "start": item["start"],
                "end": item["end"],
                "text_zh": origin_text,
                "text_vi": item["text"],
            }
        )
    return merged
