"""LLM-based conversation profile scorer.

Scores 6 qualitative dimensions that heuristics can't capture by sending
sampled conversation turns to Claude via the `claude` CLI. Results are permanently
cached per session_id since conversations are immutable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from claudealytics.analytics.parsers.message_sampler import sample_turns
from claudealytics.models.schemas import LLMDimensionScore, LLMProfile, SessionInstructions

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
CACHE_PATH = CACHE_DIR / "llm-profile-scores.json"
DEFAULT_MODEL = "sonnet"

SCHEMA_VERSION = 2  # v1 = old 6-dim, v2 = new 8-dim

LLM_DIMENSIONS = [
    # Communication (2 dims)
    {
        "key": "instruction_clarity",
        "name": "Instruction Clarity",
        "category": "communication",
        "rubric": (
            "Quality and precision of the user's intent expression. "
            "High scores = specific goals, success criteria, constraints, and context stated upfront. "
            "Low scores = vague or ambiguous requests requiring Claude to guess what's wanted."
        ),
    },
    {
        "key": "feedback_quality",
        "name": "Feedback Quality",
        "category": "communication",
        "rubric": (
            "When the user corrects Claude or gives feedback, does the correction contain enough "
            "information for Claude to act on it? High scores = pinpoints exact issue, explains what's "
            "wrong AND what's expected, gives examples. Low scores = 'that's wrong' or 'try again' "
            "without specifying what to change."
        ),
    },
    # Strategy (2 dims)
    {
        "key": "problem_framing",
        "name": "Problem Framing",
        "category": "strategy",
        "rubric": (
            "How well the user defines the problem space before requesting solutions. "
            "High scores = describes context, constraints, what was tried, why it matters. "
            "Low scores = jumps straight to 'fix this' or 'build that' without framing."
        ),
    },
    {
        "key": "scope_awareness",
        "name": "Scope Awareness",
        "category": "strategy",
        "rubric": (
            "Does the user anticipate side effects, edge cases, or cross-system impact? "
            "High scores = mentions what else might break, asks about implications, considers "
            "downstream effects. Low scores = purely local thinking with no system awareness."
        ),
    },
    # Technical (2 dims)
    {
        "key": "review_depth",
        "name": "Review Depth",
        "category": "technical",
        "rubric": (
            "Quality of reviewing Claude's output beyond just running it. "
            "High scores = reads code carefully, catches logic issues, asks probing questions, "
            "verifies edge cases. Low scores = blindly accepts or only checks if it runs."
        ),
    },
    {
        "key": "technical_judgment",
        "name": "Technical Judgment",
        "category": "technical",
        "rubric": (
            "Quality of the user's technical decisions and trade-off reasoning. "
            "High scores = makes informed choices about architecture, libraries, patterns with "
            "clear reasoning. Low scores = arbitrary decisions or deferring all choices to Claude."
        ),
    },
    # Autonomy (2 dims)
    {
        "key": "delegation_calibration",
        "name": "Delegation Calibration",
        "category": "autonomy",
        "rubric": (
            "Whether the user delegates at the right granularity — not too micro, not too macro. "
            "High scores = gives Claude appropriately-sized tasks with clear boundaries, knows when "
            "to specify vs. when to let Claude decide. Low scores = either micromanages every line "
            "or dumps massive undefined tasks."
        ),
    },
    {
        "key": "learning_progression",
        "name": "Learning Progression",
        "category": "autonomy",
        "rubric": (
            "Evidence that the user adapts their approach based on outcomes within or across turns. "
            "High scores = refines strategy after failures, builds on what worked, shows increasing "
            "sophistication. Low scores = repeats same patterns regardless of results."
        ),
    },
]


# ── Cache Management ───────────────────────────────────────────


def load_llm_cache() -> dict:
    """Load the permanent LLM score cache."""
    if not CACHE_PATH.exists():
        return {"version": SCHEMA_VERSION, "scores": {}}
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        if not isinstance(data.get("scores"), dict):
            return {"version": SCHEMA_VERSION, "scores": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": SCHEMA_VERSION, "scores": {}}


def save_llm_score(session_id: str, profile: LLMProfile):
    """Save a single session's LLM score to the permanent cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_llm_cache()
    cache["version"] = SCHEMA_VERSION
    cache["scores"][session_id] = {
        "scored_at": profile.scored_at,
        "model_used": profile.model_used,
        "schema_version": SCHEMA_VERSION,
        "data": profile.model_dump(),
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def get_cached_score(session_id: str) -> LLMProfile | None:
    """Return cached LLM profile for a session, or None.

    Only returns scores matching the current SCHEMA_VERSION.
    Old v1 scores are ignored (stale, not deleted).
    """
    cache = load_llm_cache()
    entry = cache.get("scores", {}).get(session_id)
    if entry and "data" in entry:
        if entry.get("schema_version", 1) < SCHEMA_VERSION:
            return None  # stale — needs re-scoring
        return LLMProfile(**entry["data"])
    return None


def get_all_cached_scores() -> dict[str, LLMProfile]:
    """Return all cached LLM profiles keyed by session_id.

    Only returns scores matching the current SCHEMA_VERSION.
    """
    cache = load_llm_cache()
    result = {}
    for sid, entry in cache.get("scores", {}).items():
        if "data" in entry and entry.get("schema_version", 1) >= SCHEMA_VERSION:
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
) -> tuple[LLMProfile, str | None]:
    """Score a single session using the claude CLI.

    Returns (LLMProfile, error_message). error_message is None on success.
    Never re-scores if cached. Call get_cached_score() first to check.
    """
    # Check cache first
    cached = get_cached_score(session_id)
    if cached is not None:
        return cached, None

    # Sample turns
    turns = sample_turns(session_id)
    if not turns:
        return LLMProfile(
            session_id=session_id,
            project=project,
            date=date,
            scored_at=datetime.now(UTC).isoformat(),
        ), "No turns to sample"

    # Build prompt and call claude CLI
    prompt = _build_prompt(turns)
    model = os.environ.get("CLAUDEALYTICS_LLM_MODEL", DEFAULT_MODEL)

    # Clean env so claude CLI doesn't think it's nested inside another session
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
                "You are a scoring assistant. Respond with ONLY valid JSON, no markdown fences.",
                "--max-budget-usd",
                "0.50",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            env=clean_env,
        )
    except FileNotFoundError:
        return (
            _fallback_profile(session_id, project, date, len(turns), total_messages, model),
            "claude CLI not found — ensure it is installed and on PATH",
        )
    except subprocess.TimeoutExpired:
        return (
            _fallback_profile(session_id, project, date, len(turns), total_messages, model),
            "claude CLI timed out after 120s",
        )

    if result.returncode != 0:
        error_msg = f"claude CLI error (exit {result.returncode}): {result.stderr[:200]}"
        logger.error("claude CLI error for session %s: %s", session_id[:12], error_msg)
        return (
            _fallback_profile(session_id, project, date, len(turns), total_messages, model),
            error_msg,
        )

    try:
        output = json.loads(result.stdout)
        # Check for CLI-level errors (budget exceeded, etc.)
        if output.get("is_error") or output.get("subtype", "").startswith("error"):
            error_msg = f"claude CLI: {output.get('subtype', 'unknown error')}"
            return (
                _fallback_profile(session_id, project, date, len(turns), total_messages, model),
                error_msg,
            )
        response = output.get("result", "")
    except (json.JSONDecodeError, AttributeError) as exc:
        error_msg = f"Failed to parse claude CLI output: {exc}"
        logger.error("JSON parse error for session %s: %s", session_id[:12], error_msg)
        return (
            _fallback_profile(session_id, project, date, len(turns), total_messages, model),
            error_msg,
        )

    elapsed = time.monotonic() - start_time
    logger.info("Scored session %s with %s in %.1fs", session_id[:12], model, elapsed)

    # Parse JSON response (handle markdown fences)
    parsed = _parse_llm_response(response)
    if not parsed:
        logger.warning("Failed to parse LLM JSON for session %s: %s", session_id[:12], response[:200])
        return (
            _fallback_profile(session_id, project, date, len(turns), total_messages, model),
            f"Failed to parse LLM JSON response (first 200 chars): {response[:200]}",
        )

    # Build LLMProfile from parsed response
    dimensions = []
    dim_lookup = {d["key"]: d for d in LLM_DIMENSIONS}

    for dim_data in parsed.get("dimensions", []):
        key = dim_data.get("key", "")
        if key not in dim_lookup:
            continue
        dim_def = dim_lookup[key]
        dimensions.append(
            LLMDimensionScore(
                key=key,
                name=dim_def["name"],
                category=dim_def["category"],
                score=max(1.0, min(10.0, float(dim_data.get("score", 5.0)))),
                reasoning=dim_data.get("reasoning", ""),
                evidence_quotes=dim_data.get("evidence_quotes", []),
                confidence=max(0.0, min(1.0, float(dim_data.get("confidence", 0.5)))),
            )
        )

    # Fill missing dimensions with defaults
    scored_keys = {d.key for d in dimensions}
    for dim_def in LLM_DIMENSIONS:
        if dim_def["key"] not in scored_keys:
            dimensions.append(
                LLMDimensionScore(
                    key=dim_def["key"],
                    name=dim_def["name"],
                    category=dim_def["category"],
                )
            )

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
    return profile, None


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


