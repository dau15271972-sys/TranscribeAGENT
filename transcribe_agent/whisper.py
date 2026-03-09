import math
import sys
import time
import threading
from pathlib import Path


_MAX_CHUNK_SECS = 1200  # 20 minutes


def log(msg=""):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _get_device_and_compute(config: dict):
    """Determine device and compute_type from config or auto-detect."""
    whisper_cfg = config["whisper"]
    device = whisper_cfg.get("device", "auto")
    compute_type = whisper_cfg.get("compute_type", "auto")

    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                if compute_type == "auto":
                    compute_type = "float16"
            else:
                device = "cpu"
                if compute_type == "auto":
                    compute_type = "int8"
        except ImportError:
            device = "cpu"
            if compute_type == "auto":
                compute_type = "int8"
    elif compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    return device, compute_type


def _load_model(config: dict, device: str, compute_type: str):
    """Load faster-whisper model. Returns a CTranslate2-backed model."""
    from faster_whisper import WhisperModel

    model_size = config["whisper"].get("model_size", "large-v3")
    log(f"  Загрузка модели {model_size} ({device}/{compute_type})...")
    t0 = time.time()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    log(f"  Модель загружена за {time.time() - t0:.0f}с")
    return model


class _ProgressSpinner:
    """Animated spinner with elapsed time for transcription."""

    def __init__(self, audio_duration: float = 0, speed_factor: float = 10.0):
        self._stop = threading.Event()
        self._thread = None
        self._audio_duration = audio_duration
        self._speed_factor = speed_factor  # expected realtime multiplier

    def start(self):
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        sys.stderr.write("\r" + " " * 70 + "\r")
        sys.stderr.flush()

    def _run(self):
        chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        est_total = self._audio_duration / self._speed_factor if self._speed_factor > 0 else 0
        bar_len = 20
        while not self._stop.is_set():
            elapsed = time.time() - self._start_time
            m, s = int(elapsed // 60), int(elapsed % 60)
            char = chars[idx % len(chars)]
            idx += 1
            if est_total > 0 and elapsed < est_total * 2:
                pct = min(int(elapsed / est_total * 100), 99)
                filled = int(bar_len * pct / 100)
                bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
                remaining = max(0, est_total - elapsed)
                rm, rs = int(remaining // 60), int(remaining % 60)
                line = f"\r  {char} Транскрибация [{bar}] {pct}% {m}:{s:02d} ~{rm}:{rs:02d}"
            else:
                line = f"\r  {char} Транскрибация... {m}:{s:02d}"
            sys.stderr.write(line + " " * 10)
            sys.stderr.flush()
            self._stop.wait(0.15)


def transcribe(wav_path: Path, config: dict, audio_duration: float = 0) -> str:
    """Transcribe a WAV file using faster-whisper.

    For files longer than 20 min, automatically splits into chunks
    to reduce hallucinations. Returns the transcribed text.
    """
    if audio_duration > _MAX_CHUNK_SECS:
        return _transcribe_chunked(wav_path, config, audio_duration)
    return _transcribe_single(wav_path, config, audio_duration)


def _transcribe_chunked(wav_path: Path, config: dict, audio_duration: float) -> str:
    """Split long audio into chunks, transcribe each, concatenate text."""
    import subprocess
    import tempfile

    num_chunks = math.ceil(audio_duration / _MAX_CHUNK_SECS)
    chunk_duration = audio_duration / num_chunks

    log(f"  Файл {audio_duration/60:.0f} мин > порога {_MAX_CHUNK_SECS//60} мин")
    log(f"  Разбиваю на {num_chunks} частей по ~{chunk_duration/60:.0f} мин")
    log()

    device, compute_type = _get_device_and_compute(config)
    model = _load_model(config, device, compute_type)
    language = config["whisper"].get("language", "ru")

    all_texts = []
    chunk_paths = []

    try:
        for i in range(num_chunks):
            start_sec = i * chunk_duration
            chunk_path = Path(tempfile.mktemp(suffix=f"_chunk{i}.wav"))
            chunk_paths.append(chunk_path)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(wav_path),
                "-ss", str(start_sec),
                "-t", str(chunk_duration),
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                "-f", "wav", str(chunk_path),
            ]
            subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)

            log(f"  [{i+1}/{num_chunks}] Транскрибация ({start_sec/60:.0f}–{(start_sec+chunk_duration)/60:.0f} мин)...")

            chunk_text = _transcribe_single_with_model(model, chunk_path, language, chunk_duration)
            all_texts.append(chunk_text)
            log()
    finally:
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    return "\n".join(all_texts)


