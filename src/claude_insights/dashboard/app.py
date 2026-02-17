"""Streamlit dashboard entry point for Claude Code analytics."""

from __future__ import annotations

import streamlit as st

from claude_insights.analytics.parsers.stats_cache_parser import parse_stats_cache
from claude_insights.analytics.parsers.execution_log_parser import (
    parse_agent_executions,
    parse_skill_executions,
)
from claude_insights.dashboard.layouts import overview, token_usage, sessions, agents_skills, costs


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

    # Load data (cached)
    stats = load_stats()
    agent_execs = load_agent_executions()
    skill_execs = load_skill_executions()

    # Navigation tabs
    tab_overview, tab_tokens, tab_sessions, tab_agents, tab_costs = st.tabs([
        "📊 Overview",
        "🪙 Token Usage",
        "⏱️ Sessions",
        "🤖 Agents & Skills",
        "💰 Costs",
    ])

    with tab_overview:
        overview.render(stats, agent_execs, skill_execs)

    with tab_tokens:
        token_usage.render(stats)

    with tab_sessions:
        sessions.render(stats)

    with tab_agents:
        agents_skills.render(agent_execs, skill_execs)

    with tab_costs:
        costs.render(stats)


@st.cache_data(ttl=300)
def load_stats():
    return parse_stats_cache()


@st.cache_data(ttl=300)
def load_agent_executions():
    return parse_agent_executions()


@st.cache_data(ttl=300)
def load_skill_executions():
    return parse_skill_executions()


if __name__ == "__main__":
    main()
