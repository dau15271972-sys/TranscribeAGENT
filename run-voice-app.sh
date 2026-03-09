#!/bin/bash
# Wrapper для launchd — настраивает PATH и запускает voice-app.py
# launchd не знает про Homebrew, поэтому нужен этот скрипт

# Загружаем PATH от Homebrew
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null)"

# Лог
exec >> "$HOME/VoiceInput-launch.log" 2>&1
echo "=== $(date) === Starting Voice Input ==="

# Запуск
cd "/Users/vitalijfateicev/Projects/TranscribeAGENT"
exec /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 voice-app.py
