#!/usr/bin/env python3
"""TranscribeAgent - local audio transcription using faster-whisper (Windows/CUDA).

Modes:
    transcribe.py file.mp3    – plain transcription (fast)
    transcribe.py file.mp3 --diarize   – with speaker separation (slower, needs pyannote)
    transcribe.py file.mp3 --diarize --speakers 3 --meeting "custdev"  – full meeting protocol
    transcribe.py *.m4a --diarize    – batch: process multiple files sequentially
"""

import argparse
import os
import sys
import time
from pathlib import Path

# FIX: Force ffprobe to use local copy
import subprocess

# Add current directory to PATH so ffprobe.exe is found
current_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] = current_dir + os.pathsep + os.environ["PATH"]

# Check if ffprobe works
try:
    result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True)
    print(f"✅ ffprobe found: {result.stdout.splitlines()[0]}")
except Exception as e:
    print(f"⚠️ ffprobe not found in PATH, but continuing...")
    print(f"   Error: {e}")

# Now import the rest
try:
    from faster_whisper import WhisperModel
    print("✅ faster-whisper imported")
except ImportError as e:
    print(f"❌ Error importing faster-whisper: {e}")
    print("Please install: pip install faster-whisper")
    sys.exit(1)

def format_duration(seconds):
    """Format seconds to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def transcribe_file(audio_file, diarize=False, speakers=None, meeting_name=None):
    """Transcribe a single audio file."""
    print(f"\n📁 Processing: {audio_file}")
    
    # Check if file exists
    if not os.path.exists(audio_file):
        print(f"❌ File not found: {audio_file}")
        return False
    
    # Get file size
    size_mb = os.path.getsize(audio_file) / (1024 * 1024)
    print(f"📊 Size: {size_mb:.1f} MB")
    
    # Load model
    print("\n🔄 Loading Whisper model (large-v3)...")
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    
    # Transcribe
    print("🎤 Transcribing... (this may take a while)")
    start_time = time.time()
    
    segments, info = model.transcribe(
        audio_file, 
        beam_size=5, 
        language="ru",
        task="transcribe"
    )
    
    elapsed = time.time() - start_time
    print(f"⏱️  Transcription time: {format_duration(elapsed)}")
    print(f"🌐 Detected language: {info.language} (prob: {info.language_probability:.2f})")
    
    # Save results
    output_file = Path(audio_file).stem + "_transcript.txt"
    print(f"\n💾 Saving to: {output_file}")
    
    with open(output_file, "w", encoding="utf-8") as f:
        for segment in segments:
            line = f"[{segment.start:.2f} -> {segment.end:.2f}] {segment.text}"
            print(line)
            f.write(line + "\n")
    
    print(f"\n✅ Done! Transcription saved to {output_file}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Transcribe audio files using faster-whisper")
    parser.add_argument("files", nargs="+", help="Audio files to transcribe")
    parser.add_argument("--diarize", action="store_true", help="Enable speaker diarization")
    parser.add_argument("--speakers", type=int, help="Number of speakers (for diarization)")
    parser.add_argument("--meeting", type=str, help="Meeting name for protocol")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  TRANSCRIBE AGENT")
    print("=" * 60)
    
    if args.diarize:
        print("  Mode: with speaker diarization")
        if args.speakers:
            print(f"  Speakers: {args.speakers}")
        if args.meeting:
            print(f"  Meeting: {args.meeting}")
    else:
        print("  Mode: plain transcription")
    
    print("=" * 60)
    
    # Process each file
    success_count = 0
    for file_path in args.files:
        if transcribe_file(file_path, args.diarize, args.speakers, args.meeting):
            success_count += 1
    
    print("\n" + "=" * 60)
    print(f"✅ Completed: {success_count}/{len(args.files)} files processed")
    print("=" * 60)

if __name__ == "__main__":
    main()