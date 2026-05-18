import os
from modules.audio_extractor import MediaProcessor
from utils.logger import setup_logger

logger = setup_logger(__name__)

def test_module1():
    print("="*50)
    print("BẮT ĐẦU TEST MODULE 1: DOWNLOADER & AUDIO EXTRACTOR")
    print("="*50)
    
    # Khởi tạo MediaProcessor, nó sẽ tự tạo thư mục workspace/videos và workspace/audios
    processor = MediaProcessor(workspace_dir="workspace_test")
    
    # Cách 1: Test tải video từ link
    print("\n--- Test 1: Tải video từ link TikTok/Douyin ---")
    test_urls = [
        # Bạn có thể thay bằng link TikTok hoặc Douyin thật để test
        "https://www.douyin.com/user/MS4wLjABAAAAj5S4H6DqUywJ2oeaEDgLnCs7VOIXHgEaV6avOVfIoO_acjnJrgv83jEkhmSOT3Jy?from_tab_name=main&modal_id=7592442638562490216&vid=7634590160181569187" 
    ]
    results_links = processor.process_links(test_urls, audio_format='wav')
    print(f"Kết quả Test 1: {results_links}")
    
    # Cách 2: Test xử lý từ thư mục local (nếu bạn có sẵn file mp4)
    # Giả sử bạn copy một file mp4 vào thư mục workspace_test/videos
    print("\n--- Test 2: Xử lý video local ---")
    results_local = processor.process_directory(input_dir="workspace_test/videos", audio_format='mp3')
    print(f"Kết quả Test 2: {results_local}")
    
    print("\n" + "="*50)
    print("HOÀN THÀNH TEST MODULE 1")
    print("Kiểm tra kết quả trong thư mục 'workspace_test/'")
    print("="*50)

if __name__ == "__main__":
    test_module1()
