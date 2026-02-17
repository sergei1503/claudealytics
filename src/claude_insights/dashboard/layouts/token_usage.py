"""Token Usage tab: daily trends by model, token type breakdown, cache efficiency."""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from claude_insights.models.schemas import StatsCache
from claude_insights.analytics.aggregators.token_aggregator import (
    daily_tokens_by_model,
    model_usage_summary,
)


def render(stats: StatsCache):
    """Render the token usage tab."""
    # Date filter
    col1, col2 = st.columns(2)
    dates = [e.date for e in stats.dailyModelTokens]
    if dates:
        with col1:
            date_from = st.date_input("From", value=pd.to_datetime(min(dates)))
        with col2:
            date_to = st.date_input("To", value=pd.to_datetime(max(dates)))
    else:
        st.warning("No token data available")
        return

    # Daily tokens by model (stacked area)
    st.subheader("Daily Token Usage by Model")
    tokens_df = daily_tokens_by_model(stats)
    if not tokens_df.empty:
        mask = (tokens_df["date"] >= pd.to_datetime(date_from)) & (tokens_df["date"] <= pd.to_datetime(date_to))
        filtered = tokens_df[mask]

        if not filtered.empty:
            # Shorten model names for readability
            filtered = filtered.copy()
            filtered["model_short"] = filtered["model"].apply(_short_model_name)

            fig = px.area(
                filtered,
                x="date", y="tokens", color="model_short",
                labels={"date": "Date", "tokens": "Tokens", "model_short": "Model"},
            )
            fig.update_layout(
                height=400,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

    # Model usage breakdown
    st.subheader("Token Type Breakdown by Model")
    usage_df = model_usage_summary(stats)
    if not usage_df.empty:
        usage_df = usage_df.copy()
        usage_df["model_short"] = usage_df["model"].apply(_short_model_name)

        # Melt for stacked bar
        melt_df = usage_df.melt(
            id_vars=["model_short"],
            value_vars=["input_tokens", "output_tokens"],
            var_name="token_type",
            value_name="tokens",
        )
        fig = px.bar(
            melt_df,
            x="model_short", y="tokens", color="token_type",
            barmode="group",
            labels={"model_short": "Model", "tokens": "Tokens", "token_type": "Type"},
            color_discrete_map={"input_tokens": "#6366f1", "output_tokens": "#ec4899"},
        )
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Cache efficiency
    st.subheader("Cache Efficiency")
    if stats.modelUsage:
        cache_data = []
        for model, usage in stats.modelUsage.items():
            total_input = usage.inputTokens + usage.cacheReadInputTokens + usage.cacheCreationInputTokens
            if total_input > 0:
                cache_hit_rate = usage.cacheReadInputTokens / total_input * 100
                cache_data.append({
                    "model": _short_model_name(model),
                    "cache_hit_rate": round(cache_hit_rate, 1),
                    "cache_read": usage.cacheReadInputTokens,
                    "cache_creation": usage.cacheCreationInputTokens,
                    "direct_input": usage.inputTokens,
                })

        if cache_data:
            cache_df = pd.DataFrame(cache_data)
            fig = px.bar(
                cache_df,
                x="model", y="cache_hit_rate",
                labels={"model": "Model", "cache_hit_rate": "Cache Hit Rate (%)"},
                color_discrete_sequence=["#14b8a6"],
                text="cache_hit_rate",
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)


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
    if "haiku" in model:
        return "Haiku 3.5"
    return model
