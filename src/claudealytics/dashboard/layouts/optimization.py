"""Report tab: Full Report, Config Analysis, and Optimization Insights."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from claudealytics.analytics.config_analyzer import (
    load_cached_analysis,
    run_full_analysis,
)
from claudealytics.analytics.optimization_analyzer import (
    analyze_unused_agents,
    analyze_unused_skills,
    analyze_duplicate_guidance,
    analyze_agent_efficiency,
)
from claudealytics.analytics.report_generator import (
    generate_full_report,
    load_cached_report,
)
from claudealytics.analytics.parsers.conversation_enricher import mine_tool_usage_stats
from claudealytics.models.schemas import AgentExecution, SkillExecution, StatsCache
from claudealytics.scanner.agent_scanner import scan_agents
from claudealytics.scanner.skill_scanner import scan_skills
from claudealytics.scanner.claude_md_scanner import scan_claude_md_files


# Color map for file types (shared with config_health)
TYPE_COLORS = {
    "agent": "#7c3aed",
    "skill": "#ec4899",
    "global_claude_md": "#4f46e5",
    "project_claude_md": "#6366f1",
}

TYPE_LABELS = {
    "agent": "Agent",
    "skill": "Skill",
    "global_claude_md": "Global CLAUDE.md",
    "project_claude_md": "Project CLAUDE.md",
}


def render(stats: StatsCache | None, agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Render the Report tab with three sub-tabs."""
    tab_report, tab_analysis, tab_optimize = st.tabs([
        "📄 Full Report",
        "🔬 Config Analysis",
        "📊 Optimization Insights",
    ])

    with tab_report:
        _render_full_report(stats, agent_execs, skill_execs)

    with tab_analysis:
        _render_config_analysis()

    with tab_optimize:
        _render_optimization_insights(agent_execs, skill_execs)


# ── Sub-tab 1: Full Report ────────────────────────────────────────


@st.fragment
def _render_full_report(stats, agent_execs, skill_execs):
    """LLM-generated comprehensive platform report."""
    if "full_report_result" not in st.session_state:
        st.session_state.full_report_result = load_cached_report()

    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button("📄 Generate Full Report", use_container_width=True)
    with col2:
        current = st.session_state.full_report_result
        if current and current.timestamp:
            try:
                ts = datetime.fromisoformat(current.timestamp)
                duration = current.generation_duration_seconds
                model = current.model_used or "unknown"
                st.caption(f"Last run: {ts.strftime('%Y-%m-%d %H:%M')} ({duration:.0f}s, {model})")
            except (ValueError, TypeError):
                pass
        else:
            st.caption("No previous report found — click Generate to create one")

    if run_clicked:
        progress_bar = st.progress(0, text="Starting report generation...")

        def update_progress(pct, text):
            progress_bar.progress(pct, text=text)

        result = generate_full_report(stats, agent_execs, skill_execs, progress_callback=update_progress)
        progress_bar.empty()
        st.session_state.full_report_result = result

        if result.error:
            st.error(f"Report generation failed: {result.error}")
        else:
            st.success("Report generated successfully!")
    else:
        if st.session_state.full_report_result:
            current = st.session_state.full_report_result

    report = st.session_state.full_report_result
    if not report:
        st.info("Click 'Generate Full Report' to create a comprehensive platform analysis using Opus.")
        return

    if report.error and not report.report_markdown:
        st.warning(f"Last report had an error: {report.error}")

    if report.report_markdown:
        st.markdown(report.report_markdown)

        # Download button
        st.download_button(
            label="📥 Download Report (Markdown)",
            data=report.report_markdown,
            file_name="claudealytics-full-report.md",
            mime="text/markdown",
        )

    # Expandable raw data summary
    if report.data_summary:
        with st.expander("View Raw Data Summary"):
            st.text(report.data_summary)


# ── Sub-tab 2: Config Analysis ────────────────────────────────────


