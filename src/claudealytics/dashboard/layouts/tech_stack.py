"""Tech Stack tab: language distribution, frameworks, ecosystems, dev layers, and deep intelligence sub-tabs."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from claudealytics.analytics.aggregators.edit_semantics_aggregator import (
    compute_change_type_timeline,
    compute_edit_categories,
    compute_edit_complexity,
    compute_import_tracking,
)
from claudealytics.analytics.aggregators.library_aggregator import (
    compute_library_by_project,
    compute_library_installs,
    compute_library_timeline,
)
from claudealytics.analytics.aggregators.research_aggregator import (
    compute_documentation_sources,
    compute_grep_patterns,
    compute_research_volume,
    compute_search_topics,
)
from claudealytics.analytics.aggregators.stack_aggregator import (
    compute_database_signals,
    compute_ecosystem_signals,
    compute_framework_detection,
    compute_language_daily,
    compute_language_distribution,
    compute_layer_classification,
    compute_project_profiles,
)
from claudealytics.analytics.aggregators.testing_aggregator import (
    compute_test_by_project,
    compute_test_frameworks,
    compute_test_frequency,
    compute_test_position,
)
from claudealytics.analytics.parsers.content_miner import mine_content


@st.cache_data(ttl=300)
def _load_content_data():
    return mine_content(use_cache=True)


def render(stats):
    """Render the Tech Stack tab with sub-tabs."""
    dfs = _load_content_data()

    session_stats = dfs.get("session_stats", pd.DataFrame())
    tool_calls = dfs.get("tool_calls", pd.DataFrame())

    if tool_calls.empty:
        st.warning("No tool call data available. Ensure JSONL files exist in ~/.claude/projects/")
        return

    tab_stack, tab_libs, tab_tests, tab_research, tab_edits = st.tabs(
        [
            "Stack Overview",
            "Libraries & Dependencies",
            "Testing Discipline",
            "Research & Learning",
            "Code Change Semantics",
        ]
    )

    with tab_stack:
        _render_stack_overview(tool_calls, session_stats)
    with tab_libs:
        _render_libraries(tool_calls, session_stats)
    with tab_tests:
        _render_testing(tool_calls, session_stats)
    with tab_research:
        _render_research(tool_calls)
    with tab_edits:
        _render_edit_semantics(tool_calls)


# ── Stack Overview (existing content) ─────────────────────────────


def _render_stack_overview(tool_calls: pd.DataFrame, session_stats: pd.DataFrame):
    lang_dist = compute_language_distribution(tool_calls)
    lang_daily = compute_language_daily(tool_calls)
    eco_signals = compute_ecosystem_signals(tool_calls)
    frameworks = compute_framework_detection(tool_calls)
    layers = compute_layer_classification(tool_calls)
    db_signals = compute_database_signals(tool_calls)
    profiles = compute_project_profiles(tool_calls, session_stats)

    # ── KPI Row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        primary_lang = lang_dist.iloc[0]["language"] if not lang_dist.empty else "N/A"
        st.metric("Primary Language", primary_lang)

    with col2:
        n_langs = len(lang_dist[lang_dist["language"] != "Other"]) if not lang_dist.empty else 0
        st.metric("Languages Used", n_langs)

    with col3:
        if not eco_signals.empty:
            eco_agg = eco_signals.groupby("ecosystem")["signal_count"].sum().sort_values(ascending=False)
            primary_eco = eco_agg.index[0] if len(eco_agg) > 0 else "N/A"
        else:
            primary_eco = "N/A"
        st.metric("Primary Ecosystem", primary_eco)

    with col4:
        if not layers.empty:
            fe = int(layers[layers["layer"] == "Frontend"]["file_count"].sum())
            be = int(layers[layers["layer"] == "Backend"]["file_count"].sum())
            if be > 0:
                ratio_val = round(fe / be, 2)
                ratio = f"{ratio_val:.2f}:1 ({fe:,} / {be:,})"
            else:
                ratio = f"{fe}:0"
        else:
            ratio = "N/A"
        st.metric("FE:BE Ratio", ratio)

    st.divider()

    # ── Language Distribution
    if not lang_dist.empty:
        st.subheader(
            "Language Distribution", help="File reads, writes, and edits broken down by file extension/language."
        )
        top = lang_dist.head(15)
        fig = go.Figure()
        fig.add_trace(go.Bar(y=top["language"], x=top["reads"], name="Reads", orientation="h", marker_color="#636EFA"))
        fig.add_trace(
            go.Bar(y=top["language"], x=top["writes"], name="Writes", orientation="h", marker_color="#EF553B")
        )
        fig.add_trace(go.Bar(y=top["language"], x=top["edits"], name="Edits", orientation="h", marker_color="#00CC96"))
        fig.update_layout(
            barmode="group", height=400, yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=60, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Language Trend Over Time
    if not lang_daily.empty:
        st.subheader(
            "Language Trend Over Time",
            help="Weekly file activity per language. Shows which languages dominate work over time.",
        )
        lang_daily["date"] = pd.to_datetime(lang_daily["date"])
        weekly = lang_daily.groupby([pd.Grouper(key="date", freq="W"), "language"])["count"].sum().reset_index()
        if not weekly.empty:
            fig = px.line(weekly, x="date", y="count", color="language", title=None)
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=60, b=0))
            st.plotly_chart(fig, use_container_width=True)

    # ── Ecosystem + Frameworks
    col_eco, col_fw = st.columns(2)

    with col_eco:
        st.subheader(
            "Ecosystem Signals",
            help="Detected runtime/ecosystem keywords (e.g. node_modules, venv, .gradle) across all file paths.",
        )
        if not eco_signals.empty:
            eco_agg = eco_signals.groupby("ecosystem")["signal_count"].sum().sort_values(ascending=False).reset_index()
            fig = px.bar(eco_agg, x="signal_count", y="ecosystem", orientation="h", color="ecosystem")
            fig.update_layout(
                height=300, showlegend=False, margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(autorange="reversed")
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No ecosystem signals detected")

    with col_fw:
        st.subheader(
            "Frameworks Detected",
            help="Frameworks inferred from file patterns and import paths (e.g. React, FastAPI, Django).",
        )
        if not frameworks.empty:
            st.dataframe(
                frameworks[["framework", "file_count", "confidence"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "framework": "Framework",
                    "file_count": st.column_config.NumberColumn("Files", format="%d"),
                    "confidence": "Confidence",
                },
            )
        else:
            st.info("No frameworks detected")

    st.divider()

    # ── Development Layer Split
    col_layer, col_db = st.columns(2)

    with col_layer:
        st.subheader(
            "Development Layer Split",
            help="Frontend vs Backend vs Infrastructure file split, based on path and extension heuristics.",
        )
        if not layers.empty:
            fig = px.pie(layers, values="file_count", names="layer", hole=0.4)
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No layer data available")

    with col_db:
        st.subheader(
            "Database Signals",
            help="Database technologies detected from file paths, query strings, and import patterns.",
        )
        if not db_signals.empty:
            fig = px.bar(db_signals, x="signal_count", y="database", orientation="h", color="database")
            fig.update_layout(
                height=350, showlegend=False, margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(autorange="reversed")
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No database signals detected")

    # ── Project Profiles
    if not profiles.empty:
        st.divider()
        st.subheader(
            "Project Profiles",
            help="Per-project summary: primary language, frameworks detected, and layer distribution.",
        )
        st.dataframe(
            profiles,
            use_container_width=True,
            hide_index=True,
            column_config={
                "project": "Project",
                "primary_language": "Primary Language",
                "languages": "Top Languages",
                "frameworks": "Frameworks",
                "layer_split": "Layer Split",
                "session_count": st.column_config.NumberColumn("Sessions", format="%d"),
            },
        )


# ── Libraries & Dependencies ──────────────────────────────────────


def _render_libraries(tool_calls: pd.DataFrame, session_stats: pd.DataFrame):
    installs = compute_library_installs(tool_calls)
    timeline = compute_library_timeline(tool_calls)
    by_project = compute_library_by_project(tool_calls, session_stats)

    if installs.empty:
        st.info("No package install commands detected in your sessions.")
        return

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Unique Packages", int(installs["package"].nunique()))
    with col2:
        top_mgr = installs.groupby("pkg_manager")["count"].sum().idxmax()
        st.metric("Top Manager", top_mgr)
    with col3:
        total = int(installs["count"].sum())
        st.metric("Total Installs", total)
    with col4:
        n_projects = len(by_project) if not by_project.empty else 0
        st.metric("Projects", n_projects)

    st.divider()

    # Top packages bar chart
    st.subheader(
        "Most Installed Packages",
        help="Most frequently installed packages across all sessions, grouped by package manager.",
    )
    top = installs.head(20)
    fig = px.bar(
        top,
        x="count",
        y="package",
        orientation="h",
        color="pkg_manager",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(
        height=max(300, len(top) * 25), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=60, b=0)
    )
    st.plotly_chart(fig, use_container_width=True)

    # Timeline
    if not timeline.empty:
        st.subheader(
            "Install Activity Over Time",
            help="Daily package install commands over time, broken down by package manager.",
        )
        fig = px.line(timeline, x="date", y="count", color="pkg_manager")
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=60, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Project table
    if not by_project.empty:
        st.subheader("Packages by Project")
        st.dataframe(
            by_project,
            use_container_width=True,
            hide_index=True,
            column_config={
                "project": "Project",
                "packages": "Packages",
                "install_count": st.column_config.NumberColumn("Installs", format="%d"),
            },
        )


# ── Testing Discipline ────────────────────────────────────────────


def _render_testing(tool_calls: pd.DataFrame, session_stats: pd.DataFrame):
    frequency = compute_test_frequency(tool_calls)
    frameworks = compute_test_frameworks(tool_calls)
    position = compute_test_position(tool_calls)
    by_project = compute_test_by_project(tool_calls, session_stats)

    if frequency.empty and frameworks.empty:
        st.info("No test commands detected in your sessions.")
        return

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_tests = int(frequency["test_count"].sum()) if not frequency.empty else 0
        st.metric("Total Test Runs", total_tests)
    with col2:
        n_fw = len(frameworks) if not frameworks.empty else 0
        st.metric("Frameworks", n_fw)
    with col3:
        if not position.empty:
            total_pos = position["count"].sum()
            before = int(position[position["position"] == "Before code changes"]["count"].sum())
            tdd_pct = round(before / total_pos * 100) if total_pos > 0 else 0
        else:
            tdd_pct = 0
        st.metric("TDD %", f"{tdd_pct}%")
    with col4:
        if not frequency.empty:
            n_days = len(frequency)
            avg_per_day = round(total_tests / n_days, 1) if n_days > 0 else 0
        else:
            avg_per_day = 0
        st.metric("Tests/Day", avg_per_day)

    st.divider()

    # Frequency chart
    if not frequency.empty:
        st.subheader(
            "Test Frequency Over Time", help="Daily count of test runner invocations (pytest, jest, cargo test, etc.)."
        )
        frequency["date"] = pd.to_datetime(frequency["date"])
        fig = px.bar(frequency, x="date", y="test_count", color_discrete_sequence=["#636EFA"])
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Framework + Position side by side
    col_fw, col_pos = st.columns(2)

    with col_fw:
        st.subheader(
            "Test Frameworks",
            help="Distribution of test frameworks detected from Bash commands (pytest, jest, mocha, etc.).",
        )
        if not frameworks.empty:
            fig = px.pie(frameworks, values="count", names="framework", hole=0.4)
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No framework data")

    with col_pos:
        st.subheader(
            "Test Timing", help="Whether tests were run before or after code changes — a proxy for TDD discipline."
        )
        if not position.empty:
            fig = px.pie(
                position, values="count", names="position", hole=0.4, color_discrete_sequence=["#00CC96", "#EF553B"]
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No position data")

    # Project table
    if not by_project.empty:
        st.subheader("Testing by Project")
        st.dataframe(
            by_project,
            use_container_width=True,
            hide_index=True,
            column_config={
                "project": "Project",
                "test_count": st.column_config.NumberColumn("Test Runs", format="%d"),
                "sessions": st.column_config.NumberColumn("Sessions", format="%d"),
            },
        )


# ── Research & Learning ───────────────────────────────────────────


def _render_research(tool_calls: pd.DataFrame):
    volume = compute_research_volume(tool_calls)
    topics = compute_search_topics(tool_calls)
    sources = compute_documentation_sources(tool_calls)
    grep_pats = compute_grep_patterns(tool_calls)

    if volume.empty and topics.empty and grep_pats.empty:
        st.info("No research activity (WebSearch, WebFetch, Grep) detected.")
        return

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_searches = int(volume["searches"].sum()) if not volume.empty else 0
        st.metric("Web Searches", total_searches)
    with col2:
        total_fetches = int(volume["fetches"].sum()) if not volume.empty else 0
        st.metric("Pages Fetched", total_fetches)
    with col3:
        top_domain = sources.iloc[0]["domain"] if not sources.empty else "N/A"
        st.metric("Top Domain", top_domain)
    with col4:
        n_patterns = len(grep_pats) if not grep_pats.empty else 0
        st.metric("Unique Grep Patterns", n_patterns)

    st.divider()

    # Volume line chart
    if not volume.empty:
        st.subheader(
            "Research Volume Over Time",
            help="Daily WebSearch, WebFetch, and Grep tool calls — indicators of research and information-gathering activity.",
        )
        volume["date"] = pd.to_datetime(volume["date"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=volume["date"], y=volume["searches"], name="Searches", mode="lines"))
        fig.add_trace(go.Scatter(x=volume["date"], y=volume["fetches"], name="Fetches", mode="lines"))
        fig.add_trace(go.Scatter(x=volume["date"], y=volume["greps"], name="Greps", mode="lines"))
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=60, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Search topics + Domains side by side
    col_q, col_d = st.columns(2)

    with col_q:
        st.subheader(
            "Top Search Queries", help="Most frequent search query strings passed to WebSearch across all sessions."
        )
        if not topics.empty:
            top = topics.head(15)
            fig = px.bar(top, x="count", y="query", orientation="h", color_discrete_sequence=["#636EFA"])
            fig.update_layout(
                height=max(300, len(top) * 25), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=10, b=0)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No web searches recorded")

    with col_d:
        st.subheader(
            "Documentation Sources",
            help="Top domains fetched via WebFetch — shows which documentation sites are most referenced.",
        )
        if not sources.empty:
            top = sources.head(15)
            fig = px.bar(top, x="count", y="domain", orientation="h", color_discrete_sequence=["#EF553B"])
            fig.update_layout(
                height=max(300, len(top) * 25), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=10, b=0)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No page fetches recorded")

    # Grep patterns table
    if not grep_pats.empty:
        st.subheader(
            "Top Grep Patterns",
            help="Most common regex patterns used in Grep/ripgrep tool calls — reveals what code structures are frequently searched.",
        )
        st.dataframe(
            grep_pats.head(20),
            use_container_width=True,
            hide_index=True,
            column_config={
                "pattern": "Pattern",
                "count": st.column_config.NumberColumn("Count", format="%d"),
            },
        )


# ── Code Change Semantics ─────────────────────────────────────────


def _render_edit_semantics(tool_calls: pd.DataFrame):
    categories = compute_edit_categories(tool_calls)
    complexity = compute_edit_complexity(tool_calls)
    imports = compute_import_tracking(tool_calls)
    timeline = compute_change_type_timeline(tool_calls)

    if categories.empty:
        st.info("No classified edit operations detected.")
        return

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total = int(categories["count"].sum())
        st.metric("Classified Edits", total)
    with col2:
        dominant = categories.iloc[0]["category"] if not categories.empty else "N/A"
        st.metric("Dominant Category", dominant)
    with col3:
        if not complexity.empty:
            avg_d = round(complexity["avg_delta"].mean(), 1)
        else:
            avg_d = 0
        st.metric("Avg Edit Delta", avg_d)
    with col4:
        n_imports = int(imports["import_count"].sum()) if not imports.empty else 0
        st.metric("Import Additions", n_imports)

    st.divider()

    # Categories pie + Complexity line
    col_cat, col_cplx = st.columns(2)

    with col_cat:
        st.subheader(
            "Edit Categories",
            help="Semantic classification of edits: feature additions, bug fixes, refactors, config changes, etc.",
        )
        fig = px.pie(categories, values="count", names="category", hole=0.4)
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col_cplx:
        st.subheader(
            "Edit Complexity",
            help="Average line-delta per edit operation over time, overlaid with total edit count. Higher delta = larger changes.",
        )
        if not complexity.empty:
            complexity["date"] = pd.to_datetime(complexity["date"])
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(x=complexity["date"], y=complexity["avg_delta"], name="Avg Delta", mode="lines+markers")
            )
            fig.add_trace(go.Bar(x=complexity["date"], y=complexity["edit_count"], name="Edit Count", opacity=0.3))
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No edit complexity data")

    # Change type timeline
    if not timeline.empty:
        st.subheader(
            "Change Types Over Time",
            help="Weekly breakdown of edit categories — shows how the mix of features, fixes, and refactors evolves.",
        )
        timeline["date"] = pd.to_datetime(timeline["date"])
        weekly = timeline.groupby([pd.Grouper(key="date", freq="W"), "category"])["count"].sum().reset_index()
        if not weekly.empty:
            fig = px.line(weekly, x="date", y="count", color="category")
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=60, b=0))
            st.plotly_chart(fig, use_container_width=True)

    # Import tracking
    if not imports.empty:
        st.subheader(
            "Import Additions by Language",
            help="Count of new import/require statements added across sessions, by language — tracks dependency growth.",
        )
        fig = px.bar(imports, x="import_count", y="language", orientation="h", color_discrete_sequence=["#00CC96"])
        fig.update_layout(
            height=max(250, len(imports) * 30), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=0, t=10, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)
