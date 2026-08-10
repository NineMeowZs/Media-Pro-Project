import os
import sys
import ctypes

# ── Pre-load PyTorch & C++ Runtime DLLs on Windows to fix WinError 1114 ──────
_torch_lib = r"C:\Users\User\AppData\Roaming\Python\Python314\site-packages\torch\lib"
if os.path.exists(_torch_lib):
    if hasattr(os, "add_dll_directory"):
        try: os.add_dll_directory(_torch_lib)
        except Exception: pass
    for _dll_name in ["libiomp5md.dll", "c10.dll", "torch_cpu.dll", "torch.dll"]:
        _dpath = os.path.join(_torch_lib, _dll_name)
        if os.path.exists(_dpath):
            try: ctypes.WinDLL(_dpath)
            except Exception: pass

sys.modules["torchcodec"] = None
import numpy as np

# ── ให้ Python หา ffmpeg เองผ่าน imageio-ffmpeg ────────────────────────────
try:
    import imageio_ffmpeg
    _ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

# ── Default path ของโมเดล local ──────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(_THIS_DIR, "whisper-small-final")

from subtitle_config import SubtitleStyle


def _report_progress(progress_cb, pct: int, msg: str):
    if not progress_cb:
        return
    try:
        progress_cb(pct, msg)
    except TypeError:
        progress_cb(f"[{pct}%] {msg}")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
def _extract_audio_numpy(video_path: str) -> np.ndarray:
    """แยก audio จากวิดีโอด้วย ffmpeg → numpy float32 @ 16000 Hz mono"""
    import subprocess
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-f", "s16le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="ignore")[:400]
        raise RuntimeError(f"ffmpeg แยก audio ไม่ได้: {err}")

    audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(audio) == 0:
        raise RuntimeError("ไม่พบ audio ในไฟล์วิดีโอ")
    return audio


