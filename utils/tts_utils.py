import os
import re
import asyncio
import time
import threading
import subprocess
from pathlib import Path
from abc import ABC, abstractmethod
import edge_tts

try:
    from google import genai
    from google.genai.types import GenerateContentConfig, SpeechConfig, VoiceConfig, PrebuiltVoiceConfig
except ImportError:
    pass

from utils.logger import setup_logger
from utils.ffmpeg_utils import get_ffprobe_path

logger = setup_logger(__name__)


def sanitize_text_for_tts(text: str) -> str:
    """
    Làm sạch text trước khi gửi cho Edge TTS.
    Edge TTS trả về 'No audio was received' nếu text chứa:
    - Chỉ toàn ký tự đặc biệt / số
    - Ký tự control (\x00-\x1f)
    - Chuỗi quá ngắn (< 2 ký tự chữ)
    """
    if not text:
        return ""
    # Xóa ký tự control
    text = re.sub(r'[\x00-\x1f\x7f]', '', text)
    # Xóa multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()
    # Xóa dấu ngoặc rỗng, emoji codes bị lỗi
    text = re.sub(r'[\(\)\[\]\{\}]', '', text).strip()
    return text


def is_valid_tts_text(text: str) -> bool:
    """
    Kiểm tra text có đủ nội dung để TTS hay không.
    Loại bỏ text chỉ chứa số/ký tự đặc biệt mà không có chữ cái.
    """
    if not text or len(text.strip()) < 2:
        return False
    # Phải có ít nhất 2 ký tự chữ cái (bất kỳ ngôn ngữ nào)
    letter_count = len(re.findall(r'[\w]', text, re.UNICODE))
    return letter_count >= 2

# ─── Persistent Event Loop (tránh lỗi asyncio.run() trong Streamlit) ───
# Streamlit chạy trong thread riêng, asyncio.run() sẽ xung đột với event loop 
# và crash hàng loạt khi Streamlit rerun. Giải pháp: dùng 1 event loop riêng 
# chạy trong background thread, tồn tại suốt vòng đời process.

