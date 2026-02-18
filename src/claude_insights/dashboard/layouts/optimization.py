"""Optimization tab: Configuration improvement opportunities."""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

from claude_insights.analytics.optimization_analyzer import (
    generate_optimization_report,
    analyze_unused_agents,
    analyze_unused_skills,
    analyze_duplicate_guidance,
    analyze_agent_efficiency,
)
from claude_insights.scanner.agent_scanner import scan_agents
from claude_insights.scanner.skill_scanner import scan_skills
from claude_insights.scanner.claude_md_scanner import scan_claude_md_files
from claude_insights.analytics.parsers.conversation_enricher import mine_tool_usage_stats
from claude_insights.models.schemas import AgentExecution, SkillExecution


def render(agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Render the optimization analysis tab."""

    # Load optimization data
    with st.spinner("Analyzing configuration for optimizations..."):
        # Get conversation stats
        stats = mine_tool_usage_stats(use_cache=True)

        # Scan infrastructure
        agents = scan_agents()
        skills = scan_skills()
        claude_md_files, _ = scan_claude_md_files()

        # Run analyses
        unused_agents = analyze_unused_agents(agents, agent_execs)
        unused_skills = analyze_unused_skills(skills, skill_execs)
        duplicates = analyze_duplicate_guidance(claude_md_files)
        efficiency = analyze_agent_efficiency(agent_execs)

    # Display summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Total Conversations",
            f"{stats.total_conversations:,}",
            help="Number of conversations analyzed for usage patterns"
        )

    with col2:
        st.metric(
            "Unique Agents Used",
            stats.agents.__len__(),
            delta=f"{len(stats.agents) - len(agents)} vs defined" if len(stats.agents) != len(agents) else None,
            help="Agents actually invoked vs defined in configuration"
        )

    with col3:
        st.metric(
            "Unused Components",
            len(unused_agents) + len(unused_skills),
            help="Agents and skills that have never been executed"
        )

    with col4:
        total_issues = len(unused_agents) + len(unused_skills) + len(duplicates) + len(efficiency)
        severity_color = "🟢" if total_issues < 10 else "🟡" if total_issues < 30 else "🔴"
        st.metric(
            "Optimization Opportunities",
            f"{severity_color} {total_issues}",
            help="Total number of improvements identified"
        )

    st.divider()

    # Create tabs for different optimization categories
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Usage Insights",
        "🗑️ Unused Components",
        "⚡ Quick Wins",
        "⚠️ Issues & Warnings",
        "📄 Full Report"
    ])

    with tab1:
        st.subheader("Agent-to-Definition Cross-Reference")

        # Show which used agents have definitions and which don't
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

    with tab2:
        st.subheader("🤖 Unused Agents")

        unused_agent_names = [issue.title.replace("Unused agent: ", "")
                              for issue in unused_agents]

        if unused_agent_names:
            st.warning(f"Found {len(unused_agent_names)} agents that have never been executed")

            # Create columns for better layout
            cols = st.columns(2)
            for idx, agent_name in enumerate(unused_agent_names):
                with cols[idx % 2]:
                    st.markdown(f"- `{agent_name}`")

            st.info("💡 **Recommendation:** Review these agents and remove if no longer needed to reduce cognitive load")
        else:
            st.success("✅ All defined agents are being used")

        st.divider()

        st.subheader("⚡ Unused Skills")

        unused_skill_names = [issue.title.replace("Unused skill: ", "")
                              for issue in unused_skills]

        if unused_skill_names:
            st.warning(f"Found {len(unused_skill_names)} skills that have never been executed")

            cols = st.columns(2)
            for idx, skill_name in enumerate(unused_skill_names):
                with cols[idx % 2]:
                    st.markdown(f"- `{skill_name}`")

            st.info("💡 **Recommendation:** Consider removing unused skills or documenting why they're kept")
        else:
            st.success("✅ All defined skills are being used")

    with tab3:
        st.subheader("⚡ Quick Wins")

        # High-frequency optimization
        if stats.agents:
            top_agent = max(stats.agents.items(), key=lambda x: x[1])
            if top_agent[1] > 100:
                st.markdown("### 🔥 High-Frequency Patterns")
                st.info(
                    f"**{top_agent[0]}** agent used **{top_agent[1]} times**\n\n"
                    f"Consider:\n"
                    f"- Creating pre-computed indexes for common searches\n"
                    f"- Caching frequent query results\n"
                    f"- Using a faster model (haiku) for simple lookups"
                )

        # Cleanup opportunities
        total_unused = len(unused_agents) + len(unused_skills)
        if total_unused > 0:
            st.markdown("### 🧹 Cleanup Opportunities")

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Unused Agents", len(unused_agents))
            with col2:
                st.metric("Unused Skills", len(unused_skills))

            estimated_reduction = total_unused * 0.5  # Rough estimate KB per component
            st.success(
                f"Removing {total_unused} unused components would:\n"
                f"- Reduce configuration size by ~{estimated_reduction:.0f}KB\n"
                f"- Speed up Claude's agent/skill scanning\n"
                f"- Simplify maintenance and debugging"
            )

    with tab4:
        st.subheader("Issues & Warnings")

        if duplicates:
            st.warning(f"⚠️ Found {len(duplicates)} duplicate routing issues")
            for issue in duplicates:
                with st.expander(issue.title):
                    st.markdown(f"**Impact:** {issue.impact}")
                    st.markdown(f"**Recommendation:** {issue.recommendation}")
                    if issue.files:
                        st.markdown(f"**Files:** {', '.join(issue.files)}")

        if efficiency:
            st.warning(f"💰 Found {len(efficiency)} efficiency issues")
            for issue in efficiency:
                with st.expander(issue.title):
                    st.markdown(f"**Description:** {issue.description}")
                    st.markdown(f"**Impact:** {issue.impact}")
                    st.markdown(f"**Recommendation:** {issue.recommendation}")

        if not duplicates and not efficiency:
            st.success("✅ No critical issues found")

    with tab5:
        st.subheader("📄 Full Optimization Report")

        # Generate full markdown report
        with st.spinner("Generating comprehensive report..."):
            report = generate_optimization_report(include_conversations=True)

        # Display in expandable section
        with st.expander("View Full Report", expanded=False):
            st.markdown(report)

        # Download button
        st.download_button(
            label="📥 Download Report (Markdown)",
            data=report,
            file_name="claude-optimization-report.md",
            mime="text/markdown"
        )

        # Show maintenance recommendations
        st.info(
            "### 🔧 Maintenance Recommendations\n\n"
            "- Run optimization analysis weekly\n"
            "- Document why unused components are kept (if intentional)\n"
            "- Review agent model assignments quarterly for cost optimization\n"
            "- Consider implementing caching for high-frequency operations"
        )