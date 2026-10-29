"""Configuration management for Video Production Studio."""

import json
from pathlib import Path
from typing import Dict, Any

CONFIG_PATH = Path("config.json")


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: Dict[str, Any], path: Path = CONFIG_PATH) -> None:
    """Save configuration to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
