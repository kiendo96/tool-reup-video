import os
import time
from pathlib import Path
import streamlit as st

from core.process_manager import ProcessManager
from ui.sidebar import render_sidebar
from ui.pipeline_runner import start_pipeline_thread
from utils.logger import setup_logger

logger = setup_logger(__name__)

# ─── Cấu hình trang Streamlit ───
st.set_page_config(
    page_title="ViralLocal - Auto Reup",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Khởi tạo Session State ───
if "process_manager" not in st.session_state:
    st.session_state.process_manager = ProcessManager()
if "pipeline_thread" not in st.session_state:
    st.session_state.pipeline_thread = None

pm: ProcessManager = st.session_state.process_manager


def main():
    st.title("🚀 ViralLocal - Trợ lý Auto Reup Video")
    st.markdown("Quy trình 4 Bước Tự Động: **Tách Âm thanh ➔ Dịch thuật AI ➔ Lồng tiếng ➔ Che Logo & Render**")
    
    workspace_dir = "workspace"
    os.makedirs(workspace_dir, exist_ok=True)
    
    # ─── Sidebar Cấu hình ───
    settings = render_sidebar(workspace_dir)
    
    # ─── Khu Vực Chính ───
    st.header("📂 Batch Processing (Xử lý hàng loạt)")
    
    # ═══════════════════════════════════════════════
    # TRƯỜNG HỢP 1: Pipeline ĐANG CHẠY (background thread)
    # ═══════════════════════════════════════════════
    if pm.is_running:
        _render_running_ui(pm)
        return
    
    # ═══════════════════════════════════════════════
    # TRƯỜNG HỢP 2: Pipeline ĐÃ DỪNG (hiển thị kết quả)
    # ═══════════════════════════════════════════════
    
    # Hiển thị trạng thái
    st.info(pm.get_status_display())
    
    # Hiển thị kết quả lần chạy trước (nếu có)
    logs = pm.get_logs()
    if logs:
        with st.expander("📋 Log lần chạy trước", expanded=False):
            for log in logs:
                st.write(log)
        result_vid = pm.get_result_video()
        if result_vid and os.path.exists(result_vid):
            st.video(result_vid)
            
    # ─── 📝 Transcript Editor ───
    st.subheader("📝 Chỉnh sửa Kịch bản (Transcript Editor)")
    st.markdown("Kiểm tra và sửa lỗi dịch thuật trước khi lồng tiếng (Bước 3).")
    
    transcripts_dir = Path(workspace_dir) / "transcripts"
    transcript_files = []
    if transcripts_dir.exists():
        transcript_files = [f.name for f in transcripts_dir.glob("*_transcript.json")]
        
    if not transcript_files:
        st.info("Chưa có file kịch bản nào được tạo. Hãy chạy Bước 1 và 2 trước.")
    else:
        selected_file = st.selectbox("Chọn kịch bản để sửa:", transcript_files)
        if selected_file:
            file_path = transcripts_dir / selected_file
            import json
            import pandas as pd
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    segments = json.load(f)
                    
                # ─── Hiển thị Video Gốc (nếu có) kèm Phụ đề ───
                vid_stem = selected_file.replace("_transcript.json", "")
                upload_dir = Path(workspace_dir) / "uploads"
                video_file = upload_dir / f"{vid_stem}.mp4"
                
                if video_file.exists() and segments:
                    def _format_vtt_time(seconds):
                        h = int(seconds // 3600)
                        m = int((seconds % 3600) // 60)
                        s = int(seconds % 60)
                        ms = int((seconds - int(seconds)) * 1000)
                        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

                    vtt_lines = ["WEBVTT\n"]
                    for i, seg in enumerate(segments):
                        start_str = _format_vtt_time(seg.get("start", 0))
                        end_str = _format_vtt_time(seg.get("end", 0))
                        text_vi = seg.get("text_vi", "").replace('\n', ' ')
                        if text_vi:
                            vtt_lines.append(f"{i+1}\n{start_str} --> {end_str}\n{text_vi}\n")
                    
                    vtt_content = "\n".join(vtt_lines)
                    
                    st.markdown("**🎬 Xem lại Video Gốc để căn thời gian (Bật nút CC dưới góc video để xem Phụ đề tiếng Việt):**")
                    col_vid, col_empty = st.columns([1, 3])
                    with col_vid:
                        st.video(str(video_file), subtitles=vtt_content)
                elif video_file.exists():
                    st.markdown("**🎬 Xem lại Video Gốc để căn thời gian:**")
                    col_vid, col_empty = st.columns([1, 3])
                    with col_vid:
                        st.video(str(video_file))
                else:
                    st.info(f"Không tìm thấy video gốc ({vid_stem}.mp4) để hiển thị.")
                
                if segments:
                    # Convert to DataFrame for data_editor
                    df = pd.DataFrame(segments)
                    
                    # Cấu hình các cột (Cho phép sửa cả thời gian và bản dịch)
                    st.markdown("**Bảng Kịch bản (Có thể sửa Bắt đầu, Kết thúc và Bản dịch):**")
                    
                    edited_df = st.data_editor(
                        df,
                        column_config={
                            "start": st.column_config.NumberColumn("Bắt đầu (s)", format="%.2f", step=0.1),
                            "end": st.column_config.NumberColumn("Kết thúc (s)", format="%.2f", step=0.1),
                            "text": st.column_config.TextColumn("Văn bản gốc", disabled=True),
                            "text_vi": st.column_config.TextColumn("Bản dịch tiếng Việt"),
                        },
                        disabled=["text"], # Chỉ khóa cột văn bản gốc
                        hide_index=True,
                        use_container_width=True,
                        num_rows="dynamic"
                    )
                    
                    if st.button("💾 Lưu thay đổi", type="primary"):
                        # Convert back to dict and save
                        updated_segments = edited_df.to_dict('records')
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(updated_segments, f, ensure_ascii=False, indent=2)
                        st.success(f"Đã lưu kịch bản: {selected_file}!")
                        
                else:
                    st.warning("File kịch bản trống.")
            except Exception as e:
                st.error(f"Lỗi khi đọc file kịch bản: {e}")
    
    st.divider()

    # Upload file
    uploaded_files = st.file_uploader(
        "Kéo thả các file video (.mp4) của bạn vào đây", 
        type=["mp4"], 
        accept_multiple_files=True
    )
    
    if st.button("🚀 BẮT ĐẦU XỬ LÝ", type="primary", use_container_width=True):
        start_from = settings.get("start_from_step", 1)
        
        if start_from <= 2 and settings["translator_type"] in ["gemini", "deepseek"] and not settings["api_key"]:
            st.error("❌ Vui lòng nhập API Key bên thanh cấu hình để bắt đầu!")
            return
            
        if not uploaded_files:
            st.warning("⚠️ Vui lòng tải lên ít nhất 1 video để xử lý!")
            return
            
        # Lưu file tải lên vào ổ cứng
        upload_dir = Path(workspace_dir) / "uploads"
        upload_dir.mkdir(exist_ok=True)
        
        video_paths = []
        for file in uploaded_files:
            temp_path = upload_dir / file.name
            with open(temp_path, "wb") as f:
                f.write(file.getbuffer())
            video_paths.append(temp_path)
        
        # Khởi động pipeline trong background thread
        thread = start_pipeline_thread(
            video_paths=video_paths,
            settings=settings,
            workspace_dir=workspace_dir,
            process_manager=pm
        )
        st.session_state.pipeline_thread = thread
        
        # Rerun để chuyển sang UI đang chạy
        st.rerun()


def _render_running_ui(pm: ProcessManager):
    """
    Render UI khi pipeline đang chạy trong background.
    Hiển thị progress, logs, và nút Dừng/Ép Dừng.
    Tự rerun mỗi 2 giây để cập nhật.
    """
    # ─── Thanh Progress ───
    progress_bar = st.progress(pm.progress)
    status_text = st.markdown(f"**{pm.get_status_display()}**")
    
    # ─── Nút Dừng / Ép Dừng (HOẠT ĐỘNG vì UI không bị block) ───
    col_stop, col_force = st.columns(2)
    with col_stop:
        if st.button("⏸️ Dừng sau bước hiện tại", use_container_width=True, key="btn_stop"):
            pm.stop()
            st.warning("⏸️ Đã gửi yêu cầu DỪNG.")
            st.rerun()
    with col_force:
        if st.button("🛑 ÉP DỪNG NGAY", type="secondary", use_container_width=True, key="btn_force"):
            pm.force_stop()
            st.error("🛑 Đã gửi yêu cầu ÉP DỪNG.")
            st.rerun()
    
    # ─── Hiển thị Logs realtime ───
    logs = pm.get_logs()
    if logs:
        st.subheader("📋 Log xử lý")
        log_container = st.container(height=300)
        with log_container:
            for log in logs:
                if "❌" in log:
                    st.error(log)
                elif "✅" in log or "🎉" in log:
                    st.success(log)
                elif "⏩" in log:
                    st.info(log)
                elif "⏸️" in log:
                    st.warning(log)
                else:
                    st.write(log)
    
    # ─── Hiển thị video kết quả nếu có ───
    result_vid = pm.get_result_video()
    if result_vid and os.path.exists(result_vid):
        st.subheader("🎬 Video kết quả")
        st.video(result_vid)
    
    # ─── Auto-refresh: rerun sau 2 giây nếu vẫn đang chạy ───
    # Kiểm tra thread còn sống không
    thread = st.session_state.get("pipeline_thread")
    if thread and thread.is_alive():
        time.sleep(2)
        st.rerun()
    else:
        # Thread đã kết thúc
        if pm.progress >= 1.0:
            st.success("🎊 ĐÃ HOÀN TẤT TOÀN BỘ!")
            st.balloons()
        elif pm.get_logs() and any("dừng" in l.lower() for l in pm.get_logs()):
            st.warning("⏸️ Pipeline đã dừng.")
        st.session_state.pipeline_thread = None


if __name__ == "__main__":
    main()
