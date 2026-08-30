# import os
# import sys

# # ── Fix Windows DLL & OpenMP environment for PyTorch / Whisper ───────────────
# os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# try:
#     import site
#     packages = site.getsitepackages() + [site.getusersitepackages()]
#     for p in packages:
#         torch_lib = os.path.join(p, "torch", "lib")
#         if os.path.isdir(torch_lib) and hasattr(os, "add_dll_directory"):
#             try:
#                 os.add_dll_directory(torch_lib)
#             except Exception:
#                 pass
# except Exception:
#     pass

# sys.modules["torchcodec"] = None
# import numpy as np

# # ── ให้ Python หา ffmpeg เองผ่าน imageio-ffmpeg ────────────────────────────
# try:
#     import imageio_ffmpeg
#     _ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
#     os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
# except Exception:
#     pass

# # ── Default path ของโมเดล local ──────────────────────────────────────────────
# _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# DEFAULT_MODEL_PATH = os.path.join(_THIS_DIR, "whisper-small-final")

# from subtitle_config import SubtitleStyle


# def _report_progress(progress_cb, pct: int, msg: str):
#     if not progress_cb:
#         return
#     try:
#         progress_cb(pct, msg)
#     except TypeError:
#         progress_cb(f"[{pct}%] {msg}")
#     except Exception:
#         pass


# # ─────────────────────────────────────────────────────────────────────────────
# def _extract_audio_numpy(video_path: str) -> np.ndarray:
#     """แยก audio จากวิดีโอด้วย ffmpeg → numpy float32 @ 16000 Hz mono"""
#     import subprocess
#     import imageio_ffmpeg

#     ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
#     cmd = [
#         ffmpeg_exe, "-y", "-i", video_path,
#         "-vn", "-acodec", "pcm_s16le",
#         "-ar", "16000", "-ac", "1",
#         "-f", "s16le", "pipe:1",
#     ]
#     proc = subprocess.run(cmd, capture_output=True)
#     if proc.returncode != 0:
#         err = proc.stderr.decode(errors="ignore")[:400]
#         raise RuntimeError(f"ffmpeg แยก audio ไม่ได้: {err}")

#     audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
#     if len(audio) == 0:
#         raise RuntimeError("ไม่พบ audio ในไฟล์วิดีโอ")
#     return audio

# # Alias for backwards compatibility
# _load_audio = _extract_audio_numpy


# # ─────────────────────────────────────────────────────────────────────────────
# # ─────────────────────────────────────────────────────────────────────────────
# def _run_vad(audio: np.ndarray, progress_cb=None, sample_rate: int = 16000, deadair_sensitivity: float = 1.0) -> list[dict]:
#     """
#     Offline Energy/RMS-based Voice Activity Detection (VAD).
#     Detects real speech boundaries and silence gaps (>0.3s) to split audio into natural speech chunks.
#     Filters out Dead Air silences so subtitles are generated only for active speech.
#     """
#     _report_progress(progress_cb, 20, "Analyzing audio VAD speech segments...")

#     if len(audio) == 0:
#         return []

#     # 1. Compute frame RMS energy (20ms frame = 320 samples @ 16kHz, 10ms hop = 160 samples)
#     frame_len = int(sample_rate * 0.02)
#     hop_len = int(sample_rate * 0.01)

#     num_frames = (len(audio) - frame_len) // hop_len + 1
#     if num_frames <= 0:
#         return [{"start": 0, "end": len(audio)}]

#     shape = (num_frames, frame_len)
#     strides = (audio.strides[0] * hop_len, audio.strides[0])
#     frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)
#     rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)

#     # 2. Dynamic adaptive threshold (relative to noise floor)
#     sorted_rms = np.sort(rms)
#     noise_floor = np.mean(sorted_rms[:max(1, int(len(sorted_rms) * 0.20))])
#     mult = max(1.2, 2.2 / max(0.2, deadair_sensitivity))
#     threshold = max(0.008, noise_floor * mult)

#     is_speech = rms > threshold

#     # 3. Smooth speech mask (fill short silence holes < 0.25s, drop short noise bursts < 0.15s)
#     min_silence_frames = int(0.25 / 0.01)
#     min_speech_frames = int(0.15 / 0.01)

#     silence_count = 0
#     for i in range(len(is_speech)):
#         if not is_speech[i]:
#             silence_count += 1
#         else:
#             if 0 < silence_count < min_silence_frames:
#                 is_speech[i - silence_count : i] = True
#             silence_count = 0

#     speech_segments = []
#     in_speech = False
#     seg_start = 0

#     for i in range(len(is_speech)):
#         if is_speech[i] and not in_speech:
#             in_speech = True
#             seg_start = i * hop_len
#         elif not is_speech[i] and in_speech:
#             in_speech = False
#             seg_end = i * hop_len + frame_len
#             if (seg_end - seg_start) >= (min_speech_frames * hop_len):
#                 speech_segments.append({"start": seg_start, "end": seg_end})

#     if in_speech:
#         seg_end = len(audio)
#         if (seg_end - seg_start) >= (min_speech_frames * hop_len):
#             speech_segments.append({"start": seg_start, "end": seg_end})

#     # Fallback if no speech detected (e.g. very quiet speech)
#     if not speech_segments:
#         chunk_len = 16000 * 10
#         for start in range(0, len(audio), chunk_len):
#             end = min(start + chunk_len, len(audio))
#             if (end - start) > 1600:
#                 speech_segments.append({"start": start, "end": end})
#         return speech_segments

#     # 4. Merge adjacent segments if silence gap < 0.35s and total duration <= 10s
#     merged = []
#     curr = speech_segments[0]
#     for nxt in speech_segments[1:]:
#         gap = (nxt["start"] - curr["end"]) / float(sample_rate)
#         dur = (nxt["end"] - curr["start"]) / float(sample_rate)
#         if gap < 0.35 and dur <= 10.0:
#             curr["end"] = nxt["end"]
#         else:
#             merged.append(curr)
#             curr = nxt
#     merged.append(curr)

