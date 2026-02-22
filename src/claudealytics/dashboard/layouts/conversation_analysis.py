"""Conversation Analysis tab: deep content analysis with 6 sub-tabs."""

from __future__ import annotations

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from claudealytics.analytics.parsers.content_miner import mine_content
from claudealytics.analytics.aggregators.intervention_aggregator import (
    compute_autonomy, compute_intervention_daily, compute_human_chars,
)
from claudealytics.analytics.aggregators.behavior_aggregator import (
    compute_thinking_trends, compute_output_profile, compute_decision_trends,
)
from claudealytics.analytics.aggregators.loop_aggregator import (
    compute_discipline, compute_daily_discipline, compute_tool_type_daily,
)
from claudealytics.analytics.aggregators.flow_aggregator import (
    compute_complexity, compute_sidechain_daily, compute_cwd_switches,
)
from claudealytics.analytics.aggregators.file_activity_aggregator import (
    compute_files_per_session, compute_hot_files, compute_cooccurrence, compute_change_volume,
)
from claudealytics.analytics.aggregators.error_aggregator import (
    compute_tool_error_rate, compute_error_timeline, compute_error_sessions, compute_recovery_stats,
)


def render(stats):
    """Render the Conversation Analysis tab."""
    dfs = _load_content_data()

    session_stats = dfs.get("session_stats", pd.DataFrame())
    tool_calls = dfs.get("tool_calls", pd.DataFrame())
    error_results = dfs.get("error_results", pd.DataFrame())
    daily_stats = dfs.get("daily_stats", pd.DataFrame())
    human_lengths = dfs.get("human_message_lengths", pd.DataFrame())

    if session_stats.empty and daily_stats.empty:
        st.warning("No conversation content data available. Ensure JSONL files exist in ~/.claude/projects/")
        return

    tab_interventions, tab_behavior, tab_loops, tab_flow, tab_files, tab_errors = st.tabs([
        "Human Interventions",
        "Assistant Behavior",
        "Agentic Loops",
        "Conversation Flow",
        "File Activity",
        "Errors & Recovery",
    ])

    with tab_interventions:
        _render_interventions(session_stats, daily_stats, human_lengths)

    with tab_behavior:
        _render_behavior(session_stats, daily_stats)

    with tab_loops:
        _render_loops(session_stats, tool_calls, error_results)

    with tab_flow:
        _render_flow(session_stats, daily_stats)

    with tab_files:
        _render_files(session_stats, tool_calls)

    with tab_errors:
        _render_errors(session_stats, daily_stats, tool_calls, error_results)


# ── Sub-tab 1: Human Interventions ──────────────────────────────

