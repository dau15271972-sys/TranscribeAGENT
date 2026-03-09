#!/bin/zsh
set -e

# TranscribeAGENT — Diarization module installer
# Creates a separate Python 3.12 venv with pyannote-audio
# Usage: bash install-diarize.sh [--hf-token TOKEN]
#
# Prerequisites: install.sh must be run first (base TranscribeAGENT)

echo ""
echo "\033[1;35m══════════════════════════════════════════════════\033[0m"
echo "\033[1;35m  TranscribeAGENT — Diarization Installer\033[0m"
echo "\033[1;35m══════════════════════════════════════════════════\033[0m"
echo ""

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/.venv-diarize"
HF_TOKEN=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hf-token) HF_TOKEN="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "Install dir: $INSTALL_DIR"
echo "Venv:        $VENV_DIR"
echo ""

# ── 1. Check base installation ──
echo "\033[1m[1/6] Checking base TranscribeAGENT...\033[0m"
if [ ! -f "$INSTALL_DIR/transcribe.py" ]; then
    echo "  ERROR: TranscribeAGENT not found. Run install.sh first."
    exit 1
fi
echo "  Base installation OK"
echo ""

# ── 2. Install Python 3.12 via Homebrew ──
echo "\033[1m[2/6] Checking Python 3.12+...\033[0m"

# pyannote requires Python 3.10+, macOS system Python is 3.9
# Install Python 3.12 via Homebrew for the venv
BREW_PYTHON=""
if command -v python3.12 &>/dev/null; then
    BREW_PYTHON="python3.12"
    echo "  Python 3.12 found: $(python3.12 --version)"
elif command -v python3.11 &>/dev/null; then
    BREW_PYTHON="python3.11"
    echo "  Python 3.11 found: $(python3.11 --version)"
elif command -v python3.10 &>/dev/null; then
    BREW_PYTHON="python3.10"
    echo "  Python 3.10 found: $(python3.10 --version)"
else
    echo "  Python 3.10+ not found. Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    BREW_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
    if [ ! -f "$BREW_PYTHON" ]; then
        BREW_PYTHON="python3.12"
    fi
    echo "  Installed: $($BREW_PYTHON --version)"
fi
echo ""

# ── 3. Create virtual environment ──
echo "\033[1m[3/6] Creating Python venv for diarization...\033[0m"
if [ -d "$VENV_DIR" ]; then
    echo "  Venv exists, removing old one..."
    rm -rf "$VENV_DIR"
fi

"$BREW_PYTHON" -m venv "$VENV_DIR"
VENV_PIP="$VENV_DIR/bin/pip"
VENV_PYTHON="$VENV_DIR/bin/python3"

echo "  Created: $VENV_DIR"
echo "  Python:  $("$VENV_PYTHON" --version)"
echo ""

# ── 4. Install pyannote-audio + dependencies ──
echo "\033[1m[4/6] Installing pyannote-audio (this takes a few minutes)...\033[0m"
echo "  Installing torch + pyannote-audio..."
echo ""

# Upgrade pip first
"$VENV_PIP" install --upgrade pip setuptools wheel 2>&1 | tail -1

# Install PyTorch (CPU only — MPS is unstable for pyannote)
"$VENV_PIP" install torch torchaudio --index-url https://download.pytorch.org/whl/cpu 2>&1 | tail -3

# Install pyannote-audio
"$VENV_PIP" install pyannote.audio 2>&1 | tail -3

echo ""
echo "  pyannote-audio installed"
echo ""

# ── 5. HuggingFace token ──
echo "\033[1m[5/6] Configuring HuggingFace token...\033[0m"

TOKEN_FILE="$INSTALL_DIR/.hf_token"

if [ -n "$HF_TOKEN" ]; then
    echo "$HF_TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "  Token saved to $TOKEN_FILE"
elif [ -f "$TOKEN_FILE" ]; then
    echo "  Token file exists: $TOKEN_FILE"
elif [ -n "$HF_TOKEN_ENV" ]; then
    echo "$HF_TOKEN_ENV" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "  Token saved from HF_TOKEN env var"
else
    echo ""
    echo "  \033[1;33m⚠ HuggingFace token required!\033[0m"
    echo ""
    echo "  pyannote requires a free HuggingFace account:"
    echo "  1. Create account: https://huggingface.co/join"
    echo "  2. Accept model terms:"
    echo "     https://huggingface.co/pyannote/speaker-diarization-3.1"
    echo "  3. Get token: https://huggingface.co/settings/tokens"
    echo "  4. Run:"
    echo "     echo 'hf_YOUR_TOKEN' > $TOKEN_FILE"
    echo ""
    echo "  Or re-run installer:"
    echo "     bash install-diarize.sh --hf-token hf_YOUR_TOKEN"
fi
echo ""

# ── 6. Verify ──
echo "\033[1m[6/6] Verification...\033[0m"
ERRORS=0

# Check venv python
if [ -f "$VENV_PYTHON" ]; then
    echo "  \033[32m✓\033[0m Python venv ($("$VENV_PYTHON" --version))"
else
    echo "  \033[31m✗\033[0m Python venv MISSING"
    ERRORS=$((ERRORS+1))
fi

# Check pyannote import
if "$VENV_PYTHON" -c "import pyannote.audio" 2>/dev/null; then
    echo "  \033[32m✓\033[0m pyannote.audio"
else
    echo "  \033[31m✗\033[0m pyannote.audio IMPORT FAILED"
    ERRORS=$((ERRORS+1))
fi

# Check torch
if "$VENV_PYTHON" -c "import torch; print(f'  torch {torch.__version__}')" 2>/dev/null; then
    echo "  \033[32m✓\033[0m torch"
else
    echo "  \033[31m✗\033[0m torch IMPORT FAILED"
    ERRORS=$((ERRORS+1))
fi

# Check HF token
if [ -f "$TOKEN_FILE" ] && [ -s "$TOKEN_FILE" ]; then
    echo "  \033[32m✓\033[0m HuggingFace token"
else
    echo "  \033[33m⚠\033[0m HuggingFace token NOT SET (see instructions above)"
fi

# Venv size
VENV_SIZE=$(du -sh "$VENV_DIR" 2>/dev/null | cut -f1)
echo ""
echo "  Venv size: $VENV_SIZE"

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
    echo "\033[1;32m  DIARIZATION MODULE INSTALLED!\033[0m"
    echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
    echo ""
    echo "  Usage examples:"
    echo ""
    echo "  \033[1mBasic (auto-detect speakers):\033[0m"
    echo "    python3 $INSTALL_DIR/transcribe.py audio.mp3 --diarize"
    echo ""
    echo "  \033[1mWith speaker count:\033[0m"
    echo "    python3 $INSTALL_DIR/transcribe.py meeting.mp3 --diarize --speakers 3"
    echo ""
    echo "  \033[1mFull meeting protocol:\033[0m"
    echo "    python3 $INSTALL_DIR/transcribe.py meeting.mp3 \\"
    echo "      --diarize --speakers 2 --meeting \"Custdev\" \\"
    echo "      --names '{\"SPEAKER_00\": \"Виталий (консультант)\", \"SPEAKER_01\": \"Клиент\"}'"
    echo ""
    echo "  \033[1mOutput:\033[0m"
    echo "    audio.protocol.txt   — formatted protocol with speaker labels"
else
    echo "\033[1;31m  Installation finished with $ERRORS error(s)\033[0m"
fi
