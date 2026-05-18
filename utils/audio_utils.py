"""Audio helpers for TTS timeline alignment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from utils.ffmpeg_utils import get_ffmpeg_path, run_ffmpeg
from utils.logger import setup_logger
from utils.tts_utils import get_audio_duration

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)


def create_silence_audio(
    output_path: str,
    duration: float,
    process_manager: Optional["ProcessManager"] = None,
) -> bool:
    """Create a silent MP3 file with the requested duration."""
    duration = max(0.1, float(duration or 0.1))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_ffmpeg_path(), "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{duration:.3f}",
        "-q:a", "9",
        "-acodec", "libmp3lame",
        output_path,
    ]
    res = run_ffmpeg(cmd, process_manager=process_manager, description="Create silence audio")
    return res.returncode == 0 and os.path.exists(output_path) and get_audio_duration(output_path) > 0


def _atempo_chain(speed: float) -> str:
    """Build an FFmpeg atempo chain. atempo accepts values between 0.5 and 100 in modern FFmpeg, but 0.5-2 is safest."""
    speed = max(0.5, float(speed or 1.0))
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    parts.append(f"atempo={speed:.4f}")
    return ",".join(parts)


def speed_up_audio(
    input_path: str,
    output_path: str,
    speed: float,
    process_manager: Optional["ProcessManager"] = None,
) -> bool:
    """Speed up audio into output_path using FFmpeg atempo."""
    if speed <= 1.001:
        return False
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-filter:a", _atempo_chain(speed),
        output_path,
    ]
    res = run_ffmpeg(cmd, process_manager=process_manager, description="Speed up TTS Audio")
    return res.returncode == 0 and os.path.exists(output_path) and get_audio_duration(output_path) > 0


def pad_audio_to_duration(
    input_path: str,
    output_path: str,
    target_duration: float,
    process_manager: Optional["ProcessManager"] = None,
) -> bool:
    """Pad audio with trailing silence so the output has at least target_duration."""
    target_duration = max(0.1, float(target_duration or 0.1))
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-af", f"apad,atrim=0:{target_duration:.3f}",
        output_path,
    ]
    res = run_ffmpeg(cmd, process_manager=process_manager, description="Pad TTS Audio")
    return res.returncode == 0 and os.path.exists(output_path) and get_audio_duration(output_path) > 0


def align_audio_to_duration(
    input_path: str,
    output_path: str,
    target_duration: float,
    max_speed_increase: int = 50,
    process_manager: Optional["ProcessManager"] = None,
) -> tuple[bool, float, str]:
    """Align one TTS clip to a subtitle slot.

    Returns: (success, final_duration, action)
    action: original | speed+N% | padded | speed+N%+padded | failed
    """
    target_duration = max(0.1, float(target_duration or 0.1))
    actual_duration = get_audio_duration(input_path)
    if actual_duration <= 0:
        return False, 0.0, "failed"

    temp_path = str(Path(output_path).with_suffix(".align.tmp.mp3"))
    current_path = input_path
    action = "original"

    try:
        if actual_duration > target_duration + 0.05:
            required_speed = actual_duration / target_duration
            max_speed = 1.0 + max(0, max_speed_increase) / 100.0
            speed = min(required_speed, max_speed)
            if speed > 1.001:
                if not speed_up_audio(current_path, temp_path, speed, process_manager=process_manager):
                    return False, actual_duration, "failed"
                current_path = temp_path
                actual_duration = get_audio_duration(current_path)
                action = f"speed+{int(round((speed - 1.0) * 100))}%"

        if actual_duration < target_duration - 0.05:
            padded_path = output_path if current_path != output_path else str(Path(output_path).with_suffix(".pad.tmp.mp3"))
            if not pad_audio_to_duration(current_path, padded_path, target_duration, process_manager=process_manager):
                return False, actual_duration, "failed"
            if padded_path != output_path:
                os.replace(padded_path, output_path)
            final_duration = get_audio_duration(output_path)
            action = "padded" if action == "original" else f"{action}+padded"
            return True, final_duration, action

        if current_path != output_path:
            os.replace(current_path, output_path)
        elif not os.path.exists(output_path):
            return False, actual_duration, "failed"
        return True, get_audio_duration(output_path), action
    finally:
        for path in {temp_path, str(Path(output_path).with_suffix(".pad.tmp.mp3"))}:
            if path != output_path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