# ─────────────────────────────────────────────────────────────────────────────
def _run_vad(audio: np.ndarray, progress_cb=None) -> list[dict]:
    """
    แบ่งช่วงสัญญาณเสียงออฟไลน์ 100% (หลีกเลี่ยงการเชื่อมต่อภายนอกที่ทำให้ค้าง)
    เพื่อเตรียมส่งไปถอดความด้วย Whisper
    """
    _report_progress(progress_cb, 20, "Analyzing audio VAD segments...")
        
    chunk_len = 16000 * 30  # แบ่งช่วงละ 30 วินาทีตามมาตรฐาน Whisper window size
    chunks = []
    for start in range(0, len(audio), chunk_len):
        end = min(start + chunk_len, len(audio))
        if (end - start) > 1600:  # มีขนาดมากกว่า 0.1 วินาที
            chunks.append({"start": start, "end": end})
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
def _run_local_whisper(
    model_path: str,
    audio: np.ndarray,
    speech_ts: list[dict],
    progress_cb=None,
) -> list[dict]:
    """
    ถอดเสียงด้วย Whisper pipeline และดึง timestamps คืนมาอย่างแม่นยำ
    """
    import torch
    from transformers import WhisperProcessor, WhisperForConditionalGeneration, pipeline

    if progress_cb:
        progress_cb(f"โหลดโมเดล: {os.path.basename(model_path)} …")

    # 1. Resolve paths for directory or .pt file (like best.pt)
    pt_file = None
    if os.path.isfile(model_path):
        pt_file = model_path
        model_dir = os.path.dirname(model_path)
    else:
        model_dir = model_path
        for fname in ["best.pt", "model.pt", "pytorch_model.pt", "pytorch_model.bin"]:
            fpath = os.path.join(model_dir, fname)
            if os.path.exists(fpath):
                pt_file = fpath
                break

    # 2. Load Processor (tokenizer & feature_extractor)
    processor = None
    try:
        processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
    except Exception:
        try:
            processor = WhisperProcessor.from_pretrained(model_dir)
        except Exception:
            pass

    if processor is None:
        # Fallback to standard whisper-small processor for local .pt files
        try:
            processor = WhisperProcessor.from_pretrained("openai/whisper-small")
        except Exception:
            processor = WhisperProcessor.from_pretrained("openai/whisper-base")

    # 3. Load Model Architecture & Weights
    model = None
    device_str = "cuda" if torch.cuda.is_available() else "cpu"

    if pt_file and os.path.exists(pt_file):
        try:
            state = torch.load(pt_file, map_location="cpu")
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]

            base_model_name = "openai/whisper-small"
            if isinstance(state, dict) and "model.encoder.conv1.weight" in state:
                h_dim = state["model.encoder.conv1.weight"].shape[0]
                if h_dim == 384: base_model_name = "openai/whisper-tiny"
                elif h_dim == 512: base_model_name = "openai/whisper-base"
                elif h_dim == 768: base_model_name = "openai/whisper-small"
                elif h_dim == 1024: base_model_name = "openai/whisper-medium"

            model = WhisperForConditionalGeneration.from_pretrained(base_model_name)
            model.load_state_dict(state, strict=False)
            model = model.to(device_str)
            model.eval()
        except Exception as e:
            print(f"[LocalWhisper] Loading state_dict weights failed: {e}")

    if model is None:
        try:
            model = WhisperForConditionalGeneration.from_pretrained(model_dir, local_files_only=True)
            model = model.to(device_str)
            model.eval()
        except Exception as e:
            try:
                model = WhisperForConditionalGeneration.from_pretrained(model_dir)
                model = model.to(device_str)
                model.eval()
            except Exception as e2:
                raise RuntimeError(
                    f"โหลดโมเดลจาก '{model_path}' ไม่สำเร็จ\n"
                    f"รายละเอียด: {e2}"
                )

    # Force Thai language + transcribe task
    try:
        forced_decoder_ids = processor.get_decoder_prompt_ids(
            language="thai", task="transcribe"
        )
    except Exception:
        forced_decoder_ids = None

    # Setup pipeline
    try:
        pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            device=0 if device_str == "cuda" else -1
        )
    except Exception as pe:
        raise RuntimeError(f"สร้าง Whisper pipeline ไม่สำเร็จ: {pe}")

    raw: list[dict] = []
    total = len(speech_ts)

    for i, ts in enumerate(speech_ts):
        pct = 30 + int(((i + 1) / max(total, 1)) * 60)
        _report_progress(progress_cb, pct, f"Transcribing audio chunk {i+1}/{total} ({pct}%)...")

        start_sec = ts["start"] / 16000.0
        end_sec   = ts["end"]   / 16000.0
        chunk     = audio[ts["start"]:ts["end"]]

        if len(chunk) < 1600:   # < 0.1 วิ ข้าม
            continue

        try:
            # ใช้ return_timestamps=True เพื่อดึงช่วงเวลาคำพูดจริง
            res = pipe(
                chunk.astype(np.float32),
                generate_kwargs={"forced_decoder_ids": forced_decoder_ids} if forced_decoder_ids else {},
                return_timestamps=True
            )
            chunks_list = res.get("chunks", [])
            if chunks_list:
                for c in chunks_list:
                    c_text = (c.get("text") or "").strip()
                    t_range = c.get("timestamp")
                    if c_text and t_range:
                        c_start, c_end = t_range
                        if c_start is None: c_start = 0.0
                        if c_end is None: c_end = (ts["end"] - ts["start"]) / 16000.0
                        raw.append({
                            "start": start_sec + c_start,
                            "end": start_sec + c_end,
                            "text": c_text
                        })
            else:
                text = (res.get("text") or "").strip()
                if text:
                    raw.append({"start": start_sec, "end": end_sec, "text": text})
        except Exception as e:
            if progress_cb:
                progress_cb(f"chunk {i+1} error: {type(e).__name__}: {e}")
            continue

    return raw


# ─────────────────────────────────────────────────────────────────────────────
def _segment_thai(text: str, words_per_line: int = 8) -> list[str]:
    """
    ตัดคำภาษาไทยด้วย PyThaiNLP แล้วแบ่งเป็น chunk ตาม words_per_line
    """
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(text.strip(), engine="newmm", keep_whitespace=False)
        words = [w for w in words if w.strip()]
    except Exception:
        words = text.strip().split() or [text.strip()]

    if not words:
        return [text.strip()]

    chunks = []
    for i in range(0, len(words), words_per_line):
        chunk = "".join(words[i: i + words_per_line])
        if chunk:
            chunks.append(chunk)
    return chunks or [text.strip()]


