"""Costs tab: daily cost stacked area, cumulative line, breakdown pie."""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from claudealytics.models.schemas import StatsCache
from claudealytics.analytics.cost_calculator import (
    estimate_model_costs,
    daily_cost_estimate,
    total_estimated_cost,
)


def render(stats: StatsCache):
    """Render the costs tab."""
    total_cost = total_estimated_cost(stats)
    model_costs = estimate_model_costs(stats)
    daily_costs = daily_cost_estimate(stats)

    # KPI row
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Estimated Cost", f"${total_cost:,.2f}")

    if not daily_costs.empty:
        avg_daily = daily_costs["estimated_cost"].mean()
        col2.metric("Avg Daily Cost", f"${avg_daily:,.2f}")
        max_day = daily_costs.loc[daily_costs["estimated_cost"].idxmax()]
        col3.metric("Peak Day Cost", f"${max_day['estimated_cost']:,.2f}",
                     help=f"On {max_day['date'].strftime('%Y-%m-%d')}")

    st.divider()

    # Date filter
    if not daily_costs.empty:
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From  ", value=daily_costs["date"].min(), key="cost_from")
        with col2:
            date_to = st.date_input("To  ", value=daily_costs["date"].max(), key="cost_to")

        mask = (daily_costs["date"] >= pd.to_datetime(date_from)) & (daily_costs["date"] <= pd.to_datetime(date_to))
        filtered_daily = daily_costs[mask]
    else:
        filtered_daily = pd.DataFrame()

    # Daily cost bar chart
    if not filtered_daily.empty:
        st.subheader("Daily Estimated Cost", help="Per-day API cost estimate based on token counts and public Anthropic pricing.")
        fig = px.bar(
            filtered_daily, x="date", y="estimated_cost",
            labels={"date": "Date", "estimated_cost": "Cost (USD)"},
            color_discrete_sequence=["#f59e0b"],
        )
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Cumulative cost line
    if not filtered_daily.empty:
        st.subheader("Cumulative Cost", help="Running total of estimated API costs over time.")
        # Recalculate cumulative for filtered range
        filtered_daily = filtered_daily.copy()
        filtered_daily["cumulative"] = filtered_daily["estimated_cost"].cumsum()
        fig = px.line(
            filtered_daily, x="date", y="cumulative",
            labels={"date": "Date", "cumulative": "Cumulative Cost (USD)"},
            color_discrete_sequence=["#ef4444"],
            markers=True,
        )
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Cost breakdown by model (pie chart)
    if not model_costs.empty:
        st.subheader("Cost Breakdown by Model", help="Total estimated cost split by model. Includes input, output, cache read, and cache creation token costs.")
        model_costs = model_costs.copy()
        model_costs["model_short"] = model_costs["model"].apply(_short_model_name)

        col_pie, col_table = st.columns([1, 1])

        with col_pie:
            fig = px.pie(
                model_costs, values="total_cost", names="model_short",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            st.dataframe(
                model_costs[["model_short", "input_cost", "output_cost", "cache_read_cost", "cache_creation_cost", "total_cost"]]
                .rename(columns={
                    "model_short": "Model",
                    "input_cost": "Input $",
                    "output_cost": "Output $",
                    "cache_read_cost": "Cache Read $",
                    "cache_creation_cost": "Cache Create $",
                    "total_cost": "Total $",
                }),
                hide_index=True,
                use_container_width=True,
            )

    st.caption("⚠️ Cost estimates based on public Anthropic API pricing. Actual costs via Claude Code subscription may differ.")


def _short_model_name(model: str) -> str:
    """Shorten model names for display."""
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
