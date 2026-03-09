# WhisperX Installation on Windows (with CUDA GPU)

You are an expert system administrator setting up WhisperX transcription + diarization pipeline on a Windows machine with NVIDIA GPU.

## CRITICAL: Follow phases IN ORDER. Do NOT skip ahead.

---

## PHASE 1: System Discovery (MANDATORY FIRST STEP)

Run ALL of these PowerShell commands to collect system information. Do NOT ask the user anything until you have this data:

```powershell
# 1. Windows version
(Get-WmiObject -Class Win32_OperatingSystem).Caption

# 2. CPU
(Get-WmiObject -Class Win32_Processor).Name

# 3. RAM (GB)
[math]::Round((Get-WmiObject -Class Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)

# 4. NVIDIA GPU
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output "NO NVIDIA GPU DETECTED" }

# 5. CUDA toolkit
nvcc --version 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output "CUDA TOOLKIT NOT INSTALLED" }

# 6. Python
python --version 2>$null
python3 --version 2>$null
py --version 2>$null

# 7. pip
pip --version 2>$null

# 8. ffmpeg
ffmpeg -version 2>$null | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { Write-Output "FFMPEG NOT INSTALLED" }

# 9. Git
git --version 2>$null

# 10. Free disk space on C:
[math]::Round((Get-PSDrive C).Free / 1GB, 1)

# 11. chocolatey / winget
choco --version 2>$null
winget --version 2>$null
```

After collecting this data, display a summary table to the user like:

```
=== SYSTEM INFO ===
OS:          Windows 11 Pro 24H2
CPU:         AMD Ryzen 7 5800X
RAM:         32 GB
GPU:         NVIDIA RTX 3080 (10 GB VRAM)
Driver:      560.94
CUDA:        12.6 (or NOT INSTALLED)
Python:      3.12.x (or NOT FOUND)
ffmpeg:      6.x (or NOT INSTALLED)
Git:         2.x (or NOT INSTALLED)
Disk free:   120 GB
Pkg manager: chocolatey / winget
```

---

## PHASE 2: Compatibility Check & Questions

### 2a. Blocker Check

Check for BLOCKERS before asking questions:

**HARD BLOCKERS (stop and explain):**
- No NVIDIA GPU detected → WhisperX needs CUDA. Suggest CPU-only alternative (will be 5-10x slower)
- Less than 4 GB VRAM → Cannot run large-v3 model. Suggest smaller models (small, medium)
- Less than 10 GB free disk space → Need ~8 GB for models + dependencies
- Less than 8 GB RAM → May run out of memory during diarization

**SOFT WARNINGS (inform user, continue):**
- CUDA toolkit not installed → Will install in Phase 3
- Python not found → Will install in Phase 3
- ffmpeg not found → Will install in Phase 3
- Python version < 3.10 or > 3.12 → WhisperX requires 3.10-3.12, will install correct version

### 2b. Ask User Questions

Ask ALL these questions at once using the question tool (do NOT ask one by one):

1. **Primary language** — What language will you primarily transcribe?
   - Options: Russian (ru), English (en), Other (specify ISO code)

2. **Diarization** — Do you need speaker separation (who said what)?
   - Yes (requires free HuggingFace account)
   - No (plain transcription only, faster setup)

3. **Whisper model** — Which model quality level?
   - `large-v3` (best quality, needs 4+ GB VRAM, ~3 GB download) — Recommended
   - `medium` (good quality, needs 2+ GB VRAM, ~1.5 GB download)
   - `small` (decent quality, needs 1+ GB VRAM, ~0.5 GB download)
   - Based on detected VRAM, recommend the best model that fits

4. **Installation directory** — Where to install?
   - Default: `C:\TranscribeAGENT`
   - Or user specifies custom path

5. **HuggingFace token** (only if diarization = Yes):
   - Do you already have a HuggingFace token?
   - If no: explain they need to:
     1. Create account at https://huggingface.co
     2. Go to https://huggingface.co/settings/tokens
     3. Create a token with "read" access
     4. Accept model licenses at:
        - https://huggingface.co/pyannote/speaker-diarization-3.1
        - https://huggingface.co/pyannote/segmentation-3.0
   - Ask them to provide the token (it starts with `hf_`)

---

## PHASE 3: Installation

### 3a. Install Prerequisites

