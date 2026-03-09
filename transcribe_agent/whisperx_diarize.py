"""WhisperX-based transcription + diarization.

Uses faster-whisper for transcription, wav2vec2 for word-level alignment,
and pyannote for speaker diarization. Each word gets a speaker label.

Requires whisperx, pyannote-audio, torch (with CUDA for GPU acceleration).
"""

import os
import sys
import time
import threading
import warnings
import logging

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Suppress noisy warnings from pyannote/torchcodec/torch
warnings.filterwarnings("ignore", message=".*torchcodec.*")
warnings.filterwarnings("ignore", message=".*torchaudio.*")
warnings.filterwarnings("ignore", message=".*?!.*flashback.*")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("speechbrain").setLevel(logging.ERROR)

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Approx realtime speed multipliers for time estimates
_TRANSCRIBE_SPEED_CUDA = 15.0  # faster-whisper CUDA float16: ~15x realtime
_TRANSCRIBE_SPEED_CPU = 2.0    # faster-whisper CPU int8: ~2x realtime (conservative)
_DIARIZE_SPEED = 1.5            # pyannote: ~1.5x realtime on CPU/GPU


def log(msg=""):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


class _ProgressBar:
    """Progress bar with time estimate based on audio duration."""

    def __init__(self, label="Processing", audio_duration=0, speed_factor=1.0):
        self._stop = threading.Event()
        self._thread = None
        self._label = label
        self._audio_duration = audio_duration
        self._speed_factor = speed_factor

    def start(self):
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_label(self, label):
        self._label = label

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        sys.stderr.write("\033[2K\r")
        sys.stderr.flush()

    def _run(self):
        idx = 0
        est_total = self._audio_duration / self._speed_factor if self._speed_factor > 0 else 0
        bar_len = 20

        while not self._stop.is_set():
            elapsed = time.time() - self._start_time
            m, s = int(elapsed // 60), int(elapsed % 60)
            char = _SPINNER[idx % len(_SPINNER)]
            idx += 1

            # \033[2K = clear entire line, \r = return to start
            if est_total > 0 and elapsed < est_total * 2:
                pct = min(int(elapsed / est_total * 100), 99)
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                remaining = max(0, est_total - elapsed)
                rm, rs = int(remaining // 60), int(remaining % 60)
                line = f"\033[2K\r  {char} {self._label} [{bar}] {pct}% {m}:{s:02d} ~{rm}:{rs:02d}"
            else:
                line = f"\033[2K\r  {char} {self._label}... {m}:{s:02d}"

            sys.stderr.write(line)
            sys.stderr.flush()
            self._stop.wait(0.15)


def transcribe_and_diarize(
    audio_path: str,
    hf_token: str,
    language: str = "ru",
    whisper_model: str = "large-v3",
    num_speakers: int = None,
    min_speakers: int = None,
    max_speakers: int = None,
    batch_size: int = 8,
) -> list:
    """Full WhisperX pipeline: transcribe + align + diarize.

    Returns:
        (segments, unique_speakers) tuple
    """
    import whisperx
    import torch

    has_cuda = torch.cuda.is_available()
    diarize_device = "cuda" if has_cuda else "cpu"
    align_device = "cuda" if has_cuda else "cpu"
    whisper_device = "cuda" if has_cuda else "cpu"
    compute_type = "float16" if has_cuda else "int8"
    transcribe_speed = _TRANSCRIBE_SPEED_CUDA if has_cuda else _TRANSCRIBE_SPEED_CPU

    log(f"  Whisper/Align: {'CUDA (GPU)' if has_cuda else 'CPU'} ({compute_type})")
    log(f"  Diarize: {'CUDA (GPU)' if has_cuda else 'CPU'}")
    log()

    # === STEP 1: Load audio ===
    log("  Loading audio...")
    audio = whisperx.load_audio(audio_path)
    duration = len(audio) / 16000
    log(f"  Duration: {duration/60:.1f} min")
    log()

    # === STEP 2: Transcribe ===
    log("  Loading faster-whisper model...")
    t0 = time.time()
    model = whisperx.load_model(
        whisper_model,
        whisper_device,
        compute_type=compute_type,
        language=language,
    )
    t_load = time.time() - t0
    log(f"  Model loaded in {t_load:.0f}s")
    log()

    log("  Transcribing...")
    progress = _ProgressBar("Transcription", duration, transcribe_speed)
    progress.start()

    t0 = time.time()
    result = model.transcribe(audio, batch_size=batch_size, language=language)

    progress.stop()
    t_transcribe = time.time() - t0
    n_segments = len(result.get("segments", []))
    speed = duration / t_transcribe if t_transcribe > 0 else 0
    log(f"  ✓ Transcription: {t_transcribe:.0f}s ({speed:.1f}x realtime), {n_segments} segments")
    log()

    del model
    if has_cuda:
        torch.cuda.empty_cache()

    # === STEP 3: Align (word-level timestamps) ===
    log("  Loading alignment model (wav2vec2)...")
    t0 = time.time()
    model_a, metadata = whisperx.load_align_model(
        language_code=language, device=align_device,
    )
    t_load = time.time() - t0
    log(f"  Alignment model loaded in {t_load:.0f}s")

    log("  Aligning words...")
    progress = _ProgressBar("Word alignment", duration, duration / 30)
    progress.start()

    t0 = time.time()
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, align_device,
        return_char_alignments=False,
    )

    progress.stop()
    t_align = time.time() - t0
    log(f"  ✓ Alignment: {t_align:.0f}s")
    log()

    del model_a
    if has_cuda:
        torch.cuda.empty_cache()

    # === STEP 4: Diarize ===
    log("  Loading diarization model (pyannote)...")
    t0_load = time.time()
    from whisperx.diarize import DiarizationPipeline
    try:
        diarize_model = DiarizationPipeline(
            use_auth_token=hf_token, device=torch.device(diarize_device),
        )
    except TypeError:
        diarize_model = DiarizationPipeline(
            token=hf_token, device=torch.device(diarize_device),
        )
    t_load = time.time() - t0_load
    log(f"  Diarization model loaded in {t_load:.0f}s")

    diarize_kwargs = {}
    if num_speakers is not None:
        diarize_kwargs["num_speakers"] = num_speakers
    if min_speakers is not None:
        diarize_kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        diarize_kwargs["max_speakers"] = max_speakers

    log("  Running diarization...")
    progress = _ProgressBar("Speaker diarization", duration, _DIARIZE_SPEED)
    progress.start()

    t0 = time.time()
    diarize_segments = diarize_model(audio, **diarize_kwargs)

    progress.stop()
    t_diarize = time.time() - t0
    log(f"  ✓ Diarization: {t_diarize:.0f}s")
    log()

    # === STEP 5: Assign speakers to words ===
    result = whisperx.assign_word_speakers(diarize_segments, result)

    # === Format output ===
    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": round(seg.get("start", 0), 2),
            "end": round(seg.get("end", 0), 2),
            "speaker": seg.get("speaker", "UNKNOWN"),
            "text": seg.get("text", "").strip(),
        })

    segments = [s for s in segments if s["text"]]
    unique_speakers = sorted(set(s["speaker"] for s in segments))

    total_time = t_transcribe + t_align + t_diarize
    log(f"  Speakers found: {len(unique_speakers)}")
    log(f"  Total segments: {len(segments)}")
    log(f"  Total time: {total_time:.0f}s ({duration/total_time:.1f}x realtime)")

    return segments, unique_speakers