#     return merged


# # ─────────────────────────────────────────────────────────────────────────────
# # Dead Air / Silence Detection
# # ─────────────────────────────────────────────────────────────────────────────
# def detect_deadair_segments(
#     audio_input,
#     min_silence_ms: int = 500,
#     sample_rate: int = 16000,
#     progress_cb=None
# ) -> list[dict]:
#     """
#     High-precision Dead Air / Silence Detection.
#     Uses hybrid Dual-Engine analysis:
#       1. High-resolution Waveform Envelope (Peak Amplitude & RMS Energy in dBFS) with dynamic noise-floor modeling
#       2. Optional Silero VAD (PyTorch) for neural speech protection
#       3. Speech Safety Margins (Padding ~80ms) to ensure words and consonant onsets/decays are never clipped.
#     Returns list of all detected silence intervals:
#       [{'id': 1, 'start': 0.0, 'end': 2.450, 'duration': 2.450}, ...]
#     """
#     if progress_cb:
#         _report_progress(progress_cb, 10, "กำลังเตรียมข้อมูลเสียงสำหรับวิเคราะห์ Dead Air...")

#     if isinstance(audio_input, str):
#         if not os.path.exists(audio_input):
#             return []
#         audio = _extract_audio_numpy(audio_input)
#     elif isinstance(audio_input, np.ndarray):
#         audio = audio_input.astype(np.float32)
#     else:
#         return []

#     if audio is None or len(audio) == 0:
#         return []

#     total_duration = len(audio) / float(sample_rate)
#     min_silence_sec = max(0.05, float(min_silence_ms) / 1000.0)

#     # 1. High-Resolution Audio Waveform Analysis (10ms hop, 20ms frame)
#     frame_len = int(sample_rate * 0.02)
#     hop_len = int(sample_rate * 0.01)
#     num_frames = (len(audio) - frame_len) // hop_len + 1

#     if num_frames <= 0:
#         return []

#     shape = (num_frames, frame_len)
#     strides = (audio.strides[0] * hop_len, audio.strides[0])
#     frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)

#     # Calculate Peak Amplitude and RMS energy per frame
#     peak = np.max(np.abs(frames), axis=1)
#     rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)

#     # 2. Dynamic Ambient Noise Floor Estimation
#     # Measure the quietest 15% of the recording
#     noise_rms = float(np.percentile(rms, 15))
#     noise_peak = float(np.percentile(peak, 15))

#     # Speech/Sound Threshold:
#     # A frame is speech/sound if its peak amplitude or RMS rises above the noise floor
#     # Quiet speech, whispers, and consonant onsets have peak >= 0.012 or RMS >= 0.0025
#     speech_rms_thresh = max(0.0025, min(0.018, noise_rms * 1.45))
#     speech_peak_thresh = max(0.012, min(0.040, noise_peak * 1.55))

#     is_sound = (rms > speech_rms_thresh) | (peak > speech_peak_thresh)

#     # 3. Temporal Smoothing: Bridge natural syllable pauses (< 0.20s) so words aren't cut apart
#     min_pause_frames = int(0.20 / 0.01)
#     silence_count = 0
#     for i in range(len(is_sound)):
#         if not is_sound[i]:
#             silence_count += 1
#         else:
#             if 0 < silence_count < min_pause_frames:
#                 is_sound[i - silence_count : i] = True
#             silence_count = 0

#     # 5. Extract contiguous speech/sound intervals
#     speech_intervals = []
#     in_speech = False
#     seg_start = 0

#     min_sound_frames = int(0.08 / 0.01)
#     for i in range(len(is_sound)):
#         if is_sound[i] and not in_speech:
#             in_speech = True
#             seg_start = i * 0.01
#         elif not is_sound[i] and in_speech:
#             in_speech = False
#             seg_end = i * 0.01
#             if (seg_end - seg_start) >= (min_sound_frames * 0.01):
#                 speech_intervals.append({"start": seg_start, "end": seg_end})

#     if in_speech:
#         speech_intervals.append({"start": seg_start, "end": total_duration})

#     speech_intervals.sort(key=lambda s: s["start"])

#     # Merge overlapping speech segments
#     merged_speech = []
#     for s in speech_intervals:
#         if not merged_speech:
#             merged_speech.append(dict(s))
#         else:
#             last = merged_speech[-1]
#             if s["start"] <= last["end"] + 0.05:
#                 last["end"] = max(last["end"], s["end"])
#             else:
#                 merged_speech.append(dict(s))

#     # 6. Apply Speech Safety Margins (Padding = 0.080s)
#     # Silence cut must start AFTER voice decay and finish BEFORE voice onset
#     safety_pad = 0.080  # 80ms buffer around speech

#     if progress_cb:
#         _report_progress(progress_cb, 80, "ประมวลผลช่วง Dead Air ที่สมบูรณ์...")

#     deadair_intervals = []
#     curr_time = 0.0

#     for sp in merged_speech:
#         sp_start = max(0.0, sp["start"] - safety_pad)
#         sp_end = min(total_duration, sp["end"] + safety_pad)

#         gap = sp_start - curr_time
#         if gap >= min_silence_sec:
#             deadair_intervals.append({
#                 "start": round(curr_time, 3),
#                 "end": round(sp_start, 3),
#                 "duration": round(gap, 3)
#             })
#         curr_time = max(curr_time, sp_end)

#     if total_duration - curr_time >= min_silence_sec:
#         gap = total_duration - curr_time
#         deadair_intervals.append({
#             "start": round(curr_time, 3),
#             "end": round(total_duration, 3),
#             "duration": round(gap, 3)
#         })

#     # Number all detected intervals (no 25 limit!)
#     for idx, d in enumerate(deadair_intervals):
#         d["id"] = idx + 1