**Python 3.12** (if not installed or wrong version):
```powershell
# Via winget (preferred)
winget install Python.Python.3.12

# OR via chocolatey
choco install python312 -y

# After install, verify:
py -3.12 --version
```

IMPORTANT: After Python install, close and reopen the terminal for PATH to update.

**ffmpeg** (if not installed):
```powershell
# Via winget
winget install Gyan.FFmpeg

# OR via chocolatey
choco install ffmpeg -y

# Verify
ffmpeg -version
```

**Git** (if not installed):
```powershell
winget install Git.Git
# OR
choco install git -y
```

### 3b. CUDA Toolkit (if not installed)

Check which CUDA version the NVIDIA driver supports:
```powershell
nvidia-smi
# Look for "CUDA Version: XX.X" in the top right
```

The driver's CUDA version is the MAXIMUM supported. Install matching or lower toolkit:

```powershell
# For CUDA 12.x (most modern GPUs):
winget install Nvidia.CUDA --version 12.4
# OR download from: https://developer.nvidia.com/cuda-12-4-0-download-archive

# Verify after install (may need terminal restart):
nvcc --version
```

IMPORTANT: PyTorch CUDA version must match the installed CUDA toolkit.

### 3c. Create Project

```powershell
# Create project directory (use the path from user's answer)
$PROJECT_DIR = "C:\TranscribeAGENT"  # or user-specified path
mkdir $PROJECT_DIR -Force
cd $PROJECT_DIR

# Create virtual environment with Python 3.12
py -3.12 -m venv .venv

# Activate
.venv\Scripts\Activate.ps1
```

### 3d. Install PyTorch with CUDA

CRITICAL: Match the CUDA version!

```powershell
# For CUDA 12.4 (check with nvcc --version):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# For CUDA 12.1:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# For CUDA 11.8:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

Verify CUDA is available:
```powershell
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

This MUST print `CUDA: True`. If False — stop and troubleshoot.

### 3e. Install WhisperX and Dependencies

```powershell
pip install whisperx
pip install pyannote.audio
pip install numpy
pip install soundfile
```

Verify:
```powershell
python -c "import whisperx; print('WhisperX OK')"
python -c "import pyannote.audio; print('Pyannote OK')"
```

---

## PHASE 4: Create Project Files

Create the following files in the project directory.

### 4a. config.yaml

```yaml
whisper:
  # Model will be auto-downloaded on first run
  model: "large-v3"  # or medium/small based on user choice
  language: "ru"      # from user's answer

audio:
  formats:
    - mp3
    - wav
    - m4a
    - ogg
    - flac
    - wma
    - aac
  sample_rate: 16000

diarization:
  # Set these if you know the number of speakers
  # num_speakers: 2
  # min_speakers: 1
  # max_speakers: 5
```

### 4b. transcribe_agent/__init__.py

Empty file, just create the package.

### 4c. transcribe_agent/config.py

```python
"""Configuration loader."""

import yaml
from pathlib import Path


def load_config(config_path: str = None) -> dict:
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)
```

### 4d. transcribe_agent/audio.py

```python
"""Audio utilities: probe, convert, cleanup."""

import json
import subprocess
import tempfile
from pathlib import Path


def probe(filepath: Path) -> dict:
    """Get audio file info using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {}
    )

    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "codec": audio_stream.get("codec_name", "unknown"),
        "sample_rate": audio_stream.get("sample_rate", "unknown"),
        "file_size": int(data.get("format", {}).get("size", 0)),
    }


def convert_to_wav(filepath: Path) -> Path:
    """Convert audio to WAV 16kHz mono for Whisper."""
    wav_path = filepath.with_suffix(".wav")
    if wav_path.exists() and wav_path.stat().st_size > 0:
        return wav_path

    cmd = [
        "ffmpeg", "-y", "-i", str(filepath),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav_path)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return wav_path


def cleanup(wav_path: Path):
    """Remove temporary WAV file."""
    try:
        wav_path.unlink(missing_ok=True)
    except Exception:
        pass


def format_duration(seconds: float) -> str:
    """Format seconds to human-readable duration."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
```

### 4e. transcribe_agent/whisperx_diarize.py

IMPORTANT: This is the WINDOWS/CUDA version. Key differences from Mac:
- Device is "cuda" (not "cpu" for whisper, not "mps" for diarize)
- compute_type is "float16" (GPU-optimized, not "int8")
- All three stages (transcribe, align, diarize) run on GPU
- No MPS fallback needed

