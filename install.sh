#!/usr/bin/env bash
# Installs Blackmagic Proxy Generator (Linux) in-place from wherever this
# repo was cloned. Safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
LAUNCHER="$BIN_DIR/blackmagic-proxy-generator"

echo "==> Checking dependencies"
missing=()
command -v ffmpeg >/dev/null || missing+=("ffmpeg")
command -v inotifywait >/dev/null || missing+=("inotify-tools")
command -v python3 >/dev/null || missing+=("python3")
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing required packages: ${missing[*]}"
  echo "On Arch/Omarchy: sudo pacman -S ${missing[*]}"
  exit 1
fi

if [ ! -d /opt/resolve ]; then
  echo "WARNING: DaVinci Resolve (free or Studio) was not found at /opt/resolve."
  echo "This tool renders proxies through Resolve's engine, so it is required."
  echo "Install it, then re-run this script."
fi

ICON="/opt/resolve/graphics/application-x-braw-clip_256x256_mimetypes.png"
if [ ! -f "$ICON" ]; then
  ICON="video-x-generic"
fi

echo "==> Creating Python virtualenv"
cd "$SCRIPT_DIR"
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install ttkbootstrap pystray -q || \
  echo "NOTE: pystray/ttkbootstrap install failed, GUI will fall back to a plainer look/no tray icon."

echo "==> Installing launcher"
mkdir -p "$BIN_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/gui.py"
EOF
chmod +x "$LAUNCHER"

DESKTOP_FILE="$APPS_DIR/blackmagic-proxy-generator.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Blackmagic Proxy Generator
Comment=Watch-folder proxy transcoding for editors (uses the DaVinci Resolve engine)
Exec=$LAUNCHER
Icon=$ICON
Terminal=false
Categories=AudioVideo;Video;
EOF
desktop-file-validate "$DESKTOP_FILE" 2>/dev/null || true

read -rp "Start automatically at login? [Y/n] " ans
if [[ ! "$ans" =~ ^[Nn] ]]; then
  cp "$DESKTOP_FILE" "$AUTOSTART_DIR/blackmagic-proxy-generator.desktop"
  echo "X-GNOME-Autostart-Delay=15" >> "$AUTOSTART_DIR/blackmagic-proxy-generator.desktop"
fi

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true

echo "==> Done. Launch with: blackmagic-proxy-generator (or find it in your app menu)"
