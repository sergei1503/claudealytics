"""LLM-based conversation profile scorer.

Scores 6 qualitative dimensions that heuristics can't capture by sending
sampled conversation turns to Claude via the CLI. Results are permanently
cached per session_id since conversations are immutable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from claudealytics.analytics.parsers.message_sampler import sample_turns
from claudealytics.models.schemas import LLMDimensionScore, LLMProfile

# ── Constants ──────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
CACHE_PATH = CACHE_DIR / "llm-profile-scores.json"
DEFAULT_MODEL = "claude-sonnet-4-20250514"

LLM_DIMENSIONS = [
    {
        "key": "instruction_clarity",
        "name": "Instruction Clarity",
        "category": "communication",
        "rubric": (
            "How clear, specific, and unambiguous are the user's instructions? "
            "High scores = precise intent, success criteria, and constraints stated upfront. "
            "Low scores = vague requests requiring Claude to guess intent."
        ),
    },
    {
        "key": "problem_specification",
        "name": "Problem Specification Quality",
        "category": "communication",
        "rubric": (
            "How well does the user define the problem before jumping to solutions? "
            "High scores = clear problem statement with context, constraints, examples. "
            "Low scores = jumping straight to 'fix this' without explaining what's wrong."
        ),
    },
    {
        "key": "feedback_specificity",
        "name": "Feedback Specificity",
        "category": "communication",
        "rubric": (
            "When the user gives feedback or corrections, how specific and actionable is it? "
            "High scores = points to exact issues with clear expectations. "
            "Low scores = 'that's wrong' or 'try again' without guidance."
        ),
    },
    {
        "key": "architectural_thinking",
        "name": "Architectural Thinking",
        "category": "strategy",
        "rubric": (
            "Does the user demonstrate awareness of system architecture, trade-offs, "
            "and long-term implications? High scores = considers maintainability, "
            "patterns, and broader system impact. Low scores = purely local/tactical fixes."
        ),
    },
    {
        "key": "review_depth",
        "name": "Review Depth",
        "category": "technical",
        "rubric": (
            "How thoroughly does the user review Claude's output before accepting it? "
            "High scores = asks probing questions, catches edge cases, requests tests. "
            "Low scores = accepts output without review or verification."
        ),
    },
    {
        "key": "learning_progression",
        "name": "Learning Progression",
        "category": "strategy",
        "rubric": (
            "Does the conversation show evidence of the user learning and adapting their "
            "approach? High scores = evolving questions, building on previous answers, "
            "increasing sophistication. Low scores = repetitive patterns, no growth."
        ),
    },
]


# ── Cache Management ───────────────────────────────────────────


def load_llm_cache() -> dict:
    """Load the permanent LLM score cache."""
    if not CACHE_PATH.exists():
        return {"version": 1, "scores": {}}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        if not isinstance(data.get("scores"), dict):
            return {"version": 1, "scores": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "scores": {}}


def save_llm_score(session_id: str, profile: LLMProfile):
    """Save a single session's LLM score to the permanent cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_llm_cache()
    cache["scores"][session_id] = {
        "scored_at": profile.scored_at,
        "model_used": profile.model_used,
        "data": profile.model_dump(),
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def get_cached_score(session_id: str) -> LLMProfile | None:
    """Return cached LLM profile for a session, or None."""
    cache = load_llm_cache()
    entry = cache.get("scores", {}).get(session_id)
    if entry and "data" in entry:
        return LLMProfile(**entry["data"])
    return None


def get_all_cached_scores() -> dict[str, LLMProfile]:
    """Return all cached LLM profiles keyed by session_id."""
    cache = load_llm_cache()
    result = {}
    for sid, entry in cache.get("scores", {}).items():
        if "data" in entry:
            try:
                result[sid] = LLMProfile(**entry["data"])
            except Exception:
                continue
    return result


# ── LLM Scoring ────────────────────────────────────────────────


def _build_prompt(turns: list[dict]) -> str:
    """Build the scoring prompt with sampled turns and rubric."""
    turns_text = ""
    for t in turns:
        turns_text += f"\n--- Turn {t['turn_index'] + 1} ---\n"
        turns_text += f"USER: {t['human']}\n\n"
        turns_text += f"ASSISTANT: {t['assistant']}\n"

    dimensions_text = ""
    for d in LLM_DIMENSIONS:
        dimensions_text += f"\n- **{d['name']}** (`{d['key']}`, category: {d['category']}): {d['rubric']}"

    return f"""You are scoring a human user's conversation proficiency with an AI coding assistant.
Below are sampled turns from a conversation. Score the USER (not the assistant) on each dimension.

## Conversation Turns ({len(turns)} sampled)
{turns_text}

## Scoring Dimensions
{dimensions_text}

## Instructions

Score each dimension from 1.0 to 10.0 (one decimal place).
For each dimension, provide:
- A score (1.0-10.0)
- Brief reasoning (1-2 sentences)
- 0-2 direct quotes from the user's messages as evidence
- Confidence level (0.0-1.0) based on how much evidence was available

Respond with ONLY valid JSON in this exact format:
{{
  "dimensions": [
    {{
      "key": "dimension_key",
      "score": 7.5,
      "reasoning": "Brief explanation",
      "evidence_quotes": ["quote 1"],
      "confidence": 0.8
    }}
  ]
}}"""


def score_session(
    session_id: str,
    project: str = "",
    date: str = "",
    total_messages: int = 0,
) -> LLMProfile:
    """Score a single session using Claude CLI. Returns LLMProfile.

    Never re-scores if cached. Call get_cached_score() first to check.
    """
    # Check cache first
    cached = get_cached_score(session_id)
    if cached is not None:
        return cached

    # Sample turns
    turns = sample_turns(session_id)
    if not turns:
        return LLMProfile(
            session_id=session_id,
            project=project,
            date=date,
            scored_at=datetime.now(UTC).isoformat(),
        )

    # Build prompt and call Claude CLI
    prompt = _build_prompt(turns)
    model = os.environ.get("CLAUDE_INSIGHTS_LLM_PROFILE_MODEL", DEFAULT_MODEL)

    try:
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        cmd = ["claude", "--print", "--allowedTools", "", "--model", model]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            env=clean_env,
        )

        if result.returncode != 0:
            return _fallback_profile(session_id, project, date, len(turns), total_messages, model)

        response = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _fallback_profile(session_id, project, date, len(turns), total_messages, model)

    # Parse JSON response (handle markdown fences)
    parsed = _parse_llm_response(response)
    if not parsed:
        return _fallback_profile(session_id, project, date, len(turns), total_messages, model)

    # Build LLMProfile from parsed response
    dimensions = []
    dim_lookup = {d["key"]: d for d in LLM_DIMENSIONS}

    for dim_data in parsed.get("dimensions", []):
        key = dim_data.get("key", "")
        if key not in dim_lookup:
            continue
        dim_def = dim_lookup[key]
        dimensions.append(LLMDimensionScore(
            key=key,
            name=dim_def["name"],
            category=dim_def["category"],
            score=max(1.0, min(10.0, float(dim_data.get("score", 5.0)))),
            reasoning=dim_data.get("reasoning", ""),
            evidence_quotes=dim_data.get("evidence_quotes", []),
            confidence=max(0.0, min(1.0, float(dim_data.get("confidence", 0.5)))),
        ))

    # Fill missing dimensions with defaults
    scored_keys = {d.key for d in dimensions}
    for dim_def in LLM_DIMENSIONS:
        if dim_def["key"] not in scored_keys:
            dimensions.append(LLMDimensionScore(
                key=dim_def["key"],
                name=dim_def["name"],
                category=dim_def["category"],
            ))

    # Compute category and overall scores
    category_scores: dict[str, list[float]] = {}
    for d in dimensions:
        category_scores.setdefault(d.category, []).append(d.score)

    cat_avgs = {cat: round(sum(scores) / len(scores), 1) for cat, scores in category_scores.items()}
    overall = round(sum(d.score for d in dimensions) / len(dimensions), 1) if dimensions else 5.0

    profile = LLMProfile(
        session_id=session_id,
        project=project,
        date=date,
        dimensions=dimensions,
        overall_score=overall,
        category_scores=cat_avgs,
        model_used=model,
        messages_sampled=len(turns),
        total_messages=total_messages,
        scored_at=datetime.now(UTC).isoformat(),
    )

    # Save to permanent cache
    save_llm_score(session_id, profile)
    return profile


def _parse_llm_response(response: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _fallback_profile(
    session_id: str,
    project: str,
    date: str,
    sampled: int,
    total: int,
    model: str,
) -> LLMProfile:
    """Return a default profile when LLM scoring fails."""
    dimensions = [
        LLMDimensionScore(
            key=d["key"],
            name=d["name"],
            category=d["category"],
            reasoning="Scoring failed — using defaults.",
        )
        for d in LLM_DIMENSIONS
    ]
    return LLMProfile(
        session_id=session_id,
        project=project,
        date=date,
        dimensions=dimensions,
        overall_score=5.0,
        category_scores={},
        model_used=model,
        messages_sampled=sampled,
        total_messages=total,
        scored_at=datetime.now(UTC).isoformat(),
    )