```python
"""WhisperX-based transcription + diarization (Windows/CUDA version).

Uses faster-whisper for transcription, wav2vec2 for alignment,
and pyannote for speaker diarization. Each word gets a speaker label.

Optimized for NVIDIA GPUs with CUDA support.
"""

import os
import sys
import time
import threading
import warnings
import logging

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Suppress noisy warnings
warnings.filterwarnings("ignore", message=".*torchcodec.*")
warnings.filterwarnings("ignore", message=".*torchaudio.*")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("speechbrain").setLevel(logging.ERROR)

_SPINNER = ["\u28cb", "\u28d9", "\u28f9", "\u28f8", "\u28fc", "\u28f4", "\u28e6", "\u28e7", "\u28c7", "\u28cf"]

# Speed estimates for CUDA GPU (much faster than CPU!)
_TRANSCRIBE_SPEED = 8.0   # faster-whisper CUDA float16: ~8x realtime
_DIARIZE_SPEED = 4.0      # pyannote CUDA: ~4x realtime


def log(msg=""):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


class _ProgressBar:
    """Progress bar with time estimate."""

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

            if est_total > 0 and elapsed < est_total * 2:
                pct = min(int(elapsed / est_total * 100), 99)
                filled = int(bar_len * pct / 100)
                bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
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
    batch_size: int = 16,
) -> list:
    """Full WhisperX pipeline: transcribe + align + diarize.

    Returns:
        (segments, unique_speakers) tuple
    """
    import whisperx
    import torch

    # === DEVICE CONFIGURATION ===
    has_cuda = torch.cuda.is_available()

    if has_cuda:
        device = "cuda"
        compute_type = "float16"
        gpu_name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_mem / 1024**3
        log(f"  GPU: {gpu_name} ({vram:.1f} GB VRAM)")
        log(f"  Mode: CUDA ({compute_type})")
    else:
        device = "cpu"
        compute_type = "int8"
        log("  WARNING: No CUDA GPU found! Running on CPU (slow)")

    log()

    # All stages on same device (CUDA supports everything)
    whisper_device = device
    align_device = device
    diarize_device = device

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
    progress = _ProgressBar("Transcription", duration, _TRANSCRIBE_SPEED if has_cuda else 2.0)
    progress.start()

    t0 = time.time()
    result = model.transcribe(audio, batch_size=batch_size, language=language)

    progress.stop()
    t_transcribe = time.time() - t0
    n_segments = len(result.get("segments", []))
    speed = duration / t_transcribe if t_transcribe > 0 else 0
    log(f"  Transcription: {t_transcribe:.0f}s ({speed:.1f}x realtime), {n_segments} segments")
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
    progress = _ProgressBar("Word alignment", duration, duration / 15 if has_cuda else duration / 30)
    progress.start()

    t0 = time.time()
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, align_device,
        return_char_alignments=False,
    )

    progress.stop()
    t_align = time.time() - t0
    log(f"  Alignment: {t_align:.0f}s")
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
    progress = _ProgressBar("Speaker diarization", duration, _DIARIZE_SPEED if has_cuda else 1.5)
    progress.start()

    t0 = time.time()
    diarize_segments = diarize_model(audio, **diarize_kwargs)

    progress.stop()
    t_diarize = time.time() - t0
    log(f"  Diarization: {t_diarize:.0f}s")
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
```

### 4f. transcribe_agent/protocol.py

