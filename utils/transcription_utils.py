import sqlite3
import json
import hashlib
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
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))

def normalize_text(text: str) -> str:
    """Normalize text for simple equality/quality checks."""
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text

def is_bad_translation(source_text: str, translated_text: str) -> bool:
    """Detect outputs that should be retried instead of cached/used."""
    src = (source_text or "").strip()
    out = (translated_text or "").strip()
    if not out:
        return True
    if out.startswith("[Lỗi") or out in {"...", ".", "-"}:
        return True
    if contains_chinese(out):
        return True
    if src and normalize_text(src) == normalize_text(out):
        return True
    return False

def _extract_json_array(text: str) -> List[Dict]:
    """Cố gắng trích xuất mảng JSON từ output của AI."""
    text = (text or "").strip()
    start = text.find('[')
    end = text.rfind(']') + 1
    if start != -1 and end > 0:
        json_str = text[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                return json.loads(re.sub(r'\\(?!"|u|n|r|t|b|f)', r'\\\\', json_str))
            except Exception:
                logger.error(f"Không thể parse JSON từ AI output: {text[:200]}...")
                return []
    return []

class BaseTranslator(ABC):
    @abstractmethod
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        pass

    @abstractmethod
    def translate_single(self, item: Dict, context_chunk: List[Dict] = None) -> str:
        pass

class GeminiTranslator(BaseTranslator):
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        if not api_key:
            raise ValueError("Cần có API Key để sử dụng Gemini.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.system_prompt = (
            "Bạn là chuyên gia dịch phụ đề video TikTok/Douyin từ tiếng Trung sang tiếng Việt.\n"
            "YÊU CẦU BẮT BUỘC:\n"
            "1. Dịch tự nhiên, ngắn gọn, dễ đọc khi hiện trên video.\n"
            "2. Với video bán hàng/review/livestream, dùng giọng Việt tự nhiên, có sức bán hàng nhưng không lố.\n"
            "3. Không giải thích, không thêm markdown, không thêm lời dẫn.\n"
            "4. Không được copy tiếng Trung gốc. Nếu source có chữ Trung, output vẫn phải là tiếng Việt.\n"
            "5. Giữ đúng id và trả về đúng mảng JSON: [{\"id\": 1, \"text_vi\": \"...\"}].\n"
            "6. Không bỏ sót câu ngắn. Không gộp/tách id."
        )

    def _build_prompt(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None, strict: bool = False) -> str:
        prompt = self.system_prompt + "\n\n"
        if context_chunk:
            ctx_simplified = [{"id": item.get("id"), "text_vi": item.get("text_vi", "")} for item in context_chunk]
            prompt += "--- NGỮ CẢNH ĐÃ DỊCH, CHỈ ĐỂ HIỂU MẠCH ---\n"
            prompt += json.dumps(ctx_simplified, ensure_ascii=False) + "\n\n"
        simplify_chunk = [{"id": item["id"], "text_zh": item.get("text_zh", "")} for item in chunk_to_translate]
        prompt += "--- DANH SÁCH CẦN DỊCH, BẮT BUỘC TRẢ VỀ JSON CHO ĐÚNG CÁC ID NÀY ---\n"
        prompt += json.dumps(simplify_chunk, ensure_ascii=False)
        if strict:
            prompt += "\n\nCẢNH BÁO: Bản trước lỗi vì còn tiếng Trung/giống source. Dịch lại 100% sang tiếng Việt tự nhiên. Chỉ trả JSON."
        return prompt

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        if not chunk_to_translate: return []
        response = self.model.generate_content(self._build_prompt(chunk_to_translate, context_chunk))
        results = _extract_json_array(response.text if response else "")
        if len(results) != len(chunk_to_translate) or any(
            is_bad_translation(item.get("text_zh", ""), next((r.get("text_vi", "") for r in results if r.get("id") == item.get("id")), ""))
            for item in chunk_to_translate
        ):
            logger.warning("Gemini trả kết quả thiếu/lỗi, đang retry nghiêm ngặt...")
            response = self.model.generate_content(self._build_prompt(chunk_to_translate, context_chunk, strict=True))
            results = _extract_json_array(response.text if response else "")
        return results

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
    def translate_single(self, item: Dict, context_chunk: List[Dict] = None) -> str:
        response = self.model.generate_content(self._build_prompt([item], context_chunk, strict=True))
        results = _extract_json_array(response.text if response else "")
        return (results[0].get("text_vi", "") if results else "").strip()

class DeepSeekTranslator(BaseTranslator):
    def __init__(self, api_key: str, model_name: str = "deepseek-chat"):
        if not api_key:
            raise ValueError("Cần có API Key để sử dụng DeepSeek.")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        self.model_name = model_name
        self.system_prompt = (
            "Bạn là chuyên gia dịch phụ đề video TikTok/Douyin từ tiếng Trung sang tiếng Việt. "
            "Dịch tự nhiên, ngắn gọn, dễ đọc khi hiện trên video. "
            "Nếu là video bán hàng/review/livestream, dùng giọng Việt tự nhiên, có sức bán hàng nhưng không lố. "
            "Không copy tiếng Trung gốc, không giải thích, không markdown. "
            "Luôn trả về duy nhất mảng JSON: [{\"id\": 1, \"text_vi\": \"...\"}]. "
            "Giữ đúng id, không bỏ sót, không gộp/tách câu."
        )

    def _call_api(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None, strict: bool = False) -> List[Dict]:
        user_msg = ""
        if context_chunk:
            ctx = [{"id": item.get("id"), "text_vi": item.get("text_vi", "")} for item in context_chunk]
            user_msg += f"Ngữ cảnh đã dịch, chỉ để hiểu mạch: {json.dumps(ctx, ensure_ascii=False)}\n\n"
        simplify_chunk = [{"id": item["id"], "text_zh": item.get("text_zh", "")} for item in chunk_to_translate]
        user_msg += "Dịch các item sau sang tiếng Việt. Chỉ trả JSON array, đúng id:\n"
        user_msg += json.dumps(simplify_chunk, ensure_ascii=False)
        if strict:
            user_msg += "\n\nBản trước lỗi vì còn tiếng Trung/giống source/thiếu item. Dịch lại 100% sang tiếng Việt tự nhiên. Không giữ chữ Trung."
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            stream=False,
        )
        return _extract_json_array(response.choices[0].message.content)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def translate_batch(self, chunk_to_translate: List[Dict], context_chunk: List[Dict] = None) -> List[Dict]:
        if not chunk_to_translate: return []
        results = self._call_api(chunk_to_translate, context_chunk)
        if len(results) != len(chunk_to_translate) or any(
            is_bad_translation(item.get("text_zh", ""), next((r.get("text_vi", "") for r in results if r.get("id") == item.get("id")), ""))
            for item in chunk_to_translate
        ):
            logger.warning("DeepSeek trả kết quả thiếu/lỗi, đang retry nghiêm ngặt...")
            results = self._call_api(chunk_to_translate, context_chunk, strict=True)
        return results

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
    def translate_single(self, item: Dict, context_chunk: List[Dict] = None) -> str:
        results = self._call_api([item], context_chunk, strict=True)
        return (results[0].get("text_vi", "") if results else "").strip()

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
                res_text = res_text.split('\n')[-1].strip()
                results.append({"id": item["id"], "text_vi": res_text})
            except Exception:
                results.append({"id": item["id"], "text_vi": "[Lỗi Local]"})
        return results

    def translate_single(self, item: Dict, context_chunk: List[Dict] = None) -> str:
        result = self.translate_batch([item], context_chunk=context_chunk)
        return (result[0].get("text_vi", "") if result else "").strip()

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
