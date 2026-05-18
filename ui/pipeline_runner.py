"""
Pipeline Runner — Quản lý luồng xử lý Batch Video.
Tích hợp ProcessManager để hỗ trợ Dừng / Ép Dừng.
Hỗ trợ "Tiếp tục từ bước X" — bỏ qua các bước đã hoàn thành.

Pipeline chạy trong background thread để UI không bị block,
cho phép người dùng bấm Dừng/Ép Dừng bất cứ lúc nào.
"""

import os
import threading
from pathlib import Path
from typing import List, Optional
import streamlit as st

from core.process_manager import ProcessManager, ProcessStoppedException
from modules.transcription_translator import TranscriptionTranslator
from modules.tts_generator import TTSGenerator
from modules.video_renderer import VideoRenderer
from utils.ffmpeg_utils import get_ffmpeg_path, run_ffmpeg
from utils.logger import setup_logger

logger = setup_logger(__name__)


def _find_existing_audio(workspace_dir: str, video_stem: str) -> Optional[str]:
    """Tìm file audio đã tách trước đó."""
    audio_path = Path(workspace_dir) / "audios" / f"{video_stem}.mp3"
    if audio_path.exists() and audio_path.stat().st_size > 1000:
        return str(audio_path)
    return None


def _find_existing_transcript(workspace_dir: str, video_stem: str) -> Optional[str]:
    """Tìm file transcript JSON đã dịch trước đó."""
    json_path = Path(workspace_dir) / "transcripts" / f"{video_stem}_transcript.json"
    if json_path.exists() and json_path.stat().st_size > 10:
        return str(json_path)
    return None


def _find_existing_tts_json(workspace_dir: str, video_stem: str, voice: str) -> Optional[str]:
    """Tìm file TTS sync JSON đã tạo trước đó."""
    tts_dir = Path(workspace_dir) / "tts_audios" / video_stem / voice
    tts_json = tts_dir / f"{video_stem}_tts_sync.json"
    if tts_json.exists() and tts_json.stat().st_size > 10:
        return str(tts_json)
    return None