def _transcribe_single(wav_path: Path, config: dict, audio_duration: float = 0) -> str:
    """Transcribe a single WAV file via faster-whisper."""
    device, compute_type = _get_device_and_compute(config)
    model = _load_model(config, device, compute_type)
    log()
    language = config["whisper"].get("language", "ru")
    return _transcribe_single_with_model(model, wav_path, language, audio_duration)


def _transcribe_single_with_model(model, wav_path: Path, language: str, audio_duration: float = 0) -> str:
    """Run faster-whisper on a single WAV file, stream progress."""
    # Estimate speed: faster-whisper is typically 4–8x realtime on CPU int8,
    # 20–40x on CUDA float16. Use 6x as conservative CPU default.
    speed_factor = 6.0
    spinner = _ProgressSpinner(audio_duration=audio_duration, speed_factor=speed_factor)
    spinner.start()

    try:
        segments_gen, info = model.transcribe(
            str(wav_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        # Consume the generator (triggers actual transcription)
        texts = [seg.text.strip() for seg in segments_gen]
    finally:
        spinner.stop()

    text = " ".join(t for t in texts if t)
    if not text:
        raise RuntimeError("faster-whisper вернул пустой результат")
    return text


def transcribe_with_timestamps(wav_path: Path, config: dict, audio_duration: float = 0) -> list:
    """Transcribe with segment-level timestamps for diarization merge.

    Returns list of segments: [{"start": 0.0, "end": 5.2, "text": "..."}, ...]
    """
    if audio_duration > _MAX_CHUNK_SECS:
        return _transcribe_chunked_with_timestamps(wav_path, config, audio_duration)
    return _transcribe_single_with_timestamps(wav_path, config, audio_duration)


def _transcribe_chunked_with_timestamps(wav_path: Path, config: dict, audio_duration: float) -> list:
    """Split long audio into chunks, transcribe each with timestamps, merge."""
    import subprocess
    import tempfile

    num_chunks = math.ceil(audio_duration / _MAX_CHUNK_SECS)
    chunk_duration = audio_duration / num_chunks

    log(f"  Файл {audio_duration/60:.0f} мин > порога {_MAX_CHUNK_SECS//60} мин")
    log(f"  Разбиваю на {num_chunks} частей по ~{chunk_duration/60:.0f} мин")
    log()

    device, compute_type = _get_device_and_compute(config)
    model = _load_model(config, device, compute_type)
    language = config["whisper"].get("language", "ru")

    all_segments = []
    chunk_paths = []

    try:
        for i in range(num_chunks):
            start_sec = i * chunk_duration
            chunk_path = Path(tempfile.mktemp(suffix=f"_tschunk{i}.wav"))
            chunk_paths.append(chunk_path)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(wav_path),
                "-ss", str(start_sec),
                "-t", str(chunk_duration),
                "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                "-f", "wav", str(chunk_path),
            ]
            subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)

            log(f"  [{i+1}/{num_chunks}] Транскрибация ({start_sec/60:.0f}–{(start_sec+chunk_duration)/60:.0f} мин)...")

            chunk_segs = _transcribe_single_with_timestamps_model(model, chunk_path, language, chunk_duration)
            for seg in chunk_segs:
                seg["start"] = round(seg["start"] + start_sec, 2)
                seg["end"] = round(seg["end"] + start_sec, 2)
            all_segments.extend(chunk_segs)
            log(f"    Сегментов: {len(chunk_segs)}")
            log()
    finally:
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    all_segments.sort(key=lambda s: s["start"])
    return all_segments


def _transcribe_single_with_timestamps(wav_path: Path, config: dict, audio_duration: float = 0) -> list:
    """Transcribe a single WAV file with segment-level timestamps."""
    device, compute_type = _get_device_and_compute(config)
    model = _load_model(config, device, compute_type)
    log()
    language = config["whisper"].get("language", "ru")
    return _transcribe_single_with_timestamps_model(model, wav_path, language, audio_duration)


def _transcribe_single_with_timestamps_model(model, wav_path: Path, language: str, audio_duration: float = 0) -> list:
    """Run faster-whisper with timestamps on a single WAV file."""
    spinner = _ProgressSpinner(audio_duration=audio_duration, speed_factor=6.0)
    spinner.start()

    try:
        segments_gen, info = model.transcribe(
            str(wav_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        segments = []
        for seg in segments_gen:
            text = seg.text.strip()
            if text:
                segments.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                })
    finally:
        spinner.stop()

    if not segments:
        raise RuntimeError("faster-whisper вернул пустой результат")

    return segments
