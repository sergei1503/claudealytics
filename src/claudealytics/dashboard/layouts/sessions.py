"""Sessions tab: duration histogram, daily counts, scatter plot, peak hours."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from claudealytics.analytics.aggregators.token_aggregator import daily_activity_df
from claudealytics.models.schemas import StatsCache


def render(stats: StatsCache):
    """Render the sessions tab."""
    activity_df = daily_activity_df(stats)

    if activity_df.empty:
        st.warning("No session data available")
        return

    # Date filter
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From ", value=activity_df["date"].min(), key="sess_from")
    with col2:
        date_to = st.date_input("To ", value=activity_df["date"].max(), key="sess_to")

    mask = (activity_df["date"] >= pd.to_datetime(date_from)) & (activity_df["date"] <= pd.to_datetime(date_to))
    filtered = activity_df[mask]

    # KPIs for filtered range
    total_sessions = filtered["sessions"].sum()
    total_messages = filtered["messages"].sum()
    avg_daily_sessions = filtered["sessions"].mean() if len(filtered) > 0 else 0
    total_tool_calls = filtered["tool_calls"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sessions", f"{total_sessions:,}")
    c2.metric("Messages", f"{total_messages:,}")
    c3.metric("Avg Daily Sessions", f"{avg_daily_sessions:.1f}")
    c4.metric("Tool Calls", f"{total_tool_calls:,}")

    st.divider()

    # Daily session count
    st.subheader(
        "Daily Sessions", help="Number of Claude Code sessions started per day within the selected date range."
    )
    fig = px.bar(
        filtered,
        x="date",
        y="sessions",
        labels={"date": "Date", "sessions": "Sessions"},
        color_discrete_sequence=["#6366f1"],
    )
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True)
    if stats.lastComputedDate:
        st.caption(f"Data as of: {stats.lastComputedDate}")

    # Messages vs Tool Calls scatter
    st.subheader(
        "Messages vs Tool Calls per Day",
        help="Each bubble is one day. X = messages exchanged, Y = tool calls made, size = sessions. Color shows time progression.",
    )

    # Calculate days from start for color gradient
    scatter_data = filtered.copy()
    scatter_data["days_from_start"] = (scatter_data["date"] - scatter_data["date"].min()).dt.days

    fig = px.scatter(
        scatter_data,
        x="messages",
        y="tool_calls",
        size="sessions",
        color="days_from_start",
        hover_data=["date"],
        labels={
            "messages": "Messages",
            "tool_calls": "Tool Calls",
            "sessions": "Sessions",
            "days_from_start": "Days from Start",
        },
        color_continuous_scale="Viridis",
    )
    fig.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=80, b=0),
        coloraxis_colorbar=dict(
            title=dict(text="Days from Start", font=dict(size=14)),
            x=1.1,
            len=0.6,
            y=0.5,
        ),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Bubble size reflects session count. Color indicates time progression (lighter/brighter = more recent).")

    # Tool calls trend
    st.subheader("Daily Tool Calls", help="Total tool invocations (Read, Write, Bash, etc.) per day.")
    fig = px.line(
        filtered,
        x="date",
        y="tool_calls",
        labels={"date": "Date", "tool_calls": "Tool Calls"},
        color_discrete_sequence=["#14b8a6"],
        markers=True,
    )
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=20, b=0))
    st.plotly_chart(fig, use_container_width=True)
