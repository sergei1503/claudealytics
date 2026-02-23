"""Conversation flow analysis: complexity scoring, sidechains, working directories."""

from __future__ import annotations

import pandas as pd


def compute_complexity(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: composite complexity score normalized 0-1."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[
        [
            "session_id",
            "date",
            "project",
            "total_messages",
            "total_tool_calls",
            "total_errors",
            "unique_files_touched",
            "total_input_tokens",
            "total_output_tokens",
            "sidechain_count",
            "cwd_switch_count",
        ]
    ].copy()

    # Normalize each component 0-1 using min-max
    components = ["total_messages", "total_tool_calls", "total_errors", "unique_files_touched", "sidechain_count"]
    for col in components:
        col_min = df[col].min()
        col_max = df[col].max()
        col_range = col_max - col_min
        if col_range > 0:
            df[f"{col}_norm"] = (df[col] - col_min) / col_range
        else:
            df[f"{col}_norm"] = 0.0

    # Composite: weighted average
    weights = {
        "total_messages_norm": 0.2,
        "total_tool_calls_norm": 0.3,
        "total_errors_norm": 0.15,
        "unique_files_touched_norm": 0.2,
        "sidechain_count_norm": 0.15,
    }
    df["complexity_score"] = sum(df[col] * w for col, w in weights.items())
    df["complexity_score"] = df["complexity_score"].round(3)

    # Drop intermediate norm columns
    df = df.drop(columns=[c for c in df.columns if c.endswith("_norm")])
    return df


def compute_sidechain_daily(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: sidechain message count and percentage."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[["date", "sidechain_count", "total_messages"]].copy()
    daily = df.groupby("date").sum().reset_index()
    daily["sidechain_pct"] = (
        (daily["sidechain_count"] / daily["total_messages"] * 100).where(daily["total_messages"] > 0, 0).round(1)
    )
    return daily


def compute_cwd_switches(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: working directory switch count."""
    if session_stats.empty:
        return pd.DataFrame()

    return session_stats[["session_id", "date", "project", "cwd_switch_count", "total_messages"]].copy()
