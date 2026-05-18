"""
ProcessManager — Quản lý vòng đời pipeline xử lý video.

Cơ chế:
- Graceful Stop: Set _stop_event → Pipeline kiểm tra trước mỗi bước → Dừng sau bước hiện tại
- Force Stop: Set _force_stop_event → Kill subprocess đang chạy → Dừng ngay lập tức

Trạng thái: IDLE → RUNNING → (STOPPING | FORCE_STOPPING) → IDLE

Giao tiếp UI:
- add_log() / get_logs(): Background thread ghi log, UI thread đọc log
- set_result_video() / get_result_video(): Truyền kết quả video về UI
"""

import threading
import subprocess
from typing import Optional, List
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ProcessStoppedException(Exception):
    """Exception được raise khi pipeline bị dừng bởi người dùng."""
    pass


class ProcessManager:
    """
    Singleton quản lý trạng thái chạy/dừng của toàn bộ pipeline.
    Thread-safe: có thể gọi stop/force_stop từ UI thread trong khi pipeline chạy ở worker thread.
    
    Giao tiếp giữa background thread và UI:
    - Logs: background thread gọi add_log(), UI thread gọi get_logs()
    - Result: background thread gọi set_result_video(), UI thread gọi get_result_video()
    """

    # Các trạng thái hợp lệ
    STATUS_IDLE = "IDLE"
    STATUS_RUNNING = "RUNNING"
    STATUS_STOPPING = "STOPPING"
    STATUS_FORCE_STOPPING = "FORCE_STOPPING"

    def __init__(self):
        self._stop_event = threading.Event()
        self._force_stop_event = threading.Event()
        self._lock = threading.Lock()
        self._status = self.STATUS_IDLE
        self._current_subprocess: Optional[subprocess.Popen] = None
        self._current_step = ""
        self._current_video_index = 0
        self._total_videos = 0
        self._progress = 0.0  # 0.0 → 1.0
        
        # Giao tiếp UI ↔ Background thread
        self._logs: List[str] = []
        self._result_video: Optional[str] = None

    # --- Trạng thái ---

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def current_step(self) -> str:
        with self._lock:
            return self._current_step

    @property
    def progress(self) -> float:
        with self._lock:
            return self._progress

    @property
    def is_running(self) -> bool:
        return self.status in (self.STATUS_RUNNING, self.STATUS_STOPPING, self.STATUS_FORCE_STOPPING)

    @property
    def is_idle(self) -> bool:
        return self.status == self.STATUS_IDLE

    # --- Điều khiển Pipeline ---

    def start(self, total_videos: int = 1):
        """Bắt đầu pipeline mới. Reset toàn bộ signal và logs."""
        with self._lock:
            self._stop_event.clear()
            self._force_stop_event.clear()
            self._status = self.STATUS_RUNNING
            self._current_subprocess = None
            self._current_step = "Đang khởi tạo..."
            self._current_video_index = 0
            self._total_videos = total_videos
            self._progress = 0.0
            self._logs = []
            self._result_video = None
        logger.info(f"ProcessManager: Pipeline BẮT ĐẦU ({total_videos} video)")

    def stop(self):
        """
        Dừng nhẹ (Graceful Stop).
        Pipeline sẽ hoàn thành bước hiện tại rồi dừng.
        """
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return
            self._status = self.STATUS_STOPPING
        self._stop_event.set()
        logger.info("ProcessManager: Yêu cầu DỪNG (Graceful Stop)")

    def force_stop(self):
        """
        Ép dừng (Force Stop).
        Kill ngay subprocess đang chạy (FFmpeg, etc.) và dừng pipeline.
        """
        with self._lock:
            if self._status not in (self.STATUS_RUNNING, self.STATUS_STOPPING):
                return
            self._status = self.STATUS_FORCE_STOPPING
        self._stop_event.set()
        self._force_stop_event.set()
        self._kill_current_subprocess()
        logger.info("ProcessManager: Yêu cầu ÉP DỪNG (Force Stop)")

    def finish(self):
        """Đánh dấu pipeline đã hoàn tất hoặc đã dừng xong."""
        with self._lock:
            prev_status = self._status
            self._status = self.STATUS_IDLE
            self._current_subprocess = None
        logger.info(f"ProcessManager: Pipeline KẾT THÚC (trạng thái trước: {prev_status})")

    # --- Kiểm tra Signal (Gọi từ bên trong modules) ---

    def should_stop(self) -> bool:
        """
        Kiểm tra xem pipeline có nên dừng không.
        Gọi hàm này trước mỗi bước nhỏ trong pipeline.
        """
        return self._stop_event.is_set()

    def check_stop_and_raise(self):
        """
        Kiểm tra và raise exception nếu cần dừng.
        Dùng ở đầu mỗi bước trong pipeline.
        """
        if self._force_stop_event.is_set():
            raise ProcessStoppedException("Pipeline bị ÉP DỪNG bởi người dùng.")
        if self._stop_event.is_set():
            raise ProcessStoppedException("Pipeline bị DỪNG bởi người dùng.")

    # --- Subprocess Management ---

    def register_subprocess(self, proc: subprocess.Popen):
        """Đăng ký subprocess đang chạy (FFmpeg, etc.) để có thể kill khi force stop."""
        with self._lock:
            self._current_subprocess = proc
        # Nếu force stop đã được yêu cầu trước khi subprocess chạy → kill ngay
        if self._force_stop_event.is_set():
            self._kill_current_subprocess()

    def unregister_subprocess(self):
        """Hủy đăng ký subprocess sau khi nó kết thúc."""
        with self._lock:
            self._current_subprocess = None

    def _kill_current_subprocess(self):
        """Kill subprocess đang chạy."""
        with self._lock:
            proc = self._current_subprocess
        if proc and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
                logger.info("ProcessManager: Đã KILL subprocess đang chạy.")
            except Exception as e:
                logger.warning(f"ProcessManager: Lỗi khi kill subprocess: {e}")

    # --- Cập nhật Progress (Gọi từ pipeline_runner) ---

    def update_step(self, step_name: str):
        """Cập nhật tên bước hiện tại."""
        with self._lock:
            self._current_step = step_name

    def update_progress(self, progress: float):
        """Cập nhật tiến trình (0.0 → 1.0)."""
        with self._lock:
            self._progress = min(max(progress, 0.0), 1.0)

    def set_video_index(self, index: int):
        """Cập nhật video đang xử lý."""
        with self._lock:
            self._current_video_index = index

    def get_status_display(self) -> str:
        """Trả về chuỗi trạng thái để hiển thị trên UI."""
        with self._lock:
            s = self._status
            step = self._current_step
            idx = self._current_video_index
            total = self._total_videos
        
        if s == self.STATUS_IDLE:
            return "⏹️ Sẵn sàng"
        elif s == self.STATUS_RUNNING:
            return f"▶️ [{idx+1}/{total}] {step}"
        elif s == self.STATUS_STOPPING:
            return f"⏸️ Đang dừng... (chờ bước hiện tại: {step})"
        elif s == self.STATUS_FORCE_STOPPING:
            return "🛑 Đang ép dừng..."
        return s

    # --- Giao tiếp UI ↔ Background Thread ---

    def add_log(self, message: str):
        """Thêm log message (gọi từ background thread)."""
        with self._lock:
            self._logs.append(message)
        logger.info(f"Pipeline: {message}")

    def get_logs(self) -> List[str]:
        """Lấy toàn bộ logs (gọi từ UI thread)."""
        with self._lock:
            return list(self._logs)

    def set_result_video(self, video_path: str):
        """Lưu đường dẫn video kết quả (gọi từ background thread)."""
        with self._lock:
            self._result_video = video_path

    def get_result_video(self) -> Optional[str]:
        """Lấy đường dẫn video kết quả (gọi từ UI thread)."""
        with self._lock:
            return self._result_video

