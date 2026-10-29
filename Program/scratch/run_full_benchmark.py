import os
import sys
import time
import json
import cv2
import numpy as np

# Ensure environment
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from settings_manager import get_model_folder
from transcriber import detect_deadair_segments, transcribe_video, _extract_audio_numpy
from subtitle_config import SubtitleStyle
from video_exporter import export_video_with_subtitles, _detect_gpu_encoder
from proxy_manager import ProxyManager, _proxy_path_for

VID_DIR = r"D:\Folder_For_Work\Year4_1\Media Pro Project\Test Vid"

TEST_FILES = [
    # (Category, Relative Path, Subtitle Test Duration in seconds or None for full)
    ("Outdoor", r"outdoor\เดินป่ากับคนตาบอด...คุยกันอย่างไร ThisAbl.mp4", None),
    ("Outdoor", r"outdoor\ไม่มีใครฉลาดเรื่องความรักหรอก Koendanai (720p).mp4", None),
    ("Podcast", r"podcast\บริหารเงิน bigboung.mp4", None),
    ("Podcast", r"podcast\เปอร์3.mp4", None),
    ("Podcast", r"podcast\คุณพี่ไม่รู้จัก Youtuber หรอค้าาา - Doogunyoung.mp4", 90.0),
    ("Game",    r"game\เรเชล6.mp4", 90.0),
    ("Podcast", r"podcast\กี่เวฟนะ.mp4", 90.0),
    ("Podcast", r"podcast\wanny.mkv", 90.0),
]