#     if progress_cb:
#         _report_progress(progress_cb, 100, f"ตรวจพบ Dead Air ทั้งหมด {len(deadair_intervals)} ช่วง")

#     return deadair_intervals


# # ─────────────────────────────────────────────────────────────────────────────
# def _run_local_whisper(
#     model_path: str,
#     audio: np.ndarray,
#     speech_ts: list[dict],
#     progress_cb=None,
# ) -> list[dict]:
#     """
#     ถอดเสียงด้วย Whisper pipeline และดึง timestamps คืนมาอย่างแม่นยำ
#     """
#     import torch
#     from transformers import WhisperProcessor, WhisperForConditionalGeneration, pipeline

#     if progress_cb:
#         progress_cb(f"โหลดโมเดล: {os.path.basename(model_path)} …")

#     # 1. Resolve paths for directory or .pt file (like best.pt)
#     pt_file = None
#     if os.path.isfile(model_path):
#         pt_file = model_path
#         model_dir = os.path.dirname(model_path)
#     else:
#         model_dir = model_path
#         for fname in ["best.pt", "model.pt", "pytorch_model.pt", "pytorch_model.bin"]:
#             fpath = os.path.join(model_dir, fname)
#             if os.path.exists(fpath):
#                 pt_file = fpath
#                 break

#     # 2. Load Processor (tokenizer & feature_extractor)
#     processor = None
#     try:
#         processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
#     except Exception:
#         try:
#             processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=False)
#         except Exception:
#             pass

#     if processor is None:
#         for fallback_model in ["openai/whisper-small", "openai/whisper-base", "openai/whisper-tiny"]:
#             try:
#                 processor = WhisperProcessor.from_pretrained(fallback_model, local_files_only=True)
#                 break
#             except Exception:
#                 pass
#         if processor is None:
#             raise RuntimeError(
#                 "ไม่สามารถโหลด Whisper processor ได้\n"
#                 "กรุณาตรวจสอบ internet หรือดาวน์โหลด model ไว้ใน cache ก่อน"
#             )

#     # 3. Load Model Architecture & Weights
#     model = None
#     device_str = "cuda" if torch.cuda.is_available() else "cpu"
#     torch_dtype = torch.float16 if device_str == "cuda" else torch.float32

#     if device_str == "cuda":
#         torch.backends.cudnn.benchmark = True
#         torch.backends.cuda.matmul.allow_tf32 = True
#         torch.backends.cudnn.allow_tf32 = True
#         _report_progress(progress_cb, 15, f"Using GPU: {torch.cuda.get_device_name(0)} (FP16 mode)")
#     else:
#         _report_progress(progress_cb, 15, "Using CPU for transcription (no CUDA GPU)")

#     if pt_file and os.path.exists(pt_file):
#         try:
#             state = torch.load(pt_file, map_location="cpu")
#             if isinstance(state, dict) and "state_dict" in state:
#                 state = state["state_dict"]

#             base_model_name = "openai/whisper-small"
#             if isinstance(state, dict) and "model.encoder.conv1.weight" in state:
#                 h_dim = state["model.encoder.conv1.weight"].shape[0]
#                 if h_dim == 384: base_model_name = "openai/whisper-tiny"
#                 elif h_dim == 512: base_model_name = "openai/whisper-base"
#                 elif h_dim == 768: base_model_name = "openai/whisper-small"
#                 elif h_dim == 1024: base_model_name = "openai/whisper-medium"

#             model = WhisperForConditionalGeneration.from_pretrained(
#                 base_model_name, torch_dtype=torch_dtype
#             )
#             model.load_state_dict(state, strict=False)
#             model = model.to(device_str)
#             model.eval()
#         except Exception as e:
#             print(f"[LocalWhisper] Loading state_dict weights failed: {e}")

#     if model is None:
#         try:
#             model = WhisperForConditionalGeneration.from_pretrained(
#                 model_dir, local_files_only=True, torch_dtype=torch_dtype
#             )
#             model = model.to(device_str)
#             model.eval()
#         except Exception as e:
#             try:
#                 model = WhisperForConditionalGeneration.from_pretrained(
#                     model_dir, local_files_only=False, torch_dtype=torch_dtype
#                 )
#                 model = model.to(device_str)
#                 model.eval()
#             except Exception as e2:
#                 raise RuntimeError(
#                     f"โหลดโมเดลจาก '{model_path}' ไม่สำเร็จ\n"
#                     f"รายละเอียด: {e2}\n\n"
#                     "วิธีแก้: เลือก folder ของ HuggingFace Whisper model ที่มี config.json\n"
#                     "หรือเลือก fallback model (tiny/base/small/medium) ใน dialog"
#                 )

#     # Force Thai language + transcribe task
#     try:
#         forced_decoder_ids = processor.get_decoder_prompt_ids(
#             language="thai", task="transcribe"
#         )
#     except Exception:
#         forced_decoder_ids = None

#     try:
#         pipe = pipeline(
#             "automatic-speech-recognition",
#             model=model,
#             tokenizer=processor.tokenizer,
#             feature_extractor=processor.feature_extractor,
#             torch_dtype=torch_dtype,
#             device=0 if device_str == "cuda" else -1,
#             # chunk_length_s=30,
#             batch_size=8 if device_str == "cuda" else 1,
#         )
#     except Exception as pe:
#         raise RuntimeError(f"สร้าง Whisper pipeline ไม่สำเร็จ: {pe}")

#     raw: list[dict] = []
#     total = len(speech_ts)

#     for i, ts in enumerate(speech_ts):
#         pct = 30 + int(((i + 1) / max(total, 1)) * 60)
#         _report_progress(progress_cb, pct, f"Transcribing audio chunk {i+1}/{total} ({pct}%)...")

#         start_sec = ts["start"] / 16000.0
#         end_sec   = ts["end"]   / 16000.0
#         chunk     = audio[ts["start"]:ts["end"]]

#         if len(chunk) < 1600:   # < 0.1 วิ ข้าม
#             continue

