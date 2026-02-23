"""Human intervention pattern analysis and autonomy metrics."""

from __future__ import annotations

import pandas as pd


def compute_autonomy(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: autonomy ratio, avg/max consecutive assistant turns."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[
        [
            "session_id",
            "date",
            "project",
            "human_msg_count",
            "assistant_msg_count",
            "total_tool_calls",
            "avg_autonomy_run_length",
            "max_autonomy_run_length",
        ]
    ].copy()
    total = df["human_msg_count"] + df["assistant_msg_count"]
    df["autonomy_ratio"] = (df["assistant_msg_count"] / total).where(total > 0, 0).round(3)
    return df


def compute_intervention_daily(daily_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: intervention counts by type + steering rate."""
    if daily_stats.empty:
        return pd.DataFrame()

    cols = [
        "date",
        "human_messages",
        "intervention_correction",
        "intervention_approval",
        "intervention_guidance",
        "intervention_new_instruction",
    ]
    df = daily_stats[[c for c in cols if c in daily_stats.columns]].copy()
    (
        df.get("intervention_correction", 0)
        + df.get("intervention_approval", 0)
        + df.get("intervention_guidance", 0)
        + df.get("intervention_new_instruction", 0)
    )
    corrections = df.get("intervention_correction", 0)
    df["steering_rate"] = (corrections / df["human_messages"]).where(df["human_messages"] > 0, 0).round(3)
    return df


def compute_human_chars(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: human message characteristics."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[
        [
            "session_id",
            "date",
            "project",
            "human_msg_count",
            "total_text_length_human",
            "human_questions_count",
            "human_with_code_count",
            "human_with_file_paths_count",
        ]
    ].copy()
    hm = df["human_msg_count"]
    df["avg_text_length"] = (df["total_text_length_human"] / hm).where(hm > 0, 0).round(0)
    df["pct_questions"] = (df["human_questions_count"] / hm * 100).where(hm > 0, 0).round(1)
    df["pct_with_code"] = (df["human_with_code_count"] / hm * 100).where(hm > 0, 0).round(1)
    df["pct_with_file_paths"] = (df["human_with_file_paths_count"] / hm * 100).where(hm > 0, 0).round(1)
    return df


def compute_human_length_dist(human_message_lengths: pd.DataFrame) -> pd.DataFrame:
    """All human messages: text_length + word_count for histogram."""
    if human_message_lengths.empty:
        return pd.DataFrame()
    return human_message_lengths[["text_length", "word_count", "classification"]].copy()
