#!/bin/zsh
set -e

# TranscribeAGENT — Full installer
# Installs dependencies, model, Quick Action
# Usage: bash install.sh [--language XX] [--install-dir /path]

echo ""
echo "\033[1;36m══════════════════════════════════════════════════\033[0m"
echo "\033[1;36m  TranscribeAGENT Installer\033[0m"
echo "\033[1;36m══════════════════════════════════════════════════\033[0m"
echo ""

# ── Parse arguments ──
LANGUAGE="ru"
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --language) LANGUAGE="$2"; shift 2 ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "Install dir: $INSTALL_DIR"
echo "Language:    $LANGUAGE"
echo ""

# ── 1. Check macOS + Apple Silicon ──
echo "\033[1m[1/7] Checking system...\033[0m"
if [[ "$(uname)" != "Darwin" ]]; then
    echo "  ERROR: This tool is macOS only."
    exit 1
fi
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    echo "  Apple Silicon ($ARCH) — Metal GPU will be used"
else
    echo "  Intel ($ARCH) — no Metal GPU, transcription will be slower"
fi
echo ""

# ── 2. Check/install Homebrew ──
echo "\033[1m[2/7] Checking Homebrew...\033[0m"
if ! command -v brew &>/dev/null; then
    echo "  Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "  Homebrew OK: $(brew --prefix)"
fi
echo ""

# ── 3. Install system dependencies ──
echo "\033[1m[3/7] Installing ffmpeg and whisper-cpp...\033[0m"
if ! command -v ffmpeg &>/dev/null; then
    echo "  Installing ffmpeg..."
    brew install ffmpeg
else
    echo "  ffmpeg OK: $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f3)"
fi

if ! command -v whisper-cli &>/dev/null; then
    echo "  Installing whisper-cpp..."
    brew install whisper-cpp
else
    echo "  whisper-cli OK: $(which whisper-cli)"
fi
echo ""

# ── 4. Download whisper model ──
echo "\033[1m[4/7] Downloading whisper large-v3 model (2.9GB)...\033[0m"
MODEL_DIR="$HOME/.local/share/whisper-models"
MODEL_FILE="$MODEL_DIR/ggml-large-v3.bin"
mkdir -p "$MODEL_DIR"

if [ ! -f "$MODEL_FILE" ]; then
    echo "  Downloading from HuggingFace..."
    curl -L --progress-bar -o "$MODEL_FILE" \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
    echo "  Model downloaded: $(du -h "$MODEL_FILE" | cut -f1)"
else
    echo "  Model already exists: $(du -h "$MODEL_FILE" | cut -f1)"
fi
echo ""

# ── 5. Install Python dependencies ──
echo "\033[1m[5/7] Installing Python dependencies...\033[0m"
# Install for SYSTEM python (used by Automator Quick Action)
if /usr/bin/python3 -c "import yaml" 2>/dev/null; then
    echo "  pyyaml OK (system python)"
else
    echo "  Installing pyyaml for /usr/bin/python3..."
    /usr/bin/python3 -m pip install --user pyyaml 2>/dev/null || \
    /usr/bin/python3 -m pip install pyyaml
fi
# Also install for brew python if available
if command -v python3 &>/dev/null && [[ "$(which python3)" != "/usr/bin/python3" ]]; then
    python3 -m pip install pyyaml 2>/dev/null || true
fi
echo ""

# ── 6. Generate config.yaml with correct paths ──
echo "\033[1m[6/7] Generating config.yaml...\033[0m"
WHISPER_BIN=$(which whisper-cli)
cat > "$INSTALL_DIR/config.yaml" << YAMLEOF
whisper:
  binary: $WHISPER_BIN
  model: ~/.local/share/whisper-models/ggml-large-v3.bin
  language: $LANGUAGE
  threads: 4

audio:
  formats:
    - mp3
    - wav
    - m4a
    - ogg
YAMLEOF
echo "  Created: $INSTALL_DIR/config.yaml"
echo "  Language: $LANGUAGE"
echo ""

# ── 7. Update transcribe-service.sh with install path ──
echo "\033[1m[7/7] Configuring service script...\033[0m"
SERVICE="$INSTALL_DIR/transcribe-service.sh"
if [ -f "$SERVICE" ]; then
    # Update SCRIPT_DIR in service script
    sed -i '' "s|^SCRIPT_DIR=.*|SCRIPT_DIR=\"$INSTALL_DIR\"|" "$SERVICE"
    chmod +x "$SERVICE"
    echo "  Updated: $SERVICE"
else
    echo "  WARNING: $SERVICE not found"
fi
chmod +x "$INSTALL_DIR/transcribe.py" 2>/dev/null || true
echo ""

# ── Verify ──
echo "\033[1m── Verification ──\033[0m"
ERRORS=0
for tool in ffmpeg ffprobe whisper-cli; do
    if command -v $tool &>/dev/null; then
        echo "  \033[32m✓\033[0m $tool"
    else
        echo "  \033[31m✗\033[0m $tool MISSING"
        ERRORS=$((ERRORS+1))
    fi
done

if [ -f "$MODEL_FILE" ]; then
    echo "  \033[32m✓\033[0m model ($(du -h "$MODEL_FILE" | cut -f1))"
else
    echo "  \033[31m✗\033[0m model MISSING"
    ERRORS=$((ERRORS+1))
fi

if /usr/bin/python3 -c "import yaml" 2>/dev/null; then
    echo "  \033[32m✓\033[0m pyyaml"
else
    echo "  \033[31m✗\033[0m pyyaml MISSING"
    ERRORS=$((ERRORS+1))
fi

# Quick test
if [ $ERRORS -eq 0 ]; then
    echo ""
    echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
    echo "\033[1;32m  INSTALLATION COMPLETE!\033[0m"
    echo "\033[1;32m══════════════════════════════════════════════════\033[0m"
    echo ""
    echo "  CLI usage:"
    echo "    python3 $INSTALL_DIR/transcribe.py <audio_file>"
    echo ""
    echo "  \033[1mFinder Quick Action (one-time manual step):\033[0m"
    echo "  1. Open Automator → New → Quick Action"
    echo "  2. 'Workflow receives': files or folders, in: Finder"
    echo "  3. Add action: Run Shell Script"
    echo "  4. Shell: /bin/zsh, Pass input: as arguments"
    echo "  5. Command:"
    echo "     \"$INSTALL_DIR/transcribe-service.sh\" \"\$@\""
    echo "  6. Save as: Transcribe"
    echo ""
    echo "  Then: select audio files → right-click → Quick Actions → Transcribe"
else
    echo ""
    echo "\033[1;31m  Installation finished with $ERRORS error(s)\033[0m"
fi
