import sqlite3
import json
import hashlib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Optional
import google.generativeai as genai
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from utils.logger import setup_logger

logger = setup_logger(__name__)

class CacheManager:
    """Quản lý SQLite cache cho kết quả ASR và Dịch thuật."""
    def __init__(self, db_path: str = "workspace/cache.db"):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS asr_cache (file_hash TEXT PRIMARY KEY, segments_json TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS translation_cache (text_zh TEXT PRIMARY KEY, text_vi TEXT)''')
            conn.commit()

    def get_file_hash(self, file_path: str) -> str:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            buf = f.read(65536)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(65536)
        return hasher.hexdigest()

    def get_asr_cache(self, file_hash: str) -> Optional[List[Dict]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT segments_json FROM asr_cache WHERE file_hash = ?", (file_hash,))
            row = cursor.fetchone()
            if row: return json.loads(row[0])
        return None

    def set_asr_cache(self, file_hash: str, segments: List[Dict]):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO asr_cache (file_hash, segments_json) VALUES (?, ?)",
                           (file_hash, json.dumps(segments, ensure_ascii=False)))
            conn.commit()

    def get_translation_cache(self, text_zh: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT text_vi FROM translation_cache WHERE text_zh = ?", (text_zh,))
            row = cursor.fetchone()
            if row: return row[0]
        return None

    def set_translation_cache(self, text_zh: str, text_vi: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO translation_cache (text_zh, text_vi) VALUES (?, ?)", (text_zh, text_vi))
            conn.commit()

# --- UTILS & BATCH TRANSLATION ---

def contains_chinese(text: str) -> bool:
    """Kiểm tra xem đoạn văn có chứa ký tự tiếng Trung hay không."""
    return bool(re.search(r'[\u4e00-\u9fff]', text))

def _extract_json_array(text: str) -> List[Dict]:
    """Cố gắng trích xuất mảng JSON từ output của AI."""
    text = text.strip()
    # Tìm vùng chứa dấu ngoặc vuông []
    start = text.find('[')
    end = text.rfind(']') + 1
    if start != -1 and end > 0:
        json_str = text[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                # Clean JSON bị lỗi do escape char hoặc thiếu ngoặc (cố gắng sửa cơ bản)
                return json.loads(re.sub(r'\\(?!"|u|n|r|t|b|f)', r'\\\\', json_str))
            except:
                logger.error(f"Không thể parse JSON từ AI output: {text[:200]}...")
                return []
    return []

class BaseTranslator(ABC):
    @abstractmethod
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        pass

class GeminiTranslator(BaseTranslator):
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        if not api_key:
            raise ValueError("Cần có API Key để sử dụng Gemini.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        
        self.system_prompt = (
            "Bạn là một chuyên gia dịch thuật video TikTok/Douyin (Trung -> Việt). "
            "YÊU CẦU QUAN TRỌNG:\n"
            "1. Dịch tự nhiên, ngắn gọn, giữ đúng tone giọng hội thoại, bắt trend tốt.\n"
            "2. Tôi sẽ cung cấp dữ liệu JSON. Bạn chỉ được trả về MẢNG JSON duy nhất.\n"
            "3. Giữ nguyên 'id' của từng câu.\n"
            "4. Thêm trường 'text_vi' là bản dịch tiếng Việt.\n"
            "5. TUYỆT ĐỐI KHÔNG giải thích, không thêm chữ gì ngoài mảng JSON.\n"
            "6. KHÔNG được trả lại tiếng Trung. Mọi từ ngữ phải được chuyển sang Tiếng Việt.\n"
            "Định dạng ví dụ: [{\"id\": 1, \"text_vi\": \"...\"}, ...]"
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        if not chunk_to_translate: return []
            
        prompt = self.system_prompt + "\n\n"
        if context_chunk:
            prompt += "--- NGỮ CẢNH TRƯỚC ĐÓ (Dùng để hiểu mạch truyện, KHÔNG ĐƯỢC DỊCH) ---\n"
            # Chỉ lấy id và text_vi đã dịch để làm ngữ cảnh
            ctx_simplified = [{"id": item.get("id"), "text_vi": item.get("text_vi", "")} for item in context_chunk]
            prompt += json.dumps(ctx_simplified, ensure_ascii=False) + "\n\n"
            
        prompt += "--- DANH SÁCH CẦN DỊCH (BẮT BUỘC TRẢ VỀ JSON CHO CÁC ID NÀY) ---\n"
        simplify_chunk = [{"id": item["id"], "text_zh": item["text_zh"]} for item in chunk_to_translate]
        prompt += json.dumps(simplify_chunk, ensure_ascii=False)
        
        try:
            response = self.model.generate_content(prompt)
            if not response.text: return []
            results = _extract_json_array(response.text)
            
            # --- AUTO-VERIFY & FORCE RETRY ---
            if any(contains_chinese(res.get("text_vi", "")) for res in results):
                logger.warning("Gemini trả về tiếng Trung, đang yêu cầu dịch lại nghiêm ngặt...")
                force_prompt = prompt + "\n\nCẢNH BÁO: Lần trước bạn đã để lọt tiếng Trung. Lần này hãy DỊCH 100% SANG VIỆT, kể cả tên riêng!"
                response = self.model.generate_content(force_prompt)
                results = _extract_json_array(response.text)
            return results
        except Exception as e:
            logger.warning(f"Gemini API lỗi: {str(e)}")
            raise e

class DeepSeekTranslator(BaseTranslator):
    def __init__(self, api_key: str, model_name: str = "deepseek-chat"):
        if not api_key:
            raise ValueError("Cần có API Key để sử dụng DeepSeek.")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.model_name = model_name
        self.system_prompt = (
            "Bạn là chuyên gia dịch video TikTok/Douyin (Trung sang Việt). "
            "Dịch tự nhiên, ngắn gọn. CHỈ trả về mảng JSON kết quả: [{\"id\": 1, \"text_vi\": \"...\"}, ...]. "
            "Cấm trả về tiếng Trung gốc. Dịch toàn bộ sang Tiếng Việt."
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        if not chunk_to_translate: return []
        
        def _call_api(extra_prompt=""):
            user_msg = ""
            if context_chunk:
                ctx = [{"id": item.get("id"), "text_vi": item.get("text_vi", "")} for item in context_chunk]
                user_msg += f"Previous context: {json.dumps(ctx, ensure_ascii=False)}\n\n"
            simplify_chunk = [{"id": item["id"], "text_zh": item["text_zh"]} for item in chunk_to_translate]
            user_msg += f"Translate these to Vietnamese (STRICTLY NO CHINESE): {json.dumps(simplify_chunk, ensure_ascii=False)}"
            if extra_prompt: user_msg += f"\n\n{extra_prompt}"
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_msg}],
                stream=False
            )
            return _extract_json_array(response.choices[0].message.content)

        try:
            results = _call_api()
            if any(contains_chinese(res.get("text_vi", "")) for res in results):
                logger.warning("DeepSeek trả về tiếng Trung, đang ép dịch lại...")
                results = _call_api("ERROR: You returned Chinese. FIX IT: TRANSLATE EVERYTHING TO VIETNAMESE NOW.")
            return results
        except Exception as e:
            logger.warning(f"DeepSeek API lỗi: {str(e)}")
            raise e

class LocalTranslator(BaseTranslator):
    def __init__(self, model_name: str = "Helsinki-NLP/opus-mt-zh-vi"):
        logger.info(f"Đang khởi tạo Local Translator: {model_name}")
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        except ImportError:
            raise ImportError("Thiếu thư viện local: pip install transformers torch sentencepiece sacremoses")

    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        results = []
        for item in chunk_to_translate:
            text_zh = item.get("text_zh", "")
            if not text_zh:
                results.append({"id": item["id"], "text_vi": ""})
                continue
            try:
                inputs = self.tokenizer(text_zh, return_tensors="pt", padding=True, truncation=True, max_length=512)
                outputs = self.model.generate(**inputs, max_length=512)
                res_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
                # Lọc CoT đơn giản
                res_text = res_text.split('\n')[-1].strip()
                results.append({"id": item["id"], "text_vi": res_text})
            except Exception:
                results.append({"id": item["id"], "text_vi": "[Lỗi Local]"})
        return results

class TranslatorFactory:
    @staticmethod
    def get_translator(translator_type: str, api_key: str = "", model_name: str = "") -> BaseTranslator:
        translator_type = translator_type.lower()
        if translator_type == "gemini":
            m = model_name if model_name else "gemini-1.5-flash"
            return GeminiTranslator(api_key=api_key, model_name=m)
        elif translator_type == "deepseek":
            m = model_name if model_name else "deepseek-chat"
            return DeepSeekTranslator(api_key=api_key, model_name=m)
        elif translator_type == "local":
            return LocalTranslator()
        else:
            raise ValueError(f"Không hỗ trợ: {translator_type}")