#         pad_samples = int(16000 * 0.3)
#         chunk_input = np.pad(chunk.astype(np.float32), (0, pad_samples), mode="constant")

#         try:
#             # res = pipe(
#             #     chunk.astype(np.float32),
#             #     generate_kwargs={
#             #         "forced_decoder_ids": forced_decoder_ids,
#             #         "max_new_tokens": 225,
#             #         "no_repeat_ngram_size": 3,
#             #     } if forced_decoder_ids else {"max_new_tokens": 225},
#             #     return_timestamps=True
#             # )
#             res = pipe(
#                 chunk_input,
#                 generate_kwargs={
#                     "language": "thai",
#                     "task": "transcribe",
#                     "max_new_tokens": 225,
#                     "no_repeat_ngram_size": 3,
#                 },
#                 return_timestamps=True
#             )
#         #     chunks_list = res.get("chunks", [])
#         #     if chunks_list:
#         #         for c in chunks_list:
#         #             c_text = (c.get("text") or "").strip()
#         #             t_range = c.get("timestamp")
#         #             if c_text and t_range:
#         #                 c_start, c_end = t_range
#         #                 if c_start is None: c_start = 0.0
#         #                 if c_end is None: c_end = end_sec - start_sec
#         #                 raw.append({
#         #                     "start": start_sec + c_start,
#         #                     "end": start_sec + c_end,
#         #                     "text": c_text
#         #                 })
#         #     else:
#         #         text = (res.get("text") or "").strip()
#         #         if text:
#         #             raw.append({"start": start_sec, "end": end_sec, "text": text})
#         # except Exception as e:
#         #     if progress_cb:
#         #         progress_cb(f"chunk {i+1} error: {type(e).__name__}: {e}")
#         #     continue
#             chunks_list = res.get("chunks", [])
#             if chunks_list:
#                 for c in chunks_list:
#                     c_text = (c.get("text") or "").strip()
#                     t_range = c.get("timestamp")
#                     if c_text and t_range:
#                         c_start, c_end = t_range
#                         if c_start is None: c_start = 0.0
#                         # ดักค่า None หรือเวลาที่เกินความยาวจริงก่อนเติม pad
#                         if c_end is None or c_end > (end_sec - start_sec):
#                             c_end = end_sec - start_sec
                        
#                         raw.append({
#                             "start": start_sec + c_start,
#                             "end": min(start_sec + c_end, end_sec),
#                             "text": c_text
#                         })
#             else:
#                 text = (res.get("text") or "").strip()
#                 if text:
#                     raw.append({"start": start_sec, "end": end_sec, "text": text})
#         except Exception as e:
#             if progress_cb:
#                 progress_cb(f"chunk {i+1} error: {type(e).__name__}: {e}")
#             continue

#     return raw


# # ─────────────────────────────────────────────────────────────────────────────
# def _segment_thai(text: str, words_per_line: int = 8) -> list[str]:
#     """
#     ตัดคำภาษาไทยด้วย PyThaiNLP แล้วแบ่งเป็น chunk ตาม words_per_line
#     พร้อม smart sentence-boundary detection:
#     - ตัดที่ . ? ! ก่อนเป็นอันดับแรก (sentence ends)
#     - ตัดที่ token ที่ลงท้ายประโยค เช่น ครับ ค่ะ นะ แล้ว
#     - fallback: นับจำนวนคำ
#     """
#     import re

#     # ── Sentence-boundary tokens (Thai polite particles / punctuation) ─────
#     SENTENCE_ENDERS = {"ครับ", "ค่ะ", "คะ", "นะ", "นะครับ", "นะคะ",
#                        "แล้วกัน", "เลย", "ด้วย", "เถอะ", "ละ"}

#     try:
#         from pythainlp.tokenize import word_tokenize
#         words = word_tokenize(text.strip(), engine="newmm", keep_whitespace=False)
#         words = [w for w in words if w.strip()]
#     except Exception:
#         words = text.strip().split() or [text.strip()]

#     if not words:
#         return [text.strip()]

#     # ── Group words into natural subtitle lines ───────────────────────────
#     chunks: list[str] = []
#     current: list[str] = []

#     for word in words:
#         current.append(word)
#         clean = word.strip().rstrip(".,!?")

#         # Check sentence boundary conditions
#         is_punct = re.search(r"[.!?。？！]", word)
#         is_ender = clean in SENTENCE_ENDERS

#         if is_punct or is_ender or len(current) >= words_per_line:
#             chunk = "".join(current).strip()
#             if chunk:
#                 chunks.append(chunk)
#             current = []

#     # Flush remaining words
#     if current:
#         leftover = "".join(current).strip()
#         if leftover:
#             # Merge very short trailing fragment with last chunk if possible
#             if chunks and len(leftover) <= 3:
#                 chunks[-1] = chunks[-1] + leftover
#             else:
#                 chunks.append(leftover)

#     return chunks or [text.strip()]




# # ─────────────────────────────────────────────────────────────────────────────
# def transcribe_video(
#     video_path: str,
#     model_size: str = "",
#     words_per_line: int = 8,
#     audio_range: tuple = None,
#     progress_cb=None,
# ) -> list[dict]:
#     """
#     ถอดเสียงจากวิดีโอ → list[{start, end, text}]

#     model_size: path ของ local model folder หรือชื่อ whisper ("tiny","base",...)
#     words_per_line: จำนวนคำ PyThaiNLP ต่อ 1 ซับ
#     audio_range: (start_sec, end_sec) ช่วงเวลาที่ต้องการถอดเสียง
#     """
#     if not model_size:
#         model_size = DEFAULT_MODEL_PATH

#     # 1. แยก audio
#     if progress_cb:
#         progress_cb("กำลังแยกเสียงจากวิดีโอ …")
#     audio = _extract_audio_numpy(video_path)