# ── Batch Scoring ─────────────────────────────────────────────


BATCH_SIZE = 15  # sessions per Claude call


def _build_batch_prompt(sessions: list[SessionInstructions]) -> str:
    """Build a prompt that scores multiple sessions in a single call."""
    dimensions_text = ""
    for d in LLM_DIMENSIONS:
        dimensions_text += f"\n- **{d['name']}** (`{d['key']}`, category: {d['category']}): {d['rubric']}"

    sessions_text = ""
    for s in sessions:
        sessions_text += f"\n\n--- SESSION: {s.session_id} ---\n"
        sessions_text += f"Project: {s.project} | Date: {s.date} | Messages: {s.message_count}\n\n"
        for i, instruction in enumerate(s.instructions[:20], 1):
            sessions_text += f"[{i}] {instruction}\n"

    return f"""You are scoring a human user's conversation proficiency with an AI coding assistant.
Below are human instructions extracted from {len(sessions)} different sessions.
Score the USER on each dimension based on ALL their messages in each session.

## Scoring Dimensions
{dimensions_text}

## Sessions
{sessions_text}

## Instructions

For EACH session, score every dimension from 1.0 to 10.0.
Provide brief reasoning and a confidence level (0.0-1.0).

Respond with ONLY valid JSON:
{{
  "sessions": [
    {{
      "session_id": "the-session-id",
      "dimensions": [
        {{
          "key": "dimension_key",
          "score": 7.5,
          "reasoning": "Brief explanation",
          "confidence": 0.8
        }}
      ]
    }}
  ]
}}"""