def _pipeline_worker(
    video_paths: List[str],
    settings: dict,
    workspace_dir: str,
    pm: ProcessManager
):
    """
    Worker function chạy trong background thread.
    Không gọi bất kỳ Streamlit API nào (vì chạy ngoài main thread).
    Toàn bộ progress/status được cập nhật qua ProcessManager.
    """
    start_from = settings.get("start_from_step", 1)
    end_at = settings.get("end_at_step", 4)
    
    # Khởi tạo các Module Core
    translator = None
    tts_gen = None
    renderer = None
    
    try:
        if start_from <= 2 and end_at >= 2:
            translator = TranscriptionTranslator(
                translator_type=settings["translator_type"],
                api_key=settings["api_key"],
                whisper_model_size=settings.get("whisper_model", "medium"),
                translation_model=settings["model_name"],
                workspace_dir=workspace_dir,
                batch_size=settings.get("batch_size", 20),
                context_size=settings.get("context_size", 5),
                source_language=settings.get("source_language", "zh"),
                process_manager=pm
            )
        if start_from <= 3 and end_at >= 3:
            tts_gen = TTSGenerator(
                engine_type=settings.get("tts_engine", "edge"),
                voice=settings["voice"],
                workspace_dir=workspace_dir,
                max_speed_increase=settings.get("max_speed_increase", 50),
                process_manager=pm
            )
        if start_from <= 4 and end_at >= 4:
            renderer = VideoRenderer(
                workspace_dir=workspace_dir,
                process_manager=pm
            )
    except ProcessStoppedException:
        pm.add_log("⏸️ Pipeline đã bị dừng trước khi bắt đầu.")
        pm.finish()
        return
    except Exception as e:
        pm.add_log(f"❌ Lỗi khởi tạo Module AI: {e}")
        pm.finish()
        return

    # ═══════════════════════════════════
    # VÒNG LẶP BATCH PROCESSING
    # ═══════════════════════════════════
    total = len(video_paths)
    
    for i, video_path_str in enumerate(video_paths):
        if pm.should_stop():
            pm.add_log(f"⏸️ Pipeline đã dừng. Đã xử lý {i}/{total} video.")
            break
            
        video_path = Path(video_path_str)
        vid_name = video_path.name
        vid_stem = video_path.stem
        base_prog = i / total
        step_prog = 1 / total
        
        pm.set_video_index(i)
        pm.add_log(f"🎬 Đang xử lý: {vid_name}")
        
        try:
            # ══════════════════════════════════════════
            # BƯỚC 1: Tách Audio
            # ══════════════════════════════════════════
            audio_path = str(Path(workspace_dir) / "audios" / f"{vid_stem}.mp3")
            
            if start_from <= 1:
                pm.update_step("Tách âm thanh")
                pm.check_stop_and_raise()
                
                existing_audio = _find_existing_audio(workspace_dir, vid_stem)
                if existing_audio:
                    audio_path = existing_audio
                    pm.add_log("✅ Đã có file Audio (skip tách lại).")
                else:
                    os.makedirs(Path(audio_path).parent, exist_ok=True)
                    ffmpeg_exe = get_ffmpeg_path()
                    cmd_audio = [ffmpeg_exe, '-y', '-i', str(video_path), '-vn', '-q:a', '0', audio_path]
                    run_ffmpeg(cmd_audio, process_manager=pm, description="Tách Audio")
                    pm.add_log("✅ Đã tách Audio thành công.")
            else:
                existing_audio = _find_existing_audio(workspace_dir, vid_stem)
                if existing_audio:
                    audio_path = existing_audio
                    pm.add_log("⏩ Bỏ qua Bước 1 (dùng audio đã có).")
                else:
                    pm.add_log(f"❌ Không tìm thấy audio: {audio_path}. Hãy chọn Bước 1.")
                    continue
                    
            pm.update_progress(base_prog + step_prog * 0.25)
            
            if end_at < 2:
                pm.add_log("🛑 Đã hoàn thành Bước 1 và dừng lại theo yêu cầu.")
                continue
            
            # ══════════════════════════════════════════
            # BƯỚC 2: Whisper + AI Dịch
            # ══════════════════════════════════════════
            json_transcript = None
            
            if start_from <= 2:
                pm.update_step("Dịch thuật AI")
                pm.check_stop_and_raise()
                
                results = translator.process_file(audio_path)
                if results:
                    json_transcript = str(Path(workspace_dir) / "transcripts" / f"{vid_stem}_transcript.json")
                    pm.add_log(f"✅ Dịch hoàn tất ({len(results)} câu).")
            else:
                existing_transcript = _find_existing_transcript(workspace_dir, vid_stem)
                if existing_transcript:
                    json_transcript = existing_transcript
                    pm.add_log("⏩ Bỏ qua Bước 2 (dùng bản dịch đã có).")
                else:
                    pm.add_log(f"❌ Không tìm thấy bản dịch cho: {vid_stem}. Hãy chọn Bước 2.")
                    continue
            
            pm.update_progress(base_prog + step_prog * 0.5)
            
            if not json_transcript:
                pm.add_log("❌ Lỗi dịch thuật. Bỏ qua video này.")
                continue
                
            if end_at < 3:
                pm.add_log("🛑 Đã hoàn thành Bước 2. Dừng lại để bạn chỉnh sửa kịch bản!")
                continue
                
            # ══════════════════════════════════════════
            # BƯỚC 3: Text-to-Speech (Sync)
            # ══════════════════════════════════════════
            tts_json = None
            
            if start_from <= 3:
                pm.update_step("Lồng tiếng TTS")
                pm.check_stop_and_raise()
                
                tts_json = tts_gen.process_transcript(json_transcript)
                
                if tts_json:
                    pm.add_log("✅ Đã tạo giọng đọc và đồng bộ thời gian.")
                else:
                    pm.add_log("❌ Lỗi tạo giọng đọc. Bỏ qua video này.")
                    continue
            else:
                existing_tts = _find_existing_tts_json(workspace_dir, vid_stem, settings["voice"])
                if existing_tts:
                    tts_json = existing_tts
                    pm.add_log("⏩ Bỏ qua Bước 3 (dùng giọng đọc đã có).")
                else:
                    pm.add_log(f"❌ Không tìm thấy TTS cho: {vid_stem}. Hãy chọn Bước 3.")
                    continue
                    
            pm.update_progress(base_prog + step_prog * 0.75)
            
            if end_at < 4:
                pm.add_log("🛑 Đã hoàn thành Bước 3. Dừng lại theo yêu cầu!")
                continue
            
            # ══════════════════════════════════════════
            # BƯỚC 4: Render + Visual Filters
            # ══════════════════════════════════════════
            pm.update_step("Render video")
            pm.check_stop_and_raise()
            
            final_vid = renderer.render_video(
                original_video=str(video_path),
                tts_json_path=tts_json,
                bgm_volume=settings["bgm_volume"],
                fast_preview=settings["fast_preview"],
                blur_sub=settings["blur_sub"],
                blur_logo=settings["blur_logo"],
                flip_video=settings["flip_video"],
                only_chinese_sub=settings.get("only_chinese_sub", False)
            )
            
            pm.update_progress(base_prog + step_prog)
            
            if final_vid:
                pm.add_log(f"🎉 Hoàn thành video: {vid_name}")
                pm.set_result_video(final_vid)
            else:
                pm.add_log("❌ Render video thất bại.")
                
        except ProcessStoppedException as e:
            pm.add_log(f"⏸️ {e}")
            break
        except Exception as e:
            pm.add_log(f"❌ Lỗi: {e}")
            logger.error(f"Pipeline error for {vid_name}: {e}", exc_info=True)
            continue

    # Kết thúc
    if not pm.should_stop():
        pm.add_log("🎊 ĐÃ HOÀN TẤT TOÀN BỘ!")
        pm.update_progress(1.0)
    pm.finish()


def start_pipeline_thread(
    video_paths: List[Path],
    settings: dict,
    workspace_dir: str,
    process_manager: ProcessManager
):
    """
    Khởi động pipeline trong background thread.
    Trả về thread object (lưu vào session_state).
    """
    # Chuyển Path thành str vì thread không share Streamlit context
    path_strings = [str(p) for p in video_paths]
    
    process_manager.start(total_videos=len(video_paths))
    
    thread = threading.Thread(
        target=_pipeline_worker,
        args=(path_strings, settings, workspace_dir, process_manager),
        daemon=True
    )
    thread.start()
    return thread