#     if audio_range is not None:
#         t_start, t_end = audio_range
#         sample_start = int(max(0, t_start * 16000))
#         sample_end = int(min(len(audio), t_end * 16000))
#         if sample_end > sample_start:
#             audio = audio[sample_start:sample_end]

#     # 2. VAD
#     speech_ts = _run_vad(audio, progress_cb=progress_cb)
#     if not speech_ts:
#         return []

#     raw_segments: list[dict] = []

#     # 3. ถอดเสียง
#     if os.path.isdir(model_size):
#         # ─── Local transformers model (direct generate, forced Thai) ──────────
#         raw_segments = _run_local_whisper(model_size, audio, speech_ts, progress_cb)

#     else:
#         # ─── Standard openai-whisper package ───────────────────────────────
#         try:
#             import whisper
#         except ImportError:
#             raise RuntimeError(
#                 "ไม่พบ library 'whisper'\n"
#                 "ติดตั้งด้วย: pip install openai-whisper\n"
#                 f"หรือระบุ path ของ local model ที่ถูกต้อง (ได้รับ: '{model_size}')"
#             )

#         if progress_cb:
#             progress_cb(f"โหลด Whisper '{model_size}' …")
#         model = whisper.load_model(model_size)

#         if progress_cb:
#             progress_cb(f"ถอดเสียง {len(speech_ts)} chunk (Whisper) …")

#         for i, ts in enumerate(speech_ts):
#             if progress_cb:
#                 progress_cb(f"chunk {i+1}/{len(speech_ts)} …")
#             start_sec = ts["start"] / 16000.0
#             end_sec   = ts["end"]   / 16000.0
#             chunk     = audio[ts["start"]:ts["end"]]
#             if len(chunk) < 1600:
#                 continue
#             try:
#                 result = model.transcribe(
#                     chunk.copy(),
#                     task="transcribe",
#                     language="th",
#                     no_speech_threshold=0.6,
#                     compression_ratio_threshold=2.4,
#                     condition_on_previous_text=False,
#                     initial_prompt="ภาษาไทยต่อไปนี้คือการถอดเสียงพูดภาษาไทย",
#                 )
#                 if "segments" in result:
#                     for sub_seg in result["segments"]:
#                         seg_text = (sub_seg.get("text") or "").strip()
#                         if seg_text:
#                             raw_segments.append({
#                                 "start": start_sec + sub_seg["start"],
#                                 "end": start_sec + sub_seg["end"],
#                                 "text": seg_text
#                             })
#                 else:
#                     text = (result.get("text") or "").strip()
#                     if text:
#                         raw_segments.append({"start": start_sec, "end": end_sec, "text": text})
#             except Exception as pipe_err:
#                 if progress_cb:
#                     progress_cb(f"chunk {i+1} error: {type(pipe_err).__name__}: {pipe_err}")
#                 continue

#     # 4. PyThaiNLP word segmentation & Character-Weighted Timestamp Alignment
#     if progress_cb:
#         progress_cb("ตัดคำและจัดลำดับเวลาซับด้วย PyThaiNLP …")

#     final_segments: list[dict] = []
#     for seg in raw_segments:
#         text = seg["text"].strip()
#         if not text:
#             continue

#         lines = _segment_thai(text, words_per_line=words_per_line)
#         if len(lines) == 1:
#             final_segments.append({
#                 "start": seg["start"],
#                 "end": seg["end"],
#                 "text": lines[0],
#             })
#             continue

#         # Allocate sub-segment duration proportionally by character count
#         dur = max(seg["end"] - seg["start"], 0.1)
#         total_chars = max(sum(len(l) for l in lines), 1)

#         curr_t = seg["start"]
#         for j, line in enumerate(lines):
#             line_char_ratio = len(line) / float(total_chars)
#             line_dur = dur * line_char_ratio
#             next_t = curr_t + line_dur
#             if j == len(lines) - 1:
#                 next_t = seg["end"]  # anchor exact end time

#             final_segments.append({
#                 "start": curr_t,
#                 "end": next_t,
#                 "text": line,
#             })
#             curr_t = next_t

#     if progress_cb:
#         progress_cb(f"เสร็จ! ได้ {len(final_segments)} ซับ จาก {len(raw_segments)} chunk")

#     return final_segments


# # ─────────────────────────────────────────────────────────────────────────────
# # SRT utilities
# # ─────────────────────────────────────────────────────────────────────────────

# def segments_to_srt(segments: list[dict], style=None) -> str:
#     def fmt_time(t: float) -> str:
#         h  = int(t // 3600)
#         m  = int((t % 3600) // 60)
#         s  = int(t % 60)
#         ms = int((t % 1) * 1000)
#         return f"{h:02}:{m:02}:{s:02},{ms:03}"

#     lines = []
#     for i, seg in enumerate(segments, 1):
#         lines.append(str(i))
#         lines.append(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}")
#         lines.append(seg["text"].strip())
#         lines.append("")
#     return "\n".join(lines)


# def save_srt(segments: list[dict], style, output_path: str) -> str:
#     srt_content = segments_to_srt(segments, style)
#     with open(output_path, "w", encoding="utf-8") as f:
#         f.write(srt_content)
#     return output_path


# # compat alias
# def wrap_segment(text: str, max_chars: int, max_lines: int) -> str:
#     import textwrap
#     lines = textwrap.wrap(text.strip(), width=max_chars)
#     return "\n".join(lines[:max_lines])



import os
import sys
import ctypes

# ── Fix Windows DLL & OpenMP environment for PyTorch / Whisper ───────────────
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
try:
    import site
    packages = site.getsitepackages() + [site.getusersitepackages()]
    for p in packages:
        torch_lib = os.path.join(p, "torch", "lib")
        if os.path.isdir(torch_lib) and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(torch_lib)
            except Exception:
                pass
except Exception:
    pass

sys.modules["torchcodec"] = None
import numpy as np

# ── ให้ Python หา FFmpeg ผ่าน imageio-ffmpeg ────────────────────────────────
try:
    import imageio_ffmpeg
    _ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

