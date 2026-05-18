# PROJECT_STATE — tool-reup-video

Cập nhật: 2026-05-18 18:54 GMT+7  
Đường dẫn: `E:\tool-video\tool-reup-video`  
Git branch: `feature/krillin-quality-port`  
Commit hiện tại: `fa27f24 Improve translation quality and project workflow`

## Mục tiêu dự án

Tool Streamlit tên **ViralLocal / Auto Reup** để xử lý batch video ngắn:

1. Upload/import video theo từng project.
2. Tách audio bằng FFmpeg.
3. ASR bằng `faster-whisper`.
4. Dịch phụ đề Trung/nguồn sang tiếng Việt bằng Gemini/DeepSeek/local/none.
5. Sinh TTS tiếng Việt bằng Edge TTS hoặc Gemini TTS.
6. Đồng bộ audio TTS theo timeline phụ đề.
7. Render video cuối: che sub/logo, lật ngang optional, hard-sub ASS, mix nhạc nền gốc + lồng tiếng.

## Cấu trúc chính

- `main.py` — UI Streamlit chính: chọn project, upload video, chạy pipeline, editor transcript, import SRT/KrillinAI.
- `ui/sidebar.py` — sidebar cấu hình: dịch, ASR, template, TTS, render, bước bắt đầu/kết thúc.
- `ui/pipeline_runner.py` — chạy pipeline trong background thread, hỗ trợ batch + resume từ bước 1-4.
- `core/process_manager.py` — trạng thái pipeline, stop/force stop, logs, progress, subprocess kill.
- `modules/transcription_translator.py` — ASR + dịch + cache SQLite.
- `modules/tts_generator.py` — sinh TTS từng segment, smart skip, align/pad/silence fallback.
- `modules/video_renderer.py` — tạo ASS, mix TTS, render bằng FFmpeg.
- `modules/visual_processor.py` — build filter che sub/logo/lật video.
- `utils/project_manager.py` — project workspace riêng dưới `workspace/projects/<slug>/`.
- `utils/srt_utils.py` — parse/write SRT, merge target/origin SRT thành transcript JSON.
- `utils/audio_utils.py` — helper mới cho align TTS audio: speed up, pad, create silence.
- `config/config.yaml` — config mặc định app/pipeline/tts/render/logging.
- `config/local_secrets.json` — local secret file, đã nằm trong `.gitignore`, không commit.
- `bin/ffmpeg-master-latest-win64-gpl-shared/` — FFmpeg bundle local, cũng bị ignore bởi `.gitignore`.

## Runtime/workspace

- App dùng workspace project riêng: `workspace/projects/<project-name>/`.
- Mỗi project có các folder: `uploads`, `audios`, `transcripts`, `tts_audios`, `outputs`; cache dịch/ASR nằm tại `cache.db` trong project.
- Có dữ liệu runtime/generated cũ trong `workspace/` và `workspace/projects/*`; toàn bộ `workspace/` bị ignore.
- Project đang thấy: `default`, `demo-new`, `kinh-mat-review`.

## Trạng thái Git hiện tại

`git status --short`:

```text
 M main.py
 M modules/tts_generator.py
 M ui/pipeline_runner.py
 M ui/sidebar.py
?? utils/audio_utils.py
```

Diff stat:

```text
main.py                  |  83 +++++++++++++++++++++++++++-
modules/tts_generator.py | 141 +++++++++++++++++++++++------------------------
ui/pipeline_runner.py    |   1 +
ui/sidebar.py            |  12 +++-
4 files changed, 162 insertions(+), 75 deletions(-)
```

Lưu ý: `utils/audio_utils.py` là file mới chưa tracked nên chưa nằm trong diff stat của git.

## Những thay đổi/chức năng mới đang có trong working tree

### 1. Project workflow

- UI có project selector/creator/importer.
- `utils.project_manager` tạo project riêng tại `workspace/projects/<slug>/`.
- Có thể import folder workspace/project cũ bằng copy-only, không move/xóa source.

### 2. Import SRT / KrillinAI output

Trong `main.py` có expander **Import SRT / KrillinAI output**:

- Chọn video đã upload trong project hoặc nhập manual transcript stem.
- Upload `target_srt` tiếng Việt, optional `origin_srt` tiếng Trung.
- Ghi transcript JSON vào `transcripts/<stem>_transcript.json`.
- Dùng `merge_origin_target_srt()` để tạo records `{id,start,end,text_zh,text_vi}`.
- Sau import có thể chạy từ **Bước 3: Lồng tiếng TTS**.

### 3. Dịch/ASR chất lượng hơn

`modules/transcription_translator.py` hiện có:

- Faster-Whisper với `vad_filter`, `word_timestamps`, source language configurable.
- Cache ASR theo file hash + translation cache SQLite.
- Gemini/DeepSeek prompt bắt JSON, giữ id, không copy tiếng Trung.
- `is_bad_translation()` phát hiện output rỗng, còn tiếng Trung, giống source, hoặc lỗi.
- Retry strict theo batch và retry từng câu khi bản dịch lỗi.
- Có chế độ `translator_type == "none"` để chỉ lấy kịch bản gốc.

