"""Overview tab: KPI cards, 16-dim profile radar, daily activity sparkline, top agents/skills."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from claudealytics.analytics.aggregators.token_aggregator import daily_activity_df
from claudealytics.analytics.aggregators.usage_aggregator import agent_usage_counts, skill_usage_counts
from claudealytics.models.schemas import AgentExecution, SkillExecution, StatsCache


def render(stats: StatsCache, agent_execs: list[AgentExecution], skill_execs: list[SkillExecution]):
    """Render the overview tab."""
    # KPI cards
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Sessions", f"{stats.totalSessions:,}")
    col2.metric("Total Messages", f"{stats.totalMessages:,}")
    col3.metric("Agent Invocations", f"{len(agent_execs):,}")

    st.divider()

    # 16-Dimension Profile Radar
    _render_profile_radar()

    st.divider()

    # Daily activity chart
    activity_df = daily_activity_df(stats)
    if not activity_df.empty:
        st.subheader(
            "Daily Activity", help="Total messages per day across all sessions. Hover for session and tool call counts."
        )
        fig = px.bar(
            activity_df,
            x="date",
            y="messages",
            hover_data=["sessions", "tool_calls"],
            labels={"date": "Date", "messages": "Messages"},
            color_discrete_sequence=["#6366f1"],
        )
        fig.update_layout(
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="",
            yaxis_title="Messages",
        )
        st.plotly_chart(fig, use_container_width=True)
        if stats.lastComputedDate:
            st.caption(f"Data as of: {stats.lastComputedDate}")

    # Top agents and skills side by side
    col_a, col_s = st.columns(2)

    with col_a:
        st.subheader("Top Agents", help="Most frequently invoked custom agents (via Task tool) across all sessions.")
        agent_counts = agent_usage_counts(agent_execs)
        if agent_counts:
            top_agents = dict(list(agent_counts.items())[:10])
            df = pd.DataFrame({"agent": list(top_agents.keys()), "count": list(top_agents.values())})
            fig = px.bar(
                df,
                x="count",
                y="agent",
                orientation="h",
                color_discrete_sequence=["#8b5cf6"],
            )
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions",
                yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent execution data found")

    with col_s:
        st.subheader("Top Skills", help="Most frequently invoked skills (slash commands) across all sessions.")
        skill_counts = skill_usage_counts(skill_execs)
        if skill_counts:
            top_skills = dict(list(skill_counts.items())[:10])
            df = pd.DataFrame({"skill": list(top_skills.keys()), "count": list(top_skills.values())})
            fig = px.bar(
                df,
                x="count",
                y="skill",
                orientation="h",
                color_discrete_sequence=["#ec4899"],
            )
            fig.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "total ascending"},
                xaxis_title="Executions",
                yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No skill execution data found")

    # Peak hours
    if stats.hourCounts:
        st.subheader(
            "Activity by Hour of Day",
            help="Session counts grouped by hour (24h clock, local time). Shows your peak productivity windows.",
        )
        hours_df = pd.DataFrame([{"hour": int(h), "count": c} for h, c in stats.hourCounts.items()]).sort_values("hour")
        fig = px.bar(
            hours_df,
            x="hour",
            y="count",
            labels={"hour": "Hour (24h)", "count": "Sessions"},
            color_discrete_sequence=["#14b8a6"],
        )
        fig.update_layout(
            height=250,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(dtick=1),
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Profile Radar ────────────────────────────────────────────────

# Category order and styling (from profile_scorer)
_CATEGORY_ORDER = ["communication", "strategy", "technical", "automation"]
_CATEGORY_COLORS = {
    "communication": "#6366f1",
    "strategy": "#f59e0b",
    "technical": "#14b8a6",
    "automation": "#ec4899",
}
_CATEGORY_ICONS = {
    "communication": "\U0001f4ac",
    "strategy": "\U0001f9e0",
    "technical": "\U0001f527",
    "automation": "\u2699\ufe0f",
}

# Canonical dimension order — must match conversation_profile.py exactly
_CANONICAL_DIM_ORDER = [
    "context_precision",
    "semantic_density",
    "iterative_refinement",
    "conversation_balance",
    "task_decomposition",
    "validation_rigor",
    "error_resilience",
    "planning_depth",
    "code_literacy",
    "architectural_stewardship",
    "debugging_collaboration",
    "token_efficiency",
    "strategic_delegation",
    "tool_orchestration",
    "trust_calibration",
    "session_productivity",
]

_ABBREV_LABELS = {
    "context_precision": "Ctx Precision",
    "semantic_density": "Sem Density",
    "iterative_refinement": "Iter Refine",
    "conversation_balance": "Conv Balance",
    "task_decomposition": "Task Decomp",
    "validation_rigor": "Val Rigor",
    "error_resilience": "Err Resilience",
    "planning_depth": "Plan Depth",
    "code_literacy": "Code Literacy",
    "architectural_stewardship": "Arch Steward",
    "debugging_collaboration": "Debug Collab",
    "token_efficiency": "Token Eff",
    "strategic_delegation": "Strat Deleg",
    "tool_orchestration": "Tool Orch",
    "trust_calibration": "Trust Calib",
    "session_productivity": "Sess Product",
}


def _render_profile_radar():
    """Render the full 16-dimension profile radar on the overview tab."""
    try:
        from claudealytics.analytics.aggregators.profile_scorer import (
            _load_profile_cache,
            aggregate_profiles,
            compute_all_profiles,
            get_tier,
        )
        from claudealytics.analytics.parsers.content_miner import mine_content
    except ImportError:
        return

    # Try cache first, compute with spinner if needed
    profiles = _load_profile_cache()
    if not profiles:
        with st.spinner("Computing conversation profile..."):
            try:
                dfs = mine_content(use_cache=True)
                session_stats = dfs.get("session_stats", pd.DataFrame())
                tool_calls = dfs.get("tool_calls", pd.DataFrame())
                human_lengths = dfs.get("human_message_lengths", pd.DataFrame())
                if session_stats.empty:
                    return
                profiles = compute_all_profiles(session_stats, tool_calls, human_lengths, use_cache=True)
            except Exception:
                return

    if not profiles:
        return

    profile = aggregate_profiles(profiles)
    if not profile.dimensions:
        return

    st.subheader(
        "16-Dimension Profile",
        help="Aggregated conversation profile across all sessions. See Conversation Profile tab for details.",
    )

    # Order dimensions using canonical order (same as conversation_profile tab)
    dim_by_key = {d.key: d for d in profile.dimensions}
    ordered_dims = [dim_by_key[k] for k in _CANONICAL_DIM_ORDER if k in dim_by_key]

    if not ordered_dims:
        return

    labels = [_ABBREV_LABELS.get(d.key, d.name) for d in ordered_dims]
    scores = [d.score for d in ordered_dims]
    colors = [_CATEGORY_COLORS.get(d.category, "#666") for d in ordered_dims]

    # Close polygon
    labels_closed = labels + [labels[0]]
    scores_closed = scores + [scores[0]]
    colors_closed = colors + [colors[0]]

    col_radar, col_scores = st.columns([3, 2])

    with col_radar:
        fig = go.Figure()
        fig.add_trace(
            go.Scatterpolar(
                r=scores_closed,
                theta=labels_closed,
                fill="toself",
                fillcolor="rgba(99, 102, 241, 0.12)",
                line=dict(color="#6366f1", width=2),
                marker=dict(color=colors_closed, size=8),
                hovertemplate="%{theta}: %{r:.1f}/10<extra></extra>",
                name="Profile",
            )
        )
        fig.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
                angularaxis=dict(tickfont=dict(size=10)),
            ),
            height=420,
            margin=dict(l=70, r=70, t=30, b=30),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_scores:
        tier_name, tier_color = get_tier(profile.overall_score)
        st.markdown(
            f"### Overall: **{profile.overall_score}** / 10\n"
            f"Tier: <span style='color:{tier_color};font-weight:bold'>{tier_name}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Aggregated from {len(profiles)} sessions")

        st.markdown("---")

        for cat in _CATEGORY_ORDER:
            cat_score = profile.category_scores.get(cat, 5.0)
            color = _CATEGORY_COLORS.get(cat, "#666")
            icon = _CATEGORY_ICONS.get(cat, "")
            pct = cat_score / 10 * 100
            st.markdown(
                f"<div style='margin-bottom:6px'>"
                f"<span style='text-transform:capitalize;font-weight:600'>{icon} {cat}</span>"
                f" <span style='color:#888'>{cat_score}</span>"
                f"<div style='background:#1a1a2e;border-radius:4px;height:10px;margin-top:2px'>"
                f"<div style='background:{color};width:{pct}%;height:10px;border-radius:4px'></div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("---")

        sorted_dims = sorted(profile.dimensions, key=lambda d: d.score, reverse=True)
        st.markdown("**Strengths**")
        for d in sorted_dims[:3]:
            color = _CATEGORY_COLORS.get(d.category, "#666")
            st.markdown(f"- <span style='color:{color}'>{d.name}</span> — **{d.score}**", unsafe_allow_html=True)

        st.markdown("**Gaps**")
        for d in sorted_dims[-3:]:
            color = _CATEGORY_COLORS.get(d.category, "#666")
            st.markdown(f"- <span style='color:{color}'>{d.name}</span> — **{d.score}**", unsafe_allow_html=True)