def _render_interventions(session_stats: pd.DataFrame, daily_stats: pd.DataFrame,
                          human_lengths: pd.DataFrame):
    autonomy_df = compute_autonomy(session_stats)
    intervention_daily = compute_intervention_daily(daily_stats)
    human_chars = compute_human_chars(session_stats)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not session_stats.empty:
        total_human = int(session_stats["human_msg_count"].sum())
        total_assistant = int(session_stats["assistant_msg_count"].sum())
        total = total_human + total_assistant
        avg_autonomy = round(total_assistant / total * 100, 1) if total > 0 else 0
        corrections = int(session_stats["intervention_correction"].sum())
        steering_rate = round(corrections / total_human * 100, 1) if total_human > 0 else 0
        col1.metric("Total Human Messages", f"{total_human:,}")
        col2.metric("Avg Autonomy Ratio", f"{avg_autonomy}%")
        col3.metric("Steering Rate", f"{steering_rate}%",
                     help="% of human messages that are corrections")
        col4.metric("Correction Count", f"{corrections:,}")

    st.divider()

    # Date filter
    filtered_daily, date_from, date_to = _date_filter(daily_stats, "interv")

    # Autonomy ratio over time
    if not autonomy_df.empty:
        st.subheader("Autonomy Ratio Over Time", help="Ratio of assistant messages to total messages. Higher = Claude works more independently between human inputs.")
        daily_autonomy = autonomy_df.groupby("date").agg(
            avg_ratio=("autonomy_ratio", "mean"),
        ).reset_index()
        if not daily_autonomy.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=daily_autonomy["date"], y=daily_autonomy["avg_ratio"],
                mode="lines+markers", name="Avg Autonomy Ratio",
                line=dict(color="#14b8a6", width=2), marker=dict(size=4),
            ))
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=0),
                              yaxis_title="Autonomy Ratio", xaxis_title="Date",
                              yaxis=dict(range=[0, 1.05]))
            st.plotly_chart(fig, use_container_width=True)

    # Intervention type distribution
    if not session_stats.empty:
        st.subheader("Intervention Type Distribution", help="Breakdown of human messages by intent: corrections fix mistakes, approvals confirm actions, guidance steers direction, new instructions change goals.")
        type_counts = {
            "Correction": int(session_stats["intervention_correction"].sum()),
            "Approval": int(session_stats["intervention_approval"].sum()),
            "Guidance": int(session_stats["intervention_guidance"].sum()),
            "New Instruction": int(session_stats["intervention_new_instruction"].sum()),
        }
        type_df = pd.DataFrame(list(type_counts.items()), columns=["Type", "Count"])
        type_df = type_df[type_df["Count"] > 0]
        if not type_df.empty:
            fig = px.pie(type_df, values="Count", names="Type",
                         color_discrete_sequence=["#ef4444", "#22c55e", "#6366f1", "#f59e0b"])
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)

    # Intervention type trend
    if not filtered_daily.empty:
        st.subheader("Intervention Type Trend", help="Daily count of human message types: corrections (fixing mistakes), approvals (confirming actions), guidance (directing work), new instructions (changing goals).")
        interv_cols = [c for c in ["intervention_correction", "intervention_approval",
                                    "intervention_guidance", "intervention_new_instruction"]
                       if c in filtered_daily.columns]
        if interv_cols:
            fig = go.Figure()
            colors = {"intervention_correction": "#ef4444", "intervention_approval": "#22c55e",
                      "intervention_guidance": "#6366f1", "intervention_new_instruction": "#f59e0b"}
            names = {"intervention_correction": "Correction", "intervention_approval": "Approval",
                     "intervention_guidance": "Guidance", "intervention_new_instruction": "New Instruction"}
            for col in interv_cols:
                fig.add_trace(go.Scatter(
                    x=filtered_daily["date"], y=filtered_daily[col],
                    mode="lines+markers", name=names.get(col, col),
                    line=dict(color=colors.get(col)), marker=dict(size=4),
                ))
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=60, b=0),
                              yaxis_title="Count", xaxis_title="Date",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig, use_container_width=True)

    # Session autonomy box plot by project
    if not autonomy_df.empty and len(autonomy_df) > 1:
        st.subheader("Session Autonomy", help="Autonomy ratio distribution per project (median, quartiles, outliers). Higher = Claude works more independently between human inputs.")
        box_df = autonomy_df[autonomy_df["human_msg_count"] >= 2].copy()
        if not box_df.empty:
            # Sort projects by session count (most data first)
            project_counts = box_df.groupby("project").size().sort_values(ascending=False)
            max_count = int(project_counts.max())
            min_threshold = st.slider(
                "Min sessions per project", 1, max(max_count, 2), value=min(2, max_count),
                key="autonomy_min_sessions",
            )
            qualifying = project_counts[project_counts >= min_threshold].index.tolist()
            box_df = box_df[box_df["project"].isin(qualifying)]
            if not box_df.empty:
                fig = px.box(
                    box_df, x="project", y="autonomy_ratio",
                    color="project",
                    category_orders={"project": qualifying},
                    labels={"project": "Project", "autonomy_ratio": "Autonomy Ratio"},
                    points="outliers",
                )
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=0),
                                  showlegend=False)
                st.plotly_chart(fig, use_container_width=True)


# ── Sub-tab 2: Assistant Behavior ───────────────────────────────