@st.fragment
def _render_config_analysis():
    """Config quality analysis with LLM reviews (moved from config_health)."""
    cached_analysis = load_cached_analysis()

    if "config_analysis_result" not in st.session_state:
        st.session_state.config_analysis_result = cached_analysis

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
        st.subheader("Quality Issues", help="Detected problems in config files: missing sections, redundancy, oversized files, inconsistencies, etc.")
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
        st.subheader("Complexity Metrics", help="Word count, section count, table density, and code block count per config file — higher values may indicate bloat.")
        import plotly.express as px

        cdf = pd.DataFrame([m.model_dump() for m in cached_analysis.complexity_metrics])
        cdf["type_label"] = cdf["file_type"].map(TYPE_LABELS)

        cdf_sorted = cdf.sort_values("word_count", ascending=True)
        fig = px.bar(
            cdf_sorted, x="word_count", y="name", color="type_label",
            orientation="h",
            color_discrete_map={v: TYPE_COLORS[k] for k, v in TYPE_LABELS.items()},
            labels={"word_count": "Word Count", "name": "File", "type_label": "Type"},
        )
        fig.update_layout(height=max(300, len(cdf) * 28), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

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

    # LLM reviews
    if cached_analysis.llm_reviews:
        st.subheader("LLM Reviews", help="AI-generated clarity scores and improvement suggestions for each config file. Run Config Analysis to generate.")

        def _short_path(p: str) -> str:
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

        for path, review in sorted(successful.items(), key=lambda x: x[1].clarity_score):
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

        if failed:
            with st.expander(f"⚠️ {len(failed)} files failed LLM review"):
                for path, review in sorted(failed.items()):
                    name = _short_path(path)
                    st.caption(f"`{name}` — {review.summary}")


# ── Sub-tab 3: Optimization Insights ──────────────────────────────


def _render_optimization_insights(agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Consolidated optimization insights — read-only, no button needed."""

    with st.spinner("Analyzing configuration for optimizations..."):
        stats = mine_tool_usage_stats(use_cache=True)
        agents = scan_agents()
        skills = scan_skills()
        claude_md_files, _ = scan_claude_md_files()

        unused_agents = analyze_unused_agents(agents, agent_execs)
        unused_skills = analyze_unused_skills(skills, skill_execs)
        duplicates = analyze_duplicate_guidance(claude_md_files)
        efficiency = analyze_agent_efficiency(agent_execs)

    # Summary metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "Total Conversations",
            f"{stats.total_conversations:,}",
            help="Number of conversations analyzed for usage patterns",
        )
    with col2:
        st.metric(
            "Unique Agents Used",
            len(stats.agents),
            delta=f"{len(stats.agents) - len(agents)} vs defined" if len(stats.agents) != len(agents) else None,
            help="Agents actually invoked vs defined in configuration",
        )
    with col3:
        st.metric(
            "Unused Components",
            len(unused_agents) + len(unused_skills),
            help="Agents and skills that have never been executed",
        )
    with col4:
        total_issues = len(unused_agents) + len(unused_skills) + len(duplicates) + len(efficiency)
        severity_color = "🟢" if total_issues < 10 else "🟡" if total_issues < 30 else "🔴"
        st.metric(
            "Optimization Opportunities",
            f"{severity_color} {total_issues}",
            help="Total number of improvements identified",
        )

    st.divider()

    # ── Usage Insights ──
    st.subheader("Agent-to-Definition Cross-Reference")

    defined_names = {a.name for a in agents}
    used_names = set(stats.agents.keys()) if stats.agents else set()

    mapped = used_names & defined_names
    unmapped_used = used_names - defined_names
    unused_defined = defined_names - used_names

    col_m, col_u, col_d = st.columns(3)
    with col_m:
        st.metric("Mapped (used + defined)", len(mapped))
    with col_u:
        st.metric("Used but no definition", len(unmapped_used))
    with col_d:
        st.metric("Defined but unused", len(unused_defined))

    if unmapped_used:
        st.warning(
            f"**{len(unmapped_used)} agents** found in conversations but have no "
            f"`.md` definition: {', '.join(sorted(unmapped_used))}"
        )
    if unused_defined:
        st.info(
            f"**{len(unused_defined)} agents** defined but never invoked: "
            f"{', '.join(sorted(unused_defined))}"
        )

    st.divider()

    # ── Unused Components ──
    st.subheader("Unused Components")

    unused_agent_names = [issue.title.replace("Unused agent: ", "") for issue in unused_agents]
    unused_skill_names = [issue.title.replace("Unused skill: ", "") for issue in unused_skills]

    col_a, col_s = st.columns(2)
    with col_a:
        st.markdown("**Unused Agents**")
        if unused_agent_names:
            for name in unused_agent_names:
                st.markdown(f"- `{name}`")
        else:
            st.success("All defined agents are being used")

    with col_s:
        st.markdown("**Unused Skills**")
        if unused_skill_names:
            for name in unused_skill_names:
                st.markdown(f"- `{name}`")
        else:
            st.success("All defined skills are being used")

    if unused_agent_names or unused_skill_names:
        total_unused = len(unused_agent_names) + len(unused_skill_names)
        st.info(
            f"Removing {total_unused} unused components would reduce configuration "
            f"size by ~{total_unused * 0.5:.0f}KB and speed up scanning."
        )

    st.divider()

    # ── Quick Wins ──
    st.subheader("Quick Wins")

    if stats.agents:
        top_agent = max(stats.agents.items(), key=lambda x: x[1])
        if top_agent[1] > 100:
            st.info(
                f"**{top_agent[0]}** agent used **{top_agent[1]} times** — "
                f"consider pre-computed indexes, result caching, or a faster model (haiku) for simple lookups."
            )

    if not (unused_agent_names or unused_skill_names or (stats.agents and max(stats.agents.values(), default=0) > 100)):
        st.success("No quick wins identified — configuration looks well-optimized!")

    st.divider()

    # ── Issues & Warnings ──
    st.subheader("Issues & Warnings")

    if duplicates:
        st.warning(f"Found {len(duplicates)} duplicate routing issues")
        for issue in duplicates:
            with st.expander(issue.title):
                st.markdown(f"**Impact:** {issue.impact}")
                st.markdown(f"**Recommendation:** {issue.recommendation}")
                if issue.files:
                    st.markdown(f"**Files:** {', '.join(issue.files)}")

    if efficiency:
        st.warning(f"Found {len(efficiency)} efficiency issues")
        for issue in efficiency:
            with st.expander(issue.title):
                st.markdown(f"**Description:** {issue.description}")
                st.markdown(f"**Impact:** {issue.impact}")
                st.markdown(f"**Recommendation:** {issue.recommendation}")

    if not duplicates and not efficiency:
        st.success("No critical issues found")
