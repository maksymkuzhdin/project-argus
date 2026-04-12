"""Helpers for loading Layer 1 scoring thresholds from YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


SCORING_CONFIG_ENV_VAR = "ARGUS_SCORING_CONFIG_PATH"
DEFAULT_SCORING_CONFIG_PATH = Path(__file__).with_name("config.yml")


def load_scoring_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the scoring configuration from YAML."""
    resolved_path = Path(
        config_path
        or os.getenv(SCORING_CONFIG_ENV_VAR)
        or DEFAULT_SCORING_CONFIG_PATH
    )
    if not resolved_path.exists():
        return {}

    loaded = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def config_value(config: dict[str, Any], *path: str, default: Any) -> Any:
    """Traverse a nested dict config using a dotted path."""
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node
