import os
from pathlib import Path
from typing import Optional
import yt_dlp

from utils.logger import setup_logger
from utils.ffmpeg_utils import get_ffmpeg_path

logger = setup_logger(__name__)


def download_video_ytdlp(url: str, output_dir: str) -> Optional[str]:
    """
    Tải video từ URL (TikTok, YouTube, Facebook, v.v.) bằng yt-dlp.
    (Không hỗ trợ Douyin tự động do chính sách nền tảng).
    
    Args:
        url (str): Link video
        output_dir (str): Thư mục lưu file
        
    Returns:
        Optional[str]: Đường dẫn tới file video đã tải, None nếu lỗi
    """
    if "douyin.com" in url:
        logger.warning("Tính năng tải Douyin tự động hiện không được hỗ trợ.")
        logger.warning("Vui lòng tải video Douyin thủ công và sử dụng tính năng xử lý file local.")
        return None

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        # Tránh tải playlist
        'noplaylist': True,
        'nocheckcertificate': True,
        # Hỗ trợ lấy cookies từ Chrome cho các trang web khác (YouTube, Tiktok) nếu cần
        'cookiesfrombrowser': ('chrome',), 
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.debug(f"Đang phân tích link: {url}")
            info = ydl.extract_info(url, download=True)
            if info:
                # Tìm đường dẫn file đã tải (đôi khi yt-dlp lưu mp4 hoặc mkv)
                ext = info.get('ext', 'mp4')
                video_id = info.get('id', 'video')
                file_path = os.path.join(output_dir, f"{video_id}.{ext}")
                
                # Trong vài trường hợp yt_dlp gộp file và đổi đuôi thành mkv
                expected_path_mkv = os.path.join(output_dir, f"{video_id}.mkv")
                if os.path.exists(expected_path_mkv):
                    file_path = expected_path_mkv
                    
                if os.path.exists(file_path):
                    logger.info(f"Đã tải thành công: {file_path}")
                    return file_path
                else:
                    logger.error("Đã tải nhưng không tìm thấy file đầu ra.")
            return None
    except Exception as e:
        logger.error(f"Lỗi khi tải video từ {url}: {str(e)}")
        return None


def extract_audio_ffmpeg(video_path: str, output_audio_path: str, audio_format: str = 'wav') -> bool:
    """
    Trích xuất audio gốc từ file video bằng FFmpeg.
    Lưu ý: FFmpeg chỉ lấy audio track có sẵn. Để tách giọng nói khỏi nhạc nền (BGM),
    cần dùng AI (như Demucs/UVR) ở module xử lý âm thanh riêng.
    
    Args:
        video_path (str): Đường dẫn file video
        output_audio_path (str): Đường dẫn file audio đầu ra
        audio_format (str): Định dạng (wav hoặc mp3)
        
    Returns:
        bool: True nếu thành công, False nếu thất bại
    """
    import subprocess
    
    if not os.path.exists(video_path):
        logger.error(f"File video không tồn tại: {video_path}")
        return False

    Path(output_audio_path).parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_path = get_ffmpeg_path()

    try:
        # Cấu hình lệnh FFmpeg tùy theo định dạng
        if audio_format.lower() == 'wav':
            # PCM 16-bit, 44100 Hz, stereo (chuẩn audio chất lượng cao)
            cmd = [
                ffmpeg_path, '-y', '-i', video_path,
                '-vn', # Không lấy video
                '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                output_audio_path
            ]
        else:
            # MP3 chất lượng cao (VBR)
            cmd = [
                ffmpeg_path, '-y', '-i', video_path,
                '-vn', 
                '-q:a', '0', 
                output_audio_path
            ]
            
        logger.debug(f"Đang chạy FFmpeg: {' '.join(cmd)}")
        
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            creationflags=creation_flags
        )
        
        if result.returncode == 0 and os.path.exists(output_audio_path):
            logger.info(f"Đã tách audio thành công: {output_audio_path}")
            return True
        else:
            logger.error(f"Lỗi FFmpeg: {result.stderr}")
            return False
            
    except FileNotFoundError:
        logger.error("Không tìm thấy lệnh FFmpeg trong hệ thống. Vui lòng cài đặt FFmpeg và thêm vào PATH.")
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi tách audio: {str(e)}")
        return False