def _render_behavior(session_stats: pd.DataFrame, daily_stats: pd.DataFrame):
    thinking_trends = compute_thinking_trends(daily_stats)
    output_profile = compute_output_profile(session_stats)
    decision_trends = compute_decision_trends(daily_stats)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not session_stats.empty:
        total_assistant = int(session_stats["assistant_msg_count"].sum())
        total_text = int(session_stats["total_text_length_assistant"].sum())
        avg_output = round(total_text / total_assistant) if total_assistant > 0 else 0
        thinking_msgs = int(session_stats["thinking_message_count"].sum())
        thinking_pct = round(thinking_msgs / total_assistant * 100, 1) if total_assistant > 0 else 0
        self_corrections = int(session_stats["self_correction_count"].sum())
        total_thinking = int(session_stats["total_thinking_length"].sum())
        thinking_ratio = round(total_thinking / (total_text + total_thinking) * 100, 1) if (total_text + total_thinking) > 0 else 0

        col1.metric("Avg Output Length", f"{avg_output:,} chars")
        col2.metric("Thinking Usage", f"{thinking_pct}%")
        col3.metric("Self-Corrections", f"{self_corrections:,}")
        col4.metric("Thinking-to-Output", f"{thinking_ratio}%")

    st.divider()
    filtered_daily, _, _ = _date_filter(daily_stats, "behav")

    # Thinking usage trend
    if not thinking_trends.empty:
        st.subheader("Thinking Usage Trend", help="Number of thinking blocks (internal reasoning) and their average length per day.")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=thinking_trends["date"], y=thinking_trends["thinking_blocks"],
            name="Thinking Blocks", marker_color="rgba(99,102,241,0.6)",
        ))
        fig.add_trace(go.Scatter(
            x=thinking_trends["date"], y=thinking_trends["avg_thinking_length"],
            mode="lines+markers", name="Avg Length",
            line=dict(color="#f59e0b", width=2), yaxis="y2",
        ))
        fig.update_layout(
            height=350, margin=dict(l=20, r=60, t=60, b=0),
            yaxis=dict(title="Block Count"),
            yaxis2=dict(title="Avg Length (chars)", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Decision language frequency
    if not decision_trends.empty:
        st.subheader("Decision Language Frequency", help="Count of explicit decision markers, self-corrections, and reasoning phrases in assistant output.")
        totals = {
            "Decision": int(decision_trends["decision_count"].sum()) if "decision_count" in decision_trends.columns else 0,
            "Self-Correction": int(decision_trends["self_correction_count"].sum()) if "self_correction_count" in decision_trends.columns else 0,
            "Reasoning Marker": int(decision_trends["reasoning_marker_count"].sum()) if "reasoning_marker_count" in decision_trends.columns else 0,
        }
        dec_df = pd.DataFrame(list(totals.items()), columns=["Pattern", "Count"])
        dec_df = dec_df[dec_df["Count"] > 0]
        if not dec_df.empty:
            fig = px.bar(dec_df, x="Count", y="Pattern", orientation="h",
                         color_discrete_sequence=["#8b5cf6"])
            fig.update_layout(height=200, margin=dict(l=20, r=20, t=20, b=0))
            st.plotly_chart(fig, use_container_width=True)

    # Output volume trend
    if not filtered_daily.empty:
        st.subheader("Output Volume Trend", help="Total character count of text output per day, split by assistant vs human.")
        fig = go.Figure()
        if "total_text_length_assistant" in filtered_daily.columns:
            fig.add_trace(go.Scatter(
                x=filtered_daily["date"],
                y=filtered_daily["total_text_length_assistant"],
                mode="lines+markers", name="Assistant",
                line=dict(color="#6366f1"), marker=dict(size=4),
            ))
        if "total_text_length_human" in filtered_daily.columns:
            fig.add_trace(go.Scatter(
                x=filtered_daily["date"],
                y=filtered_daily["total_text_length_human"],
                mode="lines+markers", name="Human",
                line=dict(color="#22c55e"), marker=dict(size=4),
            ))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=60, b=0),
                          yaxis_title="Total Text Length (chars)", xaxis_title="Date",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)


# ── Sub-tab 3: Agentic Loops ───────────────────────────────────

