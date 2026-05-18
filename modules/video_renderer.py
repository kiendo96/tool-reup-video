import os
import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from utils.logger import setup_logger
from utils.ffmpeg_utils import get_ffmpeg_path, run_ffmpeg
from utils.render_utils import generate_ass_subtitle, mix_tts_audios
from modules.visual_processor import VisualProcessor

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)

class VideoRenderer:
    """
    Module 5: Chịu trách nhiệm render video hoàn chỉnh.
    - Xử lý hình ảnh từ Module 4 (Che logo, sub, lật video).
    - Sinh Subtitle ASS (Hardsub).
    - Lấy nhạc nền gốc (giảm âm lượng).
    - Ghép đè Audio lồng tiếng (TTS).
    
    Tích hợp ProcessManager: Sử dụng run_ffmpeg() thay vì subprocess.run() 
    để có thể kill subprocess khi ép dừng.
    """
    def __init__(
        self, 
        workspace_dir: str = "workspace",
        process_manager: Optional["ProcessManager"] = None
    ):
        self.workspace_dir = Path(workspace_dir)
        self.output_dir = self.workspace_dir / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_path = get_ffmpeg_path()
        self.pm = process_manager

    def _check_stop(self):
        """Kiểm tra và raise nếu pipeline bị dừng."""
        if self.pm:
            self.pm.check_stop_and_raise()

    def render_video(self, 
                     original_video: str, 
                     tts_json_path: str,
                     bgm_volume: float = 0.05,
                     fast_preview: bool = True,
                     blur_sub: bool = True,
                     blur_logo: bool = True,
                     flip_video: bool = False,
                     speed_ratio: float = 1.0,
                     only_chinese_sub: bool = False) -> Optional[str]:
        """
        Thực thi render video kết hợp Xử lý hình ảnh (Module 4) và Render (Module 5).
        """
        if not os.path.exists(original_video) or not os.path.exists(tts_json_path):
            logger.error("Không tìm thấy Video gốc hoặc file JSON đồng bộ.")
            return None

        self._check_stop()
        video_name = Path(original_video).stem

        # 1. Gọi Module 4: Khởi tạo Visual Processor để phân tích và lấy chuỗi filter hình ảnh
        visual_proc = VisualProcessor(original_video)
        visual_filter_str = visual_proc.build_video_filter(
            blur_sub=blur_sub, 
            blur_logo=blur_logo, 
            flip=flip_video, 
            speed_ratio=speed_ratio
        )

        # 2. Đọc JSON và xử lý Subtitle ASS
        with open(tts_json_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)

        ass_path = str(self.output_dir / f"{video_name}.ass")
        if not generate_ass_subtitle(segments, ass_path, font_size=55, only_chinese_sub=only_chinese_sub):
            return None
            
        ass_path_escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:")

        # 3. Xử lý Audio Track (Mix toàn bộ TTS)
        self._check_stop()
        mixed_tts_wav = str(self.output_dir / f"{video_name}_mixed_tts.wav")
        logger.info("Đang ghép các file âm thanh lồng tiếng...")
        if not mix_tts_audios(segments, mixed_tts_wav, process_manager=self.pm):
            logger.error("Mix audio thất bại.")
            return None

        # 4. Chạy lệnh FFmpeg Render cuối cùng
        self._check_stop()
        final_video_path = str(self.output_dir / f"{video_name}_final.mp4")
        logger.info(f"Đang render video cuối cùng (Kết hợp Mod4 & Mod5. Preview: {fast_preview})...")
        
        # Cấu trúc chuỗi filter_complex
        v_filter = f"[0:v]{visual_filter_str},subtitles='{ass_path_escaped}'[vout]" if visual_filter_str else f"[0:v]subtitles='{ass_path_escaped}'[vout]"
        
        filter_complex_str = (
            f"[0:a]volume={bgm_volume}[a0];"  # Giảm nhạc nền
            f"[a0][1:a]amix=inputs=2:duration=longest:dropout_transition=0[aout];" # Trộn tiếng
            f"{v_filter}" # Xử lý hình + Chèn Sub
        )

        cmd = [
            self.ffmpeg_path, "-y",
            "-i", original_video,
            "-i", mixed_tts_wav,
            "-filter_complex", filter_complex_str,
            "-map", "[vout]",
            "-map", "[aout]"
        ]

        if fast_preview:
            cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-c:a", "aac", "-b:a", "96k"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "192k"])
            
        cmd.append(final_video_path)

        try:
            res = run_ffmpeg(cmd, process_manager=self.pm, description="Render Video")
            if res.returncode == 0 and os.path.exists(final_video_path):
                logger.info(f"QUÁ TRÌNH RENDER THÀNH CÔNG! File tại: {final_video_path}")
                # Xóa file tạm
                if os.path.exists(mixed_tts_wav):
                    os.remove(mixed_tts_wav)
                return final_video_path
            else:
                stderr_text = res.stderr.decode('utf-8', errors='replace') if isinstance(res.stderr, bytes) else str(res.stderr)
                logger.error(f"Lỗi Render Video FFmpeg:\n{stderr_text[-1000:]}")
                return None
        except Exception as e:
            from core.process_manager import ProcessStoppedException
            if isinstance(e, ProcessStoppedException):
                raise
            logger.error(f"Lỗi exception khi render: {e}")
            return None