_loop = None
_loop_thread = None
_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """Lấy hoặc tạo persistent event loop chạy trong background thread."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
            _loop_thread.start()
    return _loop


def _run_async(coro):
    """Chạy coroutine trong persistent event loop (thread-safe)."""
    loop = _get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)  # Timeout 30s cho mỗi câu TTS


def get_audio_duration(file_path: str) -> float:
    """Trả về độ dài của file audio (tính bằng giây) sử dụng ffprobe (đi kèm FFmpeg)."""
    import subprocess
    
    try:
        if not os.path.exists(file_path):
            return 0.0
        
        # Kiểm tra file rỗng hoặc quá nhỏ (corrupted)
        file_size = os.path.getsize(file_path)
        if file_size < 100:  # File MP3 hợp lệ ít nhất vài trăm bytes
            return 0.0
            
        ffprobe_path = get_ffprobe_path()
            
        cmd = [
            ffprobe_path, 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            file_path
        ]
        
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            text=True, creationflags=creation_flags
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        else:
            logger.error(f"Lỗi ffprobe: {result.stderr}")
            return 0.0
            
    except Exception as e:
        logger.error(f"Lỗi khi đọc duration audio {file_path}: {e}")
        return 0.0


class BaseTTS(ABC):
    """Giao diện chuẩn cho các dịch vụ TTS."""
    @abstractmethod
    def generate_audio(self, text: str, output_path: str, rate: str = "+0%") -> bool:
        pass


class EdgeTTSEngine(BaseTTS):
    """
    Sử dụng Microsoft Edge TTS. Hoàn toàn miễn phí, không cần API Key.
    Giọng đọc tiếng Việt phổ biến:
    - vi-VN-HoaiMyNeural (Nữ - Rất hay)
    - vi-VN-NamMinhNeural (Nam)
    
    Cải tiến:
    - Persistent event loop (không dùng asyncio.run()) để tương thích Streamlit.
    - Retry tự động 3 lần với delay tăng dần khi bị rate-limit.
    - Xóa file corrupted nếu Edge TTS trả về rỗng.
    """
    MAX_RETRIES = 3
    BASE_DELAY = 2.0  # Giây chờ giữa mỗi lần retry (tăng lên để tránh rate-limit)

    def __init__(self, voice: str = "vi-VN-HoaiMyNeural", volume: str = "+0%"):
        self.voice = voice
        self.volume = volume

    async def _async_generate(self, text: str, output_path: str, rate: str) -> bool:
        """Sinh audio với retry tự động khi bị rate-limit."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                communicate = edge_tts.Communicate(text, self.voice, rate=rate, volume=self.volume)
                await communicate.save(output_path)
                
                # Kiểm tra file output có hợp lệ không (Edge TTS đôi khi tạo file rỗng)
                if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                    return True
                else:
                    # File rỗng/corrupted → xóa đi
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    if attempt < self.MAX_RETRIES:
                        delay = self.BASE_DELAY * attempt
                        logger.warning(f"Edge TTS trả về file rỗng (lần {attempt}/{self.MAX_RETRIES}). Thử lại sau {delay}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Edge TTS trả về file rỗng sau {self.MAX_RETRIES} lần thử.")
                        return False
                        
            except Exception as e:
                error_msg = str(e)
                if attempt < self.MAX_RETRIES:
                    delay = self.BASE_DELAY * attempt
                    logger.warning(f"Edge TTS lỗi (lần {attempt}/{self.MAX_RETRIES}): {error_msg}. Thử lại sau {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Edge TTS thất bại sau {self.MAX_RETRIES} lần: {error_msg}")
                    # Xóa file corrupted nếu có
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    return False
        
        return False

    def generate_audio(self, text: str, output_path: str, rate: str = "+0%") -> bool:
        """
        Chạy async trong persistent event loop (tương thích Streamlit).
        Không dùng asyncio.run() vì nó xung đột với event loop của Streamlit.
        """
        if not text or not text.strip():
            return False
        
        # Sanitize text trước khi gửi cho Edge TTS
        clean_text = sanitize_text_for_tts(text)
        if not is_valid_tts_text(clean_text):
            logger.warning(f"Text không đủ nội dung cho TTS, bỏ qua: '{text[:50]}'")
            return False
        
        try:
            return _run_async(self._async_generate(clean_text, output_path, rate))
        except TimeoutError:
            logger.error(f"Edge TTS timeout (>30s) cho text: {clean_text[:50]}...")
            if os.path.exists(output_path):
                os.remove(output_path)
            return False
        except Exception as e:
            logger.error(f"Lỗi Edge TTS: {e}")
            if os.path.exists(output_path):
                os.remove(output_path)
            return False