def _render_loops(session_stats: pd.DataFrame, tool_calls: pd.DataFrame,
                  error_results: pd.DataFrame):
    discipline = compute_daily_discipline(session_stats)
    tool_daily = compute_tool_type_daily(tool_calls)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not session_stats.empty:
        total_tools = int(session_stats["total_tool_calls"].sum())
        total_assistant = int(session_stats["assistant_msg_count"].sum())
        avg_tools_per_turn = round(total_tools / total_assistant, 1) if total_assistant > 0 else 0
        col1.metric("Avg Tools/Turn", f"{avg_tools_per_turn}")

    if not tool_calls.empty and "tool_name" in tool_calls.columns:
        most_common = tool_calls["tool_name"].value_counts().index[0]
        col2.metric("Most Common Tool", most_common)

    if not session_stats.empty:
        total_writes = int(session_stats["writes_total_count"].sum())
        total_rbw = int(session_stats["writes_with_prior_read_count"].sum())
        rbw_pct = round(total_rbw / total_writes * 100, 1) if total_writes > 0 else 0
        col3.metric("Read-Before-Write %", f"{rbw_pct}%")

        total_errors = int(session_stats["total_errors"].sum())
        total_tool_calls = int(session_stats["total_tool_calls"].sum())
        error_rate = round(total_errors / total_tool_calls * 100, 1) if total_tool_calls > 0 else 0
        col4.metric("Error Rate", f"{error_rate}%")

    st.divider()

    # Tool usage by type (stacked area)
    if not tool_daily.empty:
        st.subheader("Tool Usage by Type", help="Daily tool call counts grouped by tool name (Read, Write, Edit, Bash, etc.).")
        # Pivot for stacked area
        pivot = tool_daily.pivot_table(index="date", columns="tool_name", values="count", fill_value=0)
        fig = go.Figure()
        colors = ["#6366f1", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6",
                  "#22c55e", "#ec4899", "#06b6d4", "#84cc16", "#a855f7"]
        for i, col in enumerate(pivot.columns):
            fig.add_trace(go.Scatter(
                x=pivot.index, y=pivot[col],
                mode="lines+markers", name=col,
                line=dict(color=colors[i % len(colors)]), marker=dict(size=3),
            ))
        fig.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=0),
                          yaxis_title="Tool Calls", xaxis_title="Date",
                          legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5))
        st.plotly_chart(fig, use_container_width=True)

    # Read-before-write discipline trend
    if not discipline.empty and "read_before_write_pct" in discipline.columns:
        st.subheader("Read-Before-Write Discipline", help="Percentage of file writes preceded by a read of the same file. Measures whether Claude reads before editing, avoiding blind overwrites.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=discipline["date"], y=discipline["read_before_write_pct"],
            mode="lines+markers", name="Discipline %",
            line=dict(color="#22c55e", width=2), marker=dict(size=4),
        ))
        fig.add_hline(y=80, line_dash="dash", line_color="rgba(100,100,100,0.3)",
                       annotation_text="80% target")
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=0),
                          yaxis_title="Read-Before-Write %", yaxis=dict(range=[0, 105]))
        st.plotly_chart(fig, use_container_width=True)


# ── Sub-tab 4: Conversation Flow ───────────────────────────────

def _render_flow(session_stats: pd.DataFrame, daily_stats: pd.DataFrame):
    complexity = compute_complexity(session_stats)
    sidechain_daily = compute_sidechain_daily(session_stats)
    cwd_switches = compute_cwd_switches(session_stats)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not complexity.empty:
        avg_complexity = round(complexity["complexity_score"].mean(), 3)
        col1.metric("Avg Complexity Score", f"{avg_complexity}")

    if not session_stats.empty:
        avg_msgs = round(session_stats["total_messages"].mean(), 1)
        col2.metric("Avg Messages/Session", f"{avg_msgs}")

        total_sidechain = int(session_stats["sidechain_count"].sum())
        total_msgs = int(session_stats["total_messages"].sum())
        sidechain_pct = round(total_sidechain / total_msgs * 100, 1) if total_msgs > 0 else 0
        col3.metric("Sidechain %", f"{sidechain_pct}%")

        avg_cwd = round(session_stats["cwd_switch_count"].mean(), 1) if "cwd_switch_count" in session_stats.columns else 0
        col4.metric("Avg CWD Switches", f"{avg_cwd}")

    st.divider()

    # Session complexity distribution
    if not complexity.empty:
        st.subheader("Session Complexity Distribution", help="Weighted composite score (0-1): messages (20%) + tool calls (30%) + errors (15%) + unique files (20%) + sidechains (15%). Min-max normalized per component.")
        fig = px.histogram(complexity, x="complexity_score", nbins=40,
                           color_discrete_sequence=["#6366f1"],
                           labels={"complexity_score": "Complexity Score"})
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Complexity over time
    if not complexity.empty:
        st.subheader("Complexity Over Time", help="Average session complexity score per day.")
        daily_comp = complexity.groupby("date").agg(
            avg_score=("complexity_score", "mean"),
            session_count=("session_id", "count"),
        ).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=daily_comp["date"], y=daily_comp["avg_score"],
            mode="lines+markers", name="Avg Complexity",
            line=dict(color="#8b5cf6", width=2), marker=dict(size=4),
        ))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=0),
                          yaxis_title="Avg Complexity Score")
        st.plotly_chart(fig, use_container_width=True)

    # Sidechain usage trend
    if not sidechain_daily.empty:
        st.subheader("Sidechain Usage Trend", help="Count of sidechain (sub-agent/Task tool) messages per day.")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=sidechain_daily["date"], y=sidechain_daily["sidechain_count"],
            name="Sidechain Messages", marker_color="rgba(139,92,246,0.6)",
        ))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=0),
                          yaxis_title="Sidechain Messages")
        st.plotly_chart(fig, use_container_width=True)

    # Top complex sessions table
    if not complexity.empty:
        st.subheader("Top 20 Most Complex Sessions")
        top_complex = complexity.nlargest(20, "complexity_score")
        display_cols = ["session_id", "date", "project", "complexity_score",
                        "total_messages", "total_tool_calls", "total_errors",
                        "unique_files_touched"]
        display_cols = [c for c in display_cols if c in top_complex.columns]
        display = top_complex[display_cols].copy()
        if "date" in display.columns:
            display["date"] = display["date"].dt.strftime("%Y-%m-%d")
        if "session_id" in display.columns:
            display["session_id"] = display["session_id"].str[:12] + "..."
        st.dataframe(display, hide_index=True, use_container_width=True)


