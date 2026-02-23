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
        self.cache_dir = cache_dir or Path.home() / ".cache" / "claudealytics"
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
                return pd.DataFrame(columns=["date", "model", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"])

        # Aggregate: (date, model) -> token counts
        agg: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
            lambda: {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "ephemeral_1h_input_tokens": 0,
                "ephemeral_5m_input_tokens": 0,
            }
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
                            cache_read_t = usage.get("cache_read_input_tokens", 0) or 0
                            cache_create_t = usage.get("cache_creation_input_tokens", 0) or 0

                            cache_creation = usage.get("cache_creation", {})
                            if isinstance(cache_creation, dict):
                                eph_1h = cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
                                eph_5m = cache_creation.get("ephemeral_5m_input_tokens", 0) or 0
                            else:
                                eph_1h = 0
                                eph_5m = 0

                            if input_t > 0 or output_t > 0 or cache_read_t > 0 or cache_create_t > 0:
                                key = (date_str, model)
                                agg[key]["input_tokens"] += input_t
                                agg[key]["output_tokens"] += output_t
                                agg[key]["cache_read_input_tokens"] += cache_read_t
                                agg[key]["cache_creation_input_tokens"] += cache_create_t
                                agg[key]["ephemeral_1h_input_tokens"] += eph_1h
                                agg[key]["ephemeral_5m_input_tokens"] += eph_5m

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
                "cache_read_input_tokens": vals["cache_read_input_tokens"],
                "cache_creation_input_tokens": vals["cache_creation_input_tokens"],
                "ephemeral_1h_input_tokens": vals["ephemeral_1h_input_tokens"],
                "ephemeral_5m_input_tokens": vals["ephemeral_5m_input_tokens"],
            }
            for (date_str, model), vals in agg.items()
        ]

        if use_cache:
            self._save_cache({"rows": rows})

        if not rows:
            return pd.DataFrame(columns=["date", "model", "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"])

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date")

    def clear_cache(self):
        """Clear the token mine cache."""
        if self.cache_path.exists():
            self.cache_path.unlink()


