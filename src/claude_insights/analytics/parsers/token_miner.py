"""
Mine per-message token usage data from conversation JSONL files.

Scans ALL JSONL files (including agent-*.jsonl in subdirectories) under
~/.claude/projects/ to extract input/output token counts per model per day.
This captures haiku usage from subagent files that stats-cache.json misses.

Uses file-level caching with 1-hour TTL to avoid re-parsing on repeated runs.
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


class TokenMiner:
    """Mines per-message token data from conversation JSONL files."""

    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, cache_dir: Optional[Path] = None):
        self.projects_dir = Path.home() / ".claude" / "projects"
        self.cache_dir = cache_dir or Path.home() / ".cache" / "claude-insights"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "token-mine.json"

    def _get_all_jsonl_files(self) -> List[Path]:
        """Get ALL JSONL files recursively, including agent-*.jsonl in subdirs."""
        if not self.projects_dir.exists():
            return []

        files = []
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                files.extend(project_dir.rglob("*.jsonl"))

        return sorted(files, key=lambda f: f.stat().st_mtime)

    def _load_cache(self) -> Optional[Dict]:
        """Load cached results if fresh enough."""
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path) as f:
                cached = json.load(f)
            if cached.get("timestamp", 0) > datetime.now().timestamp() - self.CACHE_TTL_SECONDS:
                return cached.get("data")
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _save_cache(self, data: Dict):
        """Save results to cache."""
        cache_data = {
            "timestamp": datetime.now().timestamp(),
            "data": data,
        }
        with open(self.cache_path, "w") as f:
            json.dump(cache_data, f)

    def mine_daily_tokens(self, use_cache: bool = True) -> pd.DataFrame:
        """Mine daily token usage by model from all JSONL files.

        Returns DataFrame with columns: date, model, input_tokens, output_tokens
        """
        if use_cache:
            cached = self._load_cache()
            if cached:
                rows = cached.get("rows", [])
                if rows:
                    df = pd.DataFrame(rows)
                    df["date"] = pd.to_datetime(df["date"])
                    return df.sort_values("date")
                return pd.DataFrame(columns=["date", "model", "input_tokens", "output_tokens"])

        # Aggregate: (date, model) -> {input_tokens, output_tokens}
        agg: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0}
        )

        for file_path in self._get_all_jsonl_files():
            try:
                with open(file_path) as f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            data = json.loads(line)
                            msg = data.get("message", {})
                            if not isinstance(msg, dict):
                                continue

                            model = msg.get("model")
                            usage = msg.get("usage")
                            if not model or not usage:
                                continue

                            timestamp_str = data.get("timestamp", "")
                            if not timestamp_str:
                                continue

                            date_str = timestamp_str[:10]  # YYYY-MM-DD

                            input_t = usage.get("input_tokens", 0) or 0
                            output_t = usage.get("output_tokens", 0) or 0

                            if input_t > 0 or output_t > 0:
                                key = (date_str, model)
                                agg[key]["input_tokens"] += input_t
                                agg[key]["output_tokens"] += output_t

                        except (json.JSONDecodeError, ValueError):
                            continue
            except (IOError, OSError):
                continue

        rows = [
            {
                "date": date_str,
                "model": model,
                "input_tokens": vals["input_tokens"],
                "output_tokens": vals["output_tokens"],
            }
            for (date_str, model), vals in agg.items()
        ]

        if use_cache:
            self._save_cache({"rows": rows})

        if not rows:
            return pd.DataFrame(columns=["date", "model", "input_tokens", "output_tokens"])

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date")

    def clear_cache(self):
        """Clear the token mine cache."""
        if self.cache_path.exists():
            self.cache_path.unlink()


# Convenience function
def mine_daily_tokens(use_cache: bool = True) -> pd.DataFrame:
    """Mine daily token usage by model from all conversation JSONL files."""
    miner = TokenMiner()
    return miner.mine_daily_tokens(use_cache=use_cache)