# ── Sub-tab 5: File Activity ───────────────────────────────────

def _render_files(session_stats: pd.DataFrame, tool_calls: pd.DataFrame):
    files_per_session = compute_files_per_session(session_stats)
    hot_files = compute_hot_files(tool_calls)
    cooccurrence = compute_cooccurrence(tool_calls)
    change_volume = compute_change_volume(tool_calls)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not session_stats.empty:
        total_files = int(session_stats["unique_files_touched"].sum())
        col1.metric("Total File Touches", f"{total_files:,}")

    if not hot_files.empty:
        top_file = hot_files.iloc[0]["file_path"]
        # Show just the filename
        short = top_file.split("/")[-1] if "/" in top_file else top_file
        col2.metric("Most-Edited File", short, help=top_file)

    if not session_stats.empty:
        avg_files = round(session_stats["unique_files_touched"].mean(), 1)
        col3.metric("Avg Files/Session", f"{avg_files}")

        total_edits = int(session_stats["total_edits"].sum())
        total_writes = int(session_stats["total_writes"].sum())
        col4.metric("Total Edits + Writes", f"{total_edits + total_writes:,}")

    st.divider()

    # Files per session histogram
    if not files_per_session.empty:
        st.subheader("Files Per Session", help="Distribution of unique file counts per session. Shows typical breadth of file changes per conversation.")
        fig = px.histogram(files_per_session, x="unique_files_touched", nbins=30,
                           color_discrete_sequence=["#14b8a6"],
                           labels={"unique_files_touched": "Unique Files"})
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Daily code change volume
    if not change_volume.empty:
        st.subheader("Daily Code Change Volume", help="Daily count of Edit vs Write tool calls, showing code modification activity over time.")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=change_volume["date"], y=change_volume["edit_count"],
            name="Edits", marker_color="rgba(99,102,241,0.6)",
        ))
        fig.add_trace(go.Bar(
            x=change_volume["date"], y=change_volume["write_count"],
            name="Writes", marker_color="rgba(20,184,166,0.6)",
        ))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=60, b=0),
                          barmode="group", yaxis_title="Operations",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

    # File co-access pairs
    if not cooccurrence.empty:
        st.subheader("File Co-Access Pairs (Top 20)", help="File pairs most frequently accessed in the same session, indicating coupled components or common change patterns.")
        top_co = cooccurrence.head(20).copy()
        top_co["file_a"] = top_co["file_a"].apply(lambda p: "/".join(p.split("/")[-2:]) if "/" in p else p)
        top_co["file_b"] = top_co["file_b"].apply(lambda p: "/".join(p.split("/")[-2:]) if "/" in p else p)
        st.dataframe(
            top_co.rename(columns={"file_a": "File A", "file_b": "File B", "sessions": "Sessions"}),
            hide_index=True, use_container_width=True,
        )

    # Hot files (collapsed)
    if not hot_files.empty:
        with st.expander("Most-Accessed Files (Top 20)", expanded=False):
            top20 = hot_files.head(20).copy()
            top20["short_path"] = top20["file_path"].apply(
                lambda p: "/".join(p.split("/")[-3:]) if p.count("/") > 3 else p
            )
            fig = px.bar(top20, x="total", y="short_path", orientation="h",
                         color_discrete_sequence=["#6366f1"],
                         labels={"total": "Access Count", "short_path": "File"})
            fig.update_layout(height=max(300, len(top20) * 25 + 80),
                              margin=dict(l=20, r=20, t=20, b=0),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)


