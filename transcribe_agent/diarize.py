"""Speaker diarization using pyannote-audio.

Requires Python 3.10+ in a virtual environment (not system Python 3.9).
Uses pyannote/speaker-diarization-3.1 model.
Runs on MPS (Metal GPU) with CPU fallback.
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

# Spinner characters for progress animation
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def log(msg=""):
    """Print to stderr (consistent with transcribe.py)."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


class _DiarizeSpinner:
    """Animated spinner with elapsed time for long-running diarization."""

    def __init__(self, audio_duration: float = 0):
        self._stop = threading.Event()
        self._thread = None
        self._audio_duration = audio_duration
        self._phase = "loading"  # loading → diarizing → done

    def start(self):
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_phase(self, phase: str):
        """Switch phase: 'loading', 'diarizing', 'done'."""
        self._phase = phase

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        # Clear the spinner line
        sys.stderr.write("\r" + " " * 60 + "\r")
        sys.stderr.flush()

    def _run(self):
        idx = 0
        while not self._stop.is_set():
            elapsed = time.time() - self._start_time
            m = int(elapsed // 60)
            s = int(elapsed % 60)
            time_str = f"{m}:{s:02d}"

            spinner_char = _SPINNER[idx % len(_SPINNER)]
            idx += 1

            if self._phase == "loading":
                msg = f"  {spinner_char} Загрузка модели... [{time_str}]"
            elif self._phase == "diarizing":
                # Rough estimate: ~0.15x realtime on M-series MPS GPU
                estimate = ""
                if self._audio_duration > 0:
                    est_total = self._audio_duration * 0.15
                    remaining = max(0, est_total - elapsed)
                    rm = int(remaining // 60)
                    rs = int(remaining % 60)
                    estimate = f"  ~{rm}:{rs:02d} осталось"
                msg = f"  {spinner_char} Диаризация... [{time_str}]{estimate}"
            else:
                msg = f"  ✓ Готово [{time_str}]"

            sys.stderr.write(f"\r{msg}" + " " * 10)
            sys.stderr.flush()

            self._stop.wait(0.15)


def get_venv_python(project_dir: Path) -> str:
    """Get path to Python in the diarize venv (Windows-compatible)."""
    import sys as _sys
    if _sys.platform == "win32":
        venv_python = project_dir / ".venv-diarize" / "Scripts" / "python.exe"
    else:
        venv_python = project_dir / ".venv-diarize" / "bin" / "python3"
    if not venv_python.exists():
        raise RuntimeError(
            "Diarization venv not found. Run: setup.ps1 (Windows) or install-diarize.sh (macOS)\n"
            f"Expected: {venv_python}"
        )
    return str(venv_python)


def check_hf_token(project_dir: Path) -> str:
    """Read HuggingFace token from config or environment."""
    import os
    token = os.environ.get("HF_TOKEN", "")
    if token:
        return token

    # Try reading from .hf_token file
    token_file = project_dir / ".hf_token"
    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            return token

    raise RuntimeError(
        "HuggingFace token not found.\n"
        "pyannote requires a free HuggingFace account.\n\n"
        "1. Create account at https://huggingface.co\n"
        "2. Accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1\n"
        "3. Get token at https://huggingface.co/settings/tokens\n"
        "4. Save token:\n"
        f"   echo 'hf_YOUR_TOKEN' > {project_dir}/.hf_token\n"
        "   OR set HF_TOKEN environment variable"
    )


# Max chunk duration in seconds for diarization.
# MPS GPU can deadlock on very long files (>70 min) due to memory pressure.
# Splitting into chunks avoids this while keeping GPU acceleration.
_MAX_CHUNK_SECS = 1200  # 20 minutes


def diarize(wav_path: Path, config: dict, project_dir: Path,
            audio_duration: float = 0) -> list:
    """Run speaker diarization on a WAV file.

    Launches pyannote in the dedicated venv via subprocess
    (because pyannote needs Python 3.10+ while system is 3.9).
    For files longer than 70 min, automatically splits into chunks
    to avoid MPS GPU deadlocks on long audio.

    Args:
        wav_path: Path to 16kHz mono WAV file
        config: Full config dict (uses config['diarization'] section)
        project_dir: Path to TranscribeAGENT directory
        audio_duration: Duration in seconds (for time estimate)

    Returns:
        List of segments: [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
    """
    if audio_duration > _MAX_CHUNK_SECS:
        return _diarize_chunked(wav_path, config, project_dir, audio_duration)
    return _diarize_single(wav_path, config, project_dir, audio_duration)


def _diarize_chunked(wav_path: Path, config: dict, project_dir: Path,
                     audio_duration: float) -> list:
    """Split long audio into chunks, diarize each, merge results."""
    import math
    import tempfile

    num_chunks = math.ceil(audio_duration / _MAX_CHUNK_SECS)
    chunk_duration = audio_duration / num_chunks

    log(f"  Файл {audio_duration/60:.0f} мин > порога {_MAX_CHUNK_SECS//60} мин")
    log(f"  Разбиваю на {num_chunks} частей по ~{chunk_duration/60:.0f} мин")
    log()

    all_segments = []
    chunk_paths = []

    try:
        for i in range(num_chunks):
            start_sec = i * chunk_duration
            # Create chunk WAV via ffmpeg
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

            log(f"  [{i+1}/{num_chunks}] Диаризация части ({start_sec/60:.0f}-{(start_sec+chunk_duration)/60:.0f} мин)...")

            # Diarize this chunk
            chunk_segments = _diarize_single(
                chunk_path, config, project_dir,
                audio_duration=chunk_duration,
            )

            # Offset timestamps to original timeline
            for seg in chunk_segments:
                seg["start"] = round(seg["start"] + start_sec, 2)
                seg["end"] = round(seg["end"] + start_sec, 2)

            all_segments.extend(chunk_segments)
            log(f"    Сегментов: {len(chunk_segments)}")
            log()

    finally:
        # Clean up chunk files
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    # Sort by start time (chunks are sequential but just in case)
    all_segments.sort(key=lambda s: s["start"])
    return all_segments


def _diarize_single(wav_path: Path, config: dict, project_dir: Path,
                    audio_duration: float = 0) -> list:
    """Run diarization on a single WAV file (no splitting)."""
    venv_python = get_venv_python(project_dir)
    hf_token = check_hf_token(project_dir)

    diarize_cfg = config.get("diarization", {})
    num_speakers = diarize_cfg.get("num_speakers")
    min_speakers = diarize_cfg.get("min_speakers")
    max_speakers = diarize_cfg.get("max_speakers")

    script = _build_diarize_script(
        wav_path=str(wav_path),
        hf_token=hf_token,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )

    # Start spinner with elapsed time
    spinner = _DiarizeSpinner(audio_duration=audio_duration)
    spinner.start()

    process = subprocess.Popen(
        [venv_python, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # CRITICAL: Drain stdout in background thread to prevent pipe deadlock.
    # pyannote outputs large JSON (thousands of segments) to stdout.
    # Without draining, stdout buffer (64KB) fills up while parent blocks
    # on stderr readline, causing both processes to deadlock.
    stdout_chunks = []
    def _drain(pipe, result_list):
        try:
            data = pipe.read()
            result_list.append(data)
        except Exception:
            pass

    stdout_thread = threading.Thread(
        target=_drain, args=(process.stdout, stdout_chunks), daemon=True
    )
    stdout_thread.start()

    # Stream stderr for progress AND collect it for error reporting
    stderr_lines = []
    try:
        for line in process.stderr:
            line = line.rstrip()
            if not line:
                continue
            stderr_lines.append(line)
            if "diarization started" in line.lower():
                spinner.set_phase("diarizing")
            elif "diarization complete" in line.lower():
                spinner.set_phase("done")
    except Exception:
        pass

    # Wait for stdout drain and process to finish
    stdout_thread.join(timeout=3600)
    process.wait(timeout=3600)

    # Stop spinner
    spinner.stop()

    full_stderr = "\n".join(stderr_lines)

    if process.returncode != 0:
        raise RuntimeError(
            f"Diarization failed (exit {process.returncode}):\n{full_stderr}"
        )

    stdout_text = (stdout_chunks[0] if stdout_chunks else "").strip()
    try:
        segments = json.loads(stdout_text)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Diarization returned invalid JSON:\n{stdout_text[:500]}"
        )

    return segments


def _build_diarize_script(
    wav_path: str,
    hf_token: str,
    num_speakers=None,
    min_speakers=None,
    max_speakers=None,
) -> str:
    """Build Python script that runs pyannote in the venv.

    The script prints JSON to stdout — a list of segments.
    Python 3.9 compatible string formatting (no quotes in f-string {}).
    """
    # Build speaker params
    params = []
    if num_speakers is not None:
        params.append(f"num_speakers={num_speakers}")
    else:
        if min_speakers is not None:
            params.append(f"min_speakers={min_speakers}")
        if max_speakers is not None:
            params.append(f"max_speakers={max_speakers}")
    params_str = ", ".join(params)

    script = f'''
import json
import sys
import os

# Suppress warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import warnings
warnings.filterwarnings("ignore")

from pyannote.audio import Pipeline
import torch

# Use CUDA if available, otherwise CPU
if torch.cuda.is_available():
    device = torch.device("cuda")
    print("Using CUDA (GPU)", file=sys.stderr, flush=True)
else:
    device = torch.device("cpu")
    print("Using CPU", file=sys.stderr, flush=True)

# Load pipeline
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token="{hf_token}",
)
pipeline.to(device)

print("Diarization started...", file=sys.stderr, flush=True)

# Run diarization (no ProgressHook - rich bars write CR not LF, blocking readline)
diarization = pipeline("{wav_path}"{", " + params_str if params_str else ""})

# Convert to list of segments
# pyannote v4 returns DiarizeOutput — use .speaker_diarization for Annotation
segments = []
annotation = diarization
if hasattr(diarization, "speaker_diarization"):
    annotation = diarization.speaker_diarization
for turn, _, speaker in annotation.itertracks(yield_label=True):
    segments.append({{
        "start": round(turn.start, 2),
        "end": round(turn.end, 2),
        "speaker": speaker,
    }})

print("Diarization complete. Segments:", len(segments), file=sys.stderr, flush=True)

# Output JSON to stdout
print(json.dumps(segments, ensure_ascii=False))
'''
    return script


def _find_nearest_speaker(t_start: float, t_end: float,
                          diarization_segments: list) -> str:
    """Find the nearest diarization segment by time distance.

    Used when a whisper segment falls in a gap between diarization segments.
    Returns the speaker of the closest segment, or "UNKNOWN" if empty.
    """
    if not diarization_segments:
        return "UNKNOWN"

    t_mid = (t_start + t_end) / 2
    best_speaker = diarization_segments[0]["speaker"]
    best_distance = float("inf")

    for dseg in diarization_segments:
        if dseg["start"] <= t_mid <= dseg["end"]:
            return dseg["speaker"]
        dist = min(abs(t_mid - dseg["end"]), abs(t_mid - dseg["start"]))
        if dist < best_distance:
            best_distance = dist
            best_speaker = dseg["speaker"]

    return best_speaker


def _split_text_by_speakers(t_start: float, t_end: float, text: str,
                            overlapping: list, speaker_map: dict) -> list:
    """Split a whisper segment's text across multiple speakers proportionally.

    Words are distributed based on each speaker's temporal overlap duration.
    Returns list of merged segment dicts, one per speaker portion.
    """
    words = text.split()

    # No meaningful split possible
    if len(words) <= 1 or len(overlapping) <= 1:
        best = max(overlapping, key=lambda d: d["overlap"])
        speaker = speaker_map.get(best["speaker"], best["speaker"])
        return [{"start": t_start, "end": t_end, "speaker": speaker,
                 "text": text.strip()}]

    total_overlap = sum(d["overlap"] for d in overlapping)
    if total_overlap <= 0:
        best = max(overlapping, key=lambda d: d["overlap"])
        speaker = speaker_map.get(best["speaker"], best["speaker"])
        return [{"start": t_start, "end": t_end, "speaker": speaker,
                 "text": text.strip()}]

    # Sort by diarization start time to maintain temporal order
    sorted_diar = sorted(overlapping, key=lambda d: d["start"])
    seg_duration = t_end - t_start

    result = []
    word_idx = 0
    for i, dseg in enumerate(sorted_diar):
        fraction = dseg["overlap"] / total_overlap
        if i == len(sorted_diar) - 1:
            n_words = len(words) - word_idx
        else:
            n_words = max(1, round(fraction * len(words)))

        chunk_words = words[word_idx:word_idx + n_words]
        if not chunk_words:
            word_idx += n_words
            continue

        time_frac_start = word_idx / len(words)
        word_idx += n_words
        time_frac_end = word_idx / len(words)

        sub_start = round(t_start + time_frac_start * seg_duration, 2)
        sub_end = round(t_start + time_frac_end * seg_duration, 2)

        speaker = speaker_map.get(dseg["speaker"], dseg["speaker"])
        result.append({
            "start": sub_start,
            "end": sub_end,
            "speaker": speaker,
            "text": " ".join(chunk_words),
        })

    return result


def merge_transcript_with_diarization(
    transcript_segments: list,
    diarization_segments: list,
    speaker_map: dict = None,
) -> list:
    """Merge whisper transcript segments with diarization results.

    For each transcript segment, finds overlapping diarization segments.
    If a whisper segment spans multiple speakers, splits the text
    proportionally by overlap duration.

    Args:
        transcript_segments: [{"start": 0.0, "end": 5.2, "text": "..."}, ...]
        diarization_segments: [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
        speaker_map: Optional {"SPEAKER_00": "Name (role)"} mapping

    Returns:
        [{"start": 0.0, "end": 5.2, "speaker": "Виталий (консультант)", "text": "..."}, ...]
    """
    if speaker_map is None:
        speaker_map = {}

    merged = []
    for tseg in transcript_segments:
        t_start = tseg["start"]
        t_end = tseg["end"]
        text = tseg["text"].strip()

        if not text:
            continue

        # Find all overlapping diarization segments
        overlapping = []
        for dseg in diarization_segments:
            overlap_start = max(t_start, dseg["start"])
            overlap_end = min(t_end, dseg["end"])
            overlap = max(0, overlap_end - overlap_start)
            if overlap > 0:
                overlapping.append({
                    "start": dseg["start"],
                    "end": dseg["end"],
                    "speaker": dseg["speaker"],
                    "overlap": overlap,
                })

        if not overlapping:
            # No overlap — find nearest speaker instead of UNKNOWN
            speaker_id = _find_nearest_speaker(t_start, t_end,
                                               diarization_segments)
            display_name = speaker_map.get(speaker_id, speaker_id)
            merged.append({
                "start": t_start,
                "end": t_end,
                "speaker": display_name,
                "text": text,
            })
        elif len(overlapping) == 1:
            # Single speaker — assign full text
            speaker = speaker_map.get(overlapping[0]["speaker"],
                                      overlapping[0]["speaker"])
            merged.append({
                "start": t_start,
                "end": t_end,
                "speaker": speaker,
                "text": text,
            })
        else:
            # Multiple speakers — split text proportionally
            sub_segments = _split_text_by_speakers(
                t_start, t_end, text, overlapping, speaker_map,
            )
            merged.extend(sub_segments)

    return merged
