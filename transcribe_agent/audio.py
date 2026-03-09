import json
import subprocess
import tempfile
from pathlib import Path


def probe(filepath: Path) -> dict:
    """Get audio metadata via ffprobe.

    Returns dict with: duration (float, seconds), codec, sample_rate, file_size (bytes).
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(filepath),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)

    duration = float(data.get("format", {}).get("duration", 0))
    file_size = int(data.get("format", {}).get("size", 0))

    codec = "unknown"
    sample_rate = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio":
            codec = stream.get("codec_name", "unknown")
            sample_rate = int(stream.get("sample_rate", 0))
            break

    return {
        "duration": duration,
        "codec": codec,
        "sample_rate": sample_rate,
        "file_size": file_size,
    }


def convert_to_wav(filepath: Path) -> Path:
    """Convert audio to 16kHz mono 16-bit WAV for whisper.cpp.

    Creates a temp file that must be cleaned up after use.
    Returns path to the temporary WAV file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_path = Path(tmp.name)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(filepath),
        "-ar", "16000",
        "-ac", "1",
        "-sample_fmt", "s16",
        "-f", "wav",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")

    return wav_path


def cleanup(wav_path: Path) -> None:
    """Remove temporary WAV file."""
    wav_path.unlink(missing_ok=True)


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable string: 1h 23m 45s."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)
