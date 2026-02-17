"""Aggregate token usage data from stats cache."""

from __future__ import annotations

import pandas as pd

from claude_insights.models.schemas import StatsCache


def daily_tokens_by_model(stats: StatsCache) -> pd.DataFrame:
    """Build a DataFrame of daily token counts by model.

    Returns:
        DataFrame with columns: date, model, tokens
    """
    rows = []
    for entry in stats.dailyModelTokens:
        for model, tokens in entry.tokensByModel.items():
            rows.append({"date": entry.date, "model": model, "tokens": tokens})

    if not rows:
        return pd.DataFrame(columns=["date", "model", "tokens"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def model_usage_summary(stats: StatsCache) -> pd.DataFrame:
    """Summarize total token usage per model.

    Returns:
        DataFrame with columns: model, input_tokens, output_tokens,
        cache_read, cache_creation, total_tokens
    """
    rows = []
    for model, usage in stats.modelUsage.items():
        total = usage.inputTokens + usage.outputTokens
        rows.append({
            "model": model,
            "input_tokens": usage.inputTokens,
            "output_tokens": usage.outputTokens,
            "cache_read": usage.cacheReadInputTokens,
            "cache_creation": usage.cacheCreationInputTokens,
            "total_tokens": total,
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("total_tokens", ascending=False)


def daily_activity_df(stats: StatsCache) -> pd.DataFrame:
    """Convert daily activity to DataFrame."""
    rows = [
        {
            "date": a.date,
            "messages": a.messageCount,
            "sessions": a.sessionCount,
            "tool_calls": a.toolCallCount,
        }
        for a in stats.dailyActivity
    ]
    if not rows:
        return pd.DataFrame(columns=["date", "messages", "sessions", "tool_calls"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")
