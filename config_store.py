import json
import os

CONFIG_DIR = os.path.expanduser("~/.config/blackmagic-proxy-generator")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_DESKTOP_PATH = os.path.expanduser(
    "~/.config/autostart/blackmagic-proxy-generator.desktop"
)

DEFAULT_CONFIG = {
    "watch_folders": [],       # [{"path": "...", "output": ""}]  output "" = mirror as <path>/Proxy
    "codec": "dnxhr_lb",
    "resolution": "1080",
    "suffix": "_proxy",
    "stabilize_seconds": 2,
    "extensions": [
        ".mp4", ".mov", ".mxf", ".avi", ".mkv", ".mts", ".m2ts",
        ".m4v", ".wmv", ".webm", ".braw", ".r3d", ".ari", ".dng",
    ],
    "autostart": True,
}


def load():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def is_autostart_enabled():
    if not os.path.exists(AUTOSTART_DESKTOP_PATH):
        return False
    with open(AUTOSTART_DESKTOP_PATH) as f:
        lines = f.readlines()
    return not any(line.strip() == "Hidden=true" for line in lines)


def set_autostart_enabled(enabled):
    if not os.path.exists(AUTOSTART_DESKTOP_PATH):
        return
    with open(AUTOSTART_DESKTOP_PATH) as f:
        lines = [l for l in f.readlines() if not l.strip().startswith("Hidden=")]
    if not enabled:
        lines.append("Hidden=true\n")
    with open(AUTOSTART_DESKTOP_PATH, "w") as f:
        f.writelines(lines)