```python
"""Protocol formatting and speaker detection."""

from datetime import datetime


def consolidate_segments(segments: list) -> list:
    """Merge consecutive segments from same speaker."""
    if not segments:
        return []

    merged = [segments[0].copy()]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg["speaker"] == prev["speaker"]:
            prev["text"] += " " + seg["text"]
            prev["end"] = seg["end"]
        else:
            merged.append(seg.copy())
    return merged


def dedup_segments(segments: list) -> list:
    """Remove duplicate segments (WhisperX sometimes produces duplicates)."""
    seen = set()
    result = []
    for seg in segments:
        key = (seg["speaker"], seg["text"].strip()[:50])
        if key not in seen:
            seen.add(key)
            result.append(seg)
    return result


def format_timestamp(seconds: float) -> str:
    """Format seconds to [M:SS] or [H:MM:SS]."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_protocol(
    segments: list,
    meeting_type: str = "",
    participants: list = None,
    audio_filename: str = "",
    audio_duration: float = 0,
) -> str:
    """Format segments as a meeting protocol."""
    lines = []
    sep = "=" * 60
    lines.append(sep)
    lines.append("MEETING PROTOCOL")
    if meeting_type:
        lines.append(f"Type: {meeting_type}")
    lines.append(sep)
    lines.append("")
    lines.append(f"Date: {datetime.now().strftime('%d.%m.%Y')}")
    if audio_filename:
        lines.append(f"File: {audio_filename}")
    if audio_duration:
        m, s = int(audio_duration // 60), int(audio_duration % 60)
        lines.append(f"Duration: {m} min {s} sec")
    lines.append("")

    if participants:
        lines.append("Participants:")
        for p in participants:
            role = f" ({p['role']})" if p.get("role") else ""
            lines.append(f"  - {p['name']}{role}")
    else:
        speakers = sorted(set(s["speaker"] for s in segments))
        lines.append("Speakers:")
        for spk in speakers:
            lines.append(f"  - {spk}")
    lines.append(f"Total speakers: {len(set(s['speaker'] for s in segments))}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("")

    for seg in segments:
        ts_start = format_timestamp(seg["start"])
        ts_end = format_timestamp(seg["end"])
        lines.append(f"[{ts_start}-{ts_end}] {seg['speaker']}:")
        lines.append(seg["text"])
        lines.append("")

    lines.append("-" * 60)
    lines.append(f"End of protocol. Total blocks: {len(segments)}")

    return "\n".join(lines)


def format_plain_diarized(segments: list) -> str:
    """Format segments as plain diarized text."""
    lines = []
    for seg in segments:
        ts = format_timestamp(seg["start"])
        lines.append(f"[{ts}] {seg['speaker']}: {seg['text']}")
    return "\n".join(lines)
```

### 4g. transcribe.py (main entry point)