# ── Sub-tab 6: Errors & Recovery ───────────────────────────────

def _render_errors(session_stats: pd.DataFrame, daily_stats: pd.DataFrame,
                   tool_calls: pd.DataFrame, error_results: pd.DataFrame):
    error_rate_df = compute_tool_error_rate(tool_calls, error_results)
    error_timeline = compute_error_timeline(daily_stats)
    error_sessions = compute_error_sessions(session_stats)
    recovery = compute_recovery_stats(session_stats)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)
    if not session_stats.empty:
        total_tools = int(session_stats["total_tool_calls"].sum())
        total_errors = recovery["total_errors"]
        overall_rate = round(total_errors / total_tools * 100, 2) if total_tools > 0 else 0
        col1.metric("Overall Error Rate", f"{overall_rate}%")
        col2.metric("Total Errors", f"{total_errors:,}")

    if not error_rate_df.empty:
        # Most error-prone = highest total calls (since we can't track per-tool errors easily)
        most_used = error_rate_df.iloc[0]["tool_name"] if len(error_rate_df) > 0 else "N/A"
        col3.metric("Most-Used Tool", most_used)

    col4.metric("Avg Errors/Session", f"{recovery['avg_errors_per_session']}")

    st.divider()

    # Error rate by tool (total calls)
    if not error_rate_df.empty:
        st.subheader("Tool Call Volume", help="Total number of calls per tool across all sessions, showing which tools Claude uses most.")
        top_tools = error_rate_df.head(15)
        fig = px.bar(top_tools, x="total_calls", y="tool_name", orientation="h",
                     color_discrete_sequence=["#6366f1"],
                     labels={"total_calls": "Total Calls", "tool_name": "Tool"})
        fig.update_layout(height=max(250, len(top_tools) * 25 + 60),
                          margin=dict(l=20, r=20, t=20, b=0),
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    # Error timeline
    if not error_timeline.empty:
        st.subheader("Error Timeline", help="Daily error count and error rate (errors / total tool calls).")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=error_timeline["date"], y=error_timeline["total_errors"],
            name="Errors", marker_color="rgba(239,68,68,0.6)",
        ))
        if "error_rate" in error_timeline.columns:
            fig.add_trace(go.Scatter(
                x=error_timeline["date"], y=error_timeline["error_rate"],
                mode="lines+markers", name="Error Rate %",
                line=dict(color="#f59e0b", width=2), yaxis="y2",
            ))
        fig.update_layout(
            height=350, margin=dict(l=20, r=60, t=60, b=0),
            yaxis=dict(title="Error Count"),
            yaxis2=dict(title="Error Rate (%)", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Error sessions table
    if not error_sessions.empty:
        st.subheader("Sessions with Most Errors", help="Sessions ranked by total error count, showing which conversations had the most tool failures.")
        display = error_sessions.copy()
        if "date" in display.columns:
            display["date"] = display["date"].dt.strftime("%Y-%m-%d")
        if "session_id" in display.columns:
            display["session_id"] = display["session_id"].str[:12] + "..."
        if "unique_tools" in display.columns:
            display["unique_tools"] = display["unique_tools"].apply(
                lambda x: ", ".join(x) if isinstance(x, list) else str(x)
            )
        st.dataframe(display, hide_index=True, use_container_width=True)


# ── Shared helpers ──────────────────────────────────────────────

def _date_filter(daily_stats: pd.DataFrame, key_prefix: str):
    """Render date filter and return filtered daily_stats."""
    if daily_stats.empty or "date" not in daily_stats.columns:
        return daily_stats, None, None

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=daily_stats["date"].min(),
                                   key=f"{key_prefix}_from")
    with col2:
        date_to = st.date_input("To", value=daily_stats["date"].max(),
                                 key=f"{key_prefix}_to")

    mask = (daily_stats["date"] >= pd.to_datetime(date_from)) & \
           (daily_stats["date"] <= pd.to_datetime(date_to))
    return daily_stats[mask], date_from, date_to


@st.cache_data(ttl=300)
def _load_content_data():
    return mine_content(use_cache=True)
