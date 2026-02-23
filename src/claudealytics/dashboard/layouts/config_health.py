"""Config Health tab: size tracking and history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from claudealytics.models.schemas import AgentExecution, SkillExecution
from claudealytics.scanner.config_size_scanner import (
    load_history,
    measure_all_config_files,
    record_snapshot,
)

# Color map for file types
TYPE_COLORS = {
    "agent": "#7c3aed",  # purple
    "skill": "#ec4899",  # pink
    "global_claude_md": "#4f46e5",  # indigo
    "project_claude_md": "#6366f1",  # lighter indigo
}

TYPE_LABELS = {
    "agent": "Agent",
    "skill": "Skill",
    "global_claude_md": "Global CLAUDE.md",
    "project_claude_md": "Project CLAUDE.md",
}


def render(
    agent_execs: list[AgentExecution] | None = None,
    skill_execs: list[SkillExecution] | None = None,
):
    """Render the Config Health tab."""
    # Auto-record a snapshot (1-hour dedup handled internally)
    record_snapshot()
    files = measure_all_config_files()

    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Config Files", len(files))
    with col2:
        total_lines = sum(f.lines for f in files)
        st.metric("Total Lines", f"{total_lines:,}")
    with col3:
        avg_lines = total_lines // max(len(files), 1)
        st.metric("Avg Lines / File", avg_lines)
    with col4:
        total_bytes = sum(f.bytes for f in files)
        if total_bytes >= 1024 * 1024:
            st.metric("Total Size", f"{total_bytes / (1024 * 1024):.1f} MB")
        else:
            st.metric("Total Size", f"{total_bytes / 1024:.1f} KB")

    st.divider()

    # Sub-tabs
    tab_sizes, tab_history = st.tabs(
        [
            "📊 Current Sizes",
            "📈 Size History",
        ]
    )

    with tab_sizes:
        _render_current_sizes(files, agent_execs or [], skill_execs or [])

    with tab_history:
        _render_size_history()


def _render_current_sizes(
    files,
    agent_execs: list[AgentExecution],
    skill_execs: list[SkillExecution],
):
    """Render the Current Sizes sub-tab."""
    if not files:
        st.info("No config files found.")
        return

    df = pd.DataFrame([f.model_dump() for f in files])
    df["type_label"] = df["file_type"].map(TYPE_LABELS)

    # Build last-used lookup from execution data
    last_used_map: dict[str, str] = {}
    for ex in agent_execs:
        key = ex.agent_type or ex.agent or ""
        if key and ex.timestamp:
            if key not in last_used_map or ex.timestamp > last_used_map[key]:
                last_used_map[key] = ex.timestamp
    for ex in skill_execs:
        key = ex.skill_name or ex.skill or ""
        if key and ex.timestamp:
            if key not in last_used_map or ex.timestamp > last_used_map[key]:
                last_used_map[key] = ex.timestamp

    # Horizontal bar chart: line count by file, colored by type
    st.subheader(
        "Line Count by File",
        help="Current line counts for all config files (agents, skills, CLAUDE.md). Larger files may need trimming.",
    )
    df_sorted = df.sort_values("lines", ascending=True)

    # Create unique labels to prevent Plotly from aggregating duplicate names
    name_counts: dict[str, int] = {}
    unique_labels = []
    for _, row in df_sorted.iterrows():
        n = row["name"]
        name_counts[n] = name_counts.get(n, 0) + 1
        if name_counts[n] > 1:
            unique_labels.append(f"{n} ({row['file_type']})")
        else:
            unique_labels.append(n)
    df_sorted = df_sorted.copy()
    df_sorted["label"] = unique_labels

    fig_bar = px.bar(
        df_sorted,
        y="label",
        x="lines",
        color="type_label",
        orientation="h",
        hover_data=["path", "bytes"],
        color_discrete_map={v: TYPE_COLORS[k] for k, v in TYPE_LABELS.items()},
        labels={"label": "File", "lines": "Lines", "type_label": "Type"},
    )
    fig_bar.update_layout(height=max(400, len(df_sorted) * 28), yaxis_title="")
    st.plotly_chart(fig_bar, use_container_width=True)

    # Table with type filter
    st.subheader("All Config Files", help="Full list of discovered config files with size, type, and last-used date.")
    available_types = sorted(df["type_label"].unique())
    selected_types = st.multiselect("Filter by type:", available_types, default=available_types)
    filtered_df = df[df["type_label"].isin(selected_types)] if selected_types else df

    # Add last-used column
    def _get_last_used(row):
        ft = row["file_type"]
        if ft == "agent":
            stem = Path(row["path"]).stem
            ts = last_used_map.get(stem, "")
            return ts[:10] if ts else "-"
        elif ft == "skill":
            skill_dir = Path(row["path"]).parent.name
            ts = last_used_map.get(skill_dir, "")
            return ts[:10] if ts else "-"
        else:
            return "Always active"

    filtered_df = filtered_df.copy()
    filtered_df["last_used"] = filtered_df.apply(_get_last_used, axis=1)

    display_df = (
        filtered_df[["name", "path", "type_label", "lines", "bytes", "last_used"]]
        .rename(
            columns={
                "name": "Name",
                "path": "Path",
                "type_label": "Type",
                "lines": "Lines",
                "bytes": "Bytes",
                "last_used": "Last Used",
            }
        )
        .sort_values("Lines", ascending=False)
    )
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Path": st.column_config.TextColumn(width="large")},
    )


def _render_size_history():
    """Render the Size History sub-tab."""
    history = load_history()

    if len(history.snapshots) < 2:
        st.info("Keep using the dashboard to accumulate history. A new snapshot is recorded at most once per hour.")
        if history.snapshots:
            st.caption(f"Current snapshot: {history.snapshots[0].timestamp}")
        return

    # Build time series dataframe
    rows = []
    for snap in history.snapshots:
        try:
            ts = datetime.fromisoformat(snap.timestamp)
        except (ValueError, TypeError):
            continue
        rows.append({"timestamp": ts, "total_lines": snap.total_lines})

        # Aggregate by type
        type_lines: dict[str, int] = {}
        for f in snap.files:
            label = TYPE_LABELS.get(f.file_type, f.file_type)
            type_lines[label] = type_lines.get(label, 0) + f.lines

        for label, lines in type_lines.items():
            rows.append({"timestamp": ts, "type": label, "lines_by_type": lines})

    df_total = pd.DataFrame([r for r in rows if "total_lines" in r])
    df_by_type = pd.DataFrame([r for r in rows if "lines_by_type" in r])

    # Total lines over time
    st.subheader(
        "Total Config Lines Over Time",
        help="Sum of all config file line counts at each recorded snapshot. Tracks config bloat over time.",
    )
    fig_total = px.line(
        df_total,
        x="timestamp",
        y="total_lines",
        labels={"timestamp": "Date", "total_lines": "Total Lines"},
    )
    fig_total.update_layout(height=350)
    st.plotly_chart(fig_total, use_container_width=True)

    # Stacked area by type
    if not df_by_type.empty:
        st.subheader(
            "Lines by File Type Over Time",
            help="Config line counts broken down by file type (agents, skills, CLAUDE.md) over time.",
        )
        fig_area = px.area(
            df_by_type,
            x="timestamp",
            y="lines_by_type",
            color="type",
            labels={"timestamp": "Date", "lines_by_type": "Lines", "type": "Type"},
        )
        fig_area.update_layout(height=350)
        st.plotly_chart(fig_area, use_container_width=True)

    # Per-file tracking for top 5
    _render_per_file_history(history)


def _render_per_file_history(history):
    """Show per-file line count over time for the largest files."""
    if not history.snapshots:
        return

    latest = history.snapshots[-1]
    top_files = sorted(latest.files, key=lambda f: f.lines, reverse=True)[:5]
    top_names = {f.name for f in top_files}

    all_names = set()
    for snap in history.snapshots:
        for f in snap.files:
            all_names.add(f.name)

    selected = st.multiselect(
        "Track specific files:",
        sorted(all_names),
        default=sorted(top_names),
    )

    if not selected:
        return

    rows = []
    for snap in history.snapshots:
        try:
            ts = datetime.fromisoformat(snap.timestamp)
        except (ValueError, TypeError):
            continue
        for f in snap.files:
            if f.name in selected:
                rows.append({"timestamp": ts, "file": f.name, "lines": f.lines})

    if rows:
        df = pd.DataFrame(rows)
        st.subheader(
            "Per-File Lines Over Time",
            help="Line count history for selected individual files. Useful for tracking growth of specific agents or skills.",
        )
        fig = px.line(
            df,
            x="timestamp",
            y="lines",
            color="file",
            labels={"timestamp": "Date", "lines": "Lines", "file": "File"},
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