def benchmark_all():
    model_folder = get_model_folder()
    print("=" * 80)
    print("STARTING REAL COMPREHENSIVE BENCHMARK ON ALL 8 TEST VIDEOS")
    print(f"Model: {model_folder}")
    enc_name, enc_args = _detect_gpu_encoder()
    print(f"Hardware Video Encoder: {enc_name}")
    print("=" * 80)

    # Pre-warm model once so model loading time doesn't distort transcription benchmarks
    print("\n[Warmup] Loading model once into memory...")
    t_warm = time.time()
    try:
        from transcriber import _run_local_whisper
        dummy_audio = np.zeros(16000 * 2, dtype=np.float32)
        _run_local_whisper(model_folder, dummy_audio, [{"start": 0, "end": 32000}])
        print(f"[Warmup] Model initialized in {time.time() - t_warm:.2f}s\n")
    except Exception as e:
        print(f"[Warmup] Note: {e}\n")

    results = []
    pm = ProxyManager()

    for idx, (cat, rel_path, sub_dur_limit) in enumerate(TEST_FILES, 1):
        full_path = os.path.join(VID_DIR, rel_path)
        if not os.path.exists(full_path):
            print(f"File not found: {full_path}")
            continue

        print(f"\n{'='*30} [{idx}/8] {cat}: {os.path.basename(full_path)} {'='*30}")

        # 1. Metadata
        cap = cv2.VideoCapture(full_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()

        dur_sec = frame_cnt / fps if fps > 0 else 0.0
        file_size_mb = os.path.getsize(full_path) / (1024 * 1024)

        print(f"Info: {w}x{h} @ {fps:.1f}fps | Duration: {dur_sec:.2f}s ({dur_sec/60:.2f}m) | Size: {file_size_mb:.1f} MB")

        # 2. Test Import & Smoothness Pipeline
        # Measure: Audio extraction time
        t0 = time.time()
        audio = _extract_audio_numpy(full_path)
        t_audio_extract = time.time() - t0

        # Measure: 480p Proxy Build time (from scratch)
        proxy_path = _proxy_path_for(full_path)
        if os.path.exists(proxy_path):
            try: os.remove(proxy_path)
            except: pass

        t0 = time.time()
        pm._run_ffmpeg(full_path, proxy_path, on_progress_cb=None)
        t_proxy_build = time.time() - t0
        proxy_size_mb = os.path.getsize(proxy_path) / (1024 * 1024) if os.path.exists(proxy_path) else 0

        # Measure Seek Latency (Original vs Proxy)
        # Seek 5 random spots in the video
        seek_points = [dur_sec * p for p in [0.1, 0.3, 0.5, 0.7, 0.9]]

        # Original seek latency
        cap_orig = cv2.VideoCapture(full_path)
        t_orig_seeks = []
        for sp in seek_points:
            f_idx = int(sp * fps)
            ts_start = time.perf_counter()
            cap_orig.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            cap_orig.read()
            t_orig_seeks.append(time.perf_counter() - ts_start)
        cap_orig.release()
        avg_seek_orig_ms = np.mean(t_orig_seeks) * 1000

        # Proxy seek latency
        cap_prx = cv2.VideoCapture(proxy_path)
        t_prx_seeks = []
        for sp in seek_points:
            f_idx = int(sp * (cap_prx.get(cv2.CAP_PROP_FPS) or fps))
            ts_start = time.perf_counter()
            cap_prx.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            cap_prx.read()
            t_prx_seeks.append(time.perf_counter() - ts_start)
        cap_prx.release()
        avg_seek_prx_ms = np.mean(t_prx_seeks) * 1000

        # Total time until smooth = time until proxy is ready & loaded
        t_until_smooth = t_proxy_build

        print(f"Import & Smoothness:")
        print(f" - Audio prep time: {t_audio_extract:.2f}s")
        print(f" - Proxy build time: {t_proxy_build:.2f}s (Proxy size: {proxy_size_mb:.1f} MB)")
        print(f" - Seek Latency: Original = {avg_seek_orig_ms:.1f} ms | Proxy = {avg_seek_prx_ms:.1f} ms (Speedup: {avg_seek_orig_ms / max(avg_seek_prx_ms, 0.01):.1f}x)")
        print(f" - Total Time until Smooth: {t_until_smooth:.2f}s")

        # 3. Dead Air Detection Test
        t0 = time.time()
        deadairs = detect_deadair_segments(audio, min_silence_ms=500, sample_rate=16000)
        t_deadair = time.time() - t0

        total_deadair_sec = sum(d["duration"] for d in deadairs)
        deadair_pct = (total_deadair_sec / max(dur_sec, 0.01)) * 100
        time_saved_sec = total_deadair_sec

        print(f"Dead Air Detection:")
        print(f" - Detection time: {t_deadair:.2f}s")
        print(f" - Intervals detected: {len(deadairs)} intervals")
        print(f" - Total Dead Air: {total_deadair_sec:.2f}s ({deadair_pct:.1f}% of video)")
        print(f" - Useful Video remaining: {dur_sec - total_deadair_sec:.2f}s")

        # 4. Subtitle Generation Test
        sub_range = (0.0, sub_dur_limit) if sub_dur_limit and sub_dur_limit < dur_sec else None
        tested_audio_dur = sub_dur_limit if sub_range else dur_sec

        t0 = time.time()
        subs = transcribe_video(full_path, model_size=model_folder, audio_range=sub_range)
        t_transcribe = time.time() - t0

        rtf = t_transcribe / max(tested_audio_dur, 0.01) # Real-Time Factor (<1 is faster than realtime)
        speed_x = tested_audio_dur / max(t_transcribe, 0.01)

        print(f"Subtitle Generation:")
        print(f" - Audio length transcribed: {tested_audio_dur:.2f}s")
        print(f" - Transcribe time: {t_transcribe:.2f}s ({speed_x:.1f}x real-time)")
        print(f" - Subtitle cues created: {len(subs)}")

        # 5. Video Export Test (Export 15s sample with ASS subtitle burn-in via GPU NVENC)
        sample_export_out = os.path.join("scratch", f"export_test_{idx}.mp4")
        if os.path.exists(sample_export_out):
            try: os.remove(sample_export_out)
            except: pass

        style = SubtitleStyle()
        # Clip test segments to export range
        export_subs = [s for s in subs if s.get("start", 0) <= 15.0]

        # Use an ffmpeg subclip for export test to keep export benchmark snappy
        subclip_in = os.path.join("scratch", f"subclip_{idx}.mp4")
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        import subprocess
        # Cut first 15s cleanly
        subprocess.run([ff, "-y", "-ss", "0", "-t", "15", "-i", full_path, "-c", "copy", subclip_in],
                       capture_output=True)

        t0 = time.time()
        export_video_with_subtitles(
            input_path=subclip_in,
            output_path=sample_export_out,
            segments=export_subs,
            style=style,
            progress_cb=None,
            target_w=w,
            target_h=h
        )
        t_export_15s = time.time() - t0
        export_speed_fps = (15.0 * fps) / max(t_export_15s, 0.01)
        export_speed_x = 15.0 / max(t_export_15s, 0.01)

        # Estimate full video export time based on measured throughput
        estimated_full_export_s = dur_sec / max(export_speed_x, 0.01)

        print(f"Video Export (GPU NVENC):")
        print(f" - 15s export time: {t_export_15s:.2f}s ({export_speed_x:.1f}x real-time, {export_speed_fps:.1f} fps)")
        print(f" - Estimated full export time: {estimated_full_export_s:.2f}s ({estimated_full_export_s/60:.2f}m)")

        # Cleanup test subclips
        for tmp_f in [subclip_in, sample_export_out]:
            if os.path.exists(tmp_f):
                try: os.remove(tmp_f)
                except: pass

        # Record item result
        res_item = {
            "index": idx,
            "category": cat,
            "filename": os.path.basename(full_path),
            "rel_path": rel_path,
            "resolution": f"{w}x{h}",
            "fps": round(fps, 1),
            "duration_sec": round(dur_sec, 2),
            "size_mb": round(file_size_mb, 1),
            # Metric 1
            "audio_prep_sec": round(t_audio_extract, 2),
            "proxy_build_sec": round(t_proxy_build, 2),
            "time_until_smooth_sec": round(t_until_smooth, 2),
            "orig_seek_ms": round(avg_seek_orig_ms, 1),
            "proxy_seek_ms": round(avg_seek_prx_ms, 1),
            "seek_speedup_ratio": round(avg_seek_orig_ms / max(avg_seek_prx_ms, 0.01), 1),
            # Metric 2
            "transcribe_tested_dur_sec": round(tested_audio_dur, 2),
            "transcribe_time_sec": round(t_transcribe, 2),
            "transcribe_speed_x": round(speed_x, 2),
            "transcribe_subs_count": len(subs),
            # Metric 3
            "deadair_detect_sec": round(t_deadair, 2),
            "deadair_count": len(deadairs),
            "deadair_total_sec": round(total_deadair_sec, 2),
            "deadair_percentage": round(deadair_pct, 1),
            "useful_dur_sec": round(dur_sec - total_deadair_sec, 2),
            # Metric 4
            "export_sample_sec": round(t_export_15s, 2),
            "export_speed_x": round(export_speed_x, 2),
            "export_fps": round(export_speed_fps, 1),
            "estimated_full_export_sec": round(estimated_full_export_s, 2),
        }
        results.append(res_item)

    out_json = os.path.join("scratch", "benchmark_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETE! Saved results to {out_json}")
    print("=" * 80)

if __name__ == "__main__":
    benchmark_all()
