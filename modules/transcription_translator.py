import os
import json
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING
from tqdm import tqdm
from faster_whisper import WhisperModel

from utils.logger import setup_logger
from utils.transcription_utils import CacheManager, TranslatorFactory, contains_chinese

if TYPE_CHECKING:
    from core.process_manager import ProcessManager

logger = setup_logger(__name__)

class TranscriptionTranslator:
    """
    Class xử lý quá trình nhận diện giọng nói (ASR) và dịch thuật (Translate).
    Áp dụng thuật toán Semantic Batching & Overlap Context để tối ưu chất lượng và Quota.
    Tích hợp ProcessManager để hỗ trợ dừng/ép dừng giữa chừng.
    """
    def __init__(
        self, 
        translator_type: str = "gemini",
        api_key: str = "",
        whisper_model_size: str = "large-v3", 
        translation_model: str = "",
        workspace_dir: str = "workspace",
        device: str = "cuda",
        compute_type: str = "float16",
        batch_size: int = 30,  # Số câu mỗi lần dịch
        context_size: int = 5,  # Số câu ngữ cảnh gửi kèm (overlap)
        process_manager: Optional["ProcessManager"] = None
    ):
        self.workspace_dir = Path(workspace_dir)
        self.output_dir = self.workspace_dir / "transcripts"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pm = process_manager
        
        db_path = str(self.workspace_dir / "cache.db")
        self.cache_manager = CacheManager(db_path=db_path)
        
        self.translator_type = translator_type
        if translator_type != "none":
            self.translator = TranslatorFactory.get_translator(
                translator_type=translator_type,
                api_key=api_key,
                model_name=translation_model
            )
        else:
            self.translator = None
        
        self.batch_size = batch_size
        self.context_size = context_size

        logger.info(f"Đang tải model Faster-Whisper ({whisper_model_size})...")
        try:
            self.asr_model = WhisperModel(
                model_size_or_path=whisper_model_size,
                device=device,
                compute_type=compute_type,
                download_root=str(self.workspace_dir / "models")
            )
        except Exception:
            logger.warning("Không thể load model trên CUDA. Fallback về CPU.")
            self.asr_model = WhisperModel(
                model_size_or_path=whisper_model_size,
                device="cpu",
                compute_type="int8",
                download_root=str(self.workspace_dir / "models")
            )

    def _check_stop(self):
        """Kiểm tra và raise nếu pipeline bị dừng."""
        if self.pm:
            self.pm.check_stop_and_raise()

    def _format_time(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def export_srt(self, segments: List[Dict], output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, seg in enumerate(segments, 1):
                start = self._format_time(seg["start"])
                end = self._format_time(seg["end"])
                text = seg.get("text_vi", "").strip() or seg.get("text_zh", "")
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    def process_file(self, audio_path: str) -> Optional[List[Dict]]:
        if not os.path.exists(audio_path):
            logger.error(f"Không tìm thấy file: {audio_path}")
            return None
        
        self._check_stop()
            
        file_hash = self.cache_manager.get_file_hash(audio_path)
        
        # 1. BƯỚC ASR (Sử dụng Cache)
        segments_zh = self.cache_manager.get_asr_cache(file_hash)
        
        if segments_zh is None:
            logger.info(f"Bắt đầu ASR cho {os.path.basename(audio_path)}...")
            try:
                self._check_stop()
                segments, info = self.asr_model.transcribe(
                    audio_path, language="zh", task="transcribe",
                    vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500)
                )
                segments_zh = []
                for i, s in enumerate(segments, 1):
                    self._check_stop()
                    segments_zh.append({
                        "id": i,
                        "start": round(s.start, 2),
                        "end": round(s.end, 2),
                        "text_zh": s.text.strip()
                    })
                self.cache_manager.set_asr_cache(file_hash, segments_zh)
            except Exception as e:
                # Re-raise nếu là ProcessStoppedException
                from core.process_manager import ProcessStoppedException
                if isinstance(e, ProcessStoppedException):
                    raise
                logger.error(f"Lỗi ASR: {e}")
                return None
                
        if self.translator_type == "none":
            logger.info("Bỏ qua dịch thuật (Lựa chọn Không Dịch).")
            final_results = []
            for s in segments_zh:
                final_results.append({**s, "text_vi": s["text_zh"]})
            
            output_json = str(self.output_dir / f"{Path(audio_path).stem}_transcript.json")
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(final_results, f, ensure_ascii=False, indent=2)
            
            output_srt = str(self.output_dir / f"{Path(audio_path).stem}_subtitles.srt")
            self.export_srt(final_results, output_srt)
            
            return final_results
        
        # 2. BƯỚC DỊCH THUẬT (Semantic Batching & Context Overlap)
        final_results = []
        logger.info(f"Bắt đầu dịch thuật {len(segments_zh)} câu theo Batch...")
        
        # Lấy các câu chưa có bản dịch sạch trong cache
        to_translate_queue = []
        id_to_segment = {s["id"]: s for s in segments_zh}
        
        for s in segments_zh:
            cached_vi = self.cache_manager.get_translation_cache(s["text_zh"])
            # Chỉ dùng cache nếu bản dịch không chứa tiếng Trung
            if cached_vi and not contains_chinese(cached_vi):
                final_results.append({**s, "text_vi": cached_vi})
            else:
                to_translate_queue.append(s)

        # Chia nhỏ queue thành các chunk
        for i in range(0, len(to_translate_queue), self.batch_size):
            # Kiểm tra dừng trước mỗi batch
            self._check_stop()
            
            chunk = to_translate_queue[i : i + self.batch_size]
            
            # Xây dựng ngữ cảnh (Context Window)
            first_id = chunk[0]["id"]
            context_indices = range(max(1, first_id - self.context_size), first_id)
            context = [id_to_segment[cid] for cid in context_indices if cid in id_to_segment]
            
            # Gửi kèm bản dịch Việt của context nếu có để AI học tone giọng
            for ctx_item in context:
                cached_vi = self.cache_manager.get_translation_cache(ctx_item["text_zh"])
                if cached_vi: ctx_item["text_vi"] = cached_vi

            logger.info(f"Đang dịch Lô {i//self.batch_size + 1}... ({len(chunk)} câu)")
            
            try:
                batch_vi = self.translator.translate_batch(chunk, context_chunk=context)
                
                # Map kết quả trả về
                vi_map = {item["id"]: item["text_vi"] for item in batch_vi if "id" in item and "text_vi" in item}
                
                for item in chunk:
                    vi_text = vi_map.get(item["id"], "[Lỗi dịch thuật]")
                    translated_item = {**item, "text_vi": vi_text}
                    final_results.append(translated_item)
                    # Lưu cache nếu dịch sạch
                    if vi_text != "[Lỗi dịch thuật]" and not contains_chinese(vi_text):
                        self.cache_manager.set_translation_cache(item["text_zh"], vi_text)
                        
            except Exception as e:
                from core.process_manager import ProcessStoppedException
                if isinstance(e, ProcessStoppedException):
                    raise
                logger.error(f"Lỗi khi dịch Batch: {e}")
                for item in chunk:
                    final_results.append({**item, "text_vi": "[Lỗi Batch]"})

        # Sắp xếp lại theo đúng thứ tự thời gian
        final_results.sort(key=lambda x: x["id"])
            
        # Xuất file
        stem = Path(audio_path).stem
        with open(self.output_dir / f"{stem}_transcript.json", 'w', encoding='utf-8') as f:
            json.dump(final_results, f, ensure_ascii=False, indent=2)
        self.export_srt(final_results, str(self.output_dir / f"{stem}_subtitles.srt"))
        
        return final_results

    def process_batch(self, audio_paths: List[str]) -> Dict[str, Optional[List[Dict]]]:
        results = {}
        for path in tqdm(audio_paths, desc="Batch Processing"):
            self._check_stop()
            results[path] = self.process_file(path)
        return results
