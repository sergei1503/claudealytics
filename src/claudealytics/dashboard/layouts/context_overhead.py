"""Context Overhead tab: baseline overhead trends, context fill curves, compaction detection, agent overhead."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from claudealytics.analytics.aggregators.context_aggregator import (
    context_fill_curve,
    daily_baseline_overhead,
    session_context_stats,
)

# Context window limit for reference lines
CONTEXT_WINDOW_LIMIT = 200_000


def render():
    """Render the context overhead tab."""
    daily_df = _load_daily_baseline()
    session_df = _load_session_stats()

    if daily_df.empty and session_df.empty:
        st.warning("No context overhead data available. Ensure conversation JSONL files exist in ~/.claude/projects/")
        return

    _render_kpis(daily_df, session_df)
    st.divider()

    # Date filter
    if not daily_df.empty:
        col1, col2 = st.columns(2)
        date_from = col1.date_input("From", value=daily_df["date"].min(), key="ctx_from")
        date_to = col2.date_input("To", value=daily_df["date"].max(), key="ctx_to")

        date_mask = (daily_df["date"] >= pd.to_datetime(date_from)) & (
            daily_df["date"] <= pd.to_datetime(date_to)
        )
        filtered_daily = daily_df[date_mask]

        if not session_df.empty:
            session_mask = (session_df["date"] >= pd.to_datetime(date_from)) & (
                session_df["date"] <= pd.to_datetime(date_to)
            )
            filtered_sessions = session_df[session_mask]
        else:
            filtered_sessions = session_df
    else:
        filtered_daily = daily_df
        filtered_sessions = session_df

    # 1. Baseline Overhead Trend
    if not filtered_daily.empty:
        st.subheader(
            "Baseline Overhead Trend",
            help="Average first-message input tokens per day. Shows config bloat growth over time.",
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=filtered_daily["date"],
                y=filtered_daily["avg_baseline_overhead"],
                mode="lines+markers",
                name="Avg Baseline Overhead",
                line=dict(color="#8b5cf6", width=2),
                marker=dict(size=5),
                hovertemplate="Date: %{x|%Y-%m-%d}<br>Avg Overhead: %{y:,.0f} tokens<extra></extra>",
            )
        )
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=40, b=0),
            yaxis_title="Tokens",
            xaxis_title="Date",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("First-message input tokens = system prompt + tools + CLAUDE.md + MCP + skills loaded before any user input.")

    # 2. Context Fill Curves
    if not filtered_sessions.empty:
        st.subheader(
            "Context Fill Curves",
            help="How quickly context fills up message by message for a selected session.",
        )
        # Build session options with date and project for readability
        session_options = filtered_sessions.sort_values("date", ascending=False).head(50)
        session_labels = {
            row["session_id"]: f"{row['date'].strftime('%Y-%m-%d')} | {row['project']} | {row['message_count']} msgs | {row['session_id'][:8]}..."
            for _, row in session_options.iterrows()
        }

        selected_label = st.selectbox(
            "Select session",
            options=list(session_labels.values()),
            key="ctx_session_select",
        )

        if selected_label:
            # Find the session_id from the label
            selected_session_id = None
            for sid, label in session_labels.items():
                if label == selected_label:
                    selected_session_id = sid
                    break

            if selected_session_id:
                series = context_fill_curve(selected_session_id)
                if series:
                    fig = go.Figure()

                    # Main fill curve
                    fig.add_trace(
                        go.Scatter(
                            x=list(range(1, len(series) + 1)),
                            y=series,
                            mode="lines+markers",
                            name="Input Tokens",
                            line=dict(color="#6366f1", width=2),
                            marker=dict(size=4),
                            hovertemplate="Message %{x}<br>Input Tokens: %{y:,.0f}<extra></extra>",
                        )
                    )

                    # Mark compaction events (>30% drop)
                    compaction_msgs = []
                    for i in range(1, len(series)):
                        if series[i - 1] > 0 and (series[i - 1] - series[i]) / series[i - 1] > 0.30:
                            compaction_msgs.append(i + 1)  # 1-indexed

                    for msg_num in compaction_msgs:
                        fig.add_vline(
                            x=msg_num,
                            line_dash="dash",
                            line_color="rgba(239,68,68,0.6)",
                            annotation_text="Compaction",
                            annotation_position="top",
                        )

                    # 200K context limit reference
                    fig.add_hline(
                        y=CONTEXT_WINDOW_LIMIT,
                        line_dash="dot",
                        line_color="rgba(245,158,11,0.5)",
                        annotation_text="200K context limit",
                    )

                    fig.update_layout(
                        height=400,
                        margin=dict(l=20, r=20, t=40, b=0),
                        xaxis_title="Message Number",
                        yaxis_title="Input Tokens",
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Show session summary
                    row = filtered_sessions[filtered_sessions["session_id"] == selected_session_id].iloc[0]
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Baseline", f"{row['baseline_overhead_tokens']:,}")
                    col2.metric("Peak", f"{row['peak_context_tokens']:,}")
                    col3.metric("Compactions", str(row["compaction_count"]))
                    col4.metric("Agent Spawns", str(row["agent_spawn_count"]))
                else:
                    st.info("No fill curve data for this session.")

    # 3. Compaction Frequency
    if not filtered_sessions.empty:
        compaction_sessions = filtered_sessions[filtered_sessions["compaction_count"] > 0]
        if not compaction_sessions.empty:
            st.subheader(
                "Compaction Frequency",
                help="Daily count of context compaction events. Compaction = input tokens dropped >30% between consecutive messages.",
            )
            daily_compactions = (
                compaction_sessions.groupby(compaction_sessions["date"].dt.date)
                .agg(total_compactions=("compaction_count", "sum"))
                .reset_index()
            )
            daily_compactions["date"] = pd.to_datetime(daily_compactions["date"])

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_compactions["date"],
                    y=daily_compactions["total_compactions"],
                    marker_color="#ef4444",
                    hovertemplate="Date: %{x|%Y-%m-%d}<br>Compactions: %{y}<extra></extra>",
                )
            )
            fig.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=40, b=0),
                yaxis_title="Compaction Events",
                xaxis_title="Date",
            )
            st.plotly_chart(fig, use_container_width=True)

    # 4. Agent Overhead
    if not filtered_sessions.empty:
        agent_sessions = filtered_sessions[filtered_sessions["agent_spawn_count"] > 0].copy()
        if not agent_sessions.empty:
            st.subheader(
                "Agent Overhead",
                help="Sessions with agent spawns. Estimated overhead = baseline_overhead x agent_spawn_count.",
            )

            total_agent_overhead = agent_sessions["estimated_agent_overhead"].sum()
            total_spawns = agent_sessions["agent_spawn_count"].sum()
            avg_spawns = agent_sessions["agent_spawn_count"].mean()

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Agent Spawns", f"{total_spawns:,}")
            col2.metric("Avg Spawns / Session", f"{avg_spawns:.1f}")
            col3.metric("Est. Total Agent Overhead", f"{total_agent_overhead:,.0f} tokens")

            # Top sessions by agent spawns
            top_agent = agent_sessions.nlargest(10, "agent_spawn_count")
            display_df = top_agent[
                [
                    "date",
                    "project",
                    "agent_spawn_count",
                    "baseline_overhead_tokens",
                    "estimated_agent_overhead",
                    "message_count",
                ]
            ].copy()
            display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")

            st.dataframe(
                display_df.rename(
                    columns={
                        "date": "Date",
                        "project": "Project",
                        "agent_spawn_count": "Agent Spawns",
                        "baseline_overhead_tokens": "Baseline (tokens)",
                        "estimated_agent_overhead": "Est. Overhead (tokens)",
                        "message_count": "Messages",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )

    st.divider()
    st.caption(
        "Baseline overhead = first API response input tokens (system prompt + tools + CLAUDE.md + MCP). "
        "Compaction detected when input tokens drop >30% between consecutive messages. "
        "Agent overhead is estimated as baseline x spawn count per session."
    )


def _render_kpis(daily_df: pd.DataFrame, session_df: pd.DataFrame):
    """Render KPI metrics row."""
    col1, col2, col3, col4 = st.columns(4)

    if not daily_df.empty:
        avg_baseline = daily_df["avg_baseline_overhead"].mean()
        col1.metric("Avg Baseline Overhead", f"{avg_baseline:,.0f} tokens")
    else:
        col1.metric("Avg Baseline Overhead", "N/A")

    if not session_df.empty:
        avg_compactions = session_df["compaction_count"].mean()
        col2.metric("Avg Compactions / Session", f"{avg_compactions:.2f}")
    else:
        col2.metric("Avg Compactions / Session", "N/A")

    if not session_df.empty:
        total_spawns = session_df["agent_spawn_count"].sum()
        col3.metric("Total Agent Spawns", f"{total_spawns:,}")
    else:
        col3.metric("Total Agent Spawns", "N/A")

    if not session_df.empty:
        avg_peak = session_df["peak_context_tokens"].mean()
        pct_of_limit = avg_peak / CONTEXT_WINDOW_LIMIT * 100
        col4.metric("Avg Peak Context", f"{avg_peak:,.0f}", help=f"{pct_of_limit:.0f}% of 200K limit")
    else:
        col4.metric("Avg Peak Context", "N/A")


@st.cache_data(ttl=300)
def _load_daily_baseline() -> pd.DataFrame:
    return daily_baseline_overhead(use_cache=True)


@st.cache_data(ttl=300)
def _load_session_stats() -> pd.DataFrame:
    return session_context_stats(use_cache=True)
