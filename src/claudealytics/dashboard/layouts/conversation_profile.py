"""Conversation Profile tab: 16-dimension scoring with multi-radar layout + LLM profile."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from claudealytics.analytics.aggregators.profile_scorer import (
    CATEGORY_COLORS,
    CATEGORY_ICONS,
    CATEGORY_ORDER,
    _load_profile_cache,
    aggregate_profiles,
    compute_all_profiles,
    get_tier,
)
from claudealytics.analytics.parsers.content_miner import mine_content

CONTENT_MINE_PATH = Path.home() / ".cache" / "claudealytics" / "content-mine.json"

# Canonical dimension order (matches ALL_SCORERS in profile_scorer.py)
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

# Sub-palette for per-dimension evolution charts (high contrast within a category)
_DIM_SUB_PALETTE = ["#6366f1", "#14b8a6", "#f59e0b", "#ef4444"]

# Abbreviated labels for 16-dim spider (key → short label)
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


def render(stats):
    """Render the Conversation Profile tab."""
    profiles = _load_profiles_with_progress()
    if not profiles:
        st.warning("Could not compute profiles from conversation data.")
        return

    projects = sorted({p.project for p in profiles if p.project})

    # ── Selectors + Badge ────────────────────────────────────────
    col_project, col_session, col_badge = st.columns([2, 2, 4])
    with col_project:
        project_options = ["All Projects"] + projects
        selected_project = st.selectbox("Project", project_options, key="profile_project")

    if selected_project != "All Projects":
        filtered_profiles = [p for p in profiles if p.project == selected_project]
    else:
        filtered_profiles = profiles

    with col_session:
        session_options = ["All Sessions (Overall)"] + [f"{p.date} — {p.session_id[:12]}..." for p in filtered_profiles]
        selected_session = st.selectbox("Session", session_options, key="profile_session")

    if selected_session == "All Sessions (Overall)":
        active_profile = aggregate_profiles(filtered_profiles)
        session_count = len(filtered_profiles)
        is_single_session = False
        active_session_id = ""
    else:
        idx = session_options.index(selected_session) - 1
        active_profile = filtered_profiles[idx]
        session_count = 1
        is_single_session = True
        active_session_id = active_profile.session_id

    with col_badge:
        st.markdown(
            f"<div style='padding:12px 0;text-align:right'>"
            f"<span style='background:#1e1e3f;padding:6px 14px;border-radius:20px;"
            f"font-size:0.85em;color:#a5b4fc'>"
            f"\U0001f4ca {len(filtered_profiles)} sessions analyzed"
            f"</span></div>",
            unsafe_allow_html=True,
        )

    if not active_profile.dimensions:
        st.warning("No dimension data for selected scope.")
        return

    # ── View Switcher ─────────────────────────────────────────────
    radar_view = st.radio(
        "Radar View",
        ["Full 16-Dimension", "Composite (4 Categories)", "Per-Category Deep Dive"],
        horizontal=True,
        key="profile_radar_view",
    )

    st.divider()

    # ── Render based on selected view ─────────────────────────────
    if radar_view == "Full 16-Dimension":
        col_radar, col_summary = st.columns([3, 2])
        with col_radar:
            _render_full_spider(active_profile)
        with col_summary:
            _render_summary(active_profile, session_count)

    elif radar_view == "Composite (4 Categories)":
        col_radar, col_summary = st.columns([3, 2])
        with col_radar:
            _render_composite_radar(active_profile)
        with col_summary:
            _render_summary(active_profile, session_count)

    else:  # Per-Category Deep Dive
        _render_summary(active_profile, session_count)
        st.divider()
        st.subheader("Category Deep Dive")
        col1, col2 = st.columns(2)
        cats = CATEGORY_ORDER
        cols = [col1, col2, col1, col2]
        for cat, col in zip(cats, cols):
            with col:
                _render_category_radar(active_profile, cat)

    st.divider()

    # ── Dimension Details (expandable) ───────────────────────────
    _render_dimension_details(active_profile)

    st.divider()

    # ── LLM-Assessed Profile ─────────────────────────────────────
    _render_llm_profile_section(
        active_profile,
        filtered_profiles,
        is_single_session,
        active_session_id,
    )

    st.divider()

    # ── Weekly LLM Analysis ──────────────────────────────────────
    _render_weekly_analysis_section(filtered_profiles)

    st.divider()

    # ── Timeline: Score evolution ────────────────────────────────
    if len(filtered_profiles) > 1:
        _render_timeline(filtered_profiles)


# ── Components ──────────────────────────────────────────────────


def _build_dimension_hover(d) -> str:
    """Build hover text for a dimension (shared by full spider and category radars)."""
    lines = [f"<b>{d.name}: {d.score}/10</b>"]
    if d.guide:
        lines.append(f"<br><i>{d.guide}</i>")
    if d.explanation:
        lines.append(f"<br>{d.explanation}")
    if d.improvement_hint:
        lines.append(f"<br>\U0001f4a1 {d.improvement_hint}")
    return "<br>".join(lines)


def _render_full_spider(profile):
    """Render all 16 dimensions as a single spider web chart."""
    # Order dimensions by category (comm → strat → tech → auto)
    ordered_dims = []
    for cat in CATEGORY_ORDER:
        ordered_dims.extend([d for d in profile.dimensions if d.category == cat])

    if not ordered_dims:
        return

    labels = [_ABBREV_LABELS.get(d.key, d.name) for d in ordered_dims]
    scores = [d.score for d in ordered_dims]
    colors = [CATEGORY_COLORS.get(d.category, "#666") for d in ordered_dims]
    hover_texts = [_build_dimension_hover(d) for d in ordered_dims]

    # Close the polygon
    labels_closed = labels + [labels[0]]
    scores_closed = scores + [scores[0]]
    colors_closed = colors + [colors[0]]
    hover_closed = hover_texts + [hover_texts[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=scores_closed,
            theta=labels_closed,
            fill="toself",
            fillcolor="rgba(99, 102, 241, 0.12)",
            line=dict(color="#6366f1", width=2),
            marker=dict(color=colors_closed, size=9),
            text=hover_closed,
            hoverinfo="text",
            name="Full Profile",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
            angularaxis=dict(tickfont=dict(size=10)),
        ),
        height=500,
        margin=dict(l=80, r=80, t=40, b=40),
        showlegend=False,
        title=dict(text="Full 16-Dimension Profile", font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_composite_radar(profile):
    """Render 4-axis composite radar (one axis per category)."""
    cats = CATEGORY_ORDER
    names = [f"{CATEGORY_ICONS.get(c, '')} {c.capitalize()}" for c in cats]
    scores = [profile.category_scores.get(c, 5.0) for c in cats]

    # Build hover text with category dimension breakdown
    hover_texts = []
    for cat in cats:
        cat_dims = [d for d in profile.dimensions if d.category == cat]
        lines = [f"<b>{cat.capitalize()}: {profile.category_scores.get(cat, 5.0)}</b><br>"]
        for d in cat_dims:
            lines.append(f"  {d.name}: {d.score}")
        hover_texts.append("<br>".join(lines))

    names_closed = names + [names[0]]
    scores_closed = scores + [scores[0]]
    hover_closed = hover_texts + [hover_texts[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=scores_closed,
            theta=names_closed,
            fill="toself",
            fillcolor="rgba(99, 102, 241, 0.15)",
            line=dict(color="#6366f1", width=2.5),
            marker=dict(
                color=[CATEGORY_COLORS.get(c, "#666") for c in cats] + [CATEGORY_COLORS.get(cats[0], "#666")],
                size=10,
            ),
            text=hover_closed,
            hoverinfo="text",
            name="Composite",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
            angularaxis=dict(tickfont=dict(size=13)),
        ),
        height=400,
        margin=dict(l=60, r=60, t=30, b=30),
        showlegend=False,
        title=dict(text="Composite Profile", font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_category_radar(profile, category: str):
    """Render a single category's 4-axis radar."""
    cat_dims = [d for d in profile.dimensions if d.category == category]
    if not cat_dims:
        return

    color = CATEGORY_COLORS.get(category, "#666")
    icon = CATEGORY_ICONS.get(category, "")
    cat_score = profile.category_scores.get(category, 5.0)

    names = [d.name for d in cat_dims]
    scores = [d.score for d in cat_dims]
    hover_texts = [_build_dimension_hover(d) for d in cat_dims]

    names_closed = names + [names[0]]
    scores_closed = scores + [scores[0]]
    hover_closed = hover_texts + [hover_texts[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=scores_closed,
            theta=names_closed,
            fill="toself",
            fillcolor=f"rgba({_hex_to_rgb(color)}, 0.15)",
            line=dict(color=color, width=2),
            marker=dict(color=color, size=8),
            text=hover_closed,
            hoverinfo="text",
            name=category.capitalize(),
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2.5, 5, 7.5, 10]),
            angularaxis=dict(tickfont=dict(size=10)),
        ),
        height=320,
        margin=dict(l=50, r=50, t=40, b=20),
        showlegend=False,
        title=dict(text=f"{icon} {category.capitalize()} — {cat_score}", font=dict(size=13)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_summary(profile, session_count: int):
    """Render category bars, overall score, strengths, and gaps."""
    tier_name, tier_color = get_tier(profile.overall_score)

    st.markdown(
        f"### Overall Score: **{profile.overall_score}** / 10\n"
        f"Tier: <span style='color:{tier_color};font-weight:bold'>{tier_name}</span>",
        unsafe_allow_html=True,
    )
    if session_count > 1:
        st.caption(f"Aggregated from {session_count} sessions")

    st.markdown("---")

    # Category score bars
    st.markdown("**Category Scores**")
    for cat in CATEGORY_ORDER:
        cat_score = profile.category_scores.get(cat, 5.0)
        color = CATEGORY_COLORS.get(cat, "#666")
        icon = CATEGORY_ICONS.get(cat, "")
        pct = cat_score / 10 * 100
        st.markdown(
            f"<div style='margin-bottom:8px'>"
            f"<span style='text-transform:capitalize;font-weight:600'>{icon} {cat}</span>"
            f" <span style='color:#888'>{cat_score}</span>"
            f"<div style='background:#1a1a2e;border-radius:4px;height:12px;margin-top:2px'>"
            f"<div style='background:{color};width:{pct}%;height:12px;border-radius:4px'></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Top 3 strengths / Bottom 3 gaps
    sorted_dims = sorted(profile.dimensions, key=lambda d: d.score, reverse=True)

    st.markdown("**Top 3 Strengths**")
    for d in sorted_dims[:3]:
        color = CATEGORY_COLORS.get(d.category, "#666")
        st.markdown(f"- <span style='color:{color}'>{d.name}</span> — **{d.score}**", unsafe_allow_html=True)

    st.markdown("**Bottom 3 Gaps**")
    for d in sorted_dims[-3:]:
        color = CATEGORY_COLORS.get(d.category, "#666")
        st.markdown(
            f"- <span style='color:{color}'>{d.name}</span> — **{d.score}**",
            unsafe_allow_html=True,
        )


def _score_tier_label(score: float) -> tuple[str, str]:
    """Return (tier_label, color) for a dimension score."""
    if score >= 8:
        return "Strong", "#22c55e"
    elif score >= 6:
        return "Good", "#84cc16"
    elif score >= 4:
        return "Moderate", "#f59e0b"
    elif score >= 2:
        return "Needs Work", "#ef4444"
    else:
        return "Critical", "#dc2626"


def _interpret_subscore(sub) -> str:
    """Return plain-English interpretation of a sub-score."""
    n = sub.normalized
    if n >= 0.8:
        level = "Excellent"
    elif n >= 0.6:
        level = "Good"
    elif n >= 0.4:
        level = "Moderate"
    elif n >= 0.2:
        level = "Low"
    else:
        level = "Very low"
    return f"{level} — {n:.0%} of ideal ({sub.threshold})" if sub.threshold else f"{level} — {n:.0%} of ideal"


def _render_dimension_details(profile):
    """Gated section — detailed sub-score analysis is on guilder.dev."""
    st.subheader("Dimension Details")
    st.info(
        "\U0001f50d **Detailed sub-score analysis, improvement guides, and work pattern insights** "
        "are available on [guilder.dev](https://guilder.dev).\n\n"
        "Upload your profile to get personalized improvement recommendations."
    )


def _format_raw_value(raw_value: float, threshold: str, name: str = "") -> str:
    """Format raw_value with context-aware formatting based on threshold and name text."""
    combined = f"{threshold or ''} {name or ''}".lower()
    if 0 <= raw_value <= 1 and any(kw in combined for kw in ("ratio", "percentage", "%", "fraction", "fit")):
        return f"{raw_value:.0%}"
    if raw_value == int(raw_value) and raw_value >= 0:
        return f"{int(raw_value)}"
    if raw_value > 10:
        return f"{raw_value:.0f}"
    return f"{raw_value:.2f}"


def _render_subscore_waterfall(dim):
    """Render horizontal bar chart showing sub-score normalized % of ideal."""
    subs = dim.sub_scores
    if not subs:
        return

    # Bar labels: name with weight annotation
    names = [f"{s.name} ({s.weight:.0%})" for s in subs]
    normalized_pct = [s.normalized * 100 for s in subs]

    # Color by normalized score — highlight extremes
    colors = []
    for s in subs:
        n = s.normalized
        if n == 0.0:
            colors.append("#dc2626")  # Red for 0%
        elif n >= 1.0:
            colors.append("#eab308")  # Gold for 100%
        elif n >= 0.7:
            colors.append("#22c55e")
        elif n >= 0.4:
            colors.append("#f59e0b")
        else:
            colors.append("#ef4444")

    # Bar text: formatted raw value
    bar_texts = [_format_raw_value(s.raw_value, s.threshold, s.name) for s in subs]

    hover_texts = [
        f"<b>{s.name}</b><br>"
        f"Value: {_format_raw_value(s.raw_value, s.threshold, s.name)}<br>"
        f"Score: {s.normalized:.0%} of ideal<br>"
        f"Weight: {s.weight:.0%} of dimension score<br>"
        f"<i>{s.threshold}</i>"
        for s in subs
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=names,
            x=normalized_pct,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            text=bar_texts,
            textposition="auto",
            hovertext=hover_texts,
            hoverinfo="text",
        )
    )

    fig.update_layout(
        height=max(120, len(subs) * 40),
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(
            title="% of Ideal",
            range=[0, 105],
            showgrid=True,
            gridcolor="rgba(255,255,255,0.05)",
            ticksuffix="%",
        ),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Flag extreme sub-scores
    for s in subs:
        if s.normalized == 0.0:
            st.caption(
                f"\u26a0\ufe0f **{s.name}**: This signal wasn't detected (e.g., no questions asked, no tests run)."
            )
        elif s.normalized >= 1.0:
            st.caption(f"\u2b50 **{s.name}**: Perfect score \u2014 verify this isn't an artifact of a short session.")


# ── LLM Profile Section ─────────────────────────────────────────


def _render_llm_profile_section(
    active_profile,
    filtered_profiles: list,
    is_single_session: bool,
    active_session_id: str,
):
    """Render the LLM-assessed profile section."""
    try:
        from claudealytics.analytics.aggregators.llm_profile_scorer import (
            get_all_cached_scores,
            get_cached_score,
            score_session,
        )
    except Exception as e:
        st.subheader("LLM-Assessed Profile")
        st.warning(f"LLM scoring unavailable: {e}")
        return

    st.subheader("LLM-Assessed Profile")
    st.caption("Qualitative dimensions scored by Claude — captures nuances heuristics can't measure.")

    try:
        if is_single_session and active_session_id:
            _render_llm_single_session(
                active_session_id,
                active_profile,
                get_cached_score,
                score_session,
            )
        else:
            _render_llm_all_sessions(filtered_profiles, get_all_cached_scores)
    except Exception as e:
        st.error(f"Error rendering LLM profile: {e}")


def _render_llm_single_session(session_id, profile, get_cached_score_fn, score_session_fn):
    """Render LLM profile for a single session."""
    cached = get_cached_score_fn(session_id)

    if cached and cached.dimensions:
        _render_llm_radar(cached)
        _render_llm_details(cached)
    else:
        st.info("This session hasn't been scored by LLM yet.")
        if st.button("Score with LLM", key="llm_score_btn", type="primary"):
            with st.spinner("Scoring with Claude..."):
                llm_profile, error = score_session_fn(
                    session_id=session_id,
                    project=profile.project,
                    date=profile.date,
                )
            if error:
                st.error(f"LLM scoring failed: {error}")
            elif llm_profile.dimensions:
                _render_llm_radar(llm_profile)
                _render_llm_details(llm_profile)
            else:
                st.warning("LLM scoring returned no dimensions.")


def _batch_score_sessions(unscored_profiles: list, max_batch: int = 50):
    """Score a batch of sessions with LLM, showing a progress bar."""
    from claudealytics.analytics.aggregators.llm_profile_scorer import score_session

    batch = unscored_profiles[:max_batch]
    progress = st.progress(0, text=f"Scoring 0/{len(batch)} sessions...")

    errors: list[str] = []
    successes = 0

    consecutive_failures = 0
    last_error = ""

    for i, p in enumerate(batch):
        _profile, error = score_session(
            session_id=p.session_id,
            project=p.project,
            date=p.date,
            total_messages=0,
        )
        if error:
            errors.append(f"{p.session_id[:12]}: {error}")
            # Track consecutive non-"No turns" failures to detect systemic issues
            if "No turns to sample" not in error:
                consecutive_failures += 1
                last_error = error
            else:
                consecutive_failures = 0
        else:
            successes += 1
            consecutive_failures = 0
        progress.progress(
            (i + 1) / len(batch),
            text=f"Scoring {i + 1}/{len(batch)} — {successes} ok, {len(errors)} failed",
        )
        if (i + 1) % 10 == 0:
            st.toast(f"Scored {i + 1}/{len(batch)} sessions...")

        # Stop early if 3+ consecutive non-trivial failures (likely a config issue)
        if consecutive_failures >= 3:
            progress.empty()
            st.error(
                f"**Stopped early after {consecutive_failures} consecutive failures.**\n\n"
                f"Root cause: `{last_error}`\n\n"
                "Ensure the `claude` CLI is installed and authenticated. "
                "Run `claude --version` in your terminal to verify."
            )
            return

    progress.empty()

    if errors:
        error_preview = "\n".join(errors[:5])
        extra = f"\n...and {len(errors) - 5} more" if len(errors) > 5 else ""
        st.error(f"**{len(errors)}/{len(batch)} sessions failed:**\n```\n{error_preview}{extra}\n```")
    if successes:
        st.success(f"Successfully scored {successes}/{len(batch)} sessions.")


def _render_llm_all_sessions(filtered_profiles, get_all_cached_fn):
    """Render aggregated LLM profile across all scored sessions."""
    all_cached = get_all_cached_fn()
    session_ids = {p.session_id for p in filtered_profiles}
    scored = {sid: prof for sid, prof in all_cached.items() if sid in session_ids}
    unscored = [p for p in filtered_profiles if p.session_id not in scored]

    st.markdown(
        "Claude reads sampled turns and scores qualitative dimensions "
        "(clarity, feedback, thinking) that heuristics can't capture. ~30s per session."
    )

    if not scored and not unscored:
        st.info("No sessions available for scoring.")
        return

    st.caption(f"{len(scored)}/{len(session_ids)} sessions scored")

    # Batch scoring button
    if unscored:
        batch_size = min(len(unscored), 50)
        remaining = len(unscored)
        label = f"Score First {batch_size}" if not scored else f"Score Next {batch_size} ({remaining} remaining)"
        if st.button(label, key="llm_batch_score_btn", type="primary"):
            try:
                with st.spinner("Scoring sessions via Claude CLI..."):
                    _batch_score_sessions(unscored, max_batch=50)
            except Exception as e:
                st.error(f"Batch scoring failed: {e}")
            else:
                st.rerun()

    if not scored:
        return

    # Average across scored sessions
    from claudealytics.models.schemas import LLMDimensionScore, LLMProfile

    dim_scores: dict[str, list[float]] = {}
    dim_meta: dict[str, dict] = {}
    for prof in scored.values():
        for d in prof.dimensions:
            dim_scores.setdefault(d.key, []).append(d.score)
            if d.key not in dim_meta:
                dim_meta[d.key] = {"name": d.name, "category": d.category}

    avg_dims = []
    for key, scores in dim_scores.items():
        meta = dim_meta[key]
        avg_dims.append(
            LLMDimensionScore(
                key=key,
                name=meta["name"],
                category=meta["category"],
                score=round(sum(scores) / len(scores), 1),
                reasoning=f"Averaged from {len(scores)} sessions",
                confidence=round(len(scores) / len(session_ids), 2),
            )
        )

    cat_scores: dict[str, list[float]] = {}
    for d in avg_dims:
        cat_scores.setdefault(d.category, []).append(d.score)
    cat_avgs = {cat: round(sum(s) / len(s), 1) for cat, s in cat_scores.items()}

    avg_profile = LLMProfile(
        dimensions=avg_dims,
        overall_score=round(sum(d.score for d in avg_dims) / len(avg_dims), 1) if avg_dims else 5.0,
        category_scores=cat_avgs,
        messages_sampled=sum(p.messages_sampled for p in scored.values()),
    )

    _render_llm_radar(avg_profile)
    _render_llm_details(avg_profile)


def _render_llm_radar(llm_profile):
    """Render 8-axis LLM profile radar with category-based colors."""
    dims = llm_profile.dimensions
    if not dims:
        return

    # Order by category for visual grouping
    cat_order = ["communication", "strategy", "technical", "autonomy"]
    ordered_dims = []
    for cat in cat_order:
        ordered_dims.extend([d for d in dims if d.category == cat])
    if not ordered_dims:
        ordered_dims = dims

    labels = [d.name for d in ordered_dims]
    scores = [d.score for d in ordered_dims]
    colors = [CATEGORY_COLORS.get(d.category, "#8b5cf6") for d in ordered_dims]

    hover_texts = []
    for d in ordered_dims:
        lines = [f"<b>{d.name}: {d.score}/10</b>"]
        if d.reasoning:
            lines.append(f"<br><i>{d.reasoning}</i>")
        if d.evidence_quotes:
            lines.append("<br><b>Evidence:</b>")
            for q in d.evidence_quotes[:2]:
                lines.append(f'  "{q[:100]}"')
        lines.append(f"<br>Confidence: {d.confidence:.0%}")
        hover_texts.append("<br>".join(lines))

    labels_closed = labels + [labels[0]]
    scores_closed = scores + [scores[0]]
    colors_closed = colors + [colors[0]]
    hover_closed = hover_texts + [hover_texts[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=scores_closed,
            theta=labels_closed,
            fill="toself",
            fillcolor="rgba(20, 184, 166, 0.12)",
            line=dict(color="#14b8a6", width=2),
            marker=dict(color=colors_closed, size=9),
            text=hover_closed,
            hoverinfo="text",
            name="LLM Profile",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        height=420,
        margin=dict(l=70, r=70, t=40, b=40),
        showlegend=False,
        title=dict(text="LLM-Assessed Dimensions (8)", font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_llm_details(llm_profile):
    """Render expandable reasoning and evidence for each LLM dimension."""
    if not llm_profile.dimensions:
        return

    for d in llm_profile.dimensions:
        with st.expander(f"{d.name} — {d.score}/10 (confidence: {d.confidence:.0%})"):
            if d.reasoning:
                st.markdown(d.reasoning)
            if d.evidence_quotes:
                st.markdown("**Evidence quotes:**")
                for q in d.evidence_quotes:
                    st.markdown(f"> {q}")

    if llm_profile.model_used:
        st.caption(
            f"Model: {llm_profile.model_used} | "
            f"Sampled: {llm_profile.messages_sampled} turn pairs | "
            f"Scored: {llm_profile.scored_at[:19] if llm_profile.scored_at else 'N/A'}"
        )


def _render_weekly_analysis_section(filtered_profiles: list):
    """Render the Weekly LLM Analysis section — batch scoring + insights pipeline."""
    st.subheader("Weekly LLM Analysis")
    st.caption("Batch-score last week's sessions and generate cross-session insights via Claude.")

    try:
        from claudealytics.analytics.aggregators.llm_meta_analyzer import (
            generate_insights,
            load_cached_insights,
        )
        from claudealytics.analytics.aggregators.llm_profile_scorer import (
            get_all_cached_scores,
            score_batch,
        )
        from claudealytics.analytics.parsers.instruction_extractor import (
            extract_weekly_instructions,
        )
    except Exception as e:
        st.warning(f"Weekly analysis unavailable: {e}")
        return

    # Check for cached insights first
    cached_insights = load_cached_insights()
    if cached_insights and cached_insights.narrative:
        st.success("Insights generated — showing cached results (refreshes every 24h).")
        _render_insights_card(cached_insights)

        if st.button("Refresh Analysis", key="weekly_refresh_btn"):
            _run_weekly_pipeline(
                filtered_profiles,
                extract_weekly_instructions,
                score_batch,
                generate_insights,
                get_all_cached_scores,
                force_refresh=True,
            )
        return

    # No cached insights — show the pipeline button
    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.info(
            "Extracts human instructions from the last 7 days, "
            "batch-scores them via Claude, then generates personalized insights."
        )
    with col_btn:
        if st.button("Analyze Last Week", key="weekly_analyze_btn", type="primary"):
            _run_weekly_pipeline(
                filtered_profiles,
                extract_weekly_instructions,
                score_batch,
                generate_insights,
                get_all_cached_scores,
            )


def _run_weekly_pipeline(
    filtered_profiles,
    extract_fn,
    score_batch_fn,
    generate_insights_fn,
    get_all_cached_fn,
    force_refresh: bool = False,
):
    """Run the full weekly analysis pipeline with progress."""
    from claudealytics.analytics.aggregators.llm_profile_scorer import BATCH_SIZE

    progress = st.progress(0, text="Extracting instructions from last week...")

    # Step 1: Extract instructions
    weekly_instructions = extract_fn(days=7)
    if not weekly_instructions:
        progress.empty()
        st.warning("No sessions found in the last 7 days.")
        return

    st.caption(
        f"Found {len(weekly_instructions)} sessions with {sum(s.message_count for s in weekly_instructions)} messages"
    )
    progress.progress(0.15, text=f"Found {len(weekly_instructions)} sessions. Scoring batches...")

    # Step 2: Batch score
    all_profiles = []
    all_errors = []
    total_batches = max(1, (len(weekly_instructions) + BATCH_SIZE - 1) // BATCH_SIZE)

    for i in range(0, len(weekly_instructions), BATCH_SIZE):
        batch = weekly_instructions[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        progress.progress(
            0.15 + 0.6 * (batch_num / total_batches),
            text=f"Scoring batch {batch_num}/{total_batches} ({len(batch)} sessions)...",
        )
        profiles, errors = score_batch_fn(batch)
        all_profiles.extend(profiles)
        all_errors.extend(errors)

    if all_errors:
        st.warning(f"{len(all_errors)} scoring errors (see details below)")
        with st.expander("Scoring errors"):
            for err in all_errors[:10]:
                st.text(err)

    if not all_profiles:
        progress.empty()
        st.error("No sessions were successfully scored.")
        return

    progress.progress(0.8, text="Generating cross-session insights via Opus...")

    # Step 3: Generate insights
    # Also pass heuristic profiles for richer analysis
    heuristic_for_week = [
        p for p in filtered_profiles if any(s.session_id == p.session_id for s in weekly_instructions)
    ]

    insights, error = generate_insights_fn(
        all_profiles,
        heuristic_profiles=heuristic_for_week or None,
        force_refresh=force_refresh,
    )

    progress.progress(1.0, text="Done!")
    progress.empty()

    if error:
        st.error(f"Insights generation failed: {error}")
        # Still show scored data
        if all_profiles:
            st.subheader("Scored Sessions (without insights)")
            _render_batch_summary(all_profiles)
        return

    _render_insights_card(insights)

    # Show combined radar
    if all_profiles:
        st.divider()
        _render_combined_radar(all_profiles, filtered_profiles)


def _render_insights_card(insights):
    """Render the ProfileInsights as a rich card layout."""
    if not insights.narrative:
        return

    # Archetype badge
    if insights.archetype:
        st.markdown(
            f"<div style='text-align:center;margin-bottom:16px'>"
            f"<span style='background:linear-gradient(135deg, #6366f1, #14b8a6);padding:8px 20px;"
            f"border-radius:20px;font-size:1.1em;font-weight:bold;color:white'>"
            f"{insights.archetype}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
        if insights.archetype_description:
            st.caption(insights.archetype_description)

    # Narrative
    with st.expander("Full Assessment", expanded=True):
        st.markdown(insights.narrative)

    # Strengths and Growth Areas side by side
    col_strengths, col_growth = st.columns(2)

    with col_strengths:
        st.markdown("**Strengths**")
        for s in insights.strengths:
            evidence_html = "<br><i style='color:#6b7280;font-size:0.85em'>" + s.evidence + "</i>" if s.evidence else ""
            st.markdown(
                f"<div style='background:#0d2818;border-left:3px solid #22c55e;padding:8px 12px;"
                f"margin-bottom:8px;border-radius:4px'>"
                f"<b>{s.title}</b><br>"
                f"<span style='color:#a3a3a3;font-size:0.9em'>{s.description}</span>"
                f"{evidence_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

    with col_growth:
        st.markdown("**Growth Areas**")
        for g in insights.growth_areas:
            evidence_html = "<br><i style='color:#6b7280;font-size:0.85em'>" + g.evidence + "</i>" if g.evidence else ""
            st.markdown(
                f"<div style='background:#1c1007;border-left:3px solid #f59e0b;padding:8px 12px;"
                f"margin-bottom:8px;border-radius:4px'>"
                f"<b>{g.title}</b><br>"
                f"<span style='color:#a3a3a3;font-size:0.9em'>{g.description}</span>"
                f"{evidence_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Trends
    if insights.trends:
        st.markdown("**Trends**")
        for t in insights.trends:
            arrow = {"improving": "\u2191", "declining": "\u2193", "stable": "\u2192"}.get(t.direction, "\u2192")
            color = {"improving": "#22c55e", "declining": "#ef4444", "stable": "#a3a3a3"}.get(t.direction, "#a3a3a3")
            st.markdown(
                f"<span style='color:{color};font-weight:bold'>{arrow}</span> **{t.dimension}**: {t.description}",
                unsafe_allow_html=True,
            )

    # Action items
    if insights.action_items:
        st.markdown("**Action Items for Next Week**")
        for item in insights.action_items:
            st.checkbox(item, key=f"action_{hash(item)}", value=False)

    # Metadata
    if insights.generated_at:
        st.caption(f"Generated: {insights.generated_at[:19]} | Model: {insights.model_used}")


def _render_batch_summary(profiles):
    """Show summary stats from batch-scored profiles."""
    dim_scores: dict[str, list[float]] = {}
    for p in profiles:
        for d in p.dimensions:
            dim_scores.setdefault(d.name, []).append(d.score)

    for name, scores in sorted(dim_scores.items()):
        avg = sum(scores) / len(scores)
        st.metric(name, f"{avg:.1f}", delta=None)


def _render_combined_radar(llm_profiles, heuristic_profiles):
    """Render combined radar with LLM dims overlaid on heuristic profile."""
    # Average LLM dims
    llm_agg: dict[str, list[float]] = {}
    llm_meta: dict[str, dict] = {}
    for p in llm_profiles:
        for d in p.dimensions:
            llm_agg.setdefault(d.key, []).append(d.score)
            if d.key not in llm_meta:
                llm_meta[d.key] = {"name": d.name, "category": d.category}

    if not llm_agg:
        return

    st.subheader("Combined Profile Radar")
    st.caption("Heuristic (solid) vs LLM-assessed (dashed) dimensions")

    # LLM radar trace
    llm_labels = []
    llm_scores = []
    llm_colors = []
    cat_order = ["communication", "strategy", "technical", "autonomy"]
    for cat in cat_order:
        for key, meta in llm_meta.items():
            if meta["category"] == cat:
                llm_labels.append(meta["name"])
                llm_scores.append(round(sum(llm_agg[key]) / len(llm_agg[key]), 1))
                llm_colors.append(CATEGORY_COLORS.get(cat, "#8b5cf6"))

    if not llm_labels:
        return

    llm_labels_closed = llm_labels + [llm_labels[0]]
    llm_scores_closed = llm_scores + [llm_scores[0]]
    llm_colors_closed = llm_colors + [llm_colors[0]]

    fig = go.Figure()

    # LLM trace (dashed)
    fig.add_trace(
        go.Scatterpolar(
            r=llm_scores_closed,
            theta=llm_labels_closed,
            fill="toself",
            fillcolor="rgba(20, 184, 166, 0.08)",
            line=dict(color="#14b8a6", width=2, dash="dash"),
            marker=dict(color=llm_colors_closed, size=8),
            name="LLM-Assessed",
        )
    )

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
            angularaxis=dict(tickfont=dict(size=10)),
        ),
        height=480,
        margin=dict(l=80, r=80, t=40, b=40),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        title=dict(text="LLM-Assessed Profile (Weekly)", font=dict(size=14)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_timeline(profiles: list):
    """Render weekly rolling category score evolution + per-dimension charts + animated radar."""
    import pandas as pd

    st.subheader(
        "Score Evolution Over Time",
        help="Weekly rolling average of category scores across conversations.",
    )

    # ── Build category-level dataframe ───────────────────────────
    cat_rows = []
    for p in profiles:
        if not p.date:
            continue
        for cat, score in p.category_scores.items():
            cat_rows.append({"date": p.date, "category": cat, "score": score})

    if not cat_rows:
        st.info("Not enough data for timeline.")
        return

    cat_df = pd.DataFrame(cat_rows)
    cat_df["date"] = pd.to_datetime(cat_df["date"], errors="coerce")
    cat_df = cat_df.dropna(subset=["date"]).sort_values("date")

    # ── Category evolution chart (with dynamic y-axis) ───────────
    all_scores = []
    fig = go.Figure()
    for cat in CATEGORY_ORDER:
        sub = cat_df[cat_df["category"] == cat].copy()
        if sub.empty:
            continue
        sub = sub.set_index("date").resample("W")["score"].mean().reset_index()
        sub = sub.dropna()
        if sub.empty:
            continue

        all_scores.extend(sub["score"].tolist())
        icon = CATEGORY_ICONS.get(cat, "")
        fig.add_trace(
            go.Scatter(
                x=sub["date"],
                y=sub["score"],
                mode="lines+markers",
                name=f"{icon} {cat.capitalize()}",
                line=dict(color=CATEGORY_COLORS.get(cat, "#666"), width=2),
                marker=dict(size=5),
            )
        )

    if all_scores:
        y_min = max(1, min(all_scores) - 0.5)
        y_max = min(10, max(all_scores) + 0.5)
    else:
        y_min, y_max = 1, 10

    fig.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=40, b=0),
        yaxis=dict(title="Average Score", range=[y_min, y_max]),
        xaxis_title="Week",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Per-dimension evolution charts ───────────────────────────
    dim_rows = []
    for p in profiles:
        if not p.date:
            continue
        for d in p.dimensions:
            dim_rows.append(
                {
                    "date": p.date,
                    "key": d.key,
                    "name": d.name,
                    "category": d.category,
                    "score": d.score,
                }
            )

    if dim_rows:
        dim_df = pd.DataFrame(dim_rows)
        dim_df["date"] = pd.to_datetime(dim_df["date"], errors="coerce")
        dim_df = dim_df.dropna(subset=["date"]).sort_values("date")

        st.subheader("Per-Dimension Evolution")

        for cat in CATEGORY_ORDER:
            icon = CATEGORY_ICONS.get(cat, "")
            cat_dims = dim_df[dim_df["category"] == cat]
            if cat_dims.empty:
                continue

            with st.expander(f"{icon} {cat.capitalize()} Dimensions", expanded=False):
                dim_fig = go.Figure()
                all_dim_scores: list[float] = []
                dim_keys = cat_dims["key"].unique()
                color_idx = 0

                for dim_key in sorted(dim_keys):
                    sub = cat_dims[cat_dims["key"] == dim_key].copy()
                    dim_name = sub["name"].iloc[0]
                    sub = sub.set_index("date").resample("W")["score"].mean().reset_index()
                    sub = sub.dropna()
                    if sub.empty:
                        continue

                    all_dim_scores.extend(sub["score"].tolist())
                    line_color = _DIM_SUB_PALETTE[color_idx % len(_DIM_SUB_PALETTE)]
                    color_idx += 1

                    dim_fig.add_trace(
                        go.Scatter(
                            x=sub["date"],
                            y=sub["score"],
                            mode="lines+markers",
                            line=dict(color=line_color, width=2),
                            marker=dict(size=4),
                            name=dim_name,
                        )
                    )

                if not all_dim_scores:
                    continue

                d_ymin = max(1, min(all_dim_scores) - 0.5)
                d_ymax = min(10, max(all_dim_scores) + 0.5)

                dim_fig.update_layout(
                    height=350,
                    margin=dict(l=20, r=20, t=30, b=0),
                    yaxis=dict(title="Score", range=[d_ymin, d_ymax]),
                    xaxis_title="Week",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(dim_fig, use_container_width=True)

    # ── Animated radar progression ───────────────────────────────
    _render_animated_radar(profiles)


def _render_animated_radar(profiles: list):
    """Render an animated 16-dimension radar chart that plays through weeks."""
    import pandas as pd

    # Build weekly averaged dimension scores
    rows = []
    for p in profiles:
        if not p.date or not p.dimensions:
            continue
        for d in p.dimensions:
            rows.append(
                {
                    "date": p.date,
                    "key": d.key,
                    "name": d.name,
                    "category": d.category,
                    "score": d.score,
                }
            )

    if not rows:
        return

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["week"] = df["date"].dt.to_period("W").dt.start_time

    weeks = sorted(df["week"].unique())
    if len(weeks) < 2:
        st.info("Need at least 2 weeks of data for score progression animation.")
        return

    # Order dimensions by canonical order (matches full 16-dim spider)
    key_to_name = {}
    for _, row in df[["key", "name"]].drop_duplicates().iterrows():
        key_to_name[row["key"]] = row["name"]

    available_keys = set(key_to_name.keys())
    ordered_keys = [k for k in _CANONICAL_DIM_ORDER if k in available_keys]
    ordered_names = [_ABBREV_LABELS.get(k, key_to_name[k]) for k in ordered_keys]

    if not ordered_keys:
        return

    # Close the polygon
    labels = ordered_names + [ordered_names[0]]

    # Build color list for markers
    key_to_cat = dict(
        zip(
            df["key"],
            df["category"],
        )
    )
    marker_colors = [CATEGORY_COLORS.get(key_to_cat.get(k, ""), "#666") for k in ordered_keys]
    marker_colors_closed = marker_colors + [marker_colors[0]]

    # Build frames
    frames = []
    week_labels = []
    for week in weeks:
        week_data = df[df["week"] == week]
        week_avg = week_data.groupby("key")["score"].mean()

        scores = [week_avg.get(k, 5.0) for k in ordered_keys]
        scores_closed = scores + [scores[0]]  # close polygon

        week_label = week.strftime("%Y-%m-%d")
        week_labels.append(week_label)

        frames.append(
            go.Frame(
                data=[
                    go.Scatterpolar(
                        r=scores_closed,
                        theta=labels,
                        fill="toself",
                        fillcolor="rgba(99, 102, 241, 0.12)",
                        line=dict(color="#6366f1", width=2),
                        marker=dict(color=marker_colors_closed, size=8),
                        name="Profile",
                    )
                ],
                name=week_label,
            )
        )

    # Initial frame
    first_scores = frames[0].data[0].r

    st.subheader("Score Progression Animation")

    fig = go.Figure(
        data=[
            go.Scatterpolar(
                r=first_scores,
                theta=labels,
                fill="toself",
                fillcolor="rgba(99, 102, 241, 0.12)",
                line=dict(color="#6366f1", width=2),
                marker=dict(color=marker_colors_closed, size=8),
                name="Profile",
            )
        ],
        frames=frames,
    )

    # Play/pause buttons
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickvals=[2, 4, 6, 8, 10]),
            angularaxis=dict(tickfont=dict(size=10)),
        ),
        height=550,
        margin=dict(l=80, r=80, t=60, b=80),
        showlegend=False,
        title=dict(text=f"Week: {week_labels[0]}", font=dict(size=14)),
        updatemenus=[
            dict(
                type="buttons",
                showactive=False,
                y=0,
                x=0.5,
                xanchor="center",
                buttons=[
                    dict(
                        label="Play",
                        method="animate",
                        args=[
                            None,
                            {
                                "frame": {"duration": 500, "redraw": True},
                                "fromcurrent": True,
                                "transition": {"duration": 300},
                            },
                        ],
                    ),
                    dict(
                        label="Pause",
                        method="animate",
                        args=[
                            [None],
                            {
                                "frame": {"duration": 0, "redraw": False},
                                "mode": "immediate",
                                "transition": {"duration": 0},
                            },
                        ],
                    ),
                ],
            )
        ],
        sliders=[
            dict(
                active=0,
                steps=[
                    dict(
                        args=[
                            [wl],
                            {
                                "frame": {"duration": 300, "redraw": True},
                                "mode": "immediate",
                                "transition": {"duration": 300},
                            },
                        ],
                        label=wl,
                        method="animate",
                    )
                    for wl in week_labels
                ],
                x=0.1,
                len=0.8,
                xanchor="left",
                y=0,
                yanchor="top",
                currentvalue=dict(
                    prefix="Week: ",
                    visible=True,
                    xanchor="center",
                ),
                transition=dict(duration=300),
            )
        ],
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Helpers ─────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> str:
    """Convert '#6366f1' to '99, 102, 241'."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


# ── Data loading ────────────────────────────────────────────────


def _load_profiles_with_progress() -> list:
    """Load profiles with spinner/progress bar when computing from scratch.

    Skips progress UI entirely on disk cache hits.
    """
    import pandas as pd

    # Fast path: disk cache hit — no UI needed
    cached = _load_profile_cache()
    if cached:
        return cached

    # Slow path: need to compute — show progress
    status = st.empty()
    progress_bar = st.empty()

    with status.container():
        with st.spinner("Mining conversation data..."):
            dfs = mine_content(use_cache=True)

    session_stats = dfs.get("session_stats", pd.DataFrame())
    tool_calls = dfs.get("tool_calls", pd.DataFrame())
    human_lengths = dfs.get("human_message_lengths", pd.DataFrame())

    if session_stats.empty:
        status.empty()
        progress_bar.empty()
        return []

    bar = progress_bar.progress(0, text="Scoring sessions...")

    def _on_progress(fraction: float, message: str):
        bar.progress(fraction, text=message)

    profiles = compute_all_profiles(
        session_stats,
        tool_calls,
        human_lengths,
        use_cache=True,
        progress_callback=_on_progress,
    )

    # Clean up progress indicators
    status.empty()
    progress_bar.empty()

    return profiles
