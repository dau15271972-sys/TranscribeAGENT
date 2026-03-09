#!/bin/bash
set -e

echo "=== TranscribeAGENT Setup ==="

# 1. Install system dependencies
echo ""
echo "[1/4] Installing ffmpeg and whisper-cpp via Homebrew..."
if ! command -v ffmpeg &> /dev/null; then
    brew install ffmpeg
else
    echo "  ffmpeg already installed: $(which ffmpeg)"
fi

if ! command -v whisper-cli &> /dev/null; then
    brew install whisper-cpp
else
    echo "  whisper-cli already installed: $(which whisper-cli)"
fi

# 2. Download whisper model
echo ""
echo "[2/4] Downloading whisper large-v3 model (2.9GB)..."
MODEL_DIR="$HOME/.local/share/whisper-models"
MODEL_FILE="$MODEL_DIR/ggml-large-v3.bin"
mkdir -p "$MODEL_DIR"

if [ ! -f "$MODEL_FILE" ]; then
    curl -L --progress-bar -o "$MODEL_FILE" \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
    echo "  Model downloaded: $(du -h "$MODEL_FILE" | cut -f1)"
else
    echo "  Model already exists: $(du -h "$MODEL_FILE" | cut -f1)"
fi

# 3. Install Python dependencies
echo ""
echo "[3/4] Installing Python dependencies..."
pip3 install -r requirements.txt

# 4. Verify
echo ""
echo "[4/4] Verifying installation..."
ERRORS=0

if command -v ffmpeg &> /dev/null; then
    echo "  ffmpeg:      OK ($(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3))"
else
    echo "  ffmpeg:      MISSING"
    ERRORS=$((ERRORS+1))
fi

if command -v ffprobe &> /dev/null; then
    echo "  ffprobe:     OK"
else
    echo "  ffprobe:     MISSING"
    ERRORS=$((ERRORS+1))
fi

if command -v whisper-cli &> /dev/null; then
    echo "  whisper-cli: OK"
else
    echo "  whisper-cli: MISSING"
    ERRORS=$((ERRORS+1))
fi

if [ -f "$MODEL_FILE" ]; then
    echo "  model:       OK ($(du -h "$MODEL_FILE" | cut -f1))"
else
    echo "  model:       MISSING"
    ERRORS=$((ERRORS+1))
fi

if python3 -c "import yaml" 2>/dev/null; then
    echo "  pyyaml:      OK"
else
    echo "  pyyaml:      MISSING"
    ERRORS=$((ERRORS+1))
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "=== Setup complete! ==="
    echo "Usage: python3 transcribe.py <audio_file>"
else
    echo "=== Setup finished with $ERRORS error(s) ==="
fi
