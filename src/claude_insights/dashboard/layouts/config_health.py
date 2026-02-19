"""Config Health tab: size tracking, history, and in-depth analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from claude_insights.analytics.config_analyzer import (
    load_cached_analysis,
    run_full_analysis,
)
from claude_insights.models.schemas import AgentExecution, SkillExecution
from claude_insights.scanner.config_size_scanner import (
    load_history,
    measure_all_config_files,
    record_snapshot,
)

# Color map for file types
TYPE_COLORS = {
    "agent": "#7c3aed",          # purple
    "skill": "#ec4899",          # pink
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

    # Current metrics for KPI row
    files = measure_all_config_files()
    cached_analysis = load_cached_analysis()

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
        if cached_analysis:
            try:
                ts = datetime.fromisoformat(cached_analysis.timestamp)
                st.metric("Last Analysis", ts.strftime("%b %d, %H:%M"))
            except (ValueError, TypeError):
                st.metric("Last Analysis", "Unknown")
        else:
            st.metric("Last Analysis", "Never")

    st.divider()

    # Sub-tabs
    tab_sizes, tab_history, tab_analysis = st.tabs([
        "📊 Current Sizes",
        "📈 Size History",
        "🔍 Analysis",
    ])

    with tab_sizes:
        _render_current_sizes(files, agent_execs or [], skill_execs or [])

    with tab_history:
        _render_size_history()

    with tab_analysis:
        _render_analysis(cached_analysis)


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
    st.subheader("Line Count by File")
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
    st.subheader("All Config Files")
    available_types = sorted(df["type_label"].unique())
    selected_types = st.multiselect("Filter by type:", available_types, default=available_types)
    filtered_df = df[df["type_label"].isin(selected_types)] if selected_types else df

    # Add last-used column
    def _get_last_used(row):
        ft = row["file_type"]
        name = row["name"]
        if ft == "agent":
            stem = Path(row["path"]).stem
            ts = last_used_map.get(stem, "")
            return ts[:10] if ts else "-"
        elif ft == "skill":
            # Skill dir name is the skill identifier
            skill_dir = Path(row["path"]).parent.name
            ts = last_used_map.get(skill_dir, "")
            return ts[:10] if ts else "-"
        else:
            return "Always active"

    filtered_df = filtered_df.copy()
    filtered_df["last_used"] = filtered_df.apply(_get_last_used, axis=1)

    display_df = filtered_df[["name", "path", "type_label", "lines", "bytes", "last_used"]].rename(columns={
        "name": "Name",
        "path": "Path",
        "type_label": "Type",
        "lines": "Lines",
        "bytes": "Bytes",
        "last_used": "Last Used",
    }).sort_values("Lines", ascending=False)
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
        st.info("Keep using the dashboard to accumulate history. "
                "A new snapshot is recorded at most once per hour.")
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
    st.subheader("Total Config Lines Over Time")
    fig_total = px.line(
        df_total, x="timestamp", y="total_lines",
        labels={"timestamp": "Date", "total_lines": "Total Lines"},
    )
    fig_total.update_layout(height=350)
    st.plotly_chart(fig_total, use_container_width=True)

    # Stacked area by type
    if not df_by_type.empty:
        st.subheader("Lines by File Type Over Time")
        fig_area = px.area(
            df_by_type, x="timestamp", y="lines_by_type", color="type",
            labels={"timestamp": "Date", "lines_by_type": "Lines", "type": "Type"},
        )
        fig_area.update_layout(height=350)
        st.plotly_chart(fig_area, use_container_width=True)

    # Per-file tracking for top 5
    _render_per_file_history(history)


def _render_per_file_history(history):
    """Show per-file line count over time for the largest files."""
    # Determine top 5 files from latest snapshot
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
        st.subheader("Per-File Lines Over Time")
        fig = px.line(
            df, x="timestamp", y="lines", color="file",
            labels={"timestamp": "Date", "lines": "Lines", "file": "File"},
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)


@st.fragment
def _render_analysis(cached_analysis):
    """Render the Analysis sub-tab."""
    # Use session_state to persist analysis across Streamlit reruns
    if "config_analysis_result" not in st.session_state:
        st.session_state.config_analysis_result = cached_analysis

    # Run button with last-run info
    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button("🔬 Run Config Analysis", use_container_width=True)
    with col2:
        current = st.session_state.config_analysis_result or cached_analysis
        if current:
            try:
                ts = datetime.fromisoformat(current.timestamp)
                duration = current.analysis_duration_seconds
                st.caption(f"Last run: {ts.strftime('%Y-%m-%d %H:%M')} ({duration}s)")
            except (ValueError, TypeError):
                pass
        else:
            st.caption("No previous analysis found")

    if run_clicked:
        progress_bar = st.progress(0, text="Starting analysis...")

        def update_progress(pct, text):
            progress_bar.progress(pct, text=text)

        with st.spinner("Running full config analysis..."):
            result = run_full_analysis(progress_callback=update_progress)
        progress_bar.empty()
        st.session_state.config_analysis_result = result
        cached_analysis = result
        st.success("Analysis complete!")
    else:
        # Use session state result if available (survives reruns)
        if st.session_state.config_analysis_result:
            cached_analysis = st.session_state.config_analysis_result

    if not cached_analysis:
        st.info("Click 'Run Config Analysis' to generate insights about your configuration files.")
        return

    # Summary metrics
    all_issues = cached_analysis.quality_issues + cached_analysis.consistency_issues
    high = sum(1 for i in all_issues if i.severity == "high")
    medium = sum(1 for i in all_issues if i.severity == "medium")
    low = sum(1 for i in all_issues if i.severity == "low")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        health = max(0, 100 - high * 15 - medium * 5 - low * 1)
        color = "🟢" if health >= 80 else "🟡" if health >= 50 else "🔴"
        st.metric("Health Score", f"{color} {health}/100")
    with col2:
        st.metric("High Severity", high)
    with col3:
        st.metric("Medium Severity", medium)
    with col4:
        st.metric("Low Severity", low)

    st.divider()

    # Quality issues (grouped by message)
    if all_issues:
        st.subheader("Quality Issues")
        for severity in ("high", "medium", "low"):
            sev_issues = [i for i in all_issues if i.severity == severity]
            if not sev_issues:
                continue
            icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}[severity]
            with st.expander(f"{icon} {severity.title()} ({len(sev_issues)})", expanded=(severity == "high")):
                grouped: dict[str, list] = defaultdict(list)
                for issue in sev_issues:
                    grouped[issue.message].append(issue)
                for message, issues in grouped.items():
                    count_str = f" ({len(issues)} files)" if len(issues) > 1 else ""
                    st.markdown(f"**{message}**{count_str}")
                    if issues[0].suggestion:
                        st.markdown(f"*Suggestion:* {issues[0].suggestion}")
                    if len(issues) > 1:
                        with st.expander(f"Affected files"):
                            for issue in issues:
                                st.caption(f"`{issue.file_path}`")
                    else:
                        st.caption(f"`{issues[0].file_path}` — {issues[0].issue_type}")
                    st.markdown("---")
    else:
        st.success("No quality issues found!")

    # Complexity metrics
    if cached_analysis.complexity_metrics:
        st.subheader("Complexity Metrics")
        cdf = pd.DataFrame([m.model_dump() for m in cached_analysis.complexity_metrics])
        cdf["type_label"] = cdf["file_type"].map(TYPE_LABELS)

        # Bar chart: top files by word count
        cdf_sorted = cdf.sort_values("word_count", ascending=True)
        fig = px.bar(
            cdf_sorted, x="word_count", y="name", color="type_label",
            orientation="h",
            color_discrete_map={v: TYPE_COLORS[k] for k, v in TYPE_LABELS.items()},
            labels={"word_count": "Word Count", "name": "File", "type_label": "Type"},
        )
        fig.update_layout(height=max(300, len(cdf) * 28), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

        # Table
        display_cols = ["name", "type_label", "lines", "word_count", "section_count",
                        "table_count", "code_block_count", "avg_line_length"]
        display_df = cdf[display_cols].rename(columns={
            "name": "Name", "type_label": "Type", "lines": "Lines",
            "word_count": "Words", "section_count": "Sections",
            "table_count": "Table Rows", "code_block_count": "Code Blocks",
            "avg_line_length": "Avg Line Len",
        }).sort_values("Words", ascending=False)
        display_df["Avg Line Len"] = display_df["Avg Line Len"].round(1)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # LLM reviews — separate successful from failed
    if cached_analysis.llm_reviews:
        st.subheader("LLM Reviews")

        def _short_path(p: str) -> str:
            """Shorten absolute path to a readable relative form."""
            home = str(Path.home())
            if p.startswith(home):
                return "~" + p[len(home):]
            return p

        successful = {
            p: r for p, r in cached_analysis.llm_reviews.items()
            if r.clarity_score > 0
        }
        failed = {
            p: r for p, r in cached_analysis.llm_reviews.items()
            if r.clarity_score == 0
        }

        # Successful reviews sorted by clarity score
        for path, review in sorted(
            successful.items(),
            key=lambda x: x[1].clarity_score,
        ):
            name = _short_path(path)
            score = review.clarity_score
            icon = "🟢" if score >= 80 else "🟡" if score >= 50 else "🔴"
            with st.expander(f"{icon} {name} — Clarity: {score:.0f}/100"):
                if review.summary:
                    st.markdown(f"**Summary:** {review.summary}")
                if review.redundancy_issues:
                    st.markdown("**Redundancy issues:**")
                    for issue in review.redundancy_issues:
                        st.markdown(f"- {issue}")
                if review.improvement_suggestions:
                    st.markdown("**Suggestions:**")
                    for sug in review.improvement_suggestions:
                        st.markdown(f"- {sug}")
                if not review.summary and not review.redundancy_issues and not review.improvement_suggestions:
                    st.caption("No detailed review available")

        # Failed reviews collapsed into a single expander
        if failed:
            with st.expander(f"⚠️ {len(failed)} files failed LLM review"):
                for path, review in sorted(failed.items()):
                    name = _short_path(path)
                    st.caption(f"`{name}` — {review.summary}")
