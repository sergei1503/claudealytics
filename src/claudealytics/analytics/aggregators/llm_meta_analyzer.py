"""Cross-session meta-analysis via Opus.

Synthesizes heuristic + LLM scores across all scored sessions into
personalized, actionable insights with archetype, trends, and action items.
Results are cached with 24h TTL.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from claudealytics.analytics.aggregators.llm_profile_scorer import LLM_DIMENSIONS
from claudealytics.models.schemas import (
    ConversationProfile,
    InsightItem,
    LLMProfile,
    ProfileInsights,
    TrendInsight,
)

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
INSIGHTS_CACHE_PATH = CACHE_DIR / "llm-insights.json"
CACHE_TTL_HOURS = 24
DEFAULT_MODEL = "opus"


def load_cached_insights() -> ProfileInsights | None:
    """Load cached insights if fresh (within TTL)."""
    if not INSIGHTS_CACHE_PATH.exists():
        return None
    try:
        with open(INSIGHTS_CACHE_PATH) as f:
            data = json.load(f)
        generated_at = data.get("generated_at", "")
        if not generated_at:
            return None
        gen_time = datetime.fromisoformat(generated_at)
        if datetime.now(UTC) - gen_time > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return ProfileInsights(**data)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def save_insights(insights: ProfileInsights) -> None:
    """Save insights to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(INSIGHTS_CACHE_PATH, "w") as f:
        json.dump(insights.model_dump(), f, indent=2)


def _build_meta_prompt(
    llm_profiles: list[LLMProfile],
    heuristic_profiles: list[ConversationProfile] | None = None,
) -> str:
    """Build the meta-analysis prompt from scored profiles."""
    # Aggregate LLM dimension scores
    llm_agg: dict[str, list[float]] = {}
    for p in llm_profiles:
        for d in p.dimensions:
            llm_agg.setdefault(d.key, []).append(d.score)

    llm_summary = ""
    dim_lookup = {d["key"]: d for d in LLM_DIMENSIONS}
    for key, scores in llm_agg.items():
        name = dim_lookup.get(key, {}).get("name", key)
        avg = sum(scores) / len(scores)
        llm_summary += f"- {name}: avg={avg:.1f} (n={len(scores)}, min={min(scores):.1f}, max={max(scores):.1f})\n"

    # Aggregate heuristic scores if available
    heuristic_summary = ""
    if heuristic_profiles:
        heur_agg: dict[str, list[float]] = {}
        for p in heuristic_profiles:
            for d in p.dimensions:
                heur_agg.setdefault(d.name, []).append(d.score)
        for name, scores in heur_agg.items():
            avg = sum(scores) / len(scores)
            heuristic_summary += f"- {name}: avg={avg:.1f} (n={len(scores)})\n"

    # Pick representative sessions (best + worst scoring)
    sorted_by_score = sorted(llm_profiles, key=lambda p: p.overall_score)
    examples = []
    if len(sorted_by_score) >= 2:
        examples = [sorted_by_score[0], sorted_by_score[-1]]  # worst, best
        if len(sorted_by_score) >= 4:
            mid = len(sorted_by_score) // 2
            examples.append(sorted_by_score[mid])  # median

    examples_text = ""
    for p in examples:
        examples_text += f"\n--- Session {p.session_id[:12]} (overall: {p.overall_score}) ---\n"
        for d in p.dimensions:
            examples_text += f"  {d.name}: {d.score}"
            if d.reasoning:
                examples_text += f" — {d.reasoning}"
            examples_text += "\n"

    return f"""You are an expert analyst reviewing a user's AI coding assistant usage patterns.
Analyze the following scored data from {len(llm_profiles)} sessions and provide actionable insights.

## LLM-Assessed Dimensions (aggregated across {len(llm_profiles)} sessions)
{llm_summary}

{"## Heuristic Dimensions (automated metrics)" if heuristic_summary else ""}
{heuristic_summary}

{"## Representative Sessions" if examples_text else ""}
{examples_text}

## Instructions

Provide a comprehensive analysis with:
1. **Narrative** (2-3 paragraphs): Overall assessment of this user's AI collaboration style
2. **Strengths** (top 3): What this user does well, with specific evidence
3. **Growth Areas** (top 3): Where to improve, with specific actionable advice
4. **Trends**: Which dimensions are improving, declining, or stable
5. **Archetype**: A 2-3 word label (e.g., "Delegator-Reviewer", "Precision Crafter") with description
6. **Action Items**: 3-5 specific things to try next week

Respond with ONLY valid JSON:
{{
  "narrative": "Overall assessment...",
  "strengths": [
    {{"dimension": "dim_name", "title": "Short title", "description": "Why this is strong", "evidence": "specific example"}}
  ],
  "growth_areas": [
    {{"dimension": "dim_name", "title": "Short title", "description": "What to improve", "evidence": "what was observed"}}
  ],
  "trends": [
    {{"dimension": "dim_name", "direction": "improving|declining|stable", "description": "trend explanation"}}
  ],
  "archetype": "Archetype Label",
  "archetype_description": "What this archetype means...",
  "action_items": ["Action 1", "Action 2", "Action 3"]
}}"""


