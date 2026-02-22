"""Assistant behavior characteristics: thinking, decisions, output profiles."""

from __future__ import annotations

import pandas as pd


def compute_thinking_trends(daily_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: thinking block count, avg length, % of messages with thinking."""
    if daily_stats.empty:
        return pd.DataFrame()

    df = daily_stats[["date", "thinking_blocks", "total_thinking_length",
                       "assistant_messages"]].copy()
    df["avg_thinking_length"] = (
        df["total_thinking_length"] / df["thinking_blocks"]
    ).where(df["thinking_blocks"] > 0, 0).round(0)
    df["thinking_pct"] = (
        df["thinking_blocks"] / df["assistant_messages"] * 100
    ).where(df["assistant_messages"] > 0, 0).round(1)
    return df


def compute_output_profile(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: output characteristics."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[["session_id", "date", "project",
                         "assistant_msg_count", "total_text_length_assistant",
                         "total_thinking_length", "thinking_message_count",
                         "has_code_blocks",
                         "decision_count", "self_correction_count",
                         "reasoning_marker_count"]].copy()
    am = df["assistant_msg_count"]
    df["avg_output_length"] = (df["total_text_length_assistant"] / am).where(am > 0, 0).round(0)
    df["thinking_ratio"] = (
        df["total_thinking_length"] /
        (df["total_text_length_assistant"] + df["total_thinking_length"])
    ).where((df["total_text_length_assistant"] + df["total_thinking_length"]) > 0, 0).round(3)
    df["code_block_pct"] = (df["has_code_blocks"] / am * 100).where(am > 0, 0).round(1)
    return df


def compute_decision_trends(daily_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: decision language pattern counts."""
    if daily_stats.empty:
        return pd.DataFrame()

    cols = ["date", "decision_count", "self_correction_count", "reasoning_marker_count"]
    return daily_stats[[c for c in cols if c in daily_stats.columns]].copy()
