"""Streamlit dashboard entry point for Claude Code analytics."""

from __future__ import annotations

import tomllib
from importlib.metadata import version as pkg_version
from pathlib import Path

import streamlit as st

from claudealytics.dashboard.layouts import (
    agents_skills,
    cache_analysis,
    config_health,
    conversation_analysis,
    conversation_profile,
    costs,
    optimization,
    overview,
    sessions,
    tech_stack,
    token_usage,
)


def run_dashboard(port: int = 8501):
    """Launch the Streamlit dashboard (called from CLI)."""
    import sys

    from streamlit.web.cli import main as st_main

    sys.argv = ["streamlit", "run", __file__, "--server.port", str(port)]
    st_main()


def main():
    st.set_page_config(
        page_title="Claudealytics",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 Claude Code Insights Dashboard")

    # Global refresh button + version in the header area
    try:
        _version = pkg_version("claudealytics")
    except Exception:
        try:
            with open(Path(__file__).parents[3] / "pyproject.toml", "rb") as f:
                _version = tomllib.load(f)["project"]["version"]
        except Exception:
            _version = "dev"

    col_spacer, col_version, col_refresh = st.columns([4, 1, 1])
    with col_version:
        st.caption(f"v{_version}")
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

    # Navigation tabs
    (
        tab_overview,
        tab_report,
        tab_tokens,
        tab_cache,
        tab_sessions,
        tab_convo,
        tab_profile,
        tab_tech,
        tab_agents,
        tab_costs,
        tab_config,
    ) = st.tabs(
        [
            "📊 Overview",
            "📋 Report",
            "🪙 Token Usage",
            "💾 Cache Analysis",
            "⏱️ Sessions",
            "🔍 Conversation Analysis",
            "🎯 Conversation Profile",
            "🛠 Tech Stack",
            "🤖 Agents & Skills",
            "💰 Costs",
            "🏥 Config Health",
        ]
    )

    with tab_overview:
        _safe_render("Overview", overview.render, stats, agent_execs, skill_execs)

    with tab_report:
        _safe_render("Report", optimization.render, stats, agent_execs, skill_execs)

    with tab_tokens:
        _safe_render("Token Usage", token_usage.render, stats)

    with tab_cache:
        _safe_render("Cache Analysis", cache_analysis.render, stats)

    with tab_sessions:
        _safe_render("Sessions", sessions.render, stats)

    with tab_convo:
        _safe_render("Conversation Analysis", conversation_analysis.render, stats)

    with tab_profile:
        _safe_render("Conversation Profile", conversation_profile.render, stats)

    with tab_tech:
        _safe_render("Tech Stack", tech_stack.render, stats)

    with tab_agents:
        _safe_render(
            "Agents & Skills",
            agents_skills.render,
            agent_execs,
            skill_execs,
            agent_definitions=agent_defs,
            skill_definitions=skill_defs,
            tool_versions=load_tool_versions(),
        )

    with tab_costs:
        _safe_render("Costs", costs.render, stats)

    with tab_config:
        _safe_render("Config Health", config_health.render, agent_execs=agent_execs, skill_execs=skill_execs)


def _safe_render(tab_name: str, render_fn, *args, **kwargs):
    """Render a tab with error boundary so one failing tab doesn't crash the rest."""
    try:
        render_fn(*args, **kwargs)
    except Exception as e:
        st.error(f"Error rendering {tab_name}: {e}")
        st.exception(e)


def _clear_data_caches():
    """Clear file-level caches so data is re-parsed from source.

    Does NOT clear config-analysis.json (deep dive) or user preferences.
    """
    cache_dir = Path.home() / ".cache" / "claudealytics"
    for name in (
        "tool-index.json",
        "tool-stats.json",
        "token-mine.json",
        "cache-session-mine.json",
        "content-mine.json",
        "profile-scores.json",
        "full-report.json",
        "llm-profile-scores.json",
    ):
        p = cache_dir / name
        if p.exists():
            p.unlink()


@st.cache_data(ttl=300)
def load_stats():
    from claudealytics.analytics.parsers.stats_cache_parser import parse_stats_cache

    return parse_stats_cache()


@st.cache_data(ttl=300)
def load_all_executions():
    """Load and merge execution data from both logs and conversations."""
    from claudealytics.analytics.data_merger import (
        merge_agent_executions,
        merge_skill_executions,
    )
    from claudealytics.analytics.parsers.conversation_enricher import extract_tool_usage_detailed
    from claudealytics.analytics.parsers.execution_log_parser import (
        parse_agent_executions,
        parse_skill_executions,
    )

    log_agents = parse_agent_executions()
    log_skills = parse_skill_executions()
    conv_data = extract_tool_usage_detailed(limit=50000)
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
    from claudealytics.scanner.agent_scanner import scan_agents

    return scan_agents()


@st.cache_data(ttl=600)
def load_skill_definitions():
    """Load skill definitions from ~/.claude/skills/."""
    from claudealytics.scanner.skill_scanner import scan_skills

    return scan_skills()


@st.cache_data(ttl=600)
def load_tool_versions():
    """Load external tool version scan results. Longer TTL due to network calls."""
    from claudealytics.scanner.tool_version_scanner import scan_tool_versions

    return scan_tool_versions()


if __name__ == "__main__":
    main()
