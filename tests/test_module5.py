import os
from pathlib import Path
from modules.video_renderer import VideoRenderer
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_module5():
    print("="*50)
    print("BẮT ĐẦU TEST MODULE 5: RENDER VIDEO (GHÉP SUB & LỒNG TIẾNG)")
    print("="*50)

    # 1. Tìm video gốc và file JSON đồng bộ
    videos_dir = Path("workspace_test/videos")
    tts_dir = Path("workspace_test/tts_audios")
    
    original_video = None
    tts_json = None
    
    if videos_dir.exists():
        video_files = list(videos_dir.glob("*.mp4"))
        if video_files:
            original_video = video_files[0]
            
            # Tìm folder tts tương ứng
            video_tts_dir = tts_dir / original_video.stem
            if video_tts_dir.exists():
                json_files = list(video_tts_dir.glob("*_tts_sync.json"))
                if json_files:
                    tts_json = json_files[0]

    if not original_video or not tts_json:
        print(f"LỖI: Không tìm thấy video mp4 trong {videos_dir} hoặc file JSON TTS trong {tts_dir}.")
        print("Vui lòng chạy tuần tự từ Module 1 -> 2 -> 3 trước khi test Render.")
        return

    print(f"\nSử dụng Video gốc: {original_video.name}")
    print(f"Sử dụng cấu hình lồng tiếng: {tts_json.name}")

    # 2. Khởi tạo Renderer
    print("\nKhởi tạo VideoRenderer...")
    renderer = VideoRenderer(workspace_dir="workspace_test")

    # 3. Yêu cầu chế độ Render và Xử lý hình ảnh
    print("\n[TÙY CHỌN HÌNH ẢNH - MODULE 4]")
    flip_choice = input("Bạn có muốn lật ngang video (Lách bản quyền)? (y/n) [Mặc định: n]: ").strip().lower()
    flip_video = True if flip_choice == 'y' else False
    
    blur_choice = input("Bạn có muốn che Sub tiếng Trung và che Logo watermark không? (y/n) [Mặc định: y]: ").strip().lower()
    blur_sub_logo = False if blur_choice == 'n' else True

    print("\n[CHẾ ĐỘ RENDER - MODULE 5]")
    print("1. Preview Nhanh (Render siêu tốc, mờ, để xem thử sub và tiếng)")
    print("2. Bản Chính Thức (Chất lượng cao, sắc nét, tốn thời gian hơn)")
    choice = input("Nhập (1 hoặc 2) [Mặc định: 1]: ").strip()
    is_fast = True if choice != "2" else False

    # 4. Thực thi Render
    print("\nĐang xử lý Hình ảnh & Render (Quá trình này phụ thuộc vào độ dài video và sức mạnh máy tính)...")
    final_video = renderer.render_video(
        original_video=str(original_video),
        tts_json_path=str(tts_json),
        bgm_volume=0.05, # Giảm âm lượng video gốc xuống còn 5% làm nhạc nền nhỏ
        fast_preview=is_fast,
        blur_sub=blur_sub_logo,
        blur_logo=blur_sub_logo,
        flip_video=flip_video
    )

    print("\n" + "="*50)
    if final_video:
        print(f"🎉 THÀNH CÔNG RỰC RỠ! Đã render xong video!")
        print(f"📂 Xem thành quả tại: {final_video}")
        print("Bạn có thể mở video này lên để xem phụ đề (viền đen đẹp) và nghe giọng đọc lồng tiếng đè lên nhạc nền gốc!")
    else:
        print("Render thất bại. Vui lòng xem file log để biết nguyên nhân.")
    print("="*50)

if __name__ == "__main__":
    test_module5()
