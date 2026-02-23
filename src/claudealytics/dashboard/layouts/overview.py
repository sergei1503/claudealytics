"""Overview tab: KPI cards, daily activity sparkline, top agents/skills."""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import pandas as pd

from claudealytics.models.schemas import AgentExecution, SkillExecution, StatsCache
from claudealytics.analytics.aggregators.token_aggregator import daily_activity_df
from claudealytics.analytics.aggregators.usage_aggregator import agent_usage_counts, skill_usage_counts


def render(stats: StatsCache, agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Render the overview tab."""
    # KPI cards
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Sessions", f"{stats.totalSessions:,}")
    col2.metric("Total Messages", f"{stats.totalMessages:,}")
    col3.metric("Agent Invocations", f"{len(agent_execs):,}")

    st.divider()

    # Daily activity chart
    activity_df = daily_activity_df(stats)
    if not activity_df.empty:
        st.subheader("Daily Activity", help="Total messages per day across all sessions. Hover for session and tool call counts.")
        fig = px.bar(
            activity_df,
            x="date",
            y="messages",
            hover_data=["sessions", "tool_calls"],
            labels={"date": "Date", "messages": "Messages"},
            color_discrete_sequence=["#6366f1"],
        )
        fig.update_layout(
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="",
            yaxis_title="Messages",
        )
        st.plotly_chart(fig, use_container_width=True)
        if stats.lastComputedDate:
            st.caption(f"Data as of: {stats.lastComputedDate}")

    # Top agents and skills side by side
    col_a, col_s = st.columns(2)

    with col_a:
        st.subheader("Top Agents", help="Most frequently invoked custom agents (via Task tool) across all sessions.")
        agent_counts = agent_usage_counts(agent_execs)
        if agent_counts:
            top_agents = dict(list(agent_counts.items())[:10])
            df = pd.DataFrame(
                {"agent": list(top_agents.keys()), "count": list(top_agents.values())}
            )
            fig = px.bar(
                df, x="count", y="agent", orientation="h",
                color_discrete_sequence=["#8b5cf6"],
            )
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data found")

    with col_s:
        st.subheader("Top Skills", help="Most frequently invoked skills (slash commands) across all sessions.")
        skill_counts = skill_usage_counts(skill_execs)
        if skill_counts:
            top_skills = dict(list(skill_counts.items())[:10])
            df = pd.DataFrame(
                {"skill": list(top_skills.keys()), "count": list(top_skills.values())}
            )
            fig = px.bar(
                df, x="count", y="skill", orientation="h",
                color_discrete_sequence=["#ec4899"],
            )
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No skill execution data found")

    # Peak hours
    if stats.hourCounts:
        st.subheader("Activity by Hour of Day", help="Session counts grouped by hour (24h clock, local time). Shows your peak productivity windows.")
        hours_df = pd.DataFrame([
            {"hour": int(h), "count": c}
            for h, c in stats.hourCounts.items()
        ]).sort_values("hour")
        fig = px.bar(
            hours_df, x="hour", y="count",
            labels={"hour": "Hour (24h)", "count": "Sessions"},
            color_discrete_sequence=["#14b8a6"],
        )
        fig.update_layout(
            height=250, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(dtick=1),
        )
        st.plotly_chart(fig, use_container_width=True)
