#!/usr/bin/env python3
"""TranscribeAGENT — local audio transcription using faster-whisper (Windows/CUDA).

Modes:
  transcribe.py file.mp3              — plain transcription (fast)
  transcribe.py file.mp3 --diarize    — with speaker separation (slower, needs pyannote)
  transcribe.py file.mp3 --diarize --speakers 3 --meeting "Custdev"  — full meeting protocol
  transcribe.py *.m4a --diarize       — batch: process multiple files sequentially
"""

import argparse
import json
import sys
import time
from pathlib import Path

from transcribe_agent.config import load_config
from transcribe_agent.audio import probe, convert_to_wav, cleanup, format_duration
from transcribe_agent.whisper import transcribe, transcribe_with_timestamps


def notify(title: str, message: str):
    """Stub — Windows toast notifications (optional, requires win10toast)."""
    pass


def log(msg=""):
    """Print to stderr so progress bar and stage messages stay in sync."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio files using whisper.cpp (Metal GPU)"
    )
    parser.add_argument("files", nargs='+', help="Path(s) to audio file(s) (mp3, wav, m4a, ogg)")
    parser.add_argument(
        "--language", "-l", default=None,
        help="Language code (default: from config, usually 'ru')"
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="Path to config.yaml (default: config.yaml in script directory)"
    )
    # Diarization options
    parser.add_argument(
        "--diarize", "-d", action="store_true",
        help="Enable speaker diarization (requires pyannote venv)"
    )
    parser.add_argument(
        "--speakers", "-s", type=int, default=None,
        help="Number of speakers (helps diarization accuracy)"
    )
    parser.add_argument(
        "--min-speakers", type=int, default=None,
        help="Minimum number of speakers"
    )
    parser.add_argument(
        "--max-speakers", type=int, default=None,
        help="Maximum number of speakers"
    )
    parser.add_argument(
        "--meeting", "-m", default="",
        help="Meeting type: custdev, consultation, strategic, client, etc."
    )
    parser.add_argument(
        "--names", "-n", default=None,
        help='Speaker names JSON: \'{"SPEAKER_00": "Name (role)"}\' or path to .json file'
    )
    parser.add_argument(
        "--no-interactive", action="store_true",
        help="Skip interactive speaker naming prompt"
    )
    args = parser.parse_args()

    # Resolve config path
    if args.config:
        config_path = args.config
    else:
        script_dir = Path(__file__).resolve().parent
        config_path = str(script_dir / "config.yaml")

    config = load_config(config_path)

    # Override language if specified
    if args.language:
        config["whisper"]["language"] = args.language

    # Override diarization settings from CLI
    if args.speakers is not None:
        config.setdefault("diarization", {})["num_speakers"] = args.speakers
    if args.min_speakers is not None:
        config.setdefault("diarization", {})["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        config.setdefault("diarization", {})["max_speakers"] = args.max_speakers

    # Validate and collect input files
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

    project_dir = Path(__file__).resolve().parent
    total = len(filepaths)

    # Batch header (only if multiple files)
    if total > 1:
        sep = "=" * 50
        log(f"\033[1;36m{sep}\033[0m")
        log(f"\033[1;36m  BATCH MODE — {total} файлов\033[0m")
        log(f"\033[1;36m{sep}\033[0m")
        log()

    succeeded = 0
    failed = 0
    failed_files = []
    batch_start = time.time()

    for idx, filepath in enumerate(filepaths, 1):
        if total > 1:
            log(f"\033[1;33m{'─' * 50}\033[0m")
            log(f"\033[1;33m  [{idx}/{total}] {filepath.name}\033[0m")
            log(f"\033[1;33m{'─' * 50}\033[0m")
            log()

        try:
            if args.diarize:
                _run_diarized(filepath, config, project_dir, args)
            else:
                _run_plain(filepath, config)
            succeeded += 1
        except Exception as e:
            failed += 1
            failed_files.append(filepath.name)
            log(f"\033[1;31m  ОШИБКА: {filepath.name}: {e}\033[0m")
            log()

    # Batch summary (only if multiple files)
    if total > 1:
        batch_time = time.time() - batch_start
        sep = "=" * 50
        log()
        log(f"\033[1;32m{sep}\033[0m")
        log(f"\033[1;32m  СЕРИЯ ЗАВЕРШЕНА!\033[0m")
        log(f"\033[1;32m  Успешно: {succeeded}/{total}\033[0m")
        if failed > 0:
            log(f"\033[1;31m  Ошибки:  {failed} ({', '.join(failed_files)})\033[0m")
        log(f"\033[1;32m  Время:   {format_duration(batch_time)}\033[0m")
        log(f"\033[1;32m{sep}\033[0m")



def _run_plain(filepath: Path, config: dict):
    """Original mode: plain transcription without speaker separation."""
    # === STAGE 1: Probe ===
    sep = "=" * 50
    log(f"\033[1;36m{sep}\033[0m")
    log(f"\033[1;36m  TRANSCRIBE AGENT\033[0m")
    log(f"\033[1;36m{sep}\033[0m")
    log()

    log(f"\033[1m[1/4] Analyzing file...\033[0m")
    info = probe(filepath)
    duration_str = format_duration(info['duration'])
    log(f"  File:     {filepath.name}")
    log(f"  Duration: {duration_str}")
    log(f"  Codec:    {info['codec']}, {info['sample_rate']}Hz")
    log(f"  Size:     {info['file_size'] / 1024 / 1024:.1f} MB")
    log()

    notify("Transcribe", f"Started: {filepath.name} ({duration_str})")  # no-op on Windows

    # === STAGE 2: Convert ===
    log(f"\033[1m[2/4] Converting to WAV (16kHz mono)...\033[0m")
    convert_start = time.time()
    wav_path = convert_to_wav(filepath)
    convert_time = time.time() - convert_start
    log(f"  WAV size: {wav_path.stat().st_size / 1024 / 1024:.1f} MB")
    log(f"  Time:     {format_duration(convert_time)}")
    log()

    # === STAGE 3: Transcribe ===
    log(f"\033[1m[3/4] Transcribing with faster-whisper...\033[0m")
    log(f"  Model:    {config['whisper'].get('model_size', 'large-v3')}")
    log(f"  Language: {config['whisper']['language']}")
    log(f"  Device:   {config['whisper'].get('device', 'auto')}")
    log()


    start_time = time.time()
    text = transcribe(wav_path, config, audio_duration=info['duration'])
    elapsed = time.time() - start_time

    # === STAGE 4: Save ===
    log()
    log(f"\033[1m[4/4] Saving result...\033[0m")

    txt_path = filepath.with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")
    cleanup(wav_path)

    word_count = len(text.split())
    speed = info['duration'] / elapsed if elapsed > 0 else 0

    log(f"  Output:   {txt_path}")
    log()
    log(f"\033[1;32m{sep}\033[0m")
    log(f"\033[1;32m  DONE!\033[0m")
    log(f"\033[1;32m  Words:    {word_count}\033[0m")
    log(f"\033[1;32m  Time:     {format_duration(elapsed)}\033[0m")
    log(f"\033[1;32m  Speed:    {speed:.1f}x realtime\033[0m")
    log(f"\033[1;32m{sep}\033[0m")



def _run_diarized(filepath: Path, config: dict, project_dir: Path, args):
    """Diarization mode using WhisperX (word-level speaker assignment)."""
    from transcribe_agent.whisperx_diarize import transcribe_and_diarize
    from transcribe_agent.diarize import check_hf_token
    from transcribe_agent.protocol import (
        consolidate_segments, dedup_segments,
        format_protocol, format_plain_diarized, detect_speakers_interactive,
    )

    sep = "=" * 50
    log(f"\033[1;35m{sep}\033[0m")
    log(f"\033[1;35m  TRANSCRIBE AGENT + WhisperX DIARIZATION\033[0m")
    log(f"\033[1;35m{sep}\033[0m")
    log()

    # === STAGE 1: Probe ===
    log(f"\033[1m[1/4] Analyzing file...\033[0m")
    info = probe(filepath)
    duration_str = format_duration(info['duration'])
    log(f"  File:     {filepath.name}")
    log(f"  Duration: {duration_str}")
    log(f"  Codec:    {info['codec']}, {info['sample_rate']}Hz")
    log(f"  Size:     {info['file_size'] / 1024 / 1024:.1f} MB")
    log()


    # === STAGE 2: WhisperX (transcribe + align + diarize) ===
    log(f"\033[1m[2/4] WhisperX pipeline...\033[0m")

    hf_token = check_hf_token(project_dir)
    language = config["whisper"].get("language", "ru")

    # Speaker params
    num_speakers = args.speakers
    min_speakers = args.min_speakers
    max_speakers = args.max_speakers
    diar_cfg = config.get("diarization", {})
    if num_speakers is None:
        num_speakers = diar_cfg.get("num_speakers")
    if min_speakers is None:
        min_speakers = diar_cfg.get("min_speakers")
    if max_speakers is None:
        max_speakers = diar_cfg.get("max_speakers")

    start_time = time.time()
    segments, unique_speakers = transcribe_and_diarize(
        audio_path=str(filepath),
        hf_token=hf_token,
        language=language,
        whisper_model="large-v3",
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )
    pipeline_time = time.time() - start_time
    log()

    # === STAGE 3: Names + Consolidation ===
    log(f"\033[1m[3/4] Speaker names + consolidation...\033[0m")

    # Resolve speaker names
    speaker_map = _resolve_speaker_map(
        args, unique_speakers, segments, segments
    )

    # Apply speaker names
    for seg in segments:
        spk = seg.get("speaker", "UNKNOWN")
        seg["speaker"] = speaker_map.get(spk, spk)

    # Consolidate consecutive same-speaker segments
    consolidated = consolidate_segments(segments)
    consolidated = dedup_segments(consolidated)

    log(f"  Consolidated: {len(consolidated)} blocks")
    log()

    # === STAGE 4: Save ===
    log(f"\033[1m[4/4] Saving protocol...\033[0m")

    # Build participants list
    participants = []
    for spk_id, display in speaker_map.items():
        if "(" in display and display.endswith(")"):
            paren_idx = display.rfind("(")
            name = display[:paren_idx].strip()
            role = display[paren_idx + 1:-1].strip()
        else:
            name = display
            role = ""
        if name and name != spk_id:
            participants.append({"name": name, "role": role})

    # Format output
    if args.meeting or participants:
        output_text = format_protocol(
            consolidated,
            meeting_type=args.meeting,
            participants=participants,
            audio_filename=filepath.name,
            audio_duration=info['duration'],
        )
    else:
        output_text = format_plain_diarized(consolidated)

    out_path = filepath.with_suffix(".protocol.txt")
    out_path.write_text(output_text, encoding="utf-8")

    # Results
    word_count = sum(len(seg["text"].split()) for seg in consolidated)

    log(f"  Файл: {out_path}")
    log()
    log(f"\033[1;32m{sep}\033[0m")
    log(f"\033[1;32m  DONE! (WhisperX)\033[0m")
    log(f"\033[1;32m  Speakers: {len(unique_speakers)}\033[0m")
    log(f"\033[1;32m  Words:    {word_count}\033[0m")
    log(f"\033[1;32m  Time:     {format_duration(pipeline_time)}\033[0m")
    log(f"\033[1;32m{sep}\033[0m")



def _resolve_speaker_map(
    args,
    unique_speakers: list,
    transcript_segments: list = None,
    diarization_segments: list = None,
) -> dict:
    """Resolve speaker names from CLI args or interactive prompt.

    Priority: --names flag > interactive prompt > default (SPEAKER_XX)
    """
    speaker_map = {}

    # 1. From --names flag
    if args.names:
        names_input = args.names.strip()
        # Check if it's a JSON file path
        if names_input.endswith(".json") and Path(names_input).exists():
            with open(names_input, encoding="utf-8") as f:
                speaker_map = json.load(f)
        else:
            # Parse inline JSON
            try:
                speaker_map = json.loads(names_input)
            except json.JSONDecodeError:
                log(f"  Warning: could not parse --names JSON, using defaults")

    # 2. Interactive prompt (if no names provided and not disabled)
    if not speaker_map and not args.no_interactive:
        # Only if running in terminal (not batch/pipe)
        if sys.stdin.isatty():
            from transcribe_agent.protocol import detect_speakers_interactive
            speaker_map = detect_speakers_interactive(
                unique_speakers, transcript_segments, diarization_segments
            )

    # 3. Default: "Спикер 1", "Спикер 2", ...
    if not speaker_map:
        for i, spk in enumerate(sorted(unique_speakers), 1):
            speaker_map[spk] = f"Спикер {i}"

    return speaker_map


if __name__ == "__main__":
    main()