```python
#!/usr/bin/env python
"""TranscribeAGENT - audio transcription with optional speaker diarization.

Usage:
  python transcribe.py file.mp3                    - plain transcription
  python transcribe.py file.mp3 --diarize          - with speaker separation
  python transcribe.py file.mp3 --diarize -s 3     - specify number of speakers
  python transcribe.py *.mp3 --diarize             - batch mode
"""

import argparse
import json
import sys
import time
from pathlib import Path

from transcribe_agent.config import load_config
from transcribe_agent.audio import probe, convert_to_wav, cleanup, format_duration


def log(msg=""):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio files with optional speaker diarization"
    )
    parser.add_argument("files", nargs='+', help="Audio file(s)")
    parser.add_argument("--language", "-l", default=None, help="Language code")
    parser.add_argument("--config", "-c", default=None, help="Path to config.yaml")
    parser.add_argument("--diarize", "-d", action="store_true", help="Enable diarization")
    parser.add_argument("--speakers", "-s", type=int, default=None, help="Number of speakers")
    parser.add_argument("--min-speakers", type=int, default=None)
    parser.add_argument("--max-speakers", type=int, default=None)
    parser.add_argument("--meeting", "-m", default="", help="Meeting type")
    parser.add_argument("--names", "-n", default=None,
                        help='Speaker names: \'{"SPEAKER_00": "Name (role)"}\'')
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip interactive speaker naming")
    args = parser.parse_args()

    # Config
    if args.config:
        config_path = args.config
    else:
        config_path = str(Path(__file__).resolve().parent / "config.yaml")
    config = load_config(config_path)

    if args.language:
        config["whisper"]["language"] = args.language

    # Validate files
    allowed = config["audio"]["formats"]
    filepaths = []
    for f in args.files:
        fp = Path(f).resolve()
        if not fp.exists():
            log(f"Error: file not found: {fp}")
            sys.exit(1)
        ext = fp.suffix.lower().lstrip(".")
        if ext not in allowed:
            log(f"Error: unsupported format '.{ext}'. Supported: {', '.join(allowed)}")
            sys.exit(1)
        filepaths.append(fp)

    total = len(filepaths)
    succeeded = 0
    failed = 0

    for idx, filepath in enumerate(filepaths, 1):
        if total > 1:
            log(f"\n--- [{idx}/{total}] {filepath.name} ---\n")

        try:
            if args.diarize:
                _run_diarized(filepath, config, args)
            else:
                _run_plain(filepath, config)
            succeeded += 1
        except Exception as e:
            failed += 1
            log(f"  ERROR: {filepath.name}: {e}")

    if total > 1:
        log(f"\nBatch complete: {succeeded}/{total} succeeded, {failed} failed")


def _run_plain(filepath: Path, config: dict):
    """Plain transcription without diarization."""
    import whisperx
    import torch

    sep = "=" * 50
    log(f"{sep}")
    log(f"  TRANSCRIBE AGENT")
    log(f"{sep}\n")

    info = probe(filepath)
    log(f"  File:     {filepath.name}")
    log(f"  Duration: {format_duration(info['duration'])}")
    log(f"  Size:     {info['file_size'] / 1024 / 1024:.1f} MB\n")

    has_cuda = torch.cuda.is_available()
    device = "cuda" if has_cuda else "cpu"
    compute_type = "float16" if has_cuda else "int8"

    log(f"  Device: {device.upper()}\n")
    log(f"  Loading model...")

    model = whisperx.load_model(
        config["whisper"].get("model", "large-v3"),
        device,
        compute_type=compute_type,
        language=config["whisper"].get("language", "ru"),
    )

    audio = whisperx.load_audio(str(filepath))

    log(f"  Transcribing...")
    t0 = time.time()
    result = model.transcribe(
        audio, batch_size=16 if has_cuda else 8,
        language=config["whisper"].get("language", "ru"),
    )
    elapsed = time.time() - t0

    text = "\n".join(seg["text"].strip() for seg in result.get("segments", []) if seg.get("text", "").strip())

    txt_path = filepath.with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")

    word_count = len(text.split())
    speed = info['duration'] / elapsed if elapsed > 0 else 0

    log(f"\n{sep}")
    log(f"  DONE!")
    log(f"  Words:  {word_count}")
    log(f"  Time:   {format_duration(elapsed)}")
    log(f"  Speed:  {speed:.1f}x realtime")
    log(f"  Output: {txt_path}")
    log(f"{sep}")


def _run_diarized(filepath: Path, config: dict, args):
    """Diarization mode using WhisperX."""
    from transcribe_agent.whisperx_diarize import transcribe_and_diarize
    from transcribe_agent.protocol import (
        consolidate_segments, dedup_segments,
        format_protocol, format_plain_diarized,
    )

    sep = "=" * 50
    log(f"{sep}")
    log(f"  TRANSCRIBE AGENT + DIARIZATION")
    log(f"{sep}\n")

    info = probe(filepath)
    log(f"  File:     {filepath.name}")
    log(f"  Duration: {format_duration(info['duration'])}")
    log(f"  Size:     {info['file_size'] / 1024 / 1024:.1f} MB\n")

    # HuggingFace token
    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        token_file = Path(__file__).resolve().parent / ".hf_token"
        if token_file.exists():
            hf_token = token_file.read_text().strip()
    if not hf_token:
        log("ERROR: HuggingFace token required for diarization.")
        log("Set HF_TOKEN environment variable or create .hf_token file.")
        sys.exit(1)

    language = config["whisper"].get("language", "ru")
    whisper_model = config["whisper"].get("model", "large-v3")

    num_speakers = args.speakers
    min_speakers = args.min_speakers
    max_speakers = args.max_speakers

    t0 = time.time()
    segments, unique_speakers = transcribe_and_diarize(
        audio_path=str(filepath),
        hf_token=hf_token,
        language=language,
        whisper_model=whisper_model,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )
    pipeline_time = time.time() - t0

    # Speaker names
    speaker_map = {}
    if args.names:
        try:
            if args.names.endswith(".json") and Path(args.names).exists():
                with open(args.names, encoding="utf-8") as f:
                    speaker_map = json.load(f)
            else:
                speaker_map = json.loads(args.names)
        except json.JSONDecodeError:
            log("Warning: could not parse --names, using defaults")

    if not speaker_map:
        for i, spk in enumerate(sorted(unique_speakers), 1):
            speaker_map[spk] = f"Speaker {i}"

    for seg in segments:
        spk = seg.get("speaker", "UNKNOWN")
        seg["speaker"] = speaker_map.get(spk, spk)

    consolidated = consolidate_segments(segments)
    consolidated = dedup_segments(consolidated)

    # Format and save
    if args.meeting:
        output_text = format_protocol(
            consolidated,
            meeting_type=args.meeting,
            audio_filename=filepath.name,
            audio_duration=info['duration'],
        )
    else:
        output_text = format_plain_diarized(consolidated)

    out_path = filepath.with_suffix(".protocol.txt")
    out_path.write_text(output_text, encoding="utf-8")

    word_count = sum(len(seg["text"].split()) for seg in consolidated)

    log(f"\n{sep}")
    log(f"  DONE!")
    log(f"  Speakers: {len(unique_speakers)}")
    log(f"  Words:    {word_count}")
    log(f"  Time:     {format_duration(pipeline_time)}")
    log(f"  Output:   {out_path}")
    log(f"{sep}")


import os

if __name__ == "__main__":
    main()
```

