#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rm -f "$HOME/.local/bin/blackmagic-proxy-generator"
rm -f "$HOME/.local/share/applications/blackmagic-proxy-generator.desktop"
rm -f "$HOME/.config/autostart/blackmagic-proxy-generator.desktop"
rm -rf "$SCRIPT_DIR/venv" "$SCRIPT_DIR/__pycache__"

echo "Removed launcher, menu entry and virtualenv."
echo "Config left untouched at: ~/.config/blackmagic-proxy-generator/"
echo "Delete this repo directory yourself if you no longer need the source."
