import os
from pathlib import Path
from typing import List, Union
from tqdm import tqdm
from utils.logger import setup_logger
from utils.video_utils import download_video_ytdlp, extract_audio_ffmpeg

logger = setup_logger(__name__)

class MediaProcessor:
    """
    Class xử lý hàng loạt media: Tải video từ link, quét folder, và tách audio.
    """
    def __init__(self, workspace_dir: str = "workspace"):
        """
        Khởi tạo MediaProcessor.
        
        Args:
            workspace_dir (str): Thư mục gốc chứa video và audio.
        """
        self.workspace_dir = Path(workspace_dir)
        self.video_dir = self.workspace_dir / "videos"
        self.audio_dir = self.workspace_dir / "audios"
        
        # Tạo sẵn cấu trúc thư mục
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Khởi tạo MediaProcessor. Workspace: {self.workspace_dir}")

    def process_links(self, urls: List[str], audio_format: str = 'wav') -> dict:
        """
        Xử lý một danh sách URL video (tải về và tách audio).
        
        Args:
            urls (List[str]): Danh sách các đường dẫn.
            audio_format (str): Định dạng audio (wav hoặc mp3).
            
        Returns:
            dict: Thống kê số lượng thành công và thất bại.
        """
        logger.info(f"Bắt đầu xử lý {len(urls)} links...")
        results = {"success": 0, "failed": 0, "details": []}
        
        for url in tqdm(urls, desc="Processing Links"):
            logger.info(f"Đang xử lý link: {url}")
            video_path = download_video_ytdlp(url, str(self.video_dir))
            
            if not video_path:
                logger.error(f"Không thể tải video từ: {url}")
                results["failed"] += 1
                results["details"].append({"url": url, "status": "download_failed"})
                continue
                
            # Tạo tên file audio tương ứng
            video_name = Path(video_path).stem
            audio_path = str(self.audio_dir / f"{video_name}.{audio_format}")
            
            success = extract_audio_ffmpeg(video_path, audio_path, audio_format)
            if success:
                results["success"] += 1
                results["details"].append({"url": url, "status": "success", "audio": audio_path})
            else:
                results["failed"] += 1
                results["details"].append({"url": url, "status": "audio_extract_failed"})
                
        logger.info(f"Hoàn thành xử lý Links. Thành công: {results['success']}, Thất bại: {results['failed']}")
        return results

    def process_directory(self, input_dir: str, audio_format: str = 'wav') -> dict:
        """
        Quét thư mục, tìm các file video local và tách audio.
        
        Args:
            input_dir (str): Thư mục chứa file mp4.
            audio_format (str): Định dạng audio.
            
        Returns:
            dict: Thống kê xử lý.
        """
        dir_path = Path(input_dir)
        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"Thư mục không tồn tại: {input_dir}")
            return {"success": 0, "failed": 0, "error": "Directory not found"}

        # Hỗ trợ nhiều định dạng video phổ biến
        valid_extensions = {'.mp4', '.mkv', '.mov', '.avi'}
        video_files = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions]
        
        logger.info(f"Tìm thấy {len(video_files)} video trong thư mục {input_dir}")
        results = {"success": 0, "failed": 0, "details": []}
        
        for video_path in tqdm(video_files, desc="Processing Local Files"):
            logger.info(f"Đang xử lý file: {video_path.name}")
            
            audio_path = str(self.audio_dir / f"{video_path.stem}.{audio_format}")
            success = extract_audio_ffmpeg(str(video_path), audio_path, audio_format)
            
            if success:
                results["success"] += 1
                results["details"].append({"file": video_path.name, "status": "success", "audio": audio_path})
            else:
                results["failed"] += 1
                results["details"].append({"file": video_path.name, "status": "failed"})
                
        logger.info(f"Hoàn thành quét Directory. Thành công: {results['success']}, Thất bại: {results['failed']}")
        return results
