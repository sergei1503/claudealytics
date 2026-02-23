"""Parse the Claude Code stats-cache.json file."""

from __future__ import annotations

import json
from pathlib import Path

from claudealytics.models.schemas import StatsCache

DEFAULT_STATS_PATH = Path.home() / ".claude" / "stats-cache.json"


def parse_stats_cache(path: Path = DEFAULT_STATS_PATH) -> StatsCache:
    """Load and validate stats-cache.json into a Pydantic model."""
    if not path.exists():
        raise FileNotFoundError(f"Stats cache not found: {path}")

    with open(path) as f:
        raw = json.load(f)

    return StatsCache.model_validate(raw)