def _parse_batch_response(response: str) -> list[dict] | None:
    """Parse batch JSON response into list of session results."""
    parsed = _parse_llm_response(response)
    if not parsed:
        return None
    sessions = parsed.get("sessions", [])
    if not isinstance(sessions, list):
        return None
    return sessions


def _build_profile_from_scores(
    session: SessionInstructions,
    dim_scores: list[dict],
    model: str,
) -> LLMProfile:
    """Build an LLMProfile from parsed dimension scores."""
    dimensions = []
    dim_lookup = {d["key"]: d for d in LLM_DIMENSIONS}

    for dim_data in dim_scores:
        key = dim_data.get("key", "")
        if key not in dim_lookup:
            continue
        dim_def = dim_lookup[key]
        dimensions.append(
            LLMDimensionScore(
                key=key,
                name=dim_def["name"],
                category=dim_def["category"],
                score=max(1.0, min(10.0, float(dim_data.get("score", 5.0)))),
                reasoning=dim_data.get("reasoning", ""),
                evidence_quotes=dim_data.get("evidence_quotes", []),
                confidence=max(0.0, min(1.0, float(dim_data.get("confidence", 0.5)))),
            )
        )

    # Fill missing dimensions
    scored_keys = {d.key for d in dimensions}
    for dim_def in LLM_DIMENSIONS:
        if dim_def["key"] not in scored_keys:
            dimensions.append(
                LLMDimensionScore(
                    key=dim_def["key"],
                    name=dim_def["name"],
                    category=dim_def["category"],
                )
            )

    # Compute scores
    category_scores: dict[str, list[float]] = {}
    for d in dimensions:
        category_scores.setdefault(d.category, []).append(d.score)
    cat_avgs = {cat: round(sum(s) / len(s), 1) for cat, s in category_scores.items()}
    overall = round(sum(d.score for d in dimensions) / len(dimensions), 1) if dimensions else 5.0

    return LLMProfile(
        session_id=session.session_id,
        project=session.project,
        date=session.date,
        dimensions=dimensions,
        overall_score=overall,
        category_scores=cat_avgs,
        model_used=model,
        messages_sampled=session.message_count,
        total_messages=session.message_count,
        scored_at=datetime.now(UTC).isoformat(),
    )


