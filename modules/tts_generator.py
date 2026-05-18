import os
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING
from tqdm import tqdm

from utils.logger import setup_logger
from utils.audio_utils import align_audio_to_duration, create_silence_audio
from utils.tts_utils import TTSFactory, get_audio_duration

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)

# Thời gian chờ giữa mỗi lần gọi Edge TTS (giây) để tránh bị rate-limit
TTS_THROTTLE_DELAY = 1.0


class TTSGenerator:
    """
    Module xử lý việc tạo giọng đọc (Voice Over) từ file JSON đã dịch.
    Đồng bộ thời gian (Timing Sync): Tự động tăng tốc độ đọc (rate) nếu câu tiếng Việt dài hơn thời gian cho phép.
    Tích hợp ProcessManager để hỗ trợ dừng/ép dừng giữa chừng.
    
    Cải tiến:
    - Smart Skip kiểm tra file corrupted (duration=0, size<100 bytes) → xóa và tạo lại.
    - Throttle 0.3s giữa mỗi request để tránh bị Microsoft rate-limit.
    """
    def __init__(
        self, 
        engine_type: str = "edge",
        voice: str = "vi-VN-HoaiMyNeural",
        workspace_dir: str = "workspace",
        process_manager: Optional["ProcessManager"] = None,
        max_speed_increase: int = 50
    ):
        self.workspace_dir = Path(workspace_dir)
        self.tts_dir = self.workspace_dir / "tts_audios"
        self.tts_dir.mkdir(parents=True, exist_ok=True)
        self.pm = process_manager
        self.max_speed_increase = max_speed_increase
        
        self.tts_engine = TTSFactory.get_engine(engine_type, voice=voice)
        logger.info(f"Khởi tạo TTSGenerator. Engine: {engine_type}, Giọng: {voice}")

    def _check_stop(self):
        """Kiểm tra và raise nếu pipeline bị dừng."""
        if self.pm:
            self.pm.check_stop_and_raise()

    def _is_valid_audio(self, file_path: str) -> bool:
        """Kiểm tra file audio có hợp lệ không (không rỗng, không corrupted)."""
        if not os.path.exists(file_path):
            return False
        # File MP3 hợp lệ ít nhất vài trăm bytes
        if os.path.getsize(file_path) < 100:
            return False
        # Kiểm tra duration
        duration = get_audio_duration(file_path)
        return duration > 0

    def _make_silence_segment(self, seg: Dict, output_path: str, target_duration: float, reason: str) -> Dict:
        """Create silence fallback so the timeline never has holes."""
        if os.path.exists(output_path):
            os.remove(output_path)
        ok = create_silence_audio(output_path, target_duration, process_manager=self.pm)
        if ok:
            seg["tts_audio_path"] = output_path
            seg["tts_duration"] = round(get_audio_duration(output_path), 2)
            seg["tts_target_duration"] = round(target_duration, 2)
            seg["tts_align_action"] = "silence"
            seg["tts_fallback_reason"] = reason
        else:
            seg["tts_audio_path"] = None
            seg["tts_duration"] = 0
            seg["tts_target_duration"] = round(target_duration, 2)
            seg["tts_align_action"] = "failed"
            seg["tts_fallback_reason"] = reason
        return seg

    def process_transcript(self, transcript_json_path: str) -> Optional[str]:
        """
        Đọc file JSON và tạo ra các file mp3 nhỏ cho từng câu.
        
        Cơ chế Smart Skip cải tiến:
        - Nếu file audio đã tồn tại VÀ hợp lệ (size>100 bytes, duration>0) → skip.
        - Nếu file tồn tại nhưng corrupted → xóa và tạo lại.
        """
        if not os.path.exists(transcript_json_path):
            logger.error(f"Không tìm thấy file JSON: {transcript_json_path}")
            return None
            
        with open(transcript_json_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
            
        logger.info(f"Bắt đầu xử lý TTS cho {len(segments)} câu...")
        
        # Tạo folder riêng cho video và theo từng giọng đọc để tránh chồng lấn khi đổi voice
        video_name = Path(transcript_json_path).stem.replace("_transcript", "")
        # Lấy tên ngắn của voice (vd: vi-VN-HoaiMyNeural)
        voice_short = self.tts_engine.voice if hasattr(self.tts_engine, 'voice') else "default"
        
        video_tts_dir = self.tts_dir / video_name / voice_short
        video_tts_dir.mkdir(parents=True, exist_ok=True)
        
        updated_segments = []
        skip_count = 0
        fail_count = 0
        
        for i, seg in enumerate(tqdm(segments, desc=f"TTS Process ({voice_short})")):
            # Kiểm tra dừng trước mỗi câu TTS
            self._check_stop()
            
            text_vi = seg.get("text_vi", "").strip()
            target_duration = max(0.1, float(seg.get("end", 0)) - float(seg.get("start", 0)))
            audio_filename = f"seg_{i:04d}.mp3"
            output_path = str(video_tts_dir / audio_filename)

            if not text_vi or text_vi == "[Lỗi dịch thuật]" or text_vi.startswith("[Lỗi"):
                fail_count += 1
                logger.warning(f"Câu {i} không có text TTS hợp lệ, tạo silence fallback.")
                updated_segments.append(self._make_silence_segment(seg, output_path, target_duration, "invalid_text"))
                continue
            
            # --- CƠ CHẾ SMART SKIP (Cải tiến: kiểm tra file corrupted) ---
            if os.path.exists(output_path):
                if self._is_valid_audio(output_path):
                    # File hợp lệ → skip
                    ok, final_duration, action = align_audio_to_duration(
                        output_path,
                        output_path,
                        target_duration,
                        max_speed_increase=self.max_speed_increase,
                        process_manager=self.pm,
                    )
                    if ok:
                        seg["tts_audio_path"] = output_path
                        seg["tts_duration"] = round(final_duration, 2)
                        seg["tts_target_duration"] = round(target_duration, 2)
                        seg["tts_align_action"] = f"cached+{action}" if action != "original" else "cached"
                        skip_count += 1
                        updated_segments.append(seg)
                        continue
                    logger.warning(f"File cache không align được, đang tạo lại: {audio_filename}")
                    os.remove(output_path)
                else:
                    # File corrupted → xóa và tạo lại
                    logger.warning(f"File corrupted, đang tạo lại: {audio_filename}")
                    os.remove(output_path)

            # Throttle để tránh bị Edge TTS rate-limit
            time.sleep(TTS_THROTTLE_DELAY)

            # Sinh audio mới
            success = self.tts_engine.generate_audio(text_vi, output_path, rate="+0%")
            
            if success and self._is_valid_audio(output_path):
                ok, final_duration, action = align_audio_to_duration(
                    output_path,
                    output_path,
                    target_duration,
                    max_speed_increase=self.max_speed_increase,
                    process_manager=self.pm,
                )
                if ok:
                    seg["tts_audio_path"] = output_path
                    seg["tts_duration"] = round(final_duration, 2)
                    seg["tts_target_duration"] = round(target_duration, 2)
                    seg["tts_align_action"] = action
                    if final_duration > target_duration + 0.2:
                        logger.warning(
                            f"Câu {i} vẫn dài hơn slot sau align: {final_duration:.2f}s > {target_duration:.2f}s"
                        )
                else:
                    fail_count += 1
                    logger.error(f"Không align được TTS cho câu {i}, tạo silence fallback.")
                    seg = self._make_silence_segment(seg, output_path, target_duration, "align_failed")
            else:
                fail_count += 1
                logger.error(f"Thất bại tạo TTS cho câu {i}: '{text_vi[:50]}...'. Tạo silence fallback.")
                if os.path.exists(output_path):
                    os.remove(output_path)
                seg = self._make_silence_segment(seg, output_path, target_duration, "tts_failed")
                
            updated_segments.append(seg)
            
        if skip_count > 0:
            logger.info(f"✅ Đã sử dụng lại {skip_count} file audio cũ từ cache.")
        if fail_count > 0:
            logger.warning(f"⚠️ Có {fail_count} câu TTS thất bại.")
            
        output_json = video_tts_dir / f"{video_name}_tts_sync.json"
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(updated_segments, f, ensure_ascii=False, indent=2)
            
        return str(output_json)