# ── Default Path ของ Local Model ─────────────────────────────────────────────
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
# 1. ดึงสัญญาณเสียงจากวิดีโอ (Audio Extraction & In-Memory Decoding @ 16kHz)
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
        err = proc.stderr.decode("utf-8", errors="ignore")[:400]
        raise RuntimeError(f"ffmpeg แยก audio ไม่ได้: {err}")

    audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(audio) == 0:
        raise RuntimeError("ไม่พบ audio ในไฟล์วิดีโอ")
    return audio


# ─────────────────────────────────────────────────────────────────────────────
# Voice Activity Detection (VAD) & Silence Detection
# ─────────────────────────────────────────────────────────────────────────────
def _run_vad(audio: np.ndarray, progress_cb=None, sample_rate: int = 16000, deadair_sensitivity: float = 1.0) -> list[dict]:
    """Offline Energy/RMS-based Voice Activity Detection (VAD)"""
    _report_progress(progress_cb, 20, "Analyzing audio VAD speech segments...")

    if len(audio) == 0:
        return []

    frame_len = int(sample_rate * 0.02)
    hop_len = int(sample_rate * 0.01)

    num_frames = (len(audio) - frame_len) // hop_len + 1
    if num_frames <= 0:
        return [{"start": 0, "end": len(audio)}]

    shape = (num_frames, frame_len)
    strides = (audio.strides[0] * hop_len, audio.strides[0])
    frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)

    sorted_rms = np.sort(rms)
    noise_floor = np.mean(sorted_rms[:max(1, int(len(sorted_rms) * 0.20))])
    mult = max(1.2, 2.2 / max(0.2, deadair_sensitivity))
    threshold = max(0.008, noise_floor * mult)

    is_speech = rms > threshold

    min_silence_frames = int(0.25 / 0.01)
    min_speech_frames = int(0.15 / 0.01)

    silence_count = 0
    for i in range(len(is_speech)):
        if not is_speech[i]:
            silence_count += 1
        else:
            if 0 < silence_count < min_silence_frames:
                is_speech[i - silence_count : i] = True
            silence_count = 0

    speech_segments = []
    in_speech = False
    seg_start = 0

    for i in range(len(is_speech)):
        if is_speech[i] and not in_speech:
            in_speech = True
            seg_start = i * hop_len
        elif not is_speech[i] and in_speech:
            in_speech = False
            seg_end = i * hop_len + frame_len
            if (seg_end - seg_start) >= (min_speech_frames * hop_len):
                speech_segments.append({"start": seg_start, "end": seg_end})

    if in_speech:
        seg_end = len(audio)
        if (seg_end - seg_start) >= (min_speech_frames * hop_len):
            speech_segments.append({"start": seg_start, "end": seg_end})

    if not speech_segments:
        chunk_len = 16000 * 10
        for start in range(0, len(audio), chunk_len):
            end = min(start + chunk_len, len(audio))
            if (end - start) > 1600:
                speech_segments.append({"start": start, "end": end})
        return speech_segments

    merged = []
    curr = speech_segments[0]
    for nxt in speech_segments[1:]:
        gap = (nxt["start"] - curr["end"]) / float(sample_rate)
        dur = (nxt["end"] - curr["start"]) / float(sample_rate)
        if gap < 0.35 and dur <= 10.0:
            curr["end"] = nxt["end"]
        else:
            merged.append(curr)
            curr = nxt
    merged.append(curr)

    return merged


def detect_deadair_segments(
    audio_input,
    min_silence_ms: int = 500,
    sample_rate: int = 16000,
    progress_cb=None
) -> list[dict]:
    """High-precision Dead Air / Silence Detection"""
    if progress_cb:
        _report_progress(progress_cb, 10, "กำลังเตรียมข้อมูลเสียงสำหรับวิเคราะห์ Dead Air...")

    if isinstance(audio_input, str):
        if not os.path.exists(audio_input):
            return []
        audio = _extract_audio_numpy(audio_input)
    elif isinstance(audio_input, np.ndarray):
        audio = audio_input.astype(np.float32)
    else:
        return []

    if audio is None or len(audio) == 0:
        return []

    total_duration = len(audio) / float(sample_rate)
    min_silence_sec = max(0.05, float(min_silence_ms) / 1000.0)

    frame_len = int(sample_rate * 0.02)
    hop_len = int(sample_rate * 0.01)
    num_frames = (len(audio) - frame_len) // hop_len + 1

    if num_frames <= 0:
        return []

    shape = (num_frames, frame_len)
    strides = (audio.strides[0] * hop_len, audio.strides[0])
    frames = np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides)

    peak = np.max(np.abs(frames), axis=1)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)

    noise_rms = float(np.percentile(rms, 15))
    noise_peak = float(np.percentile(peak, 15))

    speech_rms_thresh = max(0.0025, min(0.018, noise_rms * 1.45))
    speech_peak_thresh = max(0.012, min(0.040, noise_peak * 1.55))

    is_sound = (rms > speech_rms_thresh) | (peak > speech_peak_thresh)

    min_pause_frames = int(0.20 / 0.01)
    silence_count = 0
    for i in range(len(is_sound)):
        if not is_sound[i]:
            silence_count += 1
        else:
            if 0 < silence_count < min_pause_frames:
                is_sound[i - silence_count : i] = True
            silence_count = 0

    speech_intervals = []
    in_speech = False
    seg_start = 0

    min_sound_frames = int(0.08 / 0.01)
    for i in range(len(is_sound)):
        if is_sound[i] and not in_speech:
            in_speech = True
            seg_start = i * 0.01
        elif not is_sound[i] and in_speech:
            in_speech = False
            seg_end = i * 0.01
            if (seg_end - seg_start) >= (min_sound_frames * 0.01):
                speech_intervals.append({"start": seg_start, "end": seg_end})

    if in_speech:
        speech_intervals.append({"start": seg_start, "end": total_duration})

    speech_intervals.sort(key=lambda s: s["start"])

    merged_speech = []
    for s in speech_intervals:
        if not merged_speech:
            merged_speech.append(dict(s))
        else:
            last = merged_speech[-1]
            if s["start"] <= last["end"] + 0.05:
                last["end"] = max(last["end"], s["end"])
            else:
                merged_speech.append(dict(s))

    safety_pad = 0.080
    if progress_cb:
        _report_progress(progress_cb, 80, "ประมวลผลช่วง Dead Air ที่สมบูรณ์...")

    deadair_intervals = []
    curr_time = 0.0

    for sp in merged_speech:
        sp_start = max(0.0, sp["start"] - safety_pad)
        sp_end = min(total_duration, sp["end"] + safety_pad)

        gap = sp_start - curr_time
        if gap >= min_silence_sec:
            deadair_intervals.append({
                "start": round(curr_time, 3),
                "end": round(sp_start, 3),
                "duration": round(gap, 3)
            })
        curr_time = max(curr_time, sp_end)

    if total_duration - curr_time >= min_silence_sec:
        gap = total_duration - curr_time
        deadair_intervals.append({
            "start": round(curr_time, 3),
            "end": round(total_duration, 3),
            "duration": round(gap, 3)
        })

    for idx, d in enumerate(deadair_intervals):
        d["id"] = idx + 1

    if progress_cb:
        _report_progress(progress_cb, 100, f"ตรวจพบ Dead Air ทั้งหมด {len(deadair_intervals)} ช่วง")

    return deadair_intervals


