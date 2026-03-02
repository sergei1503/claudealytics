"""Aggregate context overhead data from ContextMiner output."""

from __future__ import annotations

import pandas as pd

from claudealytics.analytics.parsers.token_miner import mine_context_overhead


def daily_baseline_overhead(use_cache: bool = True) -> pd.DataFrame:
    """Average baseline overhead per day.

    Returns DataFrame with columns: date, avg_baseline_overhead, session_count
    """
    df = mine_context_overhead(use_cache=use_cache)
    if df.empty:
        return pd.DataFrame(columns=["date", "avg_baseline_overhead", "session_count"])

    daily = (
        df.groupby(df["date"].dt.date)
        .agg(
            avg_baseline_overhead=("baseline_overhead_tokens", "mean"),
            session_count=("session_id", "count"),
        )
        .reset_index()
    )
    daily["date"] = pd.to_datetime(daily["date"])
    return daily.sort_values("date")


def session_context_stats(use_cache: bool = True) -> pd.DataFrame:
    """Full per-session context stats (excludes context_fill_series for table display).

    Returns DataFrame with columns: session_id, date, project,
    baseline_overhead_tokens, peak_context_tokens, compaction_count,
    agent_spawn_count, message_count, estimated_agent_overhead
    """
    df = mine_context_overhead(use_cache=use_cache)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "session_id",
                "date",
                "project",
                "baseline_overhead_tokens",
                "peak_context_tokens",
                "compaction_count",
                "agent_spawn_count",
                "message_count",
                "estimated_agent_overhead",
            ]
        )

    result = df.drop(columns=["context_fill_series"]).copy()
    result["estimated_agent_overhead"] = result["baseline_overhead_tokens"] * result["agent_spawn_count"]
    return result


def context_fill_curve(session_id: str, use_cache: bool = True) -> list[int]:
    """Return the fill series for a specific session."""
    df = mine_context_overhead(use_cache=use_cache)
    if df.empty:
        return []

    match = df[df["session_id"] == session_id]
    if match.empty:
        return []

    series = match.iloc[0]["context_fill_series"]
    return series if isinstance(series, list) else []
