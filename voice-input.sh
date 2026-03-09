#!/bin/bash
# Voice Input for Claude Code
# Push-to-talk: запускаешь скрипт, говоришь, нажимаешь Enter — текст в буфер обмена
#
# Использование:
#   ./voice-input.sh        — запись → транскрипция → копирует в буфер обмена
#   ./voice-input.sh --type — запись → транскрипция → вставляет текст (симулирует набор)

MODEL="/opt/homebrew/share/whisper-cpp/models/ggml-small.bin"
LANG="ru"
AUDIO_DEVICE=":2"  # Микрофон MacBook Pro (индекс 2)
TMP_WAV="/tmp/voice-input.wav"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    rm -f "$TMP_WAV"
}
trap cleanup EXIT

# Проверка зависимостей
if ! command -v whisper-cli &>/dev/null; then
    echo -e "${RED}whisper-cli не найден. Установи: brew install whisper-cpp${NC}"
    exit 1
fi
if ! command -v ffmpeg &>/dev/null; then
    echo -e "${RED}ffmpeg не найден. Установи: brew install ffmpeg${NC}"
    exit 1
fi

echo -e "${GREEN}🎤 Говори...${NC} (нажми ${YELLOW}Enter${NC} чтобы остановить запись)"

# Запись аудио с микрофона (16kHz mono WAV — формат для whisper)
ffmpeg -y -f avfoundation -i "$AUDIO_DEVICE" \
    -ar 16000 -ac 1 -acodec pcm_s16le \
    "$TMP_WAV" \
    -loglevel quiet &
FFMPEG_PID=$!

# Ждём Enter
read -r -s

# Останавливаем запись
kill $FFMPEG_PID 2>/dev/null
wait $FFMPEG_PID 2>/dev/null

# Проверяем что файл не пустой
if [ ! -s "$TMP_WAV" ]; then
    echo -e "${RED}Запись пуста. Проверь микрофон.${NC}"
    exit 1
fi

DURATION=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$TMP_WAV" 2>/dev/null)
echo -e "${YELLOW}Транскрибирую (${DURATION}s)...${NC}"

# Транскрипция
TEXT=$(whisper-cli \
    -m "$MODEL" \
    -l "$LANG" \
    -f "$TMP_WAV" \
    --no-timestamps \
    2>/dev/null | grep -v "^$" | sed 's/^ *//')

if [ -z "$TEXT" ]; then
    echo -e "${RED}Не удалось распознать речь.${NC}"
    exit 1
fi

echo -e "${GREEN}📝 Результат:${NC}"
echo "$TEXT"
echo ""

if [ "$1" = "--type" ]; then
    # Вставка через AppleScript (симулирует набор в активное окно)
    osascript -e "tell application \"System Events\" to keystroke \"$TEXT\""
    echo -e "${GREEN}✅ Текст вставлен в активное окно${NC}"
else
    # Копируем в буфер обмена
    echo -n "$TEXT" | pbcopy
    echo -e "${GREEN}✅ Скопировано в буфер обмена (Cmd+V чтобы вставить)${NC}"
fi
