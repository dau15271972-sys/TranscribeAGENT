#!/bin/zsh
# TranscribeAGENT — Finder Quick Action wrapper
# Shows a mode selection dialog, then processes files in Terminal.
#
# Flow:
#   1. User right-clicks audio files in Finder → "Transcribe"
#   2. macOS dialog: choose mode (plain / meeting protocol)
#   3. If meeting: ask number of speakers + meeting topic
#   4. Opens Terminal with queue processing
#   5. If meeting: after diarization, interactive name input in Terminal

export PATH="/opt/homebrew/bin:$PATH"

SCRIPT_DIR="/Users/vitalijfateicev/Projects/TranscribeAGENT"

# ── Collect valid audio files ──
file_list=$(mktemp /tmp/transcribe_list_XXXXXX)
count=0
for f in "$@"; do
    ext="${f##*.}"
    ext_lower="${ext:l}"
    case "$ext_lower" in
        mp3|wav|m4a|ogg)
            echo "$f" >> "$file_list"
            count=$((count + 1))
            ;;
    esac
done

if [ $count -eq 0 ]; then
    osascript -e 'display notification "No audio files selected" with title "TranscribeAGENT"'
    rm -f "$file_list"
    exit 0
fi

# ── Show mode selection dialog ──
# AppleScript dialog with two buttons
MODE=$(osascript << 'ASEOF'
try
    set theChoice to button returned of (display dialog "TranscribeAGENT" & return & return & "Выбери режим:" buttons {"Отмена", "📝 Транскрибация", "👥 Протокол встречи"} default button "📝 Транскрибация" with title "TranscribeAGENT" with icon note)
    if theChoice is "📝 Транскрибация" then
        return "plain"
    else if theChoice is "👥 Протокол встречи" then
        return "meeting"
    else
        return "cancel"
    end if
on error
    return "cancel"
end try
ASEOF
)

if [ "$MODE" = "cancel" ] || [ -z "$MODE" ]; then
    rm -f "$file_list"
    exit 0
fi

# ── If meeting mode: ask details ──
DIARIZE_FLAGS=""
MEETING_TYPE=""
NUM_SPEAKERS=""

if [ "$MODE" = "meeting" ]; then
    # Check if diarization venv exists
    if [ ! -f "$SCRIPT_DIR/.venv-diarize/bin/python3" ]; then
        osascript -e 'display alert "Модуль диаризации не установлен" message "Запусти в Terminal:\nbash install-diarize.sh --hf-token hf_YOUR_TOKEN\n\nПодробности в CLAUDE.md" as warning'
        rm -f "$file_list"
        exit 0
    fi

    # Ask number of speakers
    NUM_SPEAKERS=$(osascript << 'ASEOF'
try
    set theAnswer to text returned of (display dialog "Сколько участников встречи?" & return & "(точное число повышает качество)" default answer "2" with title "TranscribeAGENT — Протокол" with icon note buttons {"Отмена", "Далее"} default button "Далее")
    return theAnswer
on error
    return "cancel"
end try
ASEOF
    )

    if [ "$NUM_SPEAKERS" = "cancel" ] || [ -z "$NUM_SPEAKERS" ]; then
        rm -f "$file_list"
        exit 0
    fi

    # Ask meeting topic (optional)
    MEETING_TYPE=$(osascript << 'ASEOF'
try
    set theAnswer to text returned of (display dialog "Тема/тип встречи:" & return & "(для шапки протокола, можно оставить пустым)" & return & return & "Примеры: Custdev, Консультация, Стратегическая сессия, 1-на-1" default answer "" with title "TranscribeAGENT — Протокол" with icon note buttons {"Пропустить", "Начать"} default button "Начать")
    return theAnswer
on error
    return ""
end try
ASEOF
    )

    # Build flags
    DIARIZE_FLAGS="--diarize --speakers $NUM_SPEAKERS --no-interactive"
    if [ -n "$MEETING_TYPE" ] && [ "$MEETING_TYPE" != "cancel" ]; then
        DIARIZE_FLAGS="$DIARIZE_FLAGS --meeting \"$MEETING_TYPE\""
    fi
fi

# ── Write the runner script ──
runner=$(mktemp /tmp/transcribe_runner_XXXXXX)

if [ "$MODE" = "meeting" ]; then
    MODE_LABEL="ПРОТОКОЛ ВСТРЕЧИ"
    EXTRA_INFO="  Спикеров: $NUM_SPEAKERS"
    if [ -n "$MEETING_TYPE" ] && [ "$MEETING_TYPE" != "cancel" ]; then
        EXTRA_INFO="$EXTRA_INFO\n  Тема:     $MEETING_TYPE"
    fi
else
    MODE_LABEL="ТРАНСКРИБАЦИЯ"
    EXTRA_INFO=""
fi

cat > "$runner" << INNEREOF
#!/bin/zsh
export PATH="/opt/homebrew/bin:\$PATH"
clear

FILE_LIST="$file_list"
TOTAL=$count
MODE_LABEL="$MODE_LABEL"

echo "\033[1;36m══════════════════════════════════════════════════\033[0m"
echo "\033[1;36m  TranscribeAGENT — \$MODE_LABEL\033[0m"
echo "\033[1;36m  Файлов: $count\033[0m"
INNEREOF

# Add extra info if meeting mode
if [ -n "$EXTRA_INFO" ]; then
    cat >> "$runner" << INNEREOF2
echo "$EXTRA_INFO"
INNEREOF2
fi

cat >> "$runner" << INNEREOF3
echo "\033[1;36m══════════════════════════════════════════════════\033[0m"
echo ""

CURRENT=0
SUCCEEDED=0
FAILED=0

# CRITICAL: read file list via fd 3 (not stdin!)
# stdin must stay free for interactive speaker name input in Python
while IFS= read -r f <&3; do
    CURRENT=\$((CURRENT + 1))
    filename=\$(basename "\$f")

    echo "\033[1;35m──────────────────────────────────────────────────\033[0m"
    echo "\033[1;35m  [\$CURRENT/$count] \$filename\033[0m"
    echo "\033[1;35m──────────────────────────────────────────────────\033[0m"
    echo ""

    "$SCRIPT_DIR/.venv-diarize/bin/python3" "$SCRIPT_DIR/transcribe.py" "\$f" $DIARIZE_FLAGS 2>&1

    if [ \$? -eq 0 ]; then
        SUCCEEDED=\$((SUCCEEDED + 1))
    else
        FAILED=\$((FAILED + 1))
        echo "\033[1;31m  ОШИБКА: \$filename\033[0m"
    fi
    echo ""
done 3< "\$FILE_LIST"

echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
echo "\033[1;32m  ГОТОВО!\033[0m"
echo "\033[1;32m  Обработано: \$SUCCEEDED из $count\033[0m"
if [ \$FAILED -gt 0 ]; then
    echo "\033[1;31m  Ошибок:     \$FAILED\033[0m"
fi
echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
echo ""
echo "\033[1;33mНажми любую клавишу чтобы закрыть...\033[0m"
read -k 1

rm -f "\$FILE_LIST" "$runner"
INNEREOF3

chmod +x "$runner"

# Escape single quotes in runner path for AppleScript
escaped_runner="${runner//\'/\'\\\'\'}"

# Open Terminal and execute
osascript -e "
tell application \"Terminal\"
    activate
    do script \"/bin/zsh '${escaped_runner}'\"
end tell
"
