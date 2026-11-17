"""Settings loader for social-listening configuration."""
import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path(__file__).resolve().parent


def load_yaml(path: Path) -> Dict[str, Any]:
    """Safely load a YAML file and return its dictionary representation."""
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f) or {}


def load_config() -> Dict[str, Any]:
    """Load config.yaml with environment variable overrides."""
    config = load_yaml(CONFIG_DIR / "config.yaml")

    # Environment overrides
    if "BUDGET_USD" in os.environ:
        try:
            config["budget_usd"] = float(os.environ["BUDGET_USD"])
        except ValueError:
            pass

    return config


def load_companies() -> Dict[str, Any]:
    """Load company targeting configuration from companies.yaml."""
    data = load_yaml(CONFIG_DIR / "companies.yaml")
    return data.get("companies", {})


def load_plugin_config(name: str) -> Dict[str, Any]:
    """Read config/plugins/<name>.yaml."""
    plugin_path = CONFIG_DIR / "plugins" / f"{name}.yaml"
    return load_yaml(plugin_path)

