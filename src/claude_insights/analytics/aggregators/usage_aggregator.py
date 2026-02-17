"""Aggregate agent and skill usage from execution logs."""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from claude_insights.models.schemas import AgentExecution, SkillExecution


def agent_usage_counts(executions: list[AgentExecution]) -> dict[str, int]:
    """Count executions per agent type."""
    return dict(Counter(e.agent for e in executions).most_common())


def skill_usage_counts(executions: list[SkillExecution]) -> dict[str, int]:
    """Count executions per skill."""
    return dict(Counter(e.skill for e in executions).most_common())


def agent_usage_over_time(executions: list[AgentExecution]) -> pd.DataFrame:
    """Build a DataFrame of agent usage by date."""
    rows = []
    for e in executions:
        date = e.timestamp[:10]  # YYYY-MM-DD
        rows.append({"date": date, "agent": e.agent})

    if not rows:
        return pd.DataFrame(columns=["date", "agent", "count"])

    df = pd.DataFrame(rows)
    grouped = df.groupby(["date", "agent"]).size().reset_index(name="count")
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped.sort_values("date")


def skill_usage_over_time(executions: list[SkillExecution]) -> pd.DataFrame:
    """Build a DataFrame of skill usage by date."""
    rows = []
    for e in executions:
        date = e.timestamp[:10]
        rows.append({"date": date, "skill": e.skill})

    if not rows:
        return pd.DataFrame(columns=["date", "skill", "count"])

    df = pd.DataFrame(rows)
    grouped = df.groupby(["date", "skill"]).size().reset_index(name="count")
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped.sort_values("date")


def agent_last_used(executions: list[AgentExecution]) -> dict[str, str]:
    """Get last execution timestamp for each agent."""
    last: dict[str, str] = {}
    for e in executions:
        if e.agent not in last or e.timestamp > last[e.agent]:
            last[e.agent] = e.timestamp
    return last


def skill_last_used(executions: list[SkillExecution]) -> dict[str, str]:
    """Get last execution timestamp for each skill."""
    last: dict[str, str] = {}
    for e in executions:
        if e.skill not in last or e.timestamp > last[e.skill]:
            last[e.skill] = e.timestamp
    return last