def score_batch(
    sessions: list[SessionInstructions],
    model: str = "sonnet",
) -> tuple[list[LLMProfile], list[str]]:
    """Score multiple sessions in a single Claude CLI call.

    Args:
        sessions: List of SessionInstructions to score.
        model: Claude model to use.

    Returns:
        (profiles, errors) — profiles for successfully scored sessions,
        error messages for failures.
    """
    if not sessions:
        return [], []

    # Skip already-cached sessions
    uncached = []
    cached_profiles = []
    for s in sessions:
        cached = get_cached_score(s.session_id)
        if cached is not None:
            cached_profiles.append(cached)
        else:
            uncached.append(s)

    if not uncached:
        return cached_profiles, []

    prompt = _build_batch_prompt(uncached)
    model = os.environ.get("CLAUDEALYTICS_LLM_MODEL", model)

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
                "You are a scoring assistant. Respond with ONLY valid JSON, no markdown fences.",
                "--max-budget-usd",
                "1.00",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            env=clean_env,
        )
    except FileNotFoundError:
        return cached_profiles, ["claude CLI not found"]
    except subprocess.TimeoutExpired:
        return cached_profiles, ["claude CLI timed out after 300s"]

    if result.returncode != 0:
        return cached_profiles, [f"claude CLI error (exit {result.returncode}): {result.stderr[:200]}"]

    elapsed = time.monotonic() - start_time
    logger.info("Batch scored %d sessions with %s in %.1fs", len(uncached), model, elapsed)

    try:
        output = json.loads(result.stdout)
        if output.get("is_error") or output.get("subtype", "").startswith("error"):
            return cached_profiles, [f"claude CLI: {output.get('subtype', 'unknown error')}"]
        response = output.get("result", "")
    except (json.JSONDecodeError, AttributeError) as exc:
        return cached_profiles, [f"Failed to parse CLI output: {exc}"]

    # Parse batch response
    session_results = _parse_batch_response(response)
    if not session_results:
        return cached_profiles, [f"Failed to parse batch response: {response[:200]}"]

    # Map results by session_id
    results_by_id = {r.get("session_id", ""): r for r in session_results}

    profiles = list(cached_profiles)
    errors = []
    retry_sessions = []

    for s in uncached:
        result_data = results_by_id.get(s.session_id)
        if result_data and result_data.get("dimensions"):
            profile = _build_profile_from_scores(s, result_data["dimensions"], model)
            save_llm_score(s.session_id, profile)
            profiles.append(profile)
        else:
            retry_sessions.append(s)

    # Retry individually for sessions the batch missed
    for s in retry_sessions:
        logger.info("Retrying individual scoring for session %s", s.session_id[:12])
        profile, error = score_session(
            session_id=s.session_id,
            project=s.project,
            date=s.date,
            total_messages=s.message_count,
        )
        if error:
            errors.append(f"{s.session_id[:12]}: {error}")
        else:
            profiles.append(profile)

    return profiles, errors
