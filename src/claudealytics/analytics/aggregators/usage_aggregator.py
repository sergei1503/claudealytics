"""Aggregate agent and skill usage from execution logs."""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd

from claudealytics.models.schemas import AgentExecution, SkillExecution


def normalize_name(name: str) -> str:
    """Normalize a name for grouping: lowercase with hyphens."""
    return name.lower().replace(" ", "-").replace("_", "-")


def build_canonical_map(names: list[str]) -> dict[str, str]:
    """Map all name variants to a single canonical name.

    Prefers the version that appears most often. When tied, prefers
    the Title Case version over kebab-case for readability.
    """
    groups: dict[str, Counter] = defaultdict(Counter)
    for name in names:
        groups[normalize_name(name)][name] += 1

    canonical: dict[str, str] = {}
    for norm_name, variants in groups.items():
        # Pick most frequent; break ties by preferring Title Case (has spaces/caps)
        best = max(variants, key=lambda v: (variants[v], any(c.isupper() for c in v)))
        for variant in variants:
            canonical[variant] = best

    return canonical


def agent_usage_counts(executions: list[AgentExecution]) -> dict[str, int]:
    """Count executions per agent type, merging name variants."""
    names = [e.agent for e in executions]
    canon = build_canonical_map(names)
    return dict(Counter(canon.get(n, n) for n in names).most_common())


def skill_usage_counts(executions: list[SkillExecution]) -> dict[str, int]:
    """Count executions per skill, merging name variants."""
    names = [e.skill for e in executions]
    canon = build_canonical_map(names)
    return dict(Counter(canon.get(n, n) for n in names).most_common())


def agent_usage_over_time(executions: list[AgentExecution]) -> pd.DataFrame:
    """Build a DataFrame of agent usage by date, merging name variants."""
    names = [e.agent for e in executions]
    canon = build_canonical_map(names)

    rows = []
    for e in executions:
        date = e.timestamp[:10]  # YYYY-MM-DD
        rows.append({"date": date, "agent": canon.get(e.agent, e.agent)})

    if not rows:
        return pd.DataFrame(columns=["date", "agent", "count"])

    df = pd.DataFrame(rows)
    grouped = df.groupby(["date", "agent"]).size().reset_index(name="count")
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped.sort_values("date")


def skill_usage_over_time(executions: list[SkillExecution]) -> pd.DataFrame:
    """Build a DataFrame of skill usage by date, merging name variants."""
    names = [e.skill for e in executions]
    canon = build_canonical_map(names)

    rows = []
    for e in executions:
        date = e.timestamp[:10]
        rows.append({"date": date, "skill": canon.get(e.skill, e.skill)})

    if not rows:
        return pd.DataFrame(columns=["date", "skill", "count"])

    df = pd.DataFrame(rows)
    grouped = df.groupby(["date", "skill"]).size().reset_index(name="count")
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped.sort_values("date")


def agent_last_used(executions: list[AgentExecution]) -> dict[str, str]:
    """Get last execution timestamp for each agent."""
    names = [e.agent for e in executions]
    canon = build_canonical_map(names)
    last: dict[str, str] = {}
    for e in executions:
        name = canon.get(e.agent, e.agent)
        if name not in last or e.timestamp > last[name]:
            last[name] = e.timestamp
    return last


def skill_last_used(executions: list[SkillExecution]) -> dict[str, str]:
    """Get last execution timestamp for each skill."""
    names = [e.skill for e in executions]
    canon = build_canonical_map(names)
    last: dict[str, str] = {}
    for e in executions:
        name = canon.get(e.skill, e.skill)
        if name not in last or e.timestamp > last[name]:
            last[name] = e.timestamp
    return last
