"""Agents & Skills tab: usage frequency, trends over time, unmapped components."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import streamlit as st
import plotly.express as px
import pandas as pd

from claudealytics.models.schemas import (
    AgentExecution, AgentInfo, SkillExecution, SkillInfo, ToolVersionResult,
    UnmappedPreferences,
)
from claudealytics.analytics.aggregators.usage_aggregator import (
    agent_usage_counts,
    skill_usage_counts,
    agent_usage_over_time,
    skill_usage_over_time,
    agent_last_used,
    skill_last_used,
)

_PREFS_PATH = Path.home() / ".cache" / "claudealytics" / "unmapped-preferences.json"
_CLAUDE_HOME = Path.home() / ".claude"


def _normalize(name: str) -> str:
    """Normalize agent/skill names for comparison (lowercase, hyphens)."""
    return name.lower().replace(" ", "-").replace("_", "-")


@st.cache_data(ttl=300)
def _extract_claude_md_references() -> tuple[set[str], set[str]]:
    """Extract agent/skill names referenced in CLAUDE.md files.

    Scans global ~/.claude/CLAUDE.md and project-specific CLAUDE.md files
    found under ~/repos/. Returns (agent_names, skill_names) with
    normalized names. Cached for 5 minutes to avoid redundant filesystem scans.
    """
    import re

    agents: set[str] = set()
    skills: set[str] = set()

    claude_md_paths: list[Path] = []

    # Global CLAUDE.md
    global_md = _CLAUDE_HOME / "CLAUDE.md"
    if global_md.exists():
        claude_md_paths.append(global_md)

    # Project-specific CLAUDE.md files under ~/repos/ (max 2 levels deep)
    repos_dir = Path.home() / "repos"
    if repos_dir.exists():
        for pattern in ("*/.claude/CLAUDE.md", "*/*/.claude/CLAUDE.md"):
            for md_file in repos_dir.glob(pattern):
                claude_md_paths.append(md_file)

    for md_path in claude_md_paths:
        try:
            content = md_path.read_text()
        except Exception:
            continue

        # Strategy 1: Extract from agent/skill definition tables
        # These have headers like `| subagent_type | Description |` or `| Name | Description |`
        # under sections containing "Agent" or "Skill"
        _extract_from_tables(content, agents, skills)

        # Strategy 2: Extract from routing tables with Task()/Skill() patterns
        _placeholders = {"...", "<name>", "name", "description"}
        for m in re.finditer(r'Task\(subagent_type="([^"]+)"\)', content):
            val = m.group(1)
            if val not in _placeholders:
                agents.add(_normalize(val))
        for m in re.finditer(r'Skill\(skill="([^"]+)"\)', content):
            val = m.group(1)
            if val not in _placeholders:
                skills.add(_normalize(val))

    return agents, skills


def _extract_from_tables(content: str, agents: set[str], skills: set[str]) -> None:
    """Extract agent/skill names from markdown definition tables."""
    import re

    lines = content.split("\n")
    current_section = ""

    for line in lines:
        # Track section headers
        header_match = re.match(r'^#{1,4}\s+(.+)$', line)
        if header_match:
            current_section = header_match.group(1).lower()
            continue

        # Only process table rows (not header/separator rows)
        if not line.strip().startswith("|"):
            continue
        if re.match(r'^\|\s*-', line):
            continue

        # Match first-column backtick values: | `name` | ... |
        row_match = re.match(r'^\|\s*`([^`]+)`\s*\|', line)
        if not row_match:
            continue

        name = row_match.group(1).strip()

        # Skip values that aren't agent/skill names
        if not name or "@" in name or "/" in name or name.startswith("~"):
            continue
        if name in ("...", "<name>", "name", "description") or len(name) < 2:
            continue
        # Skip tool/infra entries (from Stack Profiles, CLI Tools tables etc)
        if any(kw in current_section for kw in ("stack", "cli tool", "shared")):
            continue

        # Classify based on section context
        section = current_section
        if "agent" in section and "skill" not in section:
            agents.add(_normalize(name))
        elif "skill" in section and "agent" not in section:
            skills.add(_normalize(name))
        elif "routing" in section:
            # Routing table: check the row content for Task() vs Skill()
            if "Task(" in line or "subagent_type" in line:
                agents.add(_normalize(name))
            elif "Skill(" in line or "skill=" in line:
                skills.add(_normalize(name))
        elif "agent" in section and "skill" in section:
            # Combined section like "Agents & Skills" — use sub-headers
            # These tables typically have `subagent_type` or `Name` headers
            # Add to both; the normalization will handle dedup
            agents.add(_normalize(name))
            skills.add(_normalize(name))


def _load_prefs() -> UnmappedPreferences:
    if _PREFS_PATH.exists():
        try:
            return UnmappedPreferences.model_validate(json.loads(_PREFS_PATH.read_text()))
        except Exception:
            pass
    return UnmappedPreferences()


def _save_prefs(prefs: UnmappedPreferences) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_PATH.write_text(prefs.model_dump_json(indent=2))


def render(
    agent_execs: list[AgentExecution],
    skill_execs: list[SkillExecution],
    agent_definitions: list[AgentInfo] | None = None,
    skill_definitions: list[SkillInfo] | None = None,
    tool_versions: list[ToolVersionResult] | None = None,
):
    """Render the agents & skills tab with sub-tabs."""
    tab_usage, tab_inventory, tab_unmapped = st.tabs(["📊 Usage", "📦 Inventory", "❓ Unmapped"])

    with tab_usage:
        _render_usage(agent_execs, skill_execs)

    with tab_inventory:
        _render_inventory(
            agent_execs, skill_execs,
            agent_definitions or [],
            skill_definitions or [],
            tool_versions or [],
        )

    with tab_unmapped:
        _render_unmapped_agents(agent_execs, agent_definitions or [])
        _render_unmapped_skills(skill_execs, skill_definitions or [])


def _render_usage(agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]) -> None:
    """Render usage charts sub-tab."""
    col_a, col_s = st.columns(2)

    agent_counts = agent_usage_counts(agent_execs)
    skill_counts_map = skill_usage_counts(skill_execs)

    with col_a:
        st.subheader("Agent Usage")
        if agent_counts:
            df = pd.DataFrame(
                {"agent": list(agent_counts.keys()), "executions": list(agent_counts.values())}
            )
            fig = px.bar(
                df, x="executions", y="agent", orientation="h",
                color_discrete_sequence=["#8b5cf6"],
            )
            fig.update_layout(
                height=max(200, len(agent_counts) * 30),
                margin=dict(l=20, r=20, t=20, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data")

    with col_s:
        st.subheader("Skill Usage")
        if skill_counts_map:
            df = pd.DataFrame(
                {"skill": list(skill_counts_map.keys()), "executions": list(skill_counts_map.values())}
            )
            fig = px.bar(
                df, x="executions", y="skill", orientation="h",
                color_discrete_sequence=["#ec4899"],
            )
            fig.update_layout(
                height=max(200, len(skill_counts_map) * 30),
                margin=dict(l=20, r=20, t=20, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions", yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No skill execution data")

    st.divider()

    st.subheader("Agent Usage Over Time")
    agent_time_df = agent_usage_over_time(agent_execs)
    if not agent_time_df.empty:
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


def _render_inventory(
    agent_execs: list[AgentExecution],
    skill_execs: list[SkillExecution],
    agent_definitions: list[AgentInfo],
    skill_definitions: list[SkillInfo],
    tool_versions: list[ToolVersionResult],
) -> None:
    """Render the Inventory sub-tab."""
    counts_agents = agent_usage_counts(agent_execs)
    counts_skills = skill_usage_counts(skill_execs)
    last_used_agents = agent_last_used(agent_execs)
    last_used_skills = skill_last_used(skill_execs)

    updates_available = sum(1 for t in tool_versions if t.status == "update_available")

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Agents", len(agent_definitions))
    k2.metric("Total Skills", len(skill_definitions))
    k3.metric("External Tools", len(tool_versions))
    k4.metric("Updates Available", updates_available)

    st.divider()

    # Agents table
    st.subheader("Agents")
    if agent_definitions:
        rows = []
        for agent in agent_definitions:
            norm = _normalize(agent.name)
            # Match by normalized name against execution counts
            runs = next(
                (v for k, v in counts_agents.items() if _normalize(k) == norm), 0
            )
            last = next(
                (v[:10] for k, v in last_used_agents.items() if _normalize(k) == norm), "—"
            )
            rows.append({
                "Name": agent.name,
                "Description": agent.description or "—",
                "Model": agent.model or "—",
                "Runs": runs,
                "Last Used": last,
            })
        # Also include agents seen in executions but not in definitions
        defined_norms = {_normalize(a.name) for a in agent_definitions}
        for exec_name, count in counts_agents.items():
            if _normalize(exec_name) not in defined_norms:
                last = last_used_agents.get(exec_name, "")
                rows.append({
                    "Name": exec_name,
                    "Description": "—",
                    "Model": "—",
                    "Runs": count,
                    "Last Used": last[:10] if last else "—",
                })
        df_agents = pd.DataFrame(rows).sort_values("Runs", ascending=False)
        st.dataframe(df_agents, use_container_width=True, hide_index=True)
    else:
        st.info("No agent definitions found")

    st.divider()

    # Skills table
    st.subheader("Skills")
    if skill_definitions:
        rows = []
        for skill in skill_definitions:
            norm = _normalize(skill.name)
            runs = next(
                (v for k, v in counts_skills.items() if _normalize(k) == norm), 0
            )
            last = next(
                (v[:10] for k, v in last_used_skills.items() if _normalize(k) == norm), "—"
            )
            rows.append({
                "Name": skill.name,
                "Description": skill.description or "—",
                "Invocable": "✓" if skill.user_invocable else "",
                "Runs": runs,
                "Last Used": last,
            })
        # Include skills seen in executions but not in definitions
        defined_norms = {_normalize(s.name) for s in skill_definitions}
        for exec_name, count in counts_skills.items():
            if _normalize(exec_name) not in defined_norms:
                last = last_used_skills.get(exec_name, "")
                rows.append({
                    "Name": exec_name,
                    "Description": "—",
                    "Invocable": "",
                    "Runs": count,
                    "Last Used": last[:10] if last else "—",
                })
        df_skills = pd.DataFrame(rows).sort_values("Runs", ascending=False)
        st.dataframe(df_skills, use_container_width=True, hide_index=True)
    else:
        st.info("No skill definitions found")

    st.divider()

    # External tools table
    st.subheader("External Tools")
    if tool_versions:
        _STATUS_EMOJI = {
            "up_to_date": "🟢",
            "update_available": "🟡",
            "not_installed": "🔴",
            "unknown": "⚪",
        }
        rows = [
            {
                "Tool": t.name,
                "Installed": t.installed_version or "—",
                "Latest": t.latest_version or "—",
                "Status": f"{_STATUS_EMOJI.get(t.status, '⚪')} {t.status.replace('_', ' ').title()}",
            }
            for t in tool_versions
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No tool version data")


def _render_unmapped_agents(
    agent_execs: list[AgentExecution],
    agent_definitions: list[AgentInfo],
):
    """Show agents found in logs but not defined in ~/.claude/agents/."""
    # Build normalized lookup from definitions
    defined_normalized = {_normalize(a.name) for a in agent_definitions}
    # Also index by file stem (e.g. "k8s-log-checker" from the .md filename)
    for a in agent_definitions:
        stem = Path(a.file_path).stem
        defined_normalized.add(_normalize(stem))

    # Add agents referenced in CLAUDE.md routing tables
    claude_md_agents, _ = _extract_claude_md_references()
    defined_normalized |= claude_md_agents

    builtin_agents_normalized = {
        _normalize(b) for b in (
            "Explore", "Plan", "general-purpose", "Bash",
            "claude-code-guide", "statusline-setup",
            "code-simplifier", "code-simplifier:code-simplifier",
            "haiku", "sonnet", "opus",
        )
    }
    prefs = _load_prefs()

    agent_projects: dict[str, set[str]] = defaultdict(set)
    for ex in agent_execs:
        name = ex.agent_type or ex.agent
        if name:
            project = _extract_project(ex.session_id)
            agent_projects[name].add(project if project else "(unknown)")

    unmapped = {
        name: projects
        for name, projects in agent_projects.items()
        if _normalize(name) not in defined_normalized
        and _normalize(name) not in builtin_agents_normalized
    }

    st.subheader("Unmapped Agents")
    if not unmapped:
        st.success("All used agents have corresponding definitions (or are built-in)")
        return

    active = {n: p for n, p in unmapped.items() if n not in prefs.dismissed_agents}
    dismissed = {n: p for n, p in unmapped.items() if n in prefs.dismissed_agents}

    st.warning(
        f"**{len(active)}** unmapped agents"
        + (f" ({len(dismissed)} dismissed)" if dismissed else "")
    )

    show_dismissed = st.checkbox("Show dismissed agents", value=False, key="show_dismissed_agents")

    items_to_show = list(active.items())
    if show_dismissed:
        items_to_show += list(dismissed.items())

    # Column headers
    hcol_name, hcol_count, hcol_date, hcol_btn = st.columns([3, 1, 1.5, 1])
    with hcol_name:
        st.caption("**Name**")
    with hcol_count:
        st.caption("**Runs**")
    with hcol_date:
        st.caption("**Last Used**")

    for name, projects in sorted(items_to_show):
        is_dismissed = name in prefs.dismissed_agents
        matching_execs = [
            ex for ex in agent_execs if (ex.agent_type or ex.agent) == name
        ]
        count = len(matching_execs)
        timestamps = [ex.timestamp for ex in matching_execs if ex.timestamp]
        last_used = max(timestamps)[:10] if timestamps else "Unknown"

        col_name, col_count, col_date, col_btn = st.columns([3, 1, 1.5, 1])
        with col_name:
            label = f"~~{name}~~" if is_dismissed else f"**{name}**"
            st.markdown(label)
        with col_count:
            st.caption(f"{count} runs")
        with col_date:
            st.caption(last_used)
        with col_btn:
            if is_dismissed:
                if st.button("Restore", key=f"restore_agent_{name}"):
                    prefs.dismissed_agents.remove(name)
                    _save_prefs(prefs)
                    st.rerun()
            else:
                if st.button("Dismiss", key=f"dismiss_agent_{name}"):
                    prefs.dismissed_agents.append(name)
                    _save_prefs(prefs)
                    st.rerun()


def _render_unmapped_skills(
    skill_execs: list[SkillExecution],
    skill_definitions: list[SkillInfo],
):
    """Show skills found in logs but not defined in ~/.claude/skills/."""
    # Build normalized lookup from definitions
    defined_normalized = {_normalize(s.name) for s in skill_definitions}
    # Also index by directory name or file stem
    for s in skill_definitions:
        p = Path(s.file_path)
        defined_normalized.add(_normalize(p.parent.name))
        defined_normalized.add(_normalize(p.stem))

    # Add skills referenced in CLAUDE.md routing tables
    _, claude_md_skills = _extract_claude_md_references()
    defined_normalized |= claude_md_skills

    prefs = _load_prefs()

    skill_projects: dict[str, set[str]] = defaultdict(set)
    for ex in skill_execs:
        name = ex.skill_name or ex.skill
        if name:
            project = _extract_project(ex.session_id)
            skill_projects[name].add(project if project else "(unknown)")

    unmapped = {
        name: projects
        for name, projects in skill_projects.items()
        if _normalize(name) not in defined_normalized
    }

    st.subheader("Unmapped Skills")
    if not unmapped:
        st.success("All used skills have corresponding definitions")
        return

    active = {n: p for n, p in unmapped.items() if n not in prefs.dismissed_skills}
    dismissed = {n: p for n, p in unmapped.items() if n in prefs.dismissed_skills}

    st.warning(
        f"**{len(active)}** unmapped skills"
        + (f" ({len(dismissed)} dismissed)" if dismissed else "")
    )

    show_dismissed = st.checkbox("Show dismissed skills", value=False, key="show_dismissed_skills")

    items_to_show = list(active.items())
    if show_dismissed:
        items_to_show += list(dismissed.items())

    # Column headers
    hcol_name, hcol_count, hcol_date, hcol_btn = st.columns([3, 1, 1.5, 1])
    with hcol_name:
        st.caption("**Name**")
    with hcol_count:
        st.caption("**Runs**")
    with hcol_date:
        st.caption("**Last Used**")

    for name, projects in sorted(items_to_show):
        is_dismissed = name in prefs.dismissed_skills
        matching_execs = [
            ex for ex in skill_execs if (ex.skill_name or ex.skill) == name
        ]
        count = len(matching_execs)
        timestamps = [ex.timestamp for ex in matching_execs if ex.timestamp]
        last_used = max(timestamps)[:10] if timestamps else "Unknown"

        col_name, col_count, col_date, col_btn = st.columns([3, 1, 1.5, 1])
        with col_name:
            label = f"~~{name}~~" if is_dismissed else f"**{name}**"
            st.markdown(label)
        with col_count:
            st.caption(f"{count} runs")
        with col_date:
            st.caption(last_used)
        with col_btn:
            if is_dismissed:
                if st.button("Restore", key=f"restore_skill_{name}"):
                    prefs.dismissed_skills.remove(name)
                    _save_prefs(prefs)
                    st.rerun()
            else:
                if st.button("Dismiss", key=f"dismiss_skill_{name}"):
                    prefs.dismissed_skills.append(name)
                    _save_prefs(prefs)
                    st.rerun()


def _extract_project(session_id: str) -> str:
    """Try to extract a project name from the session context.

    Session IDs are UUIDs, but execution log entries sometimes carry
    project info. Returns empty string if not determinable.
    """
    # Session IDs are plain UUIDs — we can't extract project from them alone.
    # This is a best-effort placeholder; the real project mapping comes from
    # conversation file paths if we have that context.
    return ""
