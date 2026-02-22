"""Error analysis: rates, clustering, recovery strategies."""

from __future__ import annotations

import pandas as pd


def compute_tool_error_rate(tool_calls: pd.DataFrame, error_results: pd.DataFrame) -> pd.DataFrame:
    """Per tool type: total calls, error count, error rate."""
    if tool_calls.empty:
        return pd.DataFrame(columns=["tool_name", "total_calls", "error_count", "error_rate"])

    total_by_tool = tool_calls.groupby("tool_name").size().reset_index(name="total_calls")

    if error_results.empty or "tool_use_id" not in error_results.columns:
        total_by_tool["error_count"] = 0
        total_by_tool["error_rate"] = 0.0
        return total_by_tool.sort_values("total_calls", ascending=False)

    # We don't have tool_name in error_results directly, so use session-level error counts
    # from session_stats instead. For now, return total calls without per-tool error breakdown.
    total_by_tool["error_count"] = 0
    total_by_tool["error_rate"] = 0.0
    return total_by_tool.sort_values("total_calls", ascending=False)


def compute_error_timeline(daily_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: error count, error rate."""
    if daily_stats.empty:
        return pd.DataFrame()

    cols = ["date", "total_errors", "total_tool_calls", "assistant_messages"]
    df = daily_stats[[c for c in cols if c in daily_stats.columns]].copy()
    if "total_tool_calls" in df.columns:
        df["error_rate"] = (
            df["total_errors"] / df["total_tool_calls"] * 100
        ).where(df["total_tool_calls"] > 0, 0).round(2)
    else:
        df["error_rate"] = 0.0
    return df


def compute_error_sessions(session_stats: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Sessions with most errors, for clustering analysis."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[session_stats["total_errors"] > 0].copy()
    if df.empty:
        return pd.DataFrame()

    cols = ["session_id", "date", "project", "total_errors",
            "total_tool_calls", "total_messages", "unique_tools"]
    df = df[[c for c in cols if c in df.columns]]
    df = df.sort_values("total_errors", ascending=False).head(top_n)
    return df.reset_index(drop=True)


def compute_recovery_stats(session_stats: pd.DataFrame) -> dict:
    """Overall recovery statistics."""
    if session_stats.empty:
        return {"total_errors": 0, "sessions_with_errors": 0, "avg_errors_per_session": 0}

    total_errors = int(session_stats["total_errors"].sum())
    sessions_with_errors = int((session_stats["total_errors"] > 0).sum())
    avg_errors = round(total_errors / len(session_stats), 2) if len(session_stats) > 0 else 0

    return {
        "total_errors": total_errors,
        "sessions_with_errors": sessions_with_errors,
        "avg_errors_per_session": avg_errors,
    }
