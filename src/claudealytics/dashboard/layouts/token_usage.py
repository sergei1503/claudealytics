"""Token Usage tab: daily input/output by model, per-session view, messages vs tokens, cache efficiency."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from claudealytics.analytics.aggregators.token_aggregator import (
    daily_activity_df,
    daily_tokens_by_model_detailed,
)
from claudealytics.models.schemas import StatsCache

# Consistent color palette for models
MODEL_COLORS = {
    "Opus 4.6": "#8b5cf6",
    "Opus 4.5": "#a78bfa",
    "Opus 4.1": "#c4b5fd",
    "Sonnet 4.5": "#6366f1",
    "Sonnet 4.1": "#818cf8",
    "Haiku 3.5": "#14b8a6",
    "Haiku 4.5": "#2dd4bf",
}

# Fallback colors for models not in the map
_FALLBACK_COLORS = ["#f59e0b", "#ef4444", "#ec4899", "#06b6d4", "#84cc16"]


def render(stats: StatsCache):
    """Render the token usage tab."""
    try:
        _render_inner(stats)
    except Exception as e:
        st.error(f"Error rendering Token Usage: {e}")
        st.exception(e)


def _render_inner(stats: StatsCache):
    """Inner render logic for the token usage tab."""
    tokens_df = daily_tokens_by_model_detailed(use_cache=True)

    if tokens_df.empty:
        st.warning("No token data available")
        return

    # Add short model names
    tokens_df = tokens_df.copy()
    tokens_df["model_short"] = tokens_df["model"].apply(_short_model_name)

    # --- Token Efficiency KPIs (before date filter, uses full data) ---
    activity = daily_activity_df(stats)
    _render_efficiency_section(tokens_df, activity)

    st.divider()

    # Date filter
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=tokens_df["date"].min())
    with col2:
        date_to = st.date_input("To", value=tokens_df["date"].max())

    mask = (tokens_df["date"] >= pd.to_datetime(date_from)) & (tokens_df["date"] <= pd.to_datetime(date_to))
    filtered = tokens_df[mask]

    if filtered.empty:
        st.warning("No data in the selected date range")
        return

    # 1. Daily Input Tokens by Model
    st.subheader("Daily Input Tokens by Model")
    _scatter_line_chart(filtered, y_col="input_tokens", y_label="Input Tokens")

    # 2. Daily Output Tokens by Model
    st.subheader("Daily Output Tokens by Model")
    _scatter_line_chart(filtered, y_col="output_tokens", y_label="Output Tokens")

    # 3. Daily Tokens per Session by Model
    st.subheader("Daily Tokens per Session by Model")
    if not activity.empty:
        # Merge with session counts to normalize
        daily_sessions = activity[["date", "sessions"]].copy()
        daily_sessions["date"] = pd.to_datetime(daily_sessions["date"])

        # Sum input+output per date per model, then divide by sessions
        merged = filtered.merge(daily_sessions, on="date", how="left")
        merged = merged[merged["sessions"] > 0]
        if not merged.empty:
            merged["tokens_per_session"] = (merged["input_tokens"] + merged["output_tokens"]) / merged["sessions"]
            _scatter_line_chart(merged, y_col="tokens_per_session", y_label="Tokens per Session")
        else:
            st.info("No session data available for normalization")
    else:
        st.info("No daily activity data for session normalization")

    # 4. Daily Tokens per Message by Model
    st.subheader("Daily Tokens per Message by Model")
    if not activity.empty:
        # Merge with message counts to normalize
        daily_messages = activity[["date", "messages"]].copy()
        daily_messages["date"] = pd.to_datetime(daily_messages["date"])

        # Sum input+output per date per model, then divide by messages
        merged = filtered.merge(daily_messages, on="date", how="left")
        merged = merged[merged["messages"] > 0]
        if not merged.empty:
            merged["tokens_per_message"] = (merged["input_tokens"] + merged["output_tokens"]) / merged["messages"]
            _scatter_line_chart(merged, y_col="tokens_per_message", y_label="Tokens per Message")
        else:
            st.info("No message data available for normalization")
    else:
        st.info("No daily activity data for message normalization")

    # 5. Messages vs Token Usage - Split into two separate charts
    if not activity.empty:
        # Add aggregation toggle
        aggregation = st.radio("Aggregation", ["Daily", "Weekly"], horizontal=True, key="msg_token_agg")

        # Aggregate tokens per day (all models)
        daily_totals = (
            filtered.groupby("date")
            .agg(input_tokens=("input_tokens", "sum"), output_tokens=("output_tokens", "sum"))
            .reset_index()
        )
        daily_totals["date"] = pd.to_datetime(daily_totals["date"])

        merged_msg = daily_totals.merge(activity[["date", "messages", "sessions"]], on="date", how="inner")

        if not merged_msg.empty:
            # Apply weekly aggregation if selected
            if aggregation == "Weekly":
                merged_msg = merged_msg.set_index("date").resample("W-Mon").sum().reset_index()
                merged_msg = merged_msg[merged_msg["messages"] > 0]  # Filter out empty weeks

            # Calculate days from start for color gradient
            merged_msg["days_from_start"] = (merged_msg["date"] - merged_msg["date"].min()).dt.days

            # Chart 1: Messages vs Input Tokens
            st.subheader("Messages vs Input Tokens")
            fig_input = go.Figure()

            fig_input.add_trace(
                go.Scatter(
                    x=merged_msg["messages"],
                    y=merged_msg["input_tokens"],
                    mode="markers",
                    name="Input Tokens",
                    marker=dict(
                        size=merged_msg["sessions"].clip(lower=1, upper=15) * 3,
                        sizemin=4,
                        color=merged_msg["days_from_start"],
                        colorscale="Viridis",
                        showscale=True,
                        colorbar=dict(
                            title=dict(text="Days from Start", font=dict(size=14)),
                            x=1.1,
                            len=0.6,
                            y=0.5,
                        ),
                        opacity=0.7,
                    ),
                    text=merged_msg["date"].dt.strftime("%Y-%m-%d"),
                    hovertemplate="Date: %{text}<br>Messages: %{x}<br>Input Tokens: %{y:,}<extra></extra>",
                )
            )

            fig_input.update_layout(
                height=400,
                margin=dict(l=20, r=20, t=80, b=0),
                xaxis_title="Messages",
                yaxis_title="Input Tokens",
            )
            st.plotly_chart(fig_input, use_container_width=True)
            st.caption(
                "Bubble size reflects session count. Color indicates time progression (lighter/brighter = more recent)."
            )

            # Chart 2: Messages vs Output Tokens
            st.subheader("Messages vs Output Tokens")
            fig_output = go.Figure()

            fig_output.add_trace(
                go.Scatter(
                    x=merged_msg["messages"],
                    y=merged_msg["output_tokens"],
                    mode="markers",
                    name="Output Tokens",
                    marker=dict(
                        size=merged_msg["sessions"].clip(lower=1, upper=15) * 3,
                        sizemin=4,
                        color=merged_msg["days_from_start"],
                        colorscale="Viridis",
                        showscale=True,
                        colorbar=dict(
                            title=dict(text="Days from Start", font=dict(size=14)),
                            x=1.1,
                            len=0.6,
                            y=0.5,
                        ),
                        opacity=0.7,
                    ),
                    text=merged_msg["date"].dt.strftime("%Y-%m-%d"),
                    hovertemplate="Date: %{text}<br>Messages: %{x}<br>Output Tokens: %{y:,}<extra></extra>",
                )
            )

            fig_output.update_layout(
                height=400,
                margin=dict(l=20, r=20, t=80, b=0),
                xaxis_title="Messages",
                yaxis_title="Output Tokens",
            )
            st.plotly_chart(fig_output, use_container_width=True)
            st.caption(
                "Bubble size reflects session count. Color indicates time progression (lighter/brighter = more recent)."
            )

    # 6. Cache Efficiency (kept as-is)
    st.subheader("Cache Efficiency")
    if stats.modelUsage:
        cache_data = []
        for model, usage in stats.modelUsage.items():
            total_input = usage.inputTokens + usage.cacheReadInputTokens + usage.cacheCreationInputTokens
            if total_input > 0:
                cache_hit_rate = usage.cacheReadInputTokens / total_input * 100
                cache_data.append(
                    {
                        "model": _short_model_name(model),
                        "cache_hit_rate": round(cache_hit_rate, 1),
                        "cache_read": usage.cacheReadInputTokens,
                        "cache_creation": usage.cacheCreationInputTokens,
                        "direct_input": usage.inputTokens,
                    }
                )

        if cache_data:
            import plotly.express as px

            cache_df = pd.DataFrame(cache_data)
            fig = px.bar(
                cache_df,
                x="model",
                y="cache_hit_rate",
                labels={"model": "Model", "cache_hit_rate": "Cache Hit Rate (%)"},
                color_discrete_sequence=["#14b8a6"],
                text="cache_hit_rate",
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "For per-session cache analysis, cost savings, and cache-breaking detection, see the **Cache Analysis** tab."
            )


def _render_efficiency_section(tokens_df: pd.DataFrame, activity: pd.DataFrame):
    """Render Token Efficiency KPI row and daily ratio chart."""
    st.subheader("Token Efficiency")

    total_input = tokens_df["input_tokens"].sum()
    total_output = tokens_df["output_tokens"].sum()
    overall_ratio = total_output / total_input if total_input > 0 else 0

    # Compute per-message and per-session averages
    avg_per_message = None
    avg_per_session = None
    if not activity.empty:
        total_messages = activity["messages"].sum()
        total_sessions = activity["sessions"].sum()
        total_tokens = total_input + total_output
        if total_messages > 0:
            avg_per_message = total_tokens / total_messages
        if total_sessions > 0:
            avg_per_session = total_tokens / total_sessions

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Output / Input Ratio", f"{overall_ratio:.3f}")
    with col2:
        st.metric(
            "Avg Tokens / Message",
            f"{avg_per_message:,.0f}" if avg_per_message else "N/A",
        )
    with col3:
        st.metric(
            "Avg Tokens / Session",
            f"{avg_per_session:,.0f}" if avg_per_session else "N/A",
        )

    # Daily efficiency ratio chart
    eff = tokens_df.copy()
    eff["efficiency_ratio"] = eff["output_tokens"] / eff["input_tokens"].replace(0, float("nan"))
    eff = eff.dropna(subset=["efficiency_ratio"])

    if not eff.empty:
        _scatter_line_chart(eff, y_col="efficiency_ratio", y_label="Output / Input Ratio", agg_func="mean")


def _scatter_line_chart(df: pd.DataFrame, y_col: str, y_label: str, agg_func: str = "sum"):
    """Create a scatter+line chart with one trace per model, consistent colors."""
    fig = go.Figure()

    models = sorted(df["model_short"].unique())
    color_map = _build_color_map(models)

    for model in models:
        model_data = df[df["model_short"] == model].sort_values("date")
        # Aggregate in case there are multiple entries per date per model
        agg = model_data.groupby("date")[y_col].agg(agg_func).reset_index()

        fig.add_trace(
            go.Scatter(
                x=agg["date"],
                y=agg[y_col],
                mode="lines+markers",
                name=model,
                line=dict(color=color_map[model]),
                marker=dict(size=5, color=color_map[model]),
                hovertemplate=f"{model}<br>Date: %{{x|%Y-%m-%d}}<br>{y_label}: %{{y:,}}<extra></extra>",
            )
        )

    fig.update_layout(
        height=400,
        margin=dict(l=20, r=20, t=100, b=0),
        xaxis_title="Date",
        yaxis_title=y_label,
        legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def _build_color_map(models: list[str]) -> dict[str, str]:
    """Build a color mapping for model names."""
    color_map = {}
    fallback_idx = 0
    for model in models:
        if model in MODEL_COLORS:
            color_map[model] = MODEL_COLORS[model]
        else:
            color_map[model] = _FALLBACK_COLORS[fallback_idx % len(_FALLBACK_COLORS)]
            fallback_idx += 1
    return color_map


def _short_model_name(model: str) -> str:
    """Shorten model names for chart readability."""
    if "opus-4-6" in model:
        return "Opus 4.6"
    if "opus-4-5" in model:
        return "Opus 4.5"
    if "opus-4-1" in model:
        return "Opus 4.1"
    if "sonnet-4-5" in model:
        return "Sonnet 4.5"
    if "sonnet-4-1" in model:
        return "Sonnet 4.1"
    if "haiku-4-5" in model:
        return "Haiku 4.5"
    if "haiku-3-5" in model or "haiku" in model:
        return "Haiku 3.5"
    return model
