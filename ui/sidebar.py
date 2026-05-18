"""
Sidebar UI - Quản lý toàn bộ giao diện thanh cấu hình bên trái.
Trả về dict chứa tất cả settings người dùng đã chọn.
"""

import os
from pathlib import Path
import streamlit as st

from utils.secrets_manager import clear_secret, load_secrets, mask_secret, save_secrets


def clear_cache(workspace_dir: str) -> bool:
    """Xóa file SQLite Cache nếu người dùng yêu cầu dịch lại."""
    cache_path = Path(workspace_dir) / "cache.db"
    if cache_path.exists():
        try:
            os.remove(cache_path)
            return True
        except Exception:
            return False
    return True


def render_sidebar(workspace_dir: str = "workspace") -> dict:
    """
    Render toàn bộ sidebar cấu hình và trả về dict settings.

    Returns:
        dict với các key:
            - translator_type: str ("gemini" | "deepseek" | "local")
            - api_key: str
            - model_name: str
            - voice: str
            - blur_sub: bool
            - blur_logo: bool
            - flip_video: bool
            - bgm_volume: float
            - fast_preview: bool
    """
    with st.sidebar:
        st.header("⚙️ Cấu hình Hệ thống")

        # ─── 1. AI Dịch thuật ───
        st.subheader("1. Động cơ Dịch thuật")
        translator_type = st.selectbox(
            "Chọn AI Dịch",
            [
                "Gemini API (Google - Free/Paid)",
                "DeepSeek API (Trung Quốc - Giá rẻ)",
                "Local Offline (HuggingFace - Miễn phí)",
                "Không Dịch (Chỉ lấy Kịch bản gốc)"
            ]
        )

        trans_val = "gemini"
        if "DeepSeek" in translator_type:
            trans_val = "deepseek"
        elif "Local" in translator_type:
            trans_val = "local"
        elif "Không Dịch" in translator_type:
            trans_val = "none"

        api_key = ""
        model_name = ""
        secrets = load_secrets()

        if trans_val in ["gemini", "deepseek"]:
            secret_key = f"{trans_val}_api_key"
            saved_key = secrets.get(secret_key, "")
            if saved_key:
                st.caption(f"Đã lưu key {trans_val.capitalize()} local: `{mask_secret(saved_key)}`")
            entered_key = st.text_input(
                f"Nhập {trans_val.capitalize()} API Key:",
                value="",
                type="password",
                placeholder="Để trống để dùng key đã lưu" if saved_key else "Dán API key vào đây"
            )
            api_key = entered_key.strip() or saved_key
            default_model = "gemini-1.5-flash" if trans_val == "gemini" else "deepseek-chat"
            model_name = st.text_input(
                "Tên Model AI:",
                value=secrets.get("last_model_name") or default_model,
                help="Ví dụ: gemini-3.1-flash, gemini-2.0-flash-exp, deepseek-chat, deepseek-reasoner"
            )
            col_save, col_clear = st.columns(2)
            with col_save:
                if st.button("💾 Lưu key", use_container_width=True, key=f"save_{trans_val}_key"):
                    if api_key:
                        save_secrets({secret_key: api_key, "last_translator_type": trans_val, "last_model_name": model_name})
                        st.success("Đã lưu key local.")
                    else:
                        st.warning("Chưa có key để lưu.")
            with col_clear:
                if st.button("🧹 Xóa key", use_container_width=True, key=f"clear_{trans_val}_key"):
                    clear_secret(secret_key)
                    st.success("Đã xóa key đã lưu.")
                    st.rerun()

        if st.button("🗑️ Xóa Cache Dịch cũ (Dịch lại từ đầu)"):
            if clear_cache(workspace_dir):
                st.success("Đã xóa cache thành công!")

        # ─── 2. Nhận diện giọng nói (ASR) ───
        st.subheader("2. Nhận diện giọng nói (ASR)")
        whisper_model = st.selectbox(
            "Whisper model:",
            ["tiny", "base", "small", "medium", "large-v3"],
            index=3,
            help="Video tiếng Trung nên dùng medium nếu máy chịu được. tiny/base nhanh hơn nhưng dễ sai timing/nội dung."
        )
        source_language_label = st.selectbox(
            "Ngôn ngữ gốc:",
            ["Tiếng Trung (zh)", "Tự động nhận diện", "Tiếng Anh (en)", "Tiếng Nhật (ja)", "Tiếng Hàn (ko)"],
            index=0,
        )
        source_language_map = {
            "Tiếng Trung (zh)": "zh",
            "Tự động nhận diện": "auto",
            "Tiếng Anh (en)": "en",
            "Tiếng Nhật (ja)": "ja",
            "Tiếng Hàn (ko)": "ko",
        }
        source_language = source_language_map[source_language_label]
        batch_size = st.slider("Số câu mỗi batch dịch", 5, 40, 20, 5, help="Batch nhỏ ổn định hơn, batch lớn nhanh hơn nhưng dễ lỗi JSON/dịch sót.")
        context_size = st.slider("Số câu ngữ cảnh", 0, 10, 5, 1)

        # ─── 3. Template Phong cách ───
        st.subheader("3. Template Video")
        template = st.selectbox(
            "Chọn phong cách:",
            ["Tùy chỉnh (Custom)", "Review Phim/Truyện", "Tin Tức / Giải Trí"]
        )

        # Giá trị mặc định theo template
        is_blur_sub = True
        is_blur_logo = True
        is_flip = False
        voice_val = "vi-VN-HoaiMyNeural"
        bgm_vol = 0.05

        if template == "Review Phim/Truyện":
            is_flip = True
            voice_val = "vi-VN-NamMinhNeural"
            bgm_vol = 0.02
        elif template == "Tin Tức / Giải Trí":
            voice_val = "vi-VN-HoaiMyNeural"
            bgm_vol = 0.08

        # ─── 4. Lồng tiếng (TTS) ───
        st.subheader("4. Lồng Tiếng (TTS)")

        tts_engine_choice = st.selectbox("Chọn Engine TTS:", ["Edge TTS (Miễn phí, Mặc định)", "Gemini TTS (Google - Free/Paid)"])
        tts_engine = "gemini" if "Gemini" in tts_engine_choice else "edge"

        if tts_engine == "gemini":
            saved_tts_key = secrets.get("gemini_tts_api_key", "")
            if saved_tts_key:
                st.caption(f"Đã lưu Gemini TTS key local: `{mask_secret(saved_tts_key)}`")
            gemini_tts_key = st.text_input(
                "Nhập Gemini API Key (cho TTS):",
                type="password",
                value="",
                placeholder="Để trống để dùng key đã lưu" if saved_tts_key else "Dán Gemini TTS key vào đây",
                help="Chỉ dùng khi chọn Gemini TTS"
            )
            final_tts_key = gemini_tts_key.strip() or saved_tts_key
            if final_tts_key:
                os.environ["GEMINI_API_KEY"] = final_tts_key
            col_tts_save, col_tts_clear = st.columns(2)
            with col_tts_save:
                if st.button("💾 Lưu TTS key", use_container_width=True):
                    if final_tts_key:
                        save_secrets({"gemini_tts_api_key": final_tts_key})
                        st.success("Đã lưu TTS key local.")
                    else:
                        st.warning("Chưa có key để lưu.")
            with col_tts_clear:
                if st.button("🧹 Xóa TTS key", use_container_width=True):
                    clear_secret("gemini_tts_api_key")
                    st.success("Đã xóa TTS key đã lưu.")
                    st.rerun()
            tts_voices = ["Kore", "Aoede", "Fenrir", "Puck", "Charon"]
            default_voice_idx = 0
            voice_choice = st.selectbox("Chọn giọng đọc:", tts_voices, index=default_voice_idx)
            final_voice = voice_choice
        else:
            tts_voices = ["vi-VN-HoaiMyNeural (Nữ)", "vi-VN-NamMinhNeural (Nam)"]
            default_voice_idx = 1 if voice_val == "vi-VN-NamMinhNeural" else 0
            voice_choice = st.selectbox("Chọn giọng đọc:", tts_voices, index=default_voice_idx)
            final_voice = voice_choice.split(" ")[0]

        max_speed_increase = st.slider(
            "Tăng tốc TTS tối đa (%)",
            0,
            100,
            50,
            5,
            help="Nếu giọng đọc dài hơn slot phụ đề, tool sẽ tăng tốc tối đa mức này rồi pad/silence để giữ timeline."
        )

        # ─── 5. Hiệu ứng Hình ảnh ───
        st.subheader("5. Hiệu ứng Hình ảnh")
        blur_sub = st.checkbox("Che Sub Trung Quốc (Dải đen)", value=is_blur_sub)
        blur_logo = st.checkbox("Che Logo Watermark", value=is_blur_logo)
        flip_video = st.checkbox("Lật ngang Video", value=is_flip)
        only_chinese_sub = st.checkbox("Chỉ hiện Sub Tiếng Trung (Không hiện tiếng Việt)", value=False)

        # ─── 6. Tùy chọn Render ───
        st.subheader("6. Tùy chọn Render")
        bgm_volume = st.slider("Âm lượng nhạc nền gốc", 0.0, 0.5, bgm_vol, 0.01)
        fast_preview = st.checkbox("Chế độ Preview (Render Nhanh/Nhẹ)", value=True)

        # ─── 7. Kiểm soát Tiến trình ───
        st.subheader("7. Kiểm soát Tiến trình")
        start_steps = {
            "Bước 1: Tách Audio (Từ đầu)": 1,
            "Bước 2: Dịch thuật AI (Bỏ qua tách audio)": 2,
            "Bước 3: Lồng tiếng TTS (Bỏ qua dịch thuật)": 3,
            "Bước 4: Render Video (Chỉ render lại)": 4,
        }
        start_step_label = st.selectbox(
            "Bắt đầu từ bước:",
            list(start_steps.keys()),
            help="Chọn bước bắt đầu nếu các bước trước đã hoàn thành. Ví dụ: đã tách audio rồi → chọn Bước 2."
        )
        start_from_step = start_steps[start_step_label]

        end_steps = {
            "Chạy đến hết (Bước 4)": 4,
            "Chỉ chạy Bước 1 (Tách Audio)": 1,
            "Dừng sau Bước 2 (Để xem/sửa Kịch bản)": 2,
            "Dừng sau Bước 3 (Để kiểm tra Âm thanh)": 3,
        }

        end_step_label = st.selectbox(
            "Dừng sau khi hoàn thành:",
            list(end_steps.keys()),
            help="Chọn bước muốn dừng lại. Hữu ích khi bạn muốn tự kiểm tra kịch bản hoặc âm thanh trước khi render."
        )
        end_at_step = end_steps[end_step_label]

        if end_at_step < start_from_step:
            st.warning("⚠️ Bước dừng đang nhỏ hơn bước bắt đầu. Sẽ tự động chạy 1 bước duy nhất.")
            end_at_step = start_from_step

        if start_from_step > 1:
            st.info(f"⏩ Sẽ bỏ qua {start_from_step - 1} bước đầu, bắt đầu từ **{start_step_label.split(': ')[1].split(' (')[0]}**")

    return {
        "translator_type": trans_val,
        "api_key": api_key,
        "model_name": model_name,
        "whisper_model": whisper_model,
        "source_language": source_language,
        "batch_size": batch_size,
        "context_size": context_size,
        "tts_engine": tts_engine,
        "voice": final_voice,
        "max_speed_increase": max_speed_increase,
        "blur_sub": blur_sub,
        "blur_logo": blur_logo,
        "flip_video": flip_video,
        "only_chinese_sub": only_chinese_sub,
        "bgm_volume": bgm_volume,
        "fast_preview": fast_preview,
        "start_from_step": start_from_step,
        "end_at_step": end_at_step,
    }
