import os
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING

from utils.logger import setup_logger
from utils.ffmpeg_utils import get_ffmpeg_path, run_ffmpeg

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)


def _format_ass_time(seconds: float) -> str:
    """Format time cho file ASS (H:MM:SS.cs)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cents = int((seconds - int(seconds)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def generate_ass_subtitle(segments: List[Dict], output_path: str, font_size: int = 24, only_chinese_sub: bool = False) -> bool:
    """
    Sinh file phụ đề ASS đẹp mắt cho TikTok/Douyin (Chữ viền đen dày, nổi bật).
    """
    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TiktokStyle,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,30,30,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(ass_header)
            for seg in segments:
                start = _format_ass_time(seg["start"])
                end = _format_ass_time(seg["end"])
                if only_chinese_sub:
                    text = seg.get("text", "").strip()
                else:
                    text = seg.get("text_vi", "").strip()
                if text and text != "[Lỗi dịch thuật]":
                    f.write(f"Dialogue: 0,{start},{end},TiktokStyle,,0,0,0,,{text}\n")
        return True
    except Exception as e:
        logger.error(f"Lỗi tạo file ASS: {e}")
        return False


def mix_tts_audios(
    segments: List[Dict], 
    output_wav: str,
    process_manager: Optional["ProcessManager"] = None
) -> bool:
    """
    Dùng FFmpeg filter_complex để ghép hàng trăm file TTS nhỏ thành 1 track Audio duy nhất theo đúng thời gian.
    Sử dụng batch processing để tránh vượt quá giới hạn ký tự của dòng lệnh Windows (WinError 206).
    Tích hợp ProcessManager để hỗ trợ force-stop.
    """
    valid_segments = []
    for seg in segments:
        audio_path = seg.get("tts_audio_path")
        if audio_path and os.path.exists(audio_path):
            valid_segments.append(seg)
            
    if not valid_segments:
        logger.warning("Không có file audio nào để ghép.")
        return False

    BATCH_SIZE = 50
    batches = [valid_segments[i:i + BATCH_SIZE] for i in range(0, len(valid_segments), BATCH_SIZE)]
    batch_files = []
    script_paths = []
    
    try:
        # Mix từng batch
        for batch_idx, batch in enumerate(batches):
            inputs = []
            filter_lines = []
            amix_inputs = ""
            
            for i, seg in enumerate(batch):
                inputs.extend(["-i", seg["tts_audio_path"]])
                delay_ms = int(seg["start"] * 1000)
                filter_lines.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}];\n")
                amix_inputs += f"[a{i}]"
                
            # normalize=0 (FFmpeg mới) đảm bảo âm lượng không bị giảm khi mix quá nhiều file
            filter_lines.append(f"{amix_inputs}amix=inputs={len(batch)}:dropout_transition=0:normalize=0[out]\n")
            
            batch_output = str(Path(output_wav).parent / f"temp_batch_{batch_idx}.wav")
            script_path = str(Path(output_wav).parent / f"filter_script_{batch_idx}.txt")
            script_paths.append(script_path)
            
            with open(script_path, "w", encoding='utf-8') as f:
                f.writelines(filter_lines)
                
            cmd = [get_ffmpeg_path(), "-y"] + inputs + [
                "-filter_complex_script", script_path,
                "-map", "[out]",
                "-ac", "2", "-ar", "44100", # Xuất stereo 44.1kHz cho chuẩn
                batch_output
            ]
            
            logger.debug(f"Đang mix batch {batch_idx + 1}/{len(batches)} ({len(batch)} files)...")
            res = run_ffmpeg(cmd, process_manager=process_manager, description=f"Mix TTS Audio Batch {batch_idx}")
            
            if res.returncode == 0 and os.path.exists(batch_output):
                batch_files.append(batch_output)
            else:
                stderr_text = res.stderr.decode('utf-8', errors='replace') if isinstance(res.stderr, bytes) else str(res.stderr)
                logger.error(f"Lỗi FFmpeg khi mix audio batch {batch_idx}:\n{stderr_text[-1000:]}")
                return False

        # Gộp các batch lại
        if len(batch_files) == 1:
            import shutil
            shutil.copy2(batch_files[0], output_wav)
            res_final = True
        else:
            inputs = []
            amix_inputs = ""
            for i, b_file in enumerate(batch_files):
                inputs.extend(["-i", b_file])
                amix_inputs += f"[{i}:a]"
                
            final_script_path = str(Path(output_wav).parent / "filter_script_final.txt")
            script_paths.append(final_script_path)
            
            filter_line = f"{amix_inputs}amix=inputs={len(batch_files)}:dropout_transition=0:normalize=0[out]\n"
            with open(final_script_path, "w", encoding='utf-8') as f:
                f.write(filter_line)
                
            cmd = [get_ffmpeg_path(), "-y"] + inputs + [
                "-filter_complex_script", final_script_path,
                "-map", "[out]",
                "-ac", "2", "-ar", "44100",
                output_wav
            ]
            
            logger.debug(f"Đang mix final {len(batch_files)} batches...")
            res = run_ffmpeg(cmd, process_manager=process_manager, description="Mix TTS Audio Final")
            
            if res.returncode == 0 and os.path.exists(output_wav):
                res_final = True
            else:
                stderr_text = res.stderr.decode('utf-8', errors='replace') if isinstance(res.stderr, bytes) else str(res.stderr)
                logger.error(f"Lỗi FFmpeg khi mix audio final:\n{stderr_text[-1000:]}")
                res_final = False

        if res_final:
            logger.info(f"Đã ghép xong TTS Audio Track: {output_wav}")
        return res_final
            
    except Exception as e:
        from core.process_manager import ProcessStoppedException
        if isinstance(e, ProcessStoppedException):
            raise
        logger.error(f"Lỗi exception khi mix audio: {e}")
        return False
    finally:
        # Dọn dẹp temp files
        for f in batch_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        for f in script_paths:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
