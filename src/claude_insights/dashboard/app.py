"""Streamlit dashboard entry point for Claude Code analytics."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from claude_insights.analytics.parsers.stats_cache_parser import parse_stats_cache
from claude_insights.analytics.parsers.execution_log_parser import (
    parse_agent_executions,
    parse_skill_executions,
)
from claude_insights.analytics.parsers.conversation_enricher import (
    mine_tool_usage_stats,
    extract_tool_usage_detailed,
)
from claude_insights.analytics.data_merger import (
    merge_agent_executions,
    merge_skill_executions,
)
from claude_insights.scanner.agent_scanner import scan_agents
from claude_insights.scanner.skill_scanner import scan_skills
from claude_insights.scanner.tool_version_scanner import scan_tool_versions
from claude_insights.dashboard.layouts import overview, token_usage, sessions, agents_skills, costs, optimization, config_health


def run_dashboard(port: int = 8501):
    """Launch the Streamlit dashboard (called from CLI)."""
    import sys
    from streamlit.web.cli import main as st_main

    sys.argv = ["streamlit", "run", __file__, "--server.port", str(port)]
    st_main()


def main():
    st.set_page_config(
        page_title="Claude Insights",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 Claude Code Insights Dashboard")

    # Global refresh button in the header area
    col_spacer, col_refresh = st.columns([5, 1])
    with col_refresh:
        if st.button("🔄 Refresh Data", use_container_width=True):
            _clear_data_caches()
            st.cache_data.clear()
            st.rerun()

    # Load data (cached)
    stats = load_stats()
    agent_execs = load_agent_executions()
    skill_execs = load_skill_executions()
    agent_defs = load_agent_definitions()
    skill_defs = load_skill_definitions()
    tool_versions = load_tool_versions()

    # Navigation tabs
    tab_overview, tab_tokens, tab_sessions, tab_agents, tab_costs, tab_optimize, tab_config = st.tabs([
        "📊 Overview",
        "🪙 Token Usage",
        "⏱️ Sessions",
        "🤖 Agents & Skills",
        "💰 Costs",
        "🎯 Optimization",
        "🏥 Config Health",
    ])

    with tab_overview:
        overview.render(stats, agent_execs, skill_execs)

    with tab_tokens:
        token_usage.render(stats)

    with tab_sessions:
        sessions.render(stats)

    with tab_agents:
        agents_skills.render(
            agent_execs, skill_execs,
            agent_definitions=agent_defs,
            skill_definitions=skill_defs,
            tool_versions=tool_versions,
        )

    with tab_costs:
        costs.render(stats)

    with tab_optimize:
        optimization.render(agent_execs, skill_execs)

    with tab_config:
        config_health.render(agent_execs=agent_execs, skill_execs=skill_execs)


def _clear_data_caches():
    """Clear file-level caches so data is re-parsed from source.

    Does NOT clear config-analysis.json (deep dive) or user preferences.
    """
    cache_dir = Path.home() / ".cache" / "claude-insights"
    for name in ("tool-index.json", "tool-stats.json", "token-mine.json"):
        p = cache_dir / name
        if p.exists():
            p.unlink()


@st.cache_data(ttl=300)
def load_stats():
    return parse_stats_cache()


@st.cache_data(ttl=300)
def load_all_executions():
    """Load and merge execution data from both logs and conversations."""
    # Get data from execution logs (recent, with outcome_preview)
    log_agents = parse_agent_executions()
    log_skills = parse_skill_executions()

    # Get historical data from conversations (no cap on records)
    conv_data = extract_tool_usage_detailed(limit=50000)

    # Merge and deduplicate
    merged_agents = merge_agent_executions(log_agents, conv_data.agent_executions)
    merged_skills = merge_skill_executions(log_skills, conv_data.skill_executions)

    return merged_agents, merged_skills


@st.cache_data(ttl=300)
def load_agent_executions():
    """Load merged agent executions."""
    agents, _ = load_all_executions()
    return agents


@st.cache_data(ttl=300)
def load_skill_executions():
    """Load merged skill executions."""
    _, skills = load_all_executions()
    return skills


@st.cache_data(ttl=600)
def load_agent_definitions():
    """Load agent definitions from ~/.claude/agents/."""
    return scan_agents()


@st.cache_data(ttl=600)
def load_skill_definitions():
    """Load skill definitions from ~/.claude/skills/."""
    return scan_skills()


@st.cache_data(ttl=600)
def load_tool_versions():
    """Load external tool version scan results. Longer TTL due to network calls."""
    return scan_tool_versions()


if __name__ == "__main__":
    main()