### 4. TTS timeline alignment

`modules/tts_generator.py` + `utils/audio_utils.py` hiện có:

- `max_speed_increase` configurable từ sidebar, mặc định 50%.
- File TTS được lưu theo video + voice: `tts_audios/<video>/<voice>/...` để tránh đè khi đổi giọng.
- Smart skip cache: kiểm tra file mp3 tồn tại, size > 100, duration > 0.
- Nếu audio dài hơn slot: tăng tốc bằng FFmpeg `atempo`, giới hạn bởi `max_speed_increase`.
- Nếu audio ngắn hơn slot: pad silence để đủ duration.
- Nếu text lỗi/empty hoặc TTS/align fail: tạo silence fallback, tránh timeline bị thủng.
- Ghi metadata vào segment: `tts_duration`, `tts_target_duration`, `tts_align_action`, `tts_fallback_reason`.

### 5. Render

`modules/video_renderer.py`:

- Tạo ASS subtitle qua `generate_ass_subtitle()`.
- Mix các TTS clip thành wav tạm rồi `amix` với audio gốc giảm volume.
- Video filter gồm che sub/logo/lật video, sau đó burn subtitle.
- Fast preview: `libx264 ultrafast crf 35`, audio 96k.
- Final: `libx264 fast crf 23`, audio 192k.

## Cách chạy / kiểm tra nhanh

Chạy app:

```powershell
cd E:\tool-video\tool-reup-video
streamlit run main.py
```

Cài dependency Python nếu thiếu:

```powershell
pip install -r requirements.txt
```

Kiểm tra syntax hiện tại:

```powershell
python -m compileall -q .
```

Kết quả kiểm tra lúc 2026-05-18 18:54: **pass, không output lỗi**.

Test suite hiện chưa chạy được bằng pytest vì môi trường Python hiện tại thiếu pytest:

```text
C:\Users\cam\AppData\Local\Programs\Python\Python313\python.exe: No module named pytest
```

Các file `tests/test_module*.py` hiện thiên về script/manual/integration, có input/API/video/network; chưa phải unit test tự động sạch.

## Rủi ro / điểm cần chú ý

1. **Chưa commit working tree** — các thay đổi mới rất quan trọng, đặc biệt `utils/audio_utils.py`; cần commit sớm để không mất state.
2. **Không có pytest trong môi trường** — chỉ mới verify bằng `compileall`, chưa có test tự động end-to-end.
3. **Các test hiện tại tương tác/manual** — cần refactor nếu muốn CI/unit test thật.
4. **Generated media lớn bị ignore** — đúng hướng, nhưng nếu cần sample test thì đặt rõ trong `samples/` hoặc `examples/` vì `.gitignore` đang allow hai folder này.
5. **API keys local** — `config/local_secrets.json` bị ignore; không đưa vào note/commit.
6. **Line ending warning** — git báo LF sẽ bị thay bằng CRLF cho `main.py`, `ui/pipeline_runner.py` khi Git touch; nên cân nhắc `.gitattributes` nếu muốn ổn định line endings.
7. **FFmpeg bundle bị ignore** — máy mới cần có FFmpeg trong `bin/` hoặc `utils.ffmpeg_utils` phải tìm được binary khác.
8. **`main.py` khá lớn** — UI project/import/editor/pipeline đang gom nhiều logic; sau này nên tách `ui/transcript_editor.py` và `ui/srt_importer.py`.

## Việc nên làm tiếp theo

Ưu tiên cao:

1. Chạy manual smoke test bằng Streamlit:
   - mở `streamlit run main.py`;
   - tạo/chọn project test;
   - upload một video ngắn;
   - thử import target/origin SRT;
   - chạy từ Bước 3 rồi Bước 4.
2. Commit snapshot hiện tại sau khi smoke test ổn:
   - nhớ add cả `utils/audio_utils.py`;
   - message gợi ý: `Add SRT import and robust TTS timeline alignment`.
3. Thêm `pytest` vào dev dependency hoặc tạo `requirements-dev.txt`.
4. Viết unit test không cần API/video thật cho:
   - `utils.srt_utils.parse_srt_content`, `merge_origin_target_srt`;
   - `utils.audio_utils._atempo_chain`;
   - `utils.transcription_utils.is_bad_translation`.

Ưu tiên vừa:

1. Tách UI import/editor khỏi `main.py` để dễ maintain.
2. Thêm `.gitattributes` để cố định LF/CRLF.
3. Thêm README ngắn: setup, chạy app, workflow, lưu ý API key/workspace.
4. Thêm health check trong UI: FFmpeg found, Python deps, GPU/CPU whisper mode.

## Resume note cho phiên sau

Nếu tiếp tục làm project này, bắt đầu bằng:

```powershell
cd E:\tool-video\tool-reup-video
git status --short
python -m compileall -q .
```

Sau đó đọc file này (`PROJECT_STATE.md`) và kiểm tra diff hiện tại trước khi sửa tiếp.