class CacheSessionMiner:
    """Mines per-session cache statistics from conversation JSONL files."""

    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self, cache_dir: Optional[Path] = None):
        self.projects_dir = Path.home() / ".claude" / "projects"
        self.cache_dir = cache_dir or Path.home() / ".cache" / "claudealytics"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "cache-session-mine.json"

    def _get_all_jsonl_files(self) -> List[Path]:
        """Get ALL JSONL files recursively."""
        if not self.projects_dir.exists():
            return []
        files = []
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                files.extend(project_dir.rglob("*.jsonl"))
        return sorted(files, key=lambda f: f.stat().st_mtime)

    def _load_cache(self) -> Optional[Dict]:
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
        cache_data = {"timestamp": datetime.now().timestamp(), "data": data}
        with open(self.cache_path, "w") as f:
            json.dump(cache_data, f)

    def mine_session_cache(self, use_cache: bool = True) -> pd.DataFrame:
        """Mine per-session cache statistics from all JSONL files.

        Returns DataFrame with columns: session_id, date, project, model,
        input_tokens, output_tokens, cache_read_input_tokens,
        cache_creation_input_tokens, ephemeral_1h_input_tokens,
        ephemeral_5m_input_tokens, message_count, models_used, model_count,
        had_model_switch, cache_hit_rate, cache_reuse_multiplier
        """
        empty_cols = [
            "session_id", "date", "project", "model", "input_tokens",
            "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens", "ephemeral_1h_input_tokens",
            "ephemeral_5m_input_tokens", "message_count", "models_used",
            "model_count", "had_model_switch", "cache_hit_rate",
            "cache_reuse_multiplier",
        ]

        if use_cache:
            cached = self._load_cache()
            if cached:
                rows = cached.get("rows", [])
                if rows:
                    df = pd.DataFrame(rows)
                    df["date"] = pd.to_datetime(df["date"])
                    return df.sort_values("date")
                return pd.DataFrame(columns=empty_cols)

        # session_id -> aggregated data
        sessions: Dict[str, Dict] = defaultdict(lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "ephemeral_1h_input_tokens": 0,
            "ephemeral_5m_input_tokens": 0,
            "message_count": 0,
            "models": defaultdict(int),
            "date": None,
            "project": None,
        })

        for file_path in self._get_all_jsonl_files():
            # Derive project name from the parent directory name
            # ~/.claude/projects/<project-dir>/<session>.jsonl
            project_name = self._extract_project_name(file_path)

            try:
                with open(file_path) as f:
                    for line in f:
                        if '"usage"' not in line:
                            continue
                        try:
                            data = json.loads(line)
                            session_id = data.get("sessionId")
                            if not session_id:
                                continue

                            msg = data.get("message", {})
                            if not isinstance(msg, dict):
                                continue

                            model = msg.get("model")
                            usage = msg.get("usage")
                            if not model or not usage:
                                continue

                            # Filter out synthetic models
                            if model == "<synthetic>":
                                continue

                            timestamp_str = data.get("timestamp", "")
                            if not timestamp_str:
                                continue

                            s = sessions[session_id]
                            if s["date"] is None:
                                s["date"] = timestamp_str[:10]
                            if s["project"] is None:
                                s["project"] = project_name

                            s["input_tokens"] += usage.get("input_tokens", 0) or 0
                            s["output_tokens"] += usage.get("output_tokens", 0) or 0
                            s["cache_read_input_tokens"] += usage.get("cache_read_input_tokens", 0) or 0
                            s["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens", 0) or 0

                            cache_creation = usage.get("cache_creation", {})
                            if isinstance(cache_creation, dict):
                                s["ephemeral_1h_input_tokens"] += cache_creation.get("ephemeral_1h_input_tokens", 0) or 0
                                s["ephemeral_5m_input_tokens"] += cache_creation.get("ephemeral_5m_input_tokens", 0) or 0

                            s["message_count"] += 1
                            s["models"][model] += 1

                        except (json.JSONDecodeError, ValueError):
                            continue
            except (IOError, OSError):
                continue

        rows = []
        for session_id, s in sessions.items():
            if s["message_count"] == 0:
                continue

            models_used = dict(s["models"])
            model_count = len(models_used)
            # Primary model = most used
            primary_model = max(models_used, key=models_used.get) if models_used else ""

            total_cache_input = (
                s["input_tokens"] + s["cache_read_input_tokens"] + s["cache_creation_input_tokens"]
            )
            cache_hit_rate = (
                (s["cache_read_input_tokens"] / total_cache_input * 100)
                if total_cache_input > 0 else 0.0
            )
            # Reuse multiplier: how many times cache reads exceeded creation cost
            cache_reuse_multiplier = (
                (s["cache_read_input_tokens"] / s["cache_creation_input_tokens"])
                if s["cache_creation_input_tokens"] > 0 else 0.0
            )

            rows.append({
                "session_id": session_id,
                "date": s["date"],
                "project": s["project"],
                "model": primary_model,
                "input_tokens": s["input_tokens"],
                "output_tokens": s["output_tokens"],
                "cache_read_input_tokens": s["cache_read_input_tokens"],
                "cache_creation_input_tokens": s["cache_creation_input_tokens"],
                "ephemeral_1h_input_tokens": s["ephemeral_1h_input_tokens"],
                "ephemeral_5m_input_tokens": s["ephemeral_5m_input_tokens"],
                "message_count": s["message_count"],
                "models_used": str(models_used),
                "model_count": model_count,
                "had_model_switch": model_count > 1,
                "cache_hit_rate": round(cache_hit_rate, 2),
                "cache_reuse_multiplier": round(cache_reuse_multiplier, 2),
            })

        if use_cache:
            self._save_cache({"rows": rows})

        if not rows:
            return pd.DataFrame(columns=empty_cols)

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date")

    @staticmethod
    def _extract_project_name(file_path: Path) -> str:
        """Extract a readable project name from file path.

        Path pattern: ~/.claude/projects/<encoded-project-dir>/...
        The encoded dir uses dashes instead of path separators, e.g.
        -Users-name-repos-claudealytics -> returns 'claudealytics'.
        Filters common path prefixes like 'users', 'repos', 'projects'.
        """
        projects_dir = Path.home() / ".claude" / "projects"
        _SKIP_SEGMENTS = {"users", "home", "repos", "projects", "src", "root"}
        try:
            rel = file_path.relative_to(projects_dir)
            # First component is the project directory name
            project_dir = rel.parts[0] if rel.parts else "unknown"
            # The directory name is like -Users-name-repos-project
            # Extract last 2 meaningful segments
            parts = project_dir.strip("-").split("-")
            meaningful = [p for p in parts if p.lower() not in _SKIP_SEGMENTS and p]
            if len(meaningful) >= 2:
                return "-".join(meaningful[-2:])
            elif meaningful:
                return meaningful[-1]
        except ValueError:
            pass
        return "unknown"

    def clear_cache(self):
        if self.cache_path.exists():
            self.cache_path.unlink()


# Convenience functions
def mine_daily_tokens(use_cache: bool = True) -> pd.DataFrame:
    """Mine daily token usage by model from all conversation JSONL files."""
    miner = TokenMiner()
    return miner.mine_daily_tokens(use_cache=use_cache)


def mine_session_cache(use_cache: bool = True) -> pd.DataFrame:
    """Mine per-session cache statistics from all conversation JSONL files."""
    miner = CacheSessionMiner()
    return miner.mine_session_cache(use_cache=use_cache)
