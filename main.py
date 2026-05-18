import os
import time
from pathlib import Path
import streamlit as st

from core.process_manager import ProcessManager
from ui.sidebar import render_sidebar
from ui.pipeline_runner import start_pipeline_thread
from utils.logger import setup_logger
from utils.project_manager import ensure_project, import_project_folder, list_projects, slugify_project_name

logger = setup_logger(__name__)

# ─── Cấu hình trang Streamlit ───
st.set_page_config(
    page_title="ViralLocal - Auto Reup",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.25rem; padding-bottom: 2rem; }
        h1 { margin-bottom: 0.15rem; }
        div[data-testid="stFileUploader"] section {
            padding: 0.75rem 1rem;
            min-height: 88px;
        }
        div[data-testid="stFileUploader"] section > div { padding: 0.25rem; }
        div[data-testid="stFileUploader"] small { display: none; }
        .stAlert { padding: 0.65rem 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── Khởi tạo Session State ───
if "process_manager" not in st.session_state:
    st.session_state.process_manager = ProcessManager()
if "pipeline_thread" not in st.session_state:
    st.session_state.pipeline_thread = None
if "active_project" not in st.session_state:
    projects = list_projects()
    st.session_state.active_project = projects[0] if projects else "default"

pm: ProcessManager = st.session_state.process_manager


def _render_project_box() -> str:
    """Render project selector/creator/importer and return active workspace path."""
    st.subheader("📁 Project")
    projects = list_projects()
    if st.session_state.active_project not in projects:
        ensure_project(st.session_state.active_project)
        projects = list_projects()

    col_select, col_new, col_create = st.columns([1.2, 1.2, 0.8])
    with col_select:
        selected = st.selectbox(
            "Project đang dùng",
            projects,
            index=projects.index(st.session_state.active_project) if st.session_state.active_project in projects else 0,
        )
        if selected != st.session_state.active_project:
            st.session_state.active_project = selected
            st.rerun()
    with col_new:
        new_project_name = st.text_input("Tên project mới", placeholder="vd: kinh-mat-review")
    with col_create:
        st.write("")
        st.write("")
        if st.button("➕ Tạo/Mở", use_container_width=True):
            if new_project_name.strip():
                project_dir = ensure_project(new_project_name)
                st.session_state.active_project = project_dir.name
                st.success(f"Đã mở project: {project_dir.name}")
                st.rerun()
            else:
                st.warning("Nhập tên project trước.")

    with st.expander("📦 Import folder project/workspace cũ", expanded=False):
        import_path = st.text_input("Đường dẫn folder cũ", placeholder=r"E:\tool-video\tool-reup-video\workspace_old")
        import_name = st.text_input("Tên project sau khi import", placeholder="Để trống = dùng tên folder")
        overwrite = st.checkbox("Ghi đè nếu project đã tồn tại", value=False)
        if st.button("Import folder", use_container_width=True):
            try:
                dest = import_project_folder(import_path, import_name or Path(import_path).name, overwrite=overwrite)
                st.session_state.active_project = dest.name
                st.success(f"Đã import vào project: {dest.name}")
                st.rerun()
            except Exception as e:
                st.error(f"Import thất bại: {e}")

    workspace_dir = str(ensure_project(st.session_state.active_project))
    st.caption(f"Workspace: `{workspace_dir}`")
    return workspace_dir


def main():
    st.title("🚀 ViralLocal")
    st.caption("Auto Reup: Tách âm thanh → Dịch AI → Lồng tiếng → Che logo/render")

    # ═══════════════════════════════════════════════
    # TRƯỜNG HỢP 1: Pipeline ĐANG CHẠY (background thread)
    # ═══════════════════════════════════════════════
    if pm.is_running:
        _render_running_ui(pm)
        return

    # ─── Project + Sidebar Cấu hình ───
    workspace_dir = _render_project_box()
    settings = render_sidebar(workspace_dir)

    # ═══════════════════════════════════════════════
    # TRƯỜNG HỢP 2: Pipeline ĐÃ DỪNG (hiển thị kết quả)
    # ═══════════════════════════════════════════════
    st.info(pm.get_status_display())

    logs = pm.get_logs()
    if logs:
        with st.expander("📋 Log lần chạy trước", expanded=False):
            for log in logs:
                st.write(log)
        result_vid = pm.get_result_video()
        if result_vid and os.path.exists(result_vid):
            st.video(result_vid)

    col_left, col_right = st.columns([0.9, 1.4], gap="large")

    with col_left:
        st.subheader("📥 Video đầu vào")
        uploaded_files = st.file_uploader(
            "Kéo thả hoặc chọn video",
            type=["mp4"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploaded_files:
            st.caption(f"Đã chọn {len(uploaded_files)} file: " + ", ".join([f.name for f in uploaded_files[:3]]) + ("..." if len(uploaded_files) > 3 else ""))

        if st.button("🚀 BẮT ĐẦU XỬ LÝ", type="primary", use_container_width=True):
            start_from = settings.get("start_from_step", 1)

            if start_from <= 2 and settings["translator_type"] in ["gemini", "deepseek"] and not settings["api_key"]:
                st.error("❌ Vui lòng nhập hoặc lưu API Key bên thanh cấu hình để bắt đầu!")
                return

            if not uploaded_files:
                st.warning("⚠️ Vui lòng tải lên ít nhất 1 video để xử lý!")
                return

            upload_dir = Path(workspace_dir) / "uploads"
            upload_dir.mkdir(exist_ok=True)

            video_paths = []
            for file in uploaded_files:
                temp_path = upload_dir / file.name
                with open(temp_path, "wb") as f:
                    f.write(file.getbuffer())
                video_paths.append(temp_path)

            thread = start_pipeline_thread(
                video_paths=video_paths,
                settings=settings,
                workspace_dir=workspace_dir,
                process_manager=pm
            )
            st.session_state.pipeline_thread = thread
            st.rerun()

    with col_right:
        _render_transcript_editor(workspace_dir)


def _render_transcript_editor(workspace_dir: str):
    st.subheader("📝 Transcript Editor")
    with st.expander("Kiểm tra/sửa kịch bản trước khi TTS", expanded=True):
        transcripts_dir = Path(workspace_dir) / "transcripts"
        transcript_files = []
        if transcripts_dir.exists():
            transcript_files = [f.name for f in transcripts_dir.glob("*_transcript.json")]

        if not transcript_files:
            st.info("Chưa có kịch bản trong project này. Chạy Bước 1-2 trước.")
            return

        selected_file = st.selectbox("Chọn kịch bản", transcript_files)
        if not selected_file:
            return

        file_path = transcripts_dir / selected_file
        import json
        import pandas as pd

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                segments = json.load(f)

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
                st.video(str(video_file), subtitles="\n".join(vtt_lines))
            elif video_file.exists():
                st.video(str(video_file))

            if not segments:
                st.warning("File kịch bản trống.")
                return

            df = pd.DataFrame(segments)
            edited_df = st.data_editor(
                df,
                column_config={
                    "start": st.column_config.NumberColumn("Bắt đầu (s)", format="%.2f", step=0.1),
                    "end": st.column_config.NumberColumn("Kết thúc (s)", format="%.2f", step=0.1),
                    "text": st.column_config.TextColumn("Văn bản gốc", disabled=True),
                    "text_zh": st.column_config.TextColumn("Văn bản gốc", disabled=True),
                    "text_vi": st.column_config.TextColumn("Bản dịch tiếng Việt"),
                },
                disabled=["text", "text_zh"],
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic"
            )

            if st.button("💾 Lưu thay đổi", type="primary"):
                updated_segments = edited_df.to_dict('records')
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(updated_segments, f, ensure_ascii=False, indent=2)
                st.success(f"Đã lưu kịch bản: {selected_file}!")
        except Exception as e:
            st.error(f"Lỗi khi đọc file kịch bản: {e}")


def _render_running_ui(pm: ProcessManager):
    """
    Render UI khi pipeline đang chạy trong background.
    Hiển thị progress, logs, và nút Dừng/Ép Dừng.
    Tự rerun mỗi 2 giây để cập nhật.
    """
    progress_bar = st.progress(pm.progress)
    status_text = st.markdown(f"**{pm.get_status_display()}**")

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

    result_vid = pm.get_result_video()
    if result_vid and os.path.exists(result_vid):
        st.subheader("🎬 Video kết quả")
        st.video(result_vid)

    thread = st.session_state.get("pipeline_thread")
    if thread and thread.is_alive():
        time.sleep(2)
        st.rerun()
    else:
        if pm.progress >= 1.0:
            st.success("🎊 ĐÃ HOÀN TẤT TOÀN BỘ!")
            st.balloons()
        elif pm.get_logs() and any("dừng" in l.lower() for l in pm.get_logs()):
            st.warning("⏸️ Pipeline đã dừng.")
        st.session_state.pipeline_thread = None

if __name__ == "__main__":
    main()
