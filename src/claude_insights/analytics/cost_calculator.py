"""Estimate costs based on Anthropic model pricing.

Pricing as of early 2026. Updates may be needed as prices change.
Cache read tokens are priced at 10% of input, cache creation at 125% of input.
"""

from __future__ import annotations

import pandas as pd

from claude_insights.models.schemas import StatsCache

# Per million tokens (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-5-20251101": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-1-20250805": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-1-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.0},
}

# Fallback pricing for unknown models
DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


def _get_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model, with fallback."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)


def estimate_model_costs(stats: StatsCache) -> pd.DataFrame:
    """Calculate estimated cost per model from stats cache.

    Returns DataFrame with: model, input_cost, output_cost,
    cache_read_cost, cache_creation_cost, total_cost
    """
    rows = []
    for model, usage in stats.modelUsage.items():
        pricing = _get_pricing(model)
        input_cost = (usage.inputTokens / 1_000_000) * pricing["input"]
        output_cost = (usage.outputTokens / 1_000_000) * pricing["output"]
        cache_read_cost = (usage.cacheReadInputTokens / 1_000_000) * pricing["input"] * 0.1
        cache_creation_cost = (usage.cacheCreationInputTokens / 1_000_000) * pricing["input"] * 1.25

        rows.append({
            "model": model,
            "input_cost": round(input_cost, 2),
            "output_cost": round(output_cost, 2),
            "cache_read_cost": round(cache_read_cost, 2),
            "cache_creation_cost": round(cache_creation_cost, 2),
            "total_cost": round(input_cost + output_cost + cache_read_cost + cache_creation_cost, 2),
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("total_cost", ascending=False)


def daily_cost_estimate(stats: StatsCache) -> pd.DataFrame:
    """Estimate daily cost from dailyModelTokens.

    Approximation: assumes all tokens are output tokens for a rough upper bound,
    then divides by 2 to approximate a 50/50 input/output split.
    In practice, we only have total tokens per model per day, not in/out split.
    """
    rows = []
    for entry in stats.dailyModelTokens:
        daily_cost = 0.0
        for model, tokens in entry.tokensByModel.items():
            pricing = _get_pricing(model)
            # Use average of input and output price as approximation
            avg_price = (pricing["input"] + pricing["output"]) / 2
            daily_cost += (tokens / 1_000_000) * avg_price
        rows.append({"date": entry.date, "estimated_cost": round(daily_cost, 2)})

    if not rows:
        return pd.DataFrame(columns=["date", "estimated_cost"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["cumulative_cost"] = df["estimated_cost"].cumsum()
    return df.sort_values("date")


def total_estimated_cost(stats: StatsCache) -> float:
    """Get total estimated cost across all models."""
    costs_df = estimate_model_costs(stats)
    if costs_df.empty:
        return 0.0
    return costs_df["total_cost"].sum()
