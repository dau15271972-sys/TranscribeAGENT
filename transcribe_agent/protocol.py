"""Format diarized transcript as a meeting protocol.

Merges consecutive segments from the same speaker,
formats timestamps, applies speaker names/roles.
"""

import re
import sys
from datetime import datetime


def log(msg=""):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def format_timestamp(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def consolidate_segments(merged_segments: list) -> list:
    """Merge consecutive segments from the same speaker.

    Input:  [{"speaker": "A", "text": "Hello"}, {"speaker": "A", "text": "world"}, ...]
    Output: [{"speaker": "A", "start": 0.0, "end": 5.0, "text": "Hello world"}, ...]
    """
    if not merged_segments:
        return []

    consolidated = []
    current = {
        "speaker": merged_segments[0]["speaker"],
        "start": merged_segments[0]["start"],
        "end": merged_segments[0]["end"],
        "text": merged_segments[0]["text"],
    }

    for seg in merged_segments[1:]:
        if seg["speaker"] == current["speaker"]:
            # Same speaker — merge
            current["end"] = seg["end"]
            current["text"] += " " + seg["text"]
        else:
            # New speaker — save current and start new
            consolidated.append(current)
            current = {
                "speaker": seg["speaker"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
            }

    consolidated.append(current)
    return consolidated


def _normalize_word(word: str) -> str:
    """Normalize a word for comparison: lowercase, strip punctuation."""
    return re.sub(r'[^\w]', '', word.lower())


def _find_boundary_overlap(words_a: list, words_b: list,
                           max_window: int = 15) -> int:
    """Find the longest suffix of words_a that matches a prefix of words_b.

    Returns the number of overlapping words (0 if no overlap found).
    Minimum match length is 2 words to avoid false positives.
    """
    max_check = min(max_window, len(words_a), len(words_b))

    for length in range(max_check, 1, -1):
        suffix_a = [_normalize_word(w) for w in words_a[-length:]]
        prefix_b = [_normalize_word(w) for w in words_b[:length]]
        if suffix_a == prefix_b:
            return length

    return 0


def trim_bleeding(merged_segments: list) -> list:
    """Remove duplicated text at segment boundaries caused by whisper.cpp overlap.

    Whisper.cpp produces overlapping timestamps (200ms-2s). Text in the overlap
    zone gets transcribed twice — once at the end of segment N and the start of
    segment N+1. This function detects shared suffix/prefix between adjacent
    segments and trims the duplicate from the later segment.
    """
    if len(merged_segments) <= 1:
        return list(merged_segments)

    result = [dict(merged_segments[0])]

    for i in range(1, len(merged_segments)):
        prev_seg = result[-1]
        curr_seg = dict(merged_segments[i])

        prev_words = prev_seg["text"].split()
        curr_words = curr_seg["text"].split()

        overlap_len = _find_boundary_overlap(prev_words, curr_words)

        if overlap_len > 0:
            curr_seg["text"] = " ".join(curr_words[overlap_len:])

        if curr_seg["text"].strip():
            result.append(curr_seg)

    return result


def dedup_segments(segments: list) -> list:
    """Remove whisper hallucination repetitions from segment texts.

    Whisper sometimes gets stuck in a loop, repeating the same phrase
    2-3x within a segment. This function detects and removes such
    consecutive repeated subsequences.

    Example:
        Input:  "я иду на работу я иду на работу я иду на работу потом домой"
        Output: "я иду на работу потом домой"
    """
    result = []
    for seg in segments:
        cleaned = dict(seg)
        cleaned["text"] = _dedup_text(seg["text"])
        # Skip segments that became empty after dedup
        if cleaned["text"].strip():
            result.append(cleaned)
    return result


def _dedup_text(text: str) -> str:
    """Remove consecutive repeated word sequences from text.

    Uses greedy approach: tries longest possible repeated prefix first,
    then moves forward. Conservative settings to avoid removing legitimate
    speech repetitions.
    """
    words = text.split()
    if len(words) < 6:
        return text

    original_count = len(words)

    for _ in range(3):  # max 3 iterations
        new_words = _dedup_pass(words)
        if len(new_words) == len(words):
            break
        words = new_words

    # Safeguard: if we removed >60% of text, something went wrong
    if len(words) < original_count * 0.4:
        return text

    return " ".join(words)


def _dedup_pass(words: list) -> list:
    """Single pass of greedy consecutive deduplication."""
    result = []
    i = 0
    while i < len(words):
        best_pattern_len = 0
        best_repeat_count = 0

        max_pattern = min(len(words) - i, (len(words) - i) // 2)
        for plen in range(max_pattern, 2, -1):
            repeats = 1
            j = i + plen
            while j + plen <= len(words) and words[j:j + plen] == words[i:i + plen]:
                repeats += 1
                j += plen

            if (repeats >= 2 and plen >= 4) or (repeats >= 3 and plen >= 1):
                best_pattern_len = plen
                best_repeat_count = repeats
                break

        if best_pattern_len > 0:
            result.extend(words[i:i + best_pattern_len])
            i += best_pattern_len * best_repeat_count
        else:
            result.append(words[i])
            i += 1

    return result


def format_protocol(
    consolidated_segments: list,
    meeting_type: str = "",
    participants: list = None,
    audio_filename: str = "",
    audio_duration: float = 0,
) -> str:
    """Format consolidated segments into a meeting protocol.

    Args:
        consolidated_segments: Output from consolidate_segments()
        meeting_type: e.g. "Стратегическая сессия", "Custdev", "Консультация"
        participants: [{"name": "Виталий", "role": "консультант"}, ...]
        audio_filename: Original audio file name
        audio_duration: Duration in seconds

    Returns:
        Formatted protocol as string
    """
    lines = []

    # Header
    lines.append("=" * 60)
    title = "ПРОТОКОЛ ВСТРЕЧИ"
    if meeting_type:
        title = f"ПРОТОКОЛ: {meeting_type.upper()}"
    lines.append(title)
    lines.append("=" * 60)
    lines.append("")

    # Metadata
    lines.append(f"Дата: {datetime.now().strftime('%d.%m.%Y')}")
    if audio_filename:
        lines.append(f"Файл: {audio_filename}")
    if audio_duration > 0:
        dur_min = int(audio_duration // 60)
        dur_sec = int(audio_duration % 60)
        lines.append(f"Длительность: {dur_min} мин {dur_sec} сек")

    if participants:
        lines.append("")
        lines.append("Участники:")
        for p in participants:
            role_str = f" ({p['role']})" if p.get("role") else ""
            lines.append(f"  - {p['name']}{role_str}")

    # Count unique speakers
    speakers = set()
    for seg in consolidated_segments:
        speakers.add(seg["speaker"])
    lines.append(f"Спикеров: {len(speakers)}")

    lines.append("")
    lines.append("-" * 60)
    lines.append("")

    # Transcript body
    for seg in consolidated_segments:
        ts_start = format_timestamp(seg["start"])
        ts_end = format_timestamp(seg["end"])
        speaker = seg["speaker"]
        text = seg["text"].strip()

        lines.append(f"[{ts_start}-{ts_end}] {speaker}:")
        lines.append(text)
        lines.append("")

    lines.append("-" * 60)
    lines.append(f"Конец протокола. Всего реплик: {len(consolidated_segments)}")

    return "\n".join(lines)


def format_plain_diarized(consolidated_segments: list) -> str:
    """Format as simple speaker-labeled text (no header, for quick use).

    Output:
        [0:00-0:45] SPEAKER_00:
        Text here...

        [0:46-2:15] SPEAKER_01:
        More text...
    """
    lines = []
    for seg in consolidated_segments:
        ts_start = format_timestamp(seg["start"])
        ts_end = format_timestamp(seg["end"])
        lines.append(f"[{ts_start}-{ts_end}] {seg['speaker']}:")
        lines.append(seg["text"].strip())
        lines.append("")

    return "\n".join(lines)


def detect_speakers_interactive(
    unique_speakers: list,
    transcript_segments: list = None,
    diarization_segments: list = None,
) -> dict:
    """Interactive prompt to map SPEAKER_XX to real names.

    Shows sample quotes from each speaker so user can identify them.

    Args:
        unique_speakers: ["SPEAKER_00", "SPEAKER_01", ...]
        transcript_segments: whisper segments with timestamps + text
        diarization_segments: pyannote segments with timestamps + speaker

    Returns speaker_map: {"SPEAKER_00": "Name (role)"}
    """
    log("")
    log("=" * 50)
    log("  КТО ЕСТЬ КТО?")
    log("=" * 50)
    log("")

    # Show sample quotes for each speaker so user can identify them
    if transcript_segments and diarization_segments:
        for spk in sorted(unique_speakers):
            log(f"  \033[1;33m{spk}\033[0m говорит, например:")
            # Find diarization segments for this speaker
            spk_diar = [d for d in diarization_segments if d["speaker"] == spk]
            quotes_shown = 0
            for dseg in spk_diar:
                if quotes_shown >= 2:
                    break
                # Find transcript segments overlapping with this diarization segment
                d_start = dseg["start"]
                d_end = dseg["end"]
                for tseg in transcript_segments:
                    overlap_start = max(tseg["start"], d_start)
                    overlap_end = min(tseg["end"], d_end)
                    if overlap_end > overlap_start:
                        text = tseg["text"].strip()
                        if len(text) > 15:  # Skip very short segments
                            preview = text[:120]
                            if len(text) > 120:
                                preview += "..."
                            log(f"    \"{preview}\"")
                            quotes_shown += 1
                            break
            if quotes_shown == 0:
                log("    (короткие реплики, недостаточно текста для примера)")
            log("")
    else:
        log("  Спикеры: " + ", ".join(sorted(unique_speakers)))
        log("")

    log("Введите имя и роль для каждого спикера.")
    log("Формат: Имя (роль)  — например: Виталий (консультант)")
    log("Нажмите Enter чтобы оставить SPEAKER_XX как есть.")
    log("")

    speaker_map = {}
    for spk in sorted(unique_speakers):
        prompt_msg = f"  {spk} → "
        sys.stderr.write(prompt_msg)
        sys.stderr.flush()

        try:
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            user_input = ""

        if user_input:
            speaker_map[spk] = user_input
        else:
            speaker_map[spk] = spk

    log("")
    return speaker_map
