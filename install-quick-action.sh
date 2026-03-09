#!/bin/bash
# Install Transcribe Quick Action for Finder context menu
# This creates the workflow via Automator using AppleScript

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOW_PATH="$HOME/Library/Services/Transcribe.workflow"

# Remove old version if exists
rm -rf "$WORKFLOW_PATH"

# Create the shell script that will be called by the Quick Action
SHELL_SCRIPT="$SCRIPT_DIR/transcribe-service.sh"
cat > "$SHELL_SCRIPT" << 'SHELLEOF'
#!/bin/bash
export PATH="/opt/homebrew/bin:$PATH"

for f in "$@"; do
    ext="${f##*.}"
    ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    case "$ext_lower" in
        mp3|wav|m4a|ogg) ;;
        *) continue ;;
    esac

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    /usr/bin/python3 "$SCRIPT_DIR/transcribe.py" "$f"

    if [ $? -eq 0 ]; then
        txt_file="${f%.*}.txt"
        wc=$(wc -w < "$txt_file" | tr -d ' ')
        osascript -e "display notification \"$wc words\" with title \"Transcribe Done\""
    else
        osascript -e "display notification \"Error\" with title \"Transcribe Failed\""
    fi
done
SHELLEOF
chmod +x "$SHELL_SCRIPT"

echo ""
echo "=== Transcribe Quick Action Installer ==="
echo ""
echo "Shell script created: $SHELL_SCRIPT"
echo ""
echo "Now creating Quick Action via Automator..."
echo ""

# Use AppleScript to create the Quick Action in Automator
osascript << ASEOF
tell application "Automator"
    activate

    -- Create new Quick Action document
    set newDoc to make new document with properties {document type:quick action type}

    delay 1

    -- We need the user to manually add the Run Shell Script action
    -- because Automator's AppleScript API is very limited
end tell

tell application "System Events"
    delay 2
    -- Show dialog with instructions
end tell

display dialog "Automator is open with a new Quick Action.

Do these 3 steps:

1. In the search bar (top left), type: Run Shell Script
2. Double-click 'Run Shell Script' to add it
3. In 'Pass input', change to 'as arguments'
4. Replace the script with:

$SHELL_SCRIPT \"\$@\"

Then save as 'Transcribe' (Cmd+S)" with title "Setup Instructions" buttons {"OK"} default button "OK"
ASEOF

echo ""
echo "Follow the instructions in the dialog to complete setup."
