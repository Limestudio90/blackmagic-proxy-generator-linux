import json
import os

CONFIG_DIR = os.path.expanduser("~/.config/blackmagic-proxy-generator")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

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
