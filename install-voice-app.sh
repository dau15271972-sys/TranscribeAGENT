#!/bin/bash
# Установка Voice Input App
set -e

echo "=== Voice Input App — Установка ==="
echo ""

# Проверяем Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 не найден"
    exit 1
fi
echo "✅ Python: $(python3 --version)"

# Проверяем whisper-cli
if ! command -v whisper-cli &>/dev/null; then
    echo "❌ whisper-cli не найден. Установи: brew install whisper-cpp"
    exit 1
fi
echo "✅ whisper-cli найден"

# Проверяем модель
MODEL="$HOME/.local/share/whisper-models/ggml-large-v3.bin"
if [ ! -f "$MODEL" ]; then
    echo "❌ Модель не найдена: $MODEL"
    echo "   Скачай: curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin -o $MODEL"
    exit 1
fi
echo "✅ Модель: $(basename $MODEL)"

# Устанавливаем зависимости
echo ""
echo "Устанавливаю Python-зависимости..."
pip3 install rumps pynput sounddevice numpy

echo ""
echo "=== Готово! ==="
echo ""
echo "Запуск:  python3 voice-app.py"
echo ""
echo "Горячие клавиши:"
echo "  Ctrl+Option (удержать)  — запись пока нажаты"
echo "  Ctrl+Option (2x быстро) — toggle запись"
echo ""
echo "Menu bar: 🟢 готов | 🔴 запись | 🟡 транскрипция"
