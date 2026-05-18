import os
import cv2
from utils.logger import setup_logger

logger = setup_logger(__name__)

class VisualProcessor:
    """
    Module 4: Xử lý hình ảnh video.
    Sử dụng OpenCV để phân tích khung hình video và tính toán vùng tọa độ.
    Sinh ra các filter FFmpeg để thao tác hình ảnh: che sub, che logo, lật, đổi tốc độ.
    """
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.width = 0
        self.height = 0
        self.fps = 0
        self._get_video_info()

    def _get_video_info(self):
        if not os.path.exists(self.video_path):
            logger.error(f"Không tìm thấy video: {self.video_path}")
            return
        try:
            cap = cv2.VideoCapture(self.video_path)
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            logger.info(f"VisualProcessor - Phân tích OpenCV thành công: {self.width}x{self.height} @ {self.fps}fps")
        except Exception as e:
            logger.error(f"Lỗi khi đọc video info qua OpenCV: {e}")

    def build_video_filter(self, 
                           blur_sub: bool = True, 
                           blur_logo: bool = True,
                           flip: bool = False,
                           speed_ratio: float = 1.0) -> str:
        """
        Xây dựng chuỗi video filter string cho FFmpeg.
        
        Args:
            blur_sub: Tạo dải đen mờ che vùng Subtitle tiếng Trung gốc (đáy video).
            blur_logo: Dùng thuật toán delogo che watermark Tiktok/Douyin (góc trên trái & dưới phải).
            flip: Lật ngang video (Lách bản quyền hình ảnh).
            speed_ratio: Thay đổi tốc độ video hình (vd: 1.05 = tăng tốc 5%).
        """
        filters = []
        
        # 1. Thay đổi tốc độ video
        if speed_ratio != 1.0 and speed_ratio > 0:
            # Lệnh setpts trong FFmpeg. VD speed 1.05 -> pts * (1/1.05)
            pts_ratio = 1.0 / speed_ratio
            filters.append(f"setpts={pts_ratio}*PTS")

        # 2. Lật ngang video
        if flip:
            filters.append("hflip")

        # 3. Che Logo Douyin/TikTok (Delogo blur thông minh)
        # Tiktok thường có 2 logo di chuyển: Góc trái trên và góc phải dưới.
        if blur_logo and self.width > 0 and self.height > 0:
            # Tọa độ logo 1 (Góc trái trên)
            logo1_w = int(self.width * 0.35)
            logo1_h = int(self.height * 0.08)
            logo1_x = int(self.width * 0.02)
            logo1_y = int(self.height * 0.02)
            filters.append(f"delogo=x={logo1_x}:y={logo1_y}:w={logo1_w}:h={logo1_h}")
            
            # Tọa độ logo 2 (Góc phải dưới)
            logo2_w = int(self.width * 0.35)
            logo2_h = int(self.height * 0.08)
            logo2_x = int(self.width * 0.63)
            logo2_y = int(self.height * 0.88)
            filters.append(f"delogo=x={logo2_x}:y={logo2_y}:w={logo2_w}:h={logo2_h}")

        # 4. Che Sub tiếng Trung (Dùng dải màu đen trong suốt - opacity 0.8)
        # Sub thường nằm ở 15% đáy video
        if blur_sub and self.width > 0 and self.height > 0:
            box_x = 0
            box_y = int(self.height * 0.80) # Bắt đầu từ 80% chiều cao
            box_w = self.width
            box_h = int(self.height * 0.18) # Kéo dài 18%
            # Dùng drawbox t=fill để tạo dải đen đè lên sub
            filters.append(f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.85:t=fill")

        return ",".join(filters) if filters else ""
