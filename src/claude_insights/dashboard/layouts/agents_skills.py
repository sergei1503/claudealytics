"""Agents & Skills tab: usage frequency, trends over time."""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import pandas as pd

from claude_insights.models.schemas import AgentExecution, SkillExecution
from claude_insights.analytics.aggregators.usage_aggregator import (
    agent_usage_counts,
    skill_usage_counts,
    agent_usage_over_time,
    skill_usage_over_time,
)


def render(agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Render the agents & skills tab."""
    col_a, col_s = st.columns(2)

    # Agent section
    with col_a:
        st.subheader("🤖 Agent Usage")
        counts = agent_usage_counts(agent_execs)
        if counts:
            df = pd.DataFrame(
                {"agent": list(counts.keys()), "executions": list(counts.values())}
            )
            fig = px.bar(
                df, x="executions", y="agent", orientation="h",
                color_discrete_sequence=["#8b5cf6"],
            )
            fig.update_layout(
                height=max(200, len(counts) * 30),
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data")

    # Skill section
    with col_s:
        st.subheader("⚡ Skill Usage")
        counts = skill_usage_counts(skill_execs)
        if counts:
            df = pd.DataFrame(
                {"skill": list(counts.keys()), "executions": list(counts.values())}
            )
            fig = px.bar(
                df, x="executions", y="skill", orientation="h",
                color_discrete_sequence=["#ec4899"],
            )
            fig.update_layout(
                height=max(200, len(counts) * 30),
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No skill execution data")

    st.divider()

    # Usage over time
    st.subheader("Agent Usage Over Time")
    agent_time_df = agent_usage_over_time(agent_execs)
    if not agent_time_df.empty:
        # Show top 10 agents by total count
        top_agents = list(agent_usage_counts(agent_execs).keys())[:10]
        filtered = agent_time_df[agent_time_df["agent"].isin(top_agents)]
        if not filtered.empty:
            fig = px.line(
                filtered, x="date", y="count", color="agent",
                labels={"date": "Date", "count": "Executions", "agent": "Agent"},
            )
            fig.update_layout(
                height=350, margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Skill Usage Over Time")
    skill_time_df = skill_usage_over_time(skill_execs)
    if not skill_time_df.empty:
        fig = px.line(
            skill_time_df, x="date", y="count", color="skill",
            labels={"date": "Date", "count": "Executions", "skill": "Skill"},
        )
        fig.update_layout(
            height=350, margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
