"""Cache analysis functions for per-message and per-session cache data.

Pure analysis functions (no I/O). Takes DataFrames from TokenMiner and
CacheSessionMiner and computes cache efficiency metrics, cost savings,
and identifies cache-breaking sessions.
"""

from __future__ import annotations

import pandas as pd

from claudealytics.analytics.cost_calculator import DEFAULT_PRICING, MODEL_PRICING


def _get_input_price(model: str) -> float:
    """Get input token price per million for a model."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)["input"]


def compute_daily_cache_metrics(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Compute daily cache hit rate, reuse multiplier, and TTL breakdown.

    Input: DataFrame from mine_daily_tokens (with cache columns).
    Returns: DataFrame with date, cache_hit_rate, cache_reuse_multiplier,
             ephemeral_1h_pct, ephemeral_5m_pct, total columns.
    """
    if daily_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "cache_hit_rate",
                "cache_reuse_multiplier",
                "ephemeral_1h_tokens",
                "ephemeral_5m_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
                "input_tokens",
            ]
        )

    grouped = (
        daily_df.groupby("date")
        .agg(
            input_tokens=("input_tokens", "sum"),
            cache_read_input_tokens=("cache_read_input_tokens", "sum"),
            cache_creation_input_tokens=("cache_creation_input_tokens", "sum"),
            ephemeral_1h_tokens=("ephemeral_1h_input_tokens", "sum"),
            ephemeral_5m_tokens=("ephemeral_5m_input_tokens", "sum"),
        )
        .reset_index()
    )

    total_input = grouped["input_tokens"] + grouped["cache_read_input_tokens"] + grouped["cache_creation_input_tokens"]
    grouped["cache_hit_rate"] = (
        (grouped["cache_read_input_tokens"] / total_input.replace(0, float("nan")) * 100).fillna(0).round(2)
    )

    grouped["cache_reuse_multiplier"] = (
        (grouped["cache_read_input_tokens"] / grouped["cache_creation_input_tokens"].replace(0, float("nan")))
        .fillna(0)
        .round(2)
    )

    return grouped.sort_values("date")


def compute_cost_savings(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-day actual cost vs hypothetical no-cache cost.

    Cache read = 10% of input price, cache creation = 125% of input price.
    Without cache, all tokens would be charged at full input price.

    Returns: DataFrame with date, actual_cost, no_cache_cost, savings_usd, savings_pct
    """
    if daily_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "actual_cost",
                "no_cache_cost",
                "savings_usd",
                "savings_pct",
            ]
        )

    rows = []
    for date_val, group in daily_df.groupby("date"):
        actual_cost = 0.0
        no_cache_cost = 0.0

        for _, row in group.iterrows():
            price = _get_input_price(row["model"])
            per_m = price / 1_000_000

            # Actual cost: direct input at full price, cache read at 10%, cache create at 125%
            actual_cost += row["input_tokens"] * per_m
            actual_cost += row["cache_read_input_tokens"] * per_m * 0.1
            actual_cost += row["cache_creation_input_tokens"] * per_m * 1.25
            # Output tokens (not affected by cache, same in both scenarios)
            out_price = MODEL_PRICING.get(row["model"], DEFAULT_PRICING)["output"] / 1_000_000
            actual_cost += row["output_tokens"] * out_price

            # Hypothetical: all cache tokens charged at full input price
            total_input = row["input_tokens"] + row["cache_read_input_tokens"] + row["cache_creation_input_tokens"]
            no_cache_cost += total_input * per_m
            no_cache_cost += row["output_tokens"] * out_price

        savings = no_cache_cost - actual_cost
        savings_pct = (savings / no_cache_cost * 100) if no_cache_cost > 0 else 0.0

        rows.append(
            {
                "date": date_val,
                "actual_cost": round(actual_cost, 4),
                "no_cache_cost": round(no_cache_cost, 4),
                "savings_usd": round(savings, 4),
                "savings_pct": round(savings_pct, 1),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "actual_cost",
                "no_cache_cost",
                "savings_usd",
                "savings_pct",
            ]
        )

    return pd.DataFrame(rows).sort_values("date")


def compute_session_cache_metrics(session_df: pd.DataFrame) -> pd.DataFrame:
    """Add derived metrics to session cache DataFrame.

    Adds: total_input_tokens, cache_paid_off (bool)
    """
    if session_df.empty:
        return session_df

    df = session_df.copy()
    df["total_input_tokens"] = df["input_tokens"] + df["cache_read_input_tokens"] + df["cache_creation_input_tokens"]
    # Cache paid off when reuse multiplier > 1.25 (read savings exceed creation premium)
    df["cache_paid_off"] = df["cache_reuse_multiplier"] > 1.25
    return df


def detect_cache_breaking_sessions(session_df: pd.DataFrame, min_messages: int = 3) -> pd.DataFrame:
    """Identify sessions with poor cache efficiency and explain why.

    Filters sessions with enough messages to expect caching, then flags
    those with low hit rates or unrecovered creation costs.

    Returns: DataFrame sorted by cache_hit_rate ascending (worst first),
             with added 'reasons' column.
    """
    if session_df.empty:
        return pd.DataFrame()

    # Only consider sessions with enough messages to expect cache reuse
    df = session_df[session_df["message_count"] >= min_messages].copy()
    if df.empty:
        return pd.DataFrame()

    # Flag sessions with poor caching
    reasons_list = []
    is_poor = []

    for _, row in df.iterrows():
        reasons = []
        poor = False

        if row["had_model_switch"]:
            reasons.append(f"Model switch ({row['model_count']} models)")
            poor = True

        if row["cache_hit_rate"] < 50:
            reasons.append(f"Low hit rate ({row['cache_hit_rate']:.0f}%)")
            poor = True

        if row["cache_reuse_multiplier"] < 1.25 and row["cache_creation_input_tokens"] > 0:
            reasons.append(f"Cache didn't pay off (multiplier {row['cache_reuse_multiplier']:.1f}x)")
            poor = True

        reasons_list.append("; ".join(reasons) if reasons else "")
        is_poor.append(poor)

    df["reasons"] = reasons_list
    df = df[is_poor]

    if df.empty:
        return pd.DataFrame()

    return df.sort_values("cache_hit_rate").reset_index(drop=True)


def project_cache_summary(session_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cache metrics per project.

    Returns: DataFrame with project, session_count, avg_hit_rate,
             avg_reuse_multiplier, model_switch_pct
    """
    if session_df.empty:
        return pd.DataFrame(
            columns=[
                "project",
                "session_count",
                "avg_hit_rate",
                "avg_reuse_multiplier",
                "model_switch_pct",
            ]
        )

    grouped = (
        session_df.groupby("project")
        .agg(
            session_count=("session_id", "count"),
            avg_hit_rate=("cache_hit_rate", "mean"),
            avg_reuse_multiplier=("cache_reuse_multiplier", "mean"),
            model_switch_count=("had_model_switch", "sum"),
        )
        .reset_index()
    )

    grouped["model_switch_pct"] = (grouped["model_switch_count"] / grouped["session_count"] * 100).round(1)
    grouped["avg_hit_rate"] = grouped["avg_hit_rate"].round(1)
    grouped["avg_reuse_multiplier"] = grouped["avg_reuse_multiplier"].round(2)

    return grouped.drop(columns=["model_switch_count"]).sort_values("avg_hit_rate", ascending=False)
