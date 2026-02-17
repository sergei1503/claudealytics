"""Aggregate session data from conversation JSONL files."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from claude_insights.models.schemas import SessionInfo


def sessions_to_dataframe(sessions: list[SessionInfo]) -> pd.DataFrame:
    """Convert session list to a DataFrame for analysis."""
    if not sessions:
        return pd.DataFrame(
            columns=["date", "session_id", "project", "duration_minutes", "message_count", "hour"]
        )

    rows = []
    for s in sessions:
        hour = s.start_time.hour if s.start_time else 0
        rows.append({
            "date": s.date,
            "session_id": s.session_id,
            "project": s.project,
            "duration_minutes": s.duration_minutes,
            "message_count": s.message_count,
            "hour": hour,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def daily_session_stats(sessions_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sessions by day: count, avg duration, total duration."""
    if sessions_df.empty:
        return pd.DataFrame()

    grouped = sessions_df.groupby("date").agg(
        session_count=("session_id", "count"),
        avg_duration=("duration_minutes", "mean"),
        total_duration=("duration_minutes", "sum"),
        total_messages=("message_count", "sum"),
    ).reset_index()

    return grouped.sort_values("date")


def project_session_counts(sessions: list[SessionInfo]) -> dict[str, int]:
    """Count sessions per project."""
    counts: dict[str, int] = defaultdict(int)
    for s in sessions:
        counts[s.project] += 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
