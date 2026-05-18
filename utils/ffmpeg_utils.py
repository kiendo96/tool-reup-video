"""
FFmpeg Utilities — Tập trung hóa toàn bộ logic liên quan FFmpeg.

Cung cấp:
- get_ffmpeg_path() / get_ffprobe_path(): Tìm binary cục bộ hoặc fallback hệ thống.
- run_ffmpeg(cmd, process_manager): Wrapper chạy FFmpeg qua Popen, hỗ trợ force-stop.
"""

import os
import subprocess
from typing import List, Optional, TYPE_CHECKING
from utils.logger import setup_logger

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)

# Đường dẫn gốc project
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_BIN_DIR = os.path.join(_PROJECT_ROOT, 'bin', 'ffmpeg-master-latest-win64-gpl-shared', 'bin')


def get_ffmpeg_path() -> str:
    """Lấy đường dẫn tới ffmpeg.exe (cục bộ hoặc hệ thống)."""
    local_path = os.path.join(_BIN_DIR, 'ffmpeg.exe')
    return local_path if os.path.exists(local_path) else 'ffmpeg'


def get_ffprobe_path() -> str:
    """Lấy đường dẫn tới ffprobe.exe (cục bộ hoặc hệ thống)."""
    local_path = os.path.join(_BIN_DIR, 'ffprobe.exe')
    return local_path if os.path.exists(local_path) else 'ffprobe'


def run_ffmpeg(
    cmd: List[str],
    process_manager: Optional["ProcessManager"] = None,
    description: str = "FFmpeg"
) -> subprocess.CompletedProcess:
    """
    Chạy lệnh FFmpeg qua subprocess.Popen với hỗ trợ force-stop.
    
    Args:
        cmd: Danh sách lệnh FFmpeg (bao gồm đường dẫn ffmpeg.exe).
        process_manager: ProcessManager để đăng ký subprocess và kiểm tra force-stop.
        description: Mô tả ngắn cho log.
    
    Returns:
        subprocess.CompletedProcess — kết quả chạy lệnh.
    
    Raises:
        ProcessStoppedException: Nếu subprocess bị kill bởi force-stop.
    """
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    
    logger.debug(f"Đang chạy {description}: {' '.join(cmd[:6])}...")
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags
    )
    
    # Đăng ký với ProcessManager để có thể bị kill
    if process_manager:
        process_manager.register_subprocess(proc)
    
    try:
        stdout, stderr = proc.communicate()
    finally:
        if process_manager:
            process_manager.unregister_subprocess()
    
    # Kiểm tra nếu bị force-stop (returncode thường là -9 hoặc 1 khi bị kill)
    if process_manager and process_manager.should_stop() and proc.returncode != 0:
        from core.process_manager import ProcessStoppedException
        raise ProcessStoppedException(f"{description} bị dừng bởi người dùng.")
    
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr
    )
