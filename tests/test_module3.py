import os
from pathlib import Path
from modules.tts_generator import TTSGenerator
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_module3():
    print("="*50)
    print("BẮT ĐẦU TEST MODULE 3: TEXT-TO-SPEECH (TTS)")
    print("="*50)

    # 1. Tìm file JSON transcript từ Module 2
    transcript_dir = Path("workspace_test/transcripts")
    transcript_file = None
    
    if transcript_dir.exists():
        # Tìm file .json đầu tiên
        files = list(transcript_dir.glob("*.json"))
        if files:
            transcript_file = files[0]
            
    if not transcript_file:
        print(f"\nKhông tìm thấy file JSON nào trong {transcript_dir}.")
        print("Vui lòng chạy 'test_module2.py' trước để tạo file transcript dịch thuật.")
        return

    print(f"\nSử dụng file Transcript để tạo giọng đọc: {transcript_file.name}")

    # 2. Khởi tạo TTS Generator
    print("\nKhởi tạo TTSGenerator với Edge-TTS (Giọng: Nữ - Hoài My)...")
    # Bạn có thể thử đổi voice thành "vi-VN-NamMinhNeural" cho giọng nam
    generator = TTSGenerator(
        engine_type="edge",
        voice="vi-VN-HoaiMyNeural", 
        workspace_dir="workspace_test"
    )

    # 3. Chạy quá trình sinh Audio và tự động ép Timing
    print("\nBắt đầu sinh file âm thanh và đồng bộ thời gian (Tự động tăng tốc nếu câu quá dài)...")
    output_json_path = generator.process_transcript(str(transcript_file))

    print("\n" + "="*50)
    if output_json_path:
        print("HOÀN TẤT TẠO LỒNG TIẾNG (VOICE OVER)!")
        video_name = transcript_file.stem.replace("_transcript", "")
        audio_dir = Path("workspace_test/tts_audios") / video_name
        
        print(f"Các file audio nhỏ (mp3) đã được lưu tại thư mục: {audio_dir}")
        print(f"File cấu hình đồng bộ (để dùng cho Module sau) đã lưu tại: {output_json_path}")
        print("\nBạn có thể mở thư mục trên và nghe thử vài file mp3 xem giọng đọc và tốc độ có ổn không nhé!")
    else:
        print("Quá trình sinh TTS thất bại.")
    print("="*50)

if __name__ == "__main__":
    test_module3()
