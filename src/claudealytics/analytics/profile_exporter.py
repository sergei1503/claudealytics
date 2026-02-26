"""Export sanitized profile JSON for external sharing (leaderboard upload).

Produces a privacy-safe profile with no session IDs, project paths,
or conversation content — only aggregated scores.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version as pkg_version

from claudealytics.analytics.aggregators.llm_profile_scorer import get_all_cached_scores
from claudealytics.analytics.aggregators.profile_scorer import (
    aggregate_profiles,
    compute_all_profiles,
)
from claudealytics.analytics.parsers.content_miner import mine_content
from claudealytics.models.schemas import (
    ExportedDimension,
    ExportedLLMDimension,
    ExportedProfile,
)


def build_exported_profile() -> ExportedProfile:
    """Build a sanitized profile from all available data.

    Returns an ExportedProfile with aggregated scores across all sessions,
    stripped of any identifying information (session IDs, project paths,
    conversation content, evidence quotes).
    """
    # Mine conversation data
    dfs = mine_content(use_cache=True)
    session_stats = dfs.get("session_stats")
    tool_calls = dfs.get("tool_calls")
    human_lengths = dfs.get("human_message_lengths")

    if session_stats is None or session_stats.empty:
        return ExportedProfile(
            exported_at=datetime.now(UTC).isoformat(),
            claudealytics_version=_get_version(),
        )

    # Compute heuristic profiles for all sessions
    profiles = compute_all_profiles(session_stats, tool_calls, human_lengths, use_cache=True)

    if not profiles:
        return ExportedProfile(
            exported_at=datetime.now(UTC).isoformat(),
            claudealytics_version=_get_version(),
        )

    # Aggregate into a single summary profile
    aggregated = aggregate_profiles(profiles)

    # Determine date range from session dates
    dates = sorted(p.date for p in profiles if p.date)
    date_range = (dates[0], dates[-1]) if dates else ("", "")

    # Build sanitized dimensions (no explanations, no improvement hints — just scores)
    exported_dims = [
        ExportedDimension(
            key=d.key,
            name=d.name,
            category=d.category,
            score=d.score,
            sub_scores=d.sub_scores,
        )
        for d in aggregated.dimensions
    ]

    # Gather LLM scores if available
    llm_cached = get_all_cached_scores()
    llm_dims: list[ExportedLLMDimension] = []
    llm_overall: float | None = None
    llm_count = len(llm_cached)

    if llm_cached:
        # Aggregate LLM scores across all scored sessions
        dim_scores: dict[str, list[tuple[float, float]]] = {}  # key -> [(score, confidence)]
        for profile in llm_cached.values():
            for d in profile.dimensions:
                dim_scores.setdefault(d.key, []).append((d.score, d.confidence))

        for key, scores in dim_scores.items():
            avg_score = round(sum(s for s, _ in scores) / len(scores), 1)
            avg_conf = round(sum(c for _, c in scores) / len(scores), 2)
            # Use metadata from the first occurrence
            first_profile = next(iter(llm_cached.values()))
            dim_meta = next((d for d in first_profile.dimensions if d.key == key), None)
            if dim_meta:
                llm_dims.append(
                    ExportedLLMDimension(
                        key=key,
                        name=dim_meta.name,
                        category=dim_meta.category,
                        score=avg_score,
                        confidence=avg_conf,
                    )
                )

        if llm_dims:
            llm_overall = round(sum(d.score for d in llm_dims) / len(llm_dims), 1)

    return ExportedProfile(
        version=1,
        exported_at=datetime.now(UTC).isoformat(),
        claudealytics_version=_get_version(),
        sessions_analyzed=len(profiles),
        date_range=date_range,
        overall_score=aggregated.overall_score,
        category_scores=aggregated.category_scores,
        dimensions=exported_dims,
        llm_dimensions=llm_dims,
        llm_overall_score=llm_overall,
        llm_sessions_scored=llm_count,
    )


def _get_version() -> str:
    """Get the installed claudealytics version, or 'dev'."""
    try:
        return pkg_version("claudealytics")
    except Exception:
        return "dev"