# ─────────────────────────────────────────────────────────────────────────────
# 2. ถอดเสียงด้วย AI (Local Whisper Model)
# ─────────────────────────────────────────────────────────────────────────────
def _run_local_whisper(
    model_path: str,
    audio: np.ndarray,
    speech_ts: list[dict],
    progress_cb=None,
) -> list[dict]:
    """ถอดเสียงด้วยโมเดล Whisper ภายในเครื่องผ่าน model.generate โดยตรง (ไม่ผ่าน pipeline)"""
    import torch
    from transformers import WhisperProcessor, WhisperForConditionalGeneration

    if progress_cb:
        progress_cb(f"โหลดโมเดล: {os.path.basename(model_path)} …")

    # 1. Resolve paths
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

    # 2. Load Processor
    processor = None
    try:
        processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
    except Exception:
        try:
            processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=False)
        except Exception:
            pass

    if processor is None:
        for fallback_model in ["openai/whisper-small", "openai/whisper-base", "openai/whisper-tiny"]:
            try:
                processor = WhisperProcessor.from_pretrained(fallback_model, local_files_only=True)
                break
            except Exception:
                pass
        if processor is None:
            raise RuntimeError("ไม่สามารถโหลด Whisper processor ได้ กรุณาตรวจสอบอินเทอร์เน็ตหรือโมเดล")

    # 3. Load Model
    device_str = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if device_str == "cuda" else torch.float32

    if device_str == "cuda":
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        _report_progress(progress_cb, 15, f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        _report_progress(progress_cb, 15, "Using CPU for transcription")

    model = None
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

            model = WhisperForConditionalGeneration.from_pretrained(base_model_name, torch_dtype=torch_dtype)
            model.load_state_dict(state, strict=False)
            model = model.to(device_str)
            model.eval()
        except Exception as e:
            print(f"[LocalWhisper] Loading state_dict weights failed: {e}")

    if model is None:
        try:
            model = WhisperForConditionalGeneration.from_pretrained(model_dir, local_files_only=True, torch_dtype=torch_dtype)
            model = model.to(device_str)
            model.eval()
        except Exception:
            try:
                model = WhisperForConditionalGeneration.from_pretrained(model_dir, local_files_only=False, torch_dtype=torch_dtype)
                model = model.to(device_str)
                model.eval()
            except Exception as e2:
                raise RuntimeError(f"โหลดโมเดลจาก '{model_path}' ไม่สำเร็จ: {e2}")

    # 4. Decoder Prompt Setup (Forced Thai + English terms support)
    forced_decoder_ids = None
    try:
        forced_decoder_ids = processor.get_decoder_prompt_ids(language="thai", task="transcribe")
    except Exception:
        pass

    prompt_ids = None
    try:
        prompt_text = "บทสนทนาภาษาไทย มีคำทับศัพท์และภาษาอังกฤษ เช่น Video, Audio, Track, Cut, Edit, Clip, Timeline, AI, Python, Export"
        prompt_ids = processor.get_prompt_ids(prompt_text, return_tensors="pt").to(device_str)
    except Exception:
        pass

    raw: list[dict] = []
    total = len(speech_ts)

    # 5. Direct Inference Loop
    for i, ts in enumerate(speech_ts):
        pct = 30 + int(((i + 1) / max(total, 1)) * 60)
        _report_progress(progress_cb, pct, f"Transcribing audio chunk {i+1}/{total} ({pct}%)...")

        start_sec = ts["start"] / 16000.0
        end_sec   = ts["end"]   / 16000.0
        chunk     = audio[ts["start"]:ts["end"]]

        if len(chunk) < 1600:
            continue

        try:
            # แปลง Audio Chunk เป็น Mel Spectrogram
            input_features = processor(
                chunk.astype(np.float32),
                sampling_rate=16000,
                return_tensors="pt"
            ).input_features.to(device_str, dtype=torch_dtype)

            gen_kwargs = {
                "max_new_tokens": 225,
            }
            if forced_decoder_ids is not None:
                gen_kwargs["forced_decoder_ids"] = forced_decoder_ids
            if prompt_ids is not None:
                gen_kwargs["prompt_ids"] = prompt_ids

            with torch.no_grad():
                predicted_ids = model.generate(input_features, **gen_kwargs)

            # ถอดรหัส Tokens ออกมาเป็นข้อความ
            transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
            text = (transcription or "").strip()

            if text:
                raw.append({
                    "start": start_sec,
                    "end": end_sec,
                    "text": text
                })

        except Exception as e:
            if progress_cb:
                progress_cb(f"chunk {i+1} error: {type(e).__name__}: {e}")
            continue

    return raw


# ─────────────────────────────────────────────────────────────────────────────
# 3. ตัดคำภาษาไทยด้วย PyThaiNLP พร้อม Smart Sentence-Boundary Detection
# ─────────────────────────────────────────────────────────────────────────────
def _segment_thai(text: str, words_per_line: int = 8) -> list[str]:
    """
    ตัดคำภาษาไทยด้วย PyThaiNLP (newmm engine)
    พร้อม Smart Sentence-Boundary Detection:
    - ตัดที่เครื่องหมายวรรคตอน (. ? !) ก่อนเป็นอันดับแรก
    - ตัดที่คำลงท้ายประโยค เช่น ครับ ค่ะ นะ แล้วกัน เลย ด้วย เถอะ
    - แบ่งความยาวข้อความไม่ให้เกิน words_per_line
    """
    import re

    SENTENCE_ENDERS = {"ครับ", "ค่ะ", "คะ", "นะ", "นะครับ", "นะคะ",
                       "แล้วกัน", "เลย", "ด้วย", "เถอะ", "ละ"}

    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(text.strip(), engine="newmm", keep_whitespace=False)
        words = [w for w in words if w.strip()]
    except Exception:
        words = text.strip().split() or [text.strip()]

    if not words:
        return [text.strip()]

    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        clean = word.strip().rstrip(".,!?")

        is_punct = re.search(r"[.!?。？！]", word)
        is_ender = clean in SENTENCE_ENDERS

        if is_punct or is_ender or len(current) >= words_per_line:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []

    if current:
        leftover = "".join(current).strip()
        if leftover:
            if chunks and len(leftover) <= 3:
                chunks[-1] = chunks[-1] + leftover
            else:
                chunks.append(leftover)

    return chunks or [text.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline หลัก: Transcribe Video
# ─────────────────────────────────────────────────────────────────────────────
def transcribe_video(
    video_path: str,
    model_size: str = "",
    words_per_line: int = 8,
    audio_range: tuple = None,
    progress_cb=None,
) -> list[dict]:
    """ถอดเสียงจากวิดีโอ → list[{start, end, text}]"""
    if not model_size:
        model_size = DEFAULT_MODEL_PATH

    # 1. แยก Audio ออกมาเป็น 16kHz
    if progress_cb:
        progress_cb("กำลังแยกเสียงจากวิดีโอ …")
    audio = _extract_audio_numpy(video_path)

    if audio_range is not None:
        t_start, t_end = audio_range
        sample_start = int(max(0, t_start * 16000))
        sample_end = int(min(len(audio), t_end * 16000))
        if sample_end > sample_start:
            audio = audio[sample_start:sample_end]

    # 2. กรองเฉพาะท่อนเสียงพูดด้วย VAD
    speech_ts = _run_vad(audio, progress_cb=progress_cb)
    if not speech_ts:
        return []

    # 3. ถอดเสียงด้วย AI (Local Transformers Model หรือ Fallback OpenAI Whisper)
    raw_segments: list[dict] = []

    if os.path.isdir(model_size):
        raw_segments = _run_local_whisper(model_size, audio, speech_ts, progress_cb)
    else:
        try:
            import whisper
        except ImportError:
            raise RuntimeError("ไม่พบ library 'whisper' กรุณาติดตั้งด้วย: pip install openai-whisper")

        if progress_cb:
            progress_cb(f"โหลด Whisper '{model_size}' …")
        model = whisper.load_model(model_size)

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
                    compression_ratio_threshold=2.4,
                    condition_on_previous_text=False,
                    initial_prompt="บทสนทนาภาษาไทย มีคำทับศัพท์และภาษาอังกฤษ เช่น Video, Audio, Track, Cut, Edit, Clip, Timeline, AI, Python, Export",
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

    # 4. ตัดคำและเกลี่ยเวลาด้วย PyThaiNLP ตามความยาวตัวอักษร
    if progress_cb:
        progress_cb("ตัดคำและจัดลำดับเวลาซับด้วย PyThaiNLP …")

    final_segments: list[dict] = []
    for seg in raw_segments:
        text = seg["text"].strip()
        if not text:
            continue

        lines = _segment_thai(text, words_per_line=words_per_line)
        if len(lines) == 1:
            final_segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": lines[0],
            })
            continue

        dur = max(seg["end"] - seg["start"], 0.1)
        total_chars = max(sum(len(l) for l in lines), 1)

        curr_t = seg["start"]
        for j, line in enumerate(lines):
            line_char_ratio = len(line) / float(total_chars)
            line_dur = dur * line_char_ratio
            next_t = curr_t + line_dur
            if j == len(lines) - 1:
                next_t = seg["end"]

            final_segments.append({
                "start": curr_t,
                "end": next_t,
                "text": line,
            })
            curr_t = next_t

    if progress_cb:
        progress_cb(f"เสร็จ! ได้ {len(final_segments)} ซับ จาก {len(raw_segments)} chunk")

    return final_segments


# ─────────────────────────────────────────────────────────────────────────────
# 4. SRT Export Utilities
# ─────────────────────────────────────────────────────────────────────────────
def segments_to_srt(segments: list[dict], style=None) -> str:
    """แปลง segments เป็นข้อความ SRT Format"""
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
    """บันทึกไฟล์ SRT ลง Disk ด้วย UTF-8 Encoding"""
    srt_content = segments_to_srt(segments, style)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return output_path


def wrap_segment(text: str, max_chars: int, max_lines: int) -> str:
    """ตัดคำขึ้นบรรทัดใหม่อัตโนมัติ (Wrapper)"""
    import textwrap
    lines = textwrap.wrap(text.strip(), width=max_chars)
    return "\n".join(lines[:max_lines])