# ─────────────────────────────────────────────────────────────────────────────
def transcribe_video(
    video_path: str,
    model_size: str = "",
    words_per_line: int = 8,
    audio_range: tuple = None,
    progress_cb=None,
) -> list[dict]:
    """
    ถอดเสียงจากวิดีโอ → list[{start, end, text}]

    model_size: path ของ local model folder หรือชื่อ whisper ("tiny","base",...)
    words_per_line: จำนวนคำ PyThaiNLP ต่อ 1 ซับ
    audio_range: (start_sec, end_sec) ช่วงเวลาที่ต้องการถอดเสียง
    """
    if not model_size:
        model_size = DEFAULT_MODEL_PATH

    # 1. แยก audio
    if progress_cb:
        progress_cb("กำลังแยกเสียงจากวิดีโอ …")
    audio = _extract_audio_numpy(video_path)

    if audio_range is not None:
        t_start, t_end = audio_range
        sample_start = int(max(0, t_start * 16000))
        sample_end = int(min(len(audio), t_end * 16000))
        if sample_end > sample_start:
            audio = audio[sample_start:sample_end]

    # 2. VAD
    speech_ts = _run_vad(audio, progress_cb=progress_cb)
    if not speech_ts:
        return []

    raw_segments: list[dict] = []

    # 3. ถอดเสียง
    if os.path.isdir(model_size):
        # ─── Local transformers model (direct generate, forced Thai) ──────────
        raw_segments = _run_local_whisper(model_size, audio, speech_ts, progress_cb)


    else:
        # ─── Standard openai-whisper package ───────────────────────────────
        try:
            import whisper
        except ImportError:
            raise RuntimeError(
                "ไม่พบ library 'whisper'\n"
                "ติดตั้งด้วย: pip install openai-whisper\n"
                f"หรือระบุ path ของ local model ที่ถูกต้อง (ได้รับ: '{model_size}')"
            )

        if progress_cb:
            progress_cb(f"โหลด Whisper '{model_size}' …")
        model = whisper.load_model(model_size)

        if progress_cb:
            progress_cb(f"ถอดเสียง {len(speech_ts)} chunk (Whisper) …")

        for i, ts in enumerate(speech_ts):
            if progress_cb:
                progress_cb(f"chunk {i+1}/{len(speech_ts)} …")
            start_sec = ts["start"] / 16000.0
            end_sec   = ts["end"]   / 16000.0
            chunk     = audio[ts["start"]:ts["end"]]
            if len(chunk) < 1600:
                continue
            try:
                result = model.transcribe(
                    chunk.copy(),
                    task="transcribe",
                    language="th",
                    no_speech_threshold=0.6,
                    condition_on_previous_text=False,
                    initial_prompt="ภาษาไทย",
                )
                if "segments" in result:
                    for sub_seg in result["segments"]:
                        seg_text = (sub_seg.get("text") or "").strip()
                        if seg_text:
                            raw_segments.append({
                                "start": start_sec + sub_seg["start"],
                                "end": start_sec + sub_seg["end"],
                                "text": seg_text
                            })
                else:
                    text = (result.get("text") or "").strip()
                    if text:
                        raw_segments.append({"start": start_sec, "end": end_sec, "text": text})
            except Exception as pipe_err:
                if progress_cb:
                    progress_cb(f"chunk {i+1} error: {type(pipe_err).__name__}: {pipe_err}")
                continue

    # 4. PyThaiNLP word segmentation → แบ่ง segment ย่อย
    if progress_cb:
        progress_cb("ตัดคำด้วย PyThaiNLP …")

    final_segments: list[dict] = []
    for seg in raw_segments:
        lines = _segment_thai(seg["text"], words_per_line=words_per_line)
        dur   = seg["end"] - seg["start"]
        tpl   = dur / max(len(lines), 1)
        for j, line in enumerate(lines):
            final_segments.append({
                "start": seg["start"] + j * tpl,
                "end":   seg["start"] + (j + 1) * tpl,
                "text":  line,
            })

    if progress_cb:
        progress_cb(f"เสร็จ! ได้ {len(final_segments)} ซับ จาก {len(raw_segments)} chunk")

    return final_segments


# ─────────────────────────────────────────────────────────────────────────────
# SRT utilities
# ─────────────────────────────────────────────────────────────────────────────

def segments_to_srt(segments: list[dict], style=None) -> str:
    def fmt_time(t: float) -> str:
        h  = int(t // 3600)
        m  = int((t % 3600) // 60)
        s  = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def save_srt(segments: list[dict], style, output_path: str) -> str:
    srt_content = segments_to_srt(segments, style)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return output_path


# compat alias
def wrap_segment(text: str, max_chars: int, max_lines: int) -> str:
    import textwrap
    lines = textwrap.wrap(text.strip(), width=max_chars)
    return "\n".join(lines[:max_lines])