class GeminiTTSEngine(BaseTTS):
    """
    Sử dụng Gemini 3 TTS (gemini-3.1-flash-tts-preview).
    Hỗ trợ Multi-speaker qua thẻ [VoiceName] trong text.
    """
    MAX_RETRIES = 3

    def __init__(self, voice: str = "Kore", language_code: str = "vi-VN"):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.error("GEMINI_API_KEY chưa được set trong biến môi trường!")
            
        self.voice_name = voice # Default voice: Kore, Aoede, Fenrir, Puck, Charon
        self.language_code = language_code
        self.model = "gemini-3.1-flash-tts-preview"
        self.timeout = 30
        
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    def _generate_raw_audio(self, text: str, voice_name: str, temp_pcm_path: str):
        """Gọi Gemini TTS thật (trả về PCM bytes)"""
        config = GenerateContentConfig(
            speech_config=SpeechConfig(
                language_code=self.language_code,
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
            temperature=1.0,
            response_modalities=["AUDIO"]
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=text,
            config=config
        )

        audio_bytes = response.candidates[0].content.parts[0].inline_data.data
        
        with open(temp_pcm_path, "wb") as f:
            f.write(audio_bytes)

    def generate_audio(self, text: str, output_path: str, rate: str = "+0%") -> bool:
        if not self.client:
            logger.error("Không thể sinh audio: Thiếu GEMINI_API_KEY")
            return False

        if not text or not text.strip():
            return False
            
        # Parse Multi-speaker tag: [Speaker:Aoede] or [Aoede]
        current_voice = self.voice_name
        match = re.search(r'\[(?:Speaker:)?([a-zA-Z0-9_]+)\]', text)
        if match:
            current_voice = match.group(1)
            # Remove the tag from text
            text = text.replace(match.group(0), '').strip()
            
        clean_text = sanitize_text_for_tts(text)
        if not is_valid_tts_text(clean_text):
            logger.warning(f"Text không đủ nội dung cho TTS, bỏ qua: '{text[:50]}'")
            return False

        temp_pcm = str(Path(output_path).with_suffix(".pcm"))
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Bắt buộc phải chờ 21 giây giữa mỗi request vì Gemini Free Tier cho bản preview 
                # chỉ giới hạn 3 Requests Per Minute (RPM) -> 1 request mỗi 20 giây.
                if attempt > 0:
                    sleep_time = 21.0
                    logger.warning(f"Gemini TTS báo lỗi hoặc rate limit. Chờ {sleep_time}s trước khi thử lại (lần {attempt}/{self.MAX_RETRIES})...")
                    time.sleep(sleep_time)
                else:
                    # Chờ 21 giây ngay cả ở lần đầu tiên (nếu là câu thứ 2 trở đi) 
                    # để đảm bảo an toàn tuyệt đối cho giới hạn 3 RPM.
                    time.sleep(21.0)

                def background_task():
                    self._generate_raw_audio(clean_text, current_voice, temp_pcm)
                
                thread = threading.Thread(target=background_task, daemon=True)
                thread.start()
                thread.join(timeout=self.timeout)

                if thread.is_alive():
                    raise TimeoutError("Gemini TTS timeout (>30s)")

                if not os.path.exists(temp_pcm) or os.path.getsize(temp_pcm) < 1000:
                    raise ValueError("File PCM rỗng hoặc quá nhỏ")

                # Convert PCM -> MP3 using ffmpeg
                from utils.ffmpeg_utils import get_ffmpeg_path
                cmd = [
                    get_ffmpeg_path(), "-y",
                    "-f", "s16le", "-ar", "24000", "-ac", "1",
                    "-i", temp_pcm,
                    output_path
                ]
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, creationflags=creation_flags)

                # Clean temp pcm
                if os.path.exists(temp_pcm):
                    os.remove(temp_pcm)
                    
                return True

            except Exception as e:
                logger.error(f"Lỗi Gemini TTS (lần {attempt+1}): {e}")
                if os.path.exists(temp_pcm):
                    try:
                        os.remove(temp_pcm)
                    except:
                        pass
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except:
                        pass

        logger.error(f"Gemini TTS thất bại sau {self.MAX_RETRIES} lần.")
        return False


class LocalAPI_TTS(BaseTTS):
    """
    Module mẫu cho các hệ thống Local TTS (như VieNeu-TTS, VITS, VinaTTS).
    Các hệ thống này thường được chạy dưới dạng một local server (ví dụ: localhost:5000).
    """
    def __init__(self, api_url: str = "http://127.0.0.1:5000/api/tts"):
        self.api_url = api_url

    def generate_audio(self, text: str, output_path: str, rate: str = "+0%") -> bool:
        # Tương lai: Sử dụng thư viện requests để POST text lên self.api_url
        # và lưu file .wav/.mp3 trả về xuống output_path.
        logger.warning("LocalAPI_TTS chưa được triển khai hoàn chỉnh. Vui lòng thêm logic gọi API (vd: requests.post).")
        return False


class TTSFactory:
    """Factory Pattern để linh hoạt chọn Engine Lồng tiếng."""
    @staticmethod
    def get_engine(engine_type: str, voice: str = "vi-VN-HoaiMyNeural", local_api_url: str = "") -> BaseTTS:
        engine_type = engine_type.lower()
        if engine_type == "edge":
            return EdgeTTSEngine(voice=voice)
        elif engine_type == "gemini":
            # Map edge voice name if needed, or assume 'voice' holds Gemini voice name (e.g. Kore)
            gemini_voice = voice if voice and "Neural" not in voice else "Kore"
            return GeminiTTSEngine(voice=gemini_voice)
        elif engine_type == "local_api":
            return LocalAPI_TTS(api_url=local_api_url)
        # Thêm AzureTTS, ElevenLabsTTS ở đây trong tương lai
        else:
            raise ValueError(f"Không hỗ trợ TTS Engine: {engine_type}")
