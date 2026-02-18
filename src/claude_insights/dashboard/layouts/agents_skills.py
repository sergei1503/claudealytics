"""Agents & Skills tab: usage frequency, trends over time, unmapped components."""

from __future__ import annotations

from collections import defaultdict

import streamlit as st
import plotly.express as px
import pandas as pd

from claude_insights.models.schemas import AgentExecution, AgentInfo, SkillExecution, SkillInfo
from claude_insights.analytics.aggregators.usage_aggregator import (
    agent_usage_counts,
    skill_usage_counts,
    agent_usage_over_time,
    skill_usage_over_time,
)


def render(
    agent_execs: list[AgentExecution],
    skill_execs: list[SkillExecution],
    agent_definitions: list[AgentInfo] | None = None,
    skill_definitions: list[SkillInfo] | None = None,
):
    """Render the agents & skills tab."""
    col_a, col_s = st.columns(2)

    agent_counts = agent_usage_counts(agent_execs)
    skill_counts_map = skill_usage_counts(skill_execs)

    TOP_N = 10

    # Agent section
    with col_a:
        st.subheader("Agent Usage")
        if agent_counts:
            top_agents = dict(list(agent_counts.items())[:TOP_N])
            df = pd.DataFrame(
                {"agent": list(top_agents.keys()), "executions": list(top_agents.values())}
            )
            fig = px.bar(
                df, x="executions", y="agent", orientation="h",
                color_discrete_sequence=["#8b5cf6"],
            )
            fig.update_layout(
                height=max(200, len(top_agents) * 30),
                margin=dict(l=20, r=20, t=20, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data")

    # Skill section
    with col_s:
        st.subheader("Skill Usage")
        if skill_counts_map:
            top_skills = dict(list(skill_counts_map.items())[:TOP_N])
            df = pd.DataFrame(
                {"skill": list(top_skills.keys()), "executions": list(top_skills.values())}
            )
            fig = px.bar(
                df, x="executions", y="skill", orientation="h",
                color_discrete_sequence=["#ec4899"],
            )
            fig.update_layout(
                height=max(200, len(top_skills) * 30),
                margin=dict(l=20, r=20, t=20, b=0),
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
                height=350, margin=dict(l=20, r=20, t=100, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="right", x=1),
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
            height=350, margin=dict(l=20, r=20, t=100, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Unmapped agents/skills sections
    st.divider()
    _render_unmapped_agents(agent_execs, agent_definitions or [])
    _render_unmapped_skills(skill_execs, skill_definitions or [])


def _render_unmapped_agents(
    agent_execs: list[AgentExecution],
    agent_definitions: list[AgentInfo],
):
    """Show agents found in logs but not defined in ~/.claude/agents/."""
    defined_names = {a.name for a in agent_definitions}
    # Also include built-in agents that don't need definitions
    builtin_agents = {"Explore", "Plan", "general-purpose", "Bash"}

    # Collect used agent names with their project paths
    agent_projects: dict[str, set[str]] = defaultdict(set)
    for ex in agent_execs:
        name = ex.agent_type or ex.agent
        if name:
            # session_id sometimes encodes the project context
            project = _extract_project(ex.session_id)
            if project:
                agent_projects[name].add(project)
            else:
                agent_projects[name].add("(unknown)")

    unmapped = {
        name: projects
        for name, projects in agent_projects.items()
        if name not in defined_names and name not in builtin_agents
    }

    st.subheader("Unmapped Agents")
    if unmapped:
        st.warning(
            f"**{len(unmapped)}** agents found in conversation logs "
            f"but not defined in `~/.claude/agents/`"
        )
        rows = []
        for name, projects in sorted(unmapped.items()):
            # Find executions for this agent
            matching_execs = [
                ex for ex in agent_execs if (ex.agent_type or ex.agent) == name
            ]
            count = len(matching_execs)

            # Find last used timestamp
            last_used = None
            if matching_execs:
                timestamps = [ex.timestamp for ex in matching_execs if ex.timestamp]
                if timestamps:
                    # timestamps are already strings in ISO format
                    last_used = max(timestamps)

            rows.append({
                "Agent": name,
                "Executions": count,
                "Last Used": last_used[:10] if last_used else "Unknown",  # Extract YYYY-MM-DD from ISO string
                "Projects": ", ".join(sorted(projects)[:3]),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.success("All used agents have corresponding definitions (or are built-in)")


def _render_unmapped_skills(
    skill_execs: list[SkillExecution],
    skill_definitions: list[SkillInfo],
):
    """Show skills found in logs but not defined in ~/.claude/skills/."""
    defined_names = {s.name for s in skill_definitions}

    skill_projects: dict[str, set[str]] = defaultdict(set)
    for ex in skill_execs:
        name = ex.skill_name or ex.skill
        if name:
            project = _extract_project(ex.session_id)
            if project:
                skill_projects[name].add(project)
            else:
                skill_projects[name].add("(unknown)")

    unmapped = {
        name: projects
        for name, projects in skill_projects.items()
        if name not in defined_names
    }

    st.subheader("Unmapped Skills")
    if unmapped:
        st.warning(
            f"**{len(unmapped)}** skills found in conversation logs "
            f"but not defined in `~/.claude/skills/`"
        )
        rows = []
        for name, projects in sorted(unmapped.items()):
            # Find executions for this skill
            matching_execs = [
                ex for ex in skill_execs if (ex.skill_name or ex.skill) == name
            ]
            count = len(matching_execs)

            # Find last used timestamp
            last_used = None
            if matching_execs:
                timestamps = [ex.timestamp for ex in matching_execs if ex.timestamp]
                if timestamps:
                    # timestamps are already strings in ISO format
                    last_used = max(timestamps)

            rows.append({
                "Skill": name,
                "Executions": count,
                "Last Used": last_used[:10] if last_used else "Unknown",  # Extract YYYY-MM-DD from ISO string
                "Projects": ", ".join(sorted(projects)[:3]),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.success("All used skills have corresponding definitions")


def _extract_project(session_id: str) -> str:
    """Try to extract a project name from the session context.

    Session IDs are UUIDs, but execution log entries sometimes carry
    project info. Returns empty string if not determinable.
    """
    # Session IDs are plain UUIDs — we can't extract project from them alone.
    # This is a best-effort placeholder; the real project mapping comes from
    # conversation file paths if we have that context.
    return ""
