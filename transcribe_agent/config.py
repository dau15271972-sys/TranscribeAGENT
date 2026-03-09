import sys
from pathlib import Path

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """Load and validate config from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"Error: config file not found: {config_path}")
        sys.exit(1)

    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Ensure required sections exist with defaults
    config.setdefault("whisper", {})
    config["whisper"].setdefault("model_size", "large-v3")
    config["whisper"].setdefault("language", "ru")
    config["whisper"].setdefault("device", "auto")
    config["whisper"].setdefault("compute_type", "auto")

    config.setdefault("audio", {})
    config["audio"].setdefault("formats", ["mp3", "wav", "m4a", "ogg"])

    return config
