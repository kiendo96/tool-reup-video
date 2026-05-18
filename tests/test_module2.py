import os
from pathlib import Path
from modules.transcription_translator import TranscriptionTranslator
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_module2():
    print("="*50)
    print("BẮT ĐẦU TEST MODULE 2: TRANSCRIPTION & TRANSLATION")
    print("="*50)
    
    # 1. Yêu cầu chọn Engine Dịch thuật
    print("Chọn công cụ dịch thuật:")
    print("1. Gemini API (Cần mạng & API Key - Khuyên dùng vì dịch rất thông minh)")
    print("2. Local Offline (Không cần mạng - Chạy bằng CPU/GPU qua HuggingFace)")
    choice = input("Nhập lựa chọn của bạn (1 hoặc 2) [Mặc định: 1]: ").strip()
    
    translator_type = "local" if choice == "2" else "gemini"
    api_key = ""
    
    if translator_type == "gemini":
        api_key = input("Vui lòng nhập Gemini API Key của bạn (hoặc nhấn Enter nếu đã set biến môi trường GEMINI_API_KEY): ").strip()
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY", "")
            if not api_key:
                print("LỖI: Bạn cần cung cấp Gemini API Key để test dịch bằng Gemini.")
                return

    # 2. Xử lý Cache
    cache_path = Path("workspace_test/cache.db")
    if cache_path.exists():
        print(f"\nPhát hiện file cache tồn tại ({cache_path}).")
        print("Nếu bạn muốn dịch lại từ đầu (để sửa lỗi dịch cũ), hãy chọn xóa cache.")
        clear_cache = input("Bạn có muốn xóa cache cũ không? (y/n) [Mặc định: n]: ").strip().lower()
        if clear_cache == 'y':
            try:
                os.remove(cache_path)
                print("Đã xóa file cache. Hệ thống sẽ nhận diện và dịch lại từ đầu.")
            except Exception as e:
                print(f"Không thể xóa cache: {e}")
        else:
            print("Giữ nguyên cache. Hệ thống sẽ bỏ qua các câu đã dịch trước đó.")

    # 3. Tìm một file audio để test
    test_audio_dir = Path("workspace_test/audios")
    test_audio_file = None
    
    if test_audio_dir.exists():
        # Tìm file .wav hoặc .mp3 đầu tiên
        for ext in ['.wav', '.mp3']:
            files = list(test_audio_dir.glob(f"*{ext}"))
            if files:
                test_audio_file = files[0]
                break
                
    if not test_audio_file:
        print(f"\nKhông tìm thấy file audio nào trong {test_audio_dir}.")
        print("Vui lòng chạy 'test_module1.py' trước để tạo file audio, hoặc nhập đường dẫn tới một file audio (.mp3, .wav) có tiếng Trung: ")
        custom_path = input("Đường dẫn file audio: ").strip()
        if custom_path and os.path.exists(custom_path):
            test_audio_file = Path(custom_path)
        else:
            print("Đường dẫn không hợp lệ. Kết thúc test.")
            return

    print(f"\nSử dụng file audio để test: {test_audio_file}")

    # 3. Khởi tạo class xử lý
    # Lưu ý: Lần đầu tiên chạy, faster-whisper sẽ tải model (khoảng 1.5GB cho base, >2GB cho large-v3)
    # Để test nhanh, tôi set mặc định dùng model "base" hoặc "tiny". Bạn có thể đổi lại "large-v3" ở production
    print("\nKhởi tạo TranscriptionTranslator (Đang tải model Whisper, có thể mất vài phút lần đầu)...")
    translator = TranscriptionTranslator(
        translator_type=translator_type,
        api_key=api_key,
        whisper_model_size="base", # Dùng 'base' để test nhanh. Đổi thành 'large-v3' khi chạy thật
        translation_model="gemini-2.5-flash", # Sử dụng model Gemini hợp lệ
        workspace_dir="workspace_test"
    )

    # 4. Xử lý file
    print("\nBắt đầu quá trình nhận diện và dịch thuật...")
    results = translator.process_file(str(test_audio_file))

    print("\n" + "="*50)
    if results:
        print("KẾT QUẢ TRÍCH XUẤT VÀ DỊCH THUẬT (5 câu đầu):")
        for i, res in enumerate(results[:5]):
            print(f"[{res['start']}s - {res['end']}s]")
            print(f"🇨🇳 ZH: {res['text_zh']}")
            print(f"🇻🇳 VI: {res['text_vi']}")
            print("-" * 30)
        
        if len(results) > 5:
            print(f"... và {len(results) - 5} câu khác.")
            
        print(f"\nFile JSON đầy đủ đã được lưu tại: workspace_test/transcripts/{test_audio_file.stem}_transcript.json")
        print("Cơ sở dữ liệu Cache (SQLite) đã được lưu tại: workspace_test/cache.db")
    else:
        print("Quá trình xử lý thất bại hoặc không có kết quả.")
    print("="*50)

if __name__ == "__main__":
    test_module2()