def generate_insights(
    llm_profiles: list[LLMProfile],
    heuristic_profiles: list[ConversationProfile] | None = None,
    model: str | None = None,
    force_refresh: bool = False,
) -> tuple[ProfileInsights, str | None]:
    """Generate cross-session insights via a single Opus call.

    Args:
        llm_profiles: Scored LLM profiles from batch scoring.
        heuristic_profiles: Optional heuristic profiles for richer analysis.
        model: Model to use (default: opus).
        force_refresh: If True, ignore cache.

    Returns:
        (ProfileInsights, error_message). error_message is None on success.
    """
    if not force_refresh:
        cached = load_cached_insights()
        if cached:
            return cached, None

    if not llm_profiles:
        return ProfileInsights(), "No scored sessions to analyze"

    model = model or os.environ.get("CLAUDEALYTICS_META_MODEL", DEFAULT_MODEL)
    prompt = _build_meta_prompt(llm_profiles, heuristic_profiles)

    clean_env = {
        k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and not k.startswith("CLAUDE_CODE")
    }

    start_time = time.monotonic()
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--dangerously-skip-permissions",
                "--output-format",
                "json",
                "--model",
                model,
                "--no-session-persistence",
                "--system-prompt",
                "You are an expert analyst. Respond with ONLY valid JSON, no markdown fences.",
                "--max-budget-usd",
                "2.00",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=clean_env,
        )
    except FileNotFoundError:
        return ProfileInsights(), "claude CLI not found"
    except subprocess.TimeoutExpired:
        return ProfileInsights(), "claude CLI timed out after 180s"

    if result.returncode != 0:
        return ProfileInsights(), f"claude CLI error (exit {result.returncode}): {result.stderr[:200]}"

    elapsed = time.monotonic() - start_time
    logger.info("Generated insights with %s in %.1fs", model, elapsed)

    try:
        output = json.loads(result.stdout)
        if output.get("is_error") or output.get("subtype", "").startswith("error"):
            return ProfileInsights(), f"claude CLI: {output.get('subtype', 'unknown error')}"
        response = output.get("result", "")
    except (json.JSONDecodeError, AttributeError) as exc:
        return ProfileInsights(), f"Failed to parse CLI output: {exc}"

    # Parse JSON response
    parsed = _parse_insights_response(response)
    if not parsed:
        return ProfileInsights(), f"Failed to parse insights JSON: {response[:200]}"

    insights = ProfileInsights(
        narrative=parsed.get("narrative", ""),
        strengths=[InsightItem(**s) for s in parsed.get("strengths", []) if isinstance(s, dict)],
        growth_areas=[InsightItem(**g) for g in parsed.get("growth_areas", []) if isinstance(g, dict)],
        trends=[TrendInsight(**t) for t in parsed.get("trends", []) if isinstance(t, dict)],
        archetype=parsed.get("archetype", ""),
        archetype_description=parsed.get("archetype_description", ""),
        action_items=parsed.get("action_items", []),
        generated_at=datetime.now(UTC).isoformat(),
        model_used=model,
    )

    save_insights(insights)
    return insights, None


def _parse_insights_response(response: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