### 4h. .hf_token

Save the user's HuggingFace token to this file:
```
hf_xxxxxxxxxxxxxxxxxxxxx
```

### 4i. requirements.txt

```
torch
torchaudio
whisperx
pyannote.audio
numpy
soundfile
pyyaml
```

---

## PHASE 5: Test Installation

### 5a. Quick Smoke Test

```powershell
cd C:\TranscribeAGENT   # or user's path
.venv\Scripts\Activate.ps1

# Test CUDA
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0))"

# Test WhisperX import
python -c "import whisperx; print('WhisperX OK')"

# Test pyannote import
python -c "from whisperx.diarize import DiarizationPipeline; print('Diarize OK')"
```

### 5b. Test with Real Audio

Ask the user to provide a short audio file (1-5 minutes) for testing. Then run:

```powershell
# Plain transcription test
python transcribe.py "path\to\test.mp3"

# Diarization test (if enabled)
python transcribe.py "path\to\test.mp3" --diarize
```

### 5c. Expected Performance (NVIDIA GPU)

| Audio | GPU (CUDA) | CPU (fallback) |
|-------|-----------|----------------|
| 5 min | ~30-40s   | ~2-3 min       |
| 30 min| ~3-4 min  | ~15-20 min     |
| 1 hour| ~6-8 min  | ~30-40 min     |

If performance is significantly worse, check:
1. `torch.cuda.is_available()` returns True
2. GPU is not throttling (check `nvidia-smi` during transcription)
3. batch_size is appropriate (16 for 8GB+ VRAM, 8 for 4-6GB VRAM)

---

## PHASE 6: Create Launch Script (Optional)

Create a `transcribe.bat` for easy double-click launch:

```batch
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python transcribe.py %*
```

And a `transcribe-diarize.bat`:

```batch
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python transcribe.py %* --diarize
pause
```

---

## TROUBLESHOOTING

### CUDA Not Available
```powershell
python -c "import torch; print(torch.version.cuda); print(torch.__version__)"
```
- If `torch.version.cuda` is None → PyTorch installed without CUDA. Reinstall with correct CUDA index URL.
- If version mismatch → Uninstall torch, reinstall with matching CUDA version.

### Out of Memory (OOM)
- Reduce batch_size in whisperx_diarize.py (try 8, then 4)
- Use smaller model (medium instead of large-v3)
- Close other GPU-using applications

### Model Download Fails
WhisperX downloads models automatically on first run. If it fails:
- Check internet connection
- Check disk space
- Try manual download: `python -c "import whisperx; whisperx.load_model('large-v3', 'cuda')"`

### pyannote License Error
- Go to https://huggingface.co/pyannote/speaker-diarization-3.1
- Click "Agree and access repository"
- Same for https://huggingface.co/pyannote/segmentation-3.0

### ffmpeg Not Found
- Ensure ffmpeg is in PATH: `$env:PATH` should contain ffmpeg directory
- Restart terminal after installation

---

## KEY DIFFERENCES: Windows (CUDA) vs Mac (MPS/CPU)

| Feature | Windows + CUDA | Mac (Apple Silicon) |
|---------|---------------|---------------------|
| Whisper transcription | GPU (CUDA, float16) | CPU only (int8) |
| Word alignment | GPU (CUDA) | CPU only (MPS crashes) |
| Diarization | GPU (CUDA) | MPS (Metal GPU) |
| Expected speed | ~8-10x realtime | ~2-3x realtime |
| compute_type | float16 | int8 |
| batch_size | 16 (8GB VRAM) | 8 |

Windows with a good NVIDIA GPU will be **3-4x faster** than Mac because ALL stages run on GPU.
