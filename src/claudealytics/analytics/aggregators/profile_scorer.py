"""16-dimension conversation profile scorer.

Computes heuristic scores for each dimension from content_miner data.
All scoring uses signals already available — no LLM calls.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd

from claudealytics.models.schemas import ConversationProfile, DimensionScore, SubScore

# ── Disk Cache ─────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
PROFILE_CACHE_PATH = CACHE_DIR / "profile-scores.json"
CONTENT_MINE_PATH = CACHE_DIR / "content-mine.json"
CACHE_TTL_SECONDS = 3600  # 1 hour


def _get_content_mine_timestamp() -> float:
    """Return the timestamp stored inside content-mine.json, or 0."""
    try:
        with open(CONTENT_MINE_PATH) as f:
            return json.load(f).get("timestamp", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def _load_profile_cache() -> list[ConversationProfile] | None:
    if not PROFILE_CACHE_PATH.exists():
        return None
    try:
        with open(PROFILE_CACHE_PATH) as f:
            cached = json.load(f)
        # Invalidate if older than TTL
        if cached.get("timestamp", 0) < datetime.now().timestamp() - CACHE_TTL_SECONDS:
            return None
        # Invalidate if content-mine has been refreshed since cache was written
        if cached.get("content_mine_timestamp", 0) != _get_content_mine_timestamp():
            return None
        return [ConversationProfile(**d) for d in cached.get("data", [])]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _save_profile_cache(profiles: list[ConversationProfile]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "timestamp": datetime.now().timestamp(),
        "content_mine_timestamp": _get_content_mine_timestamp(),
        "data": [p.model_dump() for p in profiles],
    }
    with open(PROFILE_CACHE_PATH, "w") as f:
        json.dump(cache_data, f)


# ── Helpers ─────────────────────────────────────────────────────


def _clamp(value: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def _dampen(raw_score: float, human_msg_count: int, threshold: int = 2) -> float:
    """Pull short sessions toward neutral 5.0.

    Uses a log-curve: confidence = log2(n+1) / log2(threshold+2).
    For threshold=2, a 1-message session gets confidence=log2(2)/log2(4)=0.5,
    preserving 50% of variance. Full confidence is reached at threshold messages.
    """
    if human_msg_count == 0:
        return 5.0
    import math

    confidence = min(math.log2(human_msg_count + 1) / math.log2(threshold + 2), 1.0)
    return 5.0 + (raw_score - 5.0) * confidence


SCORE_EXPONENT = 0.7


def _raw_to_score(contribution_sum: float) -> float:
    """Convert sub-score contribution sum to a 1-10 raw score.

    Applies x^0.7 power-curve stretching before scaling. Using 0.7 (vs 0.6)
    gives more credit to mid-range sessions and reduces score compression in
    the typical contribution range (0.25-0.50).
    """
    stretched = max(contribution_sum, 0.0) ** SCORE_EXPONENT
    return stretched * 9 + 1


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator > 0 else default


def _sub(name: str, raw: float, normalized: float, weight: float, threshold: str = "") -> SubScore:
    return SubScore(
        name=name,
        raw_value=round(raw, 4),
        normalized=round(min(max(normalized, 0.0), 1.0), 4),
        weight=weight,
        contribution=round(min(max(normalized, 0.0), 1.0) * weight, 4),
        threshold=threshold,
    )


# ── Dimension Scorers ───────────────────────────────────────────

# COMMUNICATION


def score_context_precision(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    path_pct = _safe_ratio(s.get("human_with_file_paths_count", 0), human_count)
    guidance_pct = _safe_ratio(s.get("intervention_guidance", 0), human_count)

    avg_len = _safe_ratio(s.get("total_text_length_human", 0), human_count)
    length_score = 1.0 - min(abs(avg_len - 300) / 600, 1.0)

    subs = [
        _sub("File path ratio", path_pct, path_pct, 0.40, "1.0 = every message has file paths"),
        _sub("Guidance ratio", guidance_pct, guidance_pct, 0.30, "1.0 = every message is guidance"),
        _sub("Message length fit", avg_len, length_score, 0.30, "Sweet spot ~300 chars"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if path_pct < 0.3:
        hint = f"Only {path_pct:.0%} of messages had file paths — adding paths helps Claude find context faster."
    elif guidance_pct < 0.2:
        hint = "Including more guidance in messages helps Claude understand intent and constraints."

    return DimensionScore(
        key="context_precision",
        name="Context Precision",
        category="communication",
        score=round(score, 1),
        explanation=f"{path_pct:.0%} with file paths, {guidance_pct:.0%} guidance, avg {avg_len:.0f} chars",
        sub_scores=subs,
        guide="How precisely do you set context? Goes up with file paths, guidance messages, and focused messages (~300 chars). Goes down with vague or overly long messages.",
        improvement_hint=hint,
    )


def score_semantic_density(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    total_text = s.get("total_text_length_human", 0) or 1
    human_words = int(hm["word_count"].sum()) if (not hm.empty and "word_count" in hm.columns) else total_text / 5
    tool_calls = s.get("total_tool_calls", 0)
    approval_ratio = _safe_ratio(s.get("intervention_approval", 0), human_count)

    efficiency = _safe_ratio(tool_calls, human_words)
    eff_score = min(efficiency / 0.15, 1.0)
    penalty = approval_ratio * 0.5

    subs = [
        _sub("Actions per word", efficiency, eff_score, 0.70, "0.15 actions/word = excellent"),
        _sub("Approval penalty", approval_ratio, 1.0 - penalty, 0.30, "High approval = rubber-stamping"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if approval_ratio > 0.5:
        hint = f"{approval_ratio:.0%} of messages are approvals — try giving more specific instructions instead."
    elif eff_score < 0.3:
        hint = "Messages trigger few actions — try being more concise and action-oriented."

    return DimensionScore(
        key="semantic_density",
        name="Semantic Density",
        category="communication",
        score=round(score, 1),
        explanation=f"{efficiency:.2f} tool actions per word, {approval_ratio:.0%} approval messages",
        sub_scores=subs,
        guide="How much work does each message trigger? Goes up when concise messages drive many tool actions. Goes down with rubber-stamp approvals.",
        improvement_hint=hint,
    )


def score_iterative_refinement(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    total_msgs = s.get("total_messages", 0) or 1
    correction_count = s.get("intervention_correction", 0)
    correction_rate = _safe_ratio(correction_count, human_count)

    front_loaded = 0.5
    if not hm.empty and "classification" in hm.columns:
        classifications = hm["classification"].tolist()
        mid = len(classifications) // 2
        if mid > 0:
            first_half_corrections = sum(1 for c in classifications[:mid] if c == "correction")
            second_half_corrections = sum(1 for c in classifications[mid:] if c == "correction")
            total_corrections = first_half_corrections + second_half_corrections
            if total_corrections > 0:
                front_loaded = first_half_corrections / total_corrections

    rate_score = 1.0 - min(correction_rate / 0.4, 1.0)
    front_score = front_loaded
    length_bonus = min(total_msgs / 10, 1.0) * 0.1

    subs = [
        _sub("Correction rate", correction_rate, rate_score, 0.60, "Lower is better; >40% is poor"),
        _sub("Front-loaded corrections", front_loaded, front_score, 0.30, "1.0 = all corrections early"),
        _sub("Session length bonus", total_msgs, length_bonus / 0.1, 0.10, "Longer sessions show learning"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if correction_rate > 0.3:
        hint = f"{correction_rate:.0%} correction rate — try providing clearer initial instructions to reduce back-and-forth."
    elif front_loaded < 0.4 and correction_count > 2:
        hint = "Corrections are spread throughout — front-load clarifications early in the conversation."

    return DimensionScore(
        key="iterative_refinement",
        name="Iterative Refinement",
        category="communication",
        score=round(score, 1),
        explanation=f"{correction_rate:.0%} correction rate, corrections {front_loaded:.0%} front-loaded",
        sub_scores=subs,
        guide="How quickly do conversations converge? Goes up when corrections happen early and decrease over time. Goes down with persistent late-stage fixes.",
        improvement_hint=hint,
    )


def score_conversation_balance(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    """Communication: Conversation Balance (NEW) — healthy back-and-forth."""
    human_count = s.get("human_msg_count", 0) or 1
    assistant_count = s.get("assistant_msg_count", 0) or 1
    human_text = s.get("total_text_length_human", 0) or 1
    assistant_text = s.get("total_text_length_assistant", 0) or 1
    total_msgs = s.get("total_messages", 0) or 1
    question_count = s.get("human_questions_count", 0)

    # Message ratio balance: ideal is ~1:3 human:assistant
    msg_ratio = _safe_ratio(human_count, assistant_count)
    msg_balance = 1.0 - min(abs(msg_ratio - 0.33) / 0.5, 1.0)

    # Text length balance: human should be ~10-30% of total text
    text_ratio = _safe_ratio(human_text, human_text + assistant_text)
    text_balance = 1.0 - min(abs(text_ratio - 0.2) / 0.3, 1.0)

    # Messages per session density
    density = min(total_msgs / 10, 1.0)

    # Question frequency — diminishing returns above 20%
    question_freq = _safe_ratio(question_count, human_count)
    if question_freq <= 0.2:
        q_score = question_freq / 0.2 * 0.8
    else:
        q_score = 0.8 + min((question_freq - 0.2) / 0.8, 1.0) * 0.2

    subs = [
        _sub("Message ratio balance", msg_ratio, msg_balance, 0.30, "Ideal ~1:3 human:assistant"),
        _sub("Text length balance", text_ratio, text_balance, 0.30, "Human text ~20% of total"),
        _sub("Session density", total_msgs, density, 0.20, "20+ messages = dense session"),
        _sub("Question frequency", question_freq, q_score, 0.20, "Questions drive exploration"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if msg_ratio > 0.8:
        hint = "Conversation is very back-and-forth — try giving Claude more autonomy with longer instructions."
    elif msg_ratio < 0.1:
        hint = "Very few human messages — consider checking in more to guide the work."

    return DimensionScore(
        key="conversation_balance",
        name="Conversation Balance",
        category="communication",
        score=round(score, 1),
        explanation=f"Message ratio {msg_ratio:.2f}, text ratio {text_ratio:.0%}, {question_count} questions",
        sub_scores=subs,
        guide="How balanced is the conversation? Goes up with regular check-ins and questions (~30% of messages). Goes down when one side dominates.",
        improvement_hint=hint,
    )


# STRATEGY


def score_task_decomposition(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1

    agent_skill_count = 0
    if not tc.empty and "tool_name" in tc.columns:
        agent_skill_count = int(tc["tool_name"].isin(["Task", "Skill"]).sum())

    guidance_ratio = _safe_ratio(s.get("intervention_guidance", 0), human_count)
    new_instr_ratio = _safe_ratio(s.get("intervention_new_instruction", 0), human_count)
    structured_ratio = guidance_ratio + new_instr_ratio

    files_touched = s.get("unique_files_touched", 0)
    cwd_switches = s.get("cwd_switch_count", 0)

    agent_score = min(agent_skill_count / 5, 1.0)
    struct_score = min(structured_ratio / 0.5, 1.0)
    file_score = min(files_touched / 8, 1.0)
    cwd_score = min(cwd_switches / 3, 1.0)

    subs = [
        _sub("Agent/skill usage", agent_skill_count, agent_score, 0.30, "5+ agent/skill calls = excellent"),
        _sub("Structured instructions", structured_ratio, struct_score, 0.30, "Guidance + new instruction ratio"),
        _sub("File breadth", files_touched, file_score, 0.25, "8+ files = wide scope"),
        _sub("CWD switches", cwd_switches, cwd_score, 0.15, "Cross-directory work"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if agent_skill_count == 0:
        hint = "No agent/skill usage detected — try using Task or Skill tools for complex sub-tasks."
    elif files_touched < 5:
        hint = f"Only {files_touched} files touched — broader file scope shows better task decomposition."

    return DimensionScore(
        key="task_decomposition",
        name="Task Decomposition",
        category="strategy",
        score=round(score, 1),
        explanation=f"{agent_skill_count} agent/skill uses, {files_touched} files, {cwd_switches} cwd switches",
        sub_scores=subs,
        guide="Do you break work into sub-tasks? Goes up with agent/skill delegation and structured instructions. Goes down with monolithic requests.",
        improvement_hint=hint,
    )


def score_validation_rigor(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1

    test_count = 0
    post_edit_verify = 0
    if not tc.empty and "tool_name" in tc.columns:
        if "is_test_command" in tc.columns:
            test_count = int(tc["is_test_command"].sum())
        # Post-edit verification: count Edit tool calls followed by Bash/test within 2 rows
        tool_names = tc["tool_name"].tolist()
        for i, name in enumerate(tool_names):
            if name == "Edit":
                for j in range(i + 1, min(i + 3, len(tool_names))):
                    if tool_names[j] in ("Bash", "Task"):
                        post_edit_verify += 1
                        break

    correction_bonus = min(s.get("intervention_correction", 0) / 5, 1.0)

    # Per-message rate normalization for test_score
    test_score = min(test_count / human_count / 0.2, 1.0)
    post_verify_score = min(post_edit_verify / max(test_count + 1, 3), 1.0)

    subs = [
        _sub("Test commands", test_count, test_score, 0.40, "0.2 test runs/msg = thorough"),
        _sub("Post-edit verification", post_edit_verify, post_verify_score, 0.30, "Bash/test after Edit = verified"),
        _sub("Bug-catching corrections", correction_bonus, correction_bonus, 0.30, "Corrections that catch bugs"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if test_count == 0:
        hint = "No test commands detected — running tests validates changes and prevents regressions."
    elif post_edit_verify == 0:
        hint = "No post-edit verification detected — running checks after edits catches issues early."

    return DimensionScore(
        key="validation_rigor",
        name="Validation Rigor",
        category="strategy",
        score=round(score, 1),
        explanation=f"{test_count} test runs, {post_edit_verify} post-edit verifications",
        sub_scores=subs,
        guide="How thoroughly do you verify results? Goes up with test runs and verification after edits. Goes down when output is accepted without review.",
        improvement_hint=hint,
    )


def score_error_resilience(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    total_msgs = s.get("total_messages", 0) or 1
    total_errors = s.get("total_errors", 0)
    avg_autonomy = s.get("avg_autonomy_run_length", 0)

    error_density = _safe_ratio(total_errors, total_msgs)

    max_consecutive = 0
    if not hm.empty and "classification" in hm.columns:
        current_streak = 0
        for c in hm["classification"].tolist():
            if c == "correction":
                current_streak += 1
                max_consecutive = max(max_consecutive, current_streak)
            else:
                current_streak = 0

    density_score = 1.0 - min(error_density / 0.15, 1.0)
    loop_score = 1.0 - min(max_consecutive / 5, 1.0)
    autonomy_score = min(avg_autonomy / 5, 1.0) if total_errors > 0 else 0.7

    subs = [
        _sub("Error density", error_density, density_score, 0.40, "Lower is better; >15% is poor"),
        _sub("No frustration loops", max_consecutive, loop_score, 0.35, "Max consecutive corrections <5"),
        _sub("Autonomy despite errors", avg_autonomy, autonomy_score, 0.25, "Maintained autonomy after errors"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if max_consecutive >= 3:
        hint = f"{max_consecutive} consecutive corrections detected — try a different approach when stuck instead of repeating."
    elif error_density > 0.1:
        hint = f"Error rate of {error_density:.0%} — more upfront context can prevent errors."

    return DimensionScore(
        key="error_resilience",
        name="Error Resilience",
        category="strategy",
        score=round(score, 1),
        explanation=f"{total_errors} errors across {total_msgs} messages, max {max_consecutive} consecutive corrections",
        sub_scores=subs,
        guide="How well do conversations handle errors? Goes up when errors are rare and recovery is quick. Goes down with repeated correction loops.",
        improvement_hint=hint,
    )


def score_planning_depth(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    """Strategy: Planning Depth (NEW) — plan vs execute dimension."""
    human_count = s.get("human_msg_count", 0) or 1
    total_tool_calls = s.get("total_tool_calls", 0) or 1
    thinking_length = s.get("total_thinking_length", 0)
    thinking_count = s.get("thinking_message_count", 0)
    total_output = s.get("total_text_length_assistant", 0) or 1

    # Research tools: Read, Grep, Glob, WebSearch, WebFetch
    research_count = 0
    thinking_before_first_tool = 0
    if not tc.empty and "tool_name" in tc.columns:
        research_tools = {"Read", "Grep", "Glob", "WebSearch", "WebFetch"}
        research_count = int(tc["tool_name"].isin(research_tools).sum())
        # Thinking-to-action ratio: thinking blocks before first non-research tool call
        tool_names = tc["tool_name"].tolist()
        for i, name in enumerate(tool_names):
            if name not in research_tools:
                thinking_before_first_tool = i
                break
        else:
            thinking_before_first_tool = len(tool_names)

    # Thinking ratio: thinking length relative to output
    thinking_ratio = _safe_ratio(thinking_length, total_output)
    thinking_score = min(thinking_ratio / 0.3, 1.0)

    # Research-before-action ratio
    research_ratio = _safe_ratio(research_count, total_tool_calls)
    research_score = min(research_ratio / 0.4, 1.0)

    # Thinking-to-action ratio: research calls before first action
    thinking_to_action = _safe_ratio(thinking_before_first_tool, total_tool_calls)
    thinking_action_score = min(thinking_to_action / 0.3, 1.0)

    subs = [
        _sub("Thinking ratio", thinking_ratio, thinking_score, 0.40, "Thinking length vs output length"),
        _sub("Research-before-action", research_ratio, research_score, 0.40, "Read/Grep/Glob/Web ratio of all tools"),
        _sub("Thinking-to-action ratio", thinking_to_action, thinking_action_score, 0.20, "Research calls before first action"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if research_ratio < 0.2:
        hint = f"Only {research_ratio:.0%} of tool calls are research (Read/Grep/Glob/Web) — more exploration before action reduces errors."
    elif thinking_score < 0.3 and thinking_count == 0:
        hint = "No extended thinking detected — complex tasks benefit from deliberate planning phases."

    return DimensionScore(
        key="planning_depth",
        name="Planning Depth",
        category="strategy",
        score=round(score, 1),
        explanation=f"Thinking ratio {thinking_ratio:.2f}, research {research_ratio:.0%}, thinking-to-action {thinking_to_action:.0%}",
        sub_scores=subs,
        guide="How much planning happens before action? Goes up with research-first approaches (Read/Grep/Glob/Web). Goes down when jumping straight to edits.",
        improvement_hint=hint,
    )


# TECHNICAL


def score_code_literacy(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    code_pct = _safe_ratio(s.get("human_with_code_count", 0), human_count)
    correction_count = s.get("intervention_correction", 0)
    code_count = s.get("human_with_code_count", 0)

    code_correction_overlap = min(_safe_ratio(min(correction_count, code_count), human_count) / 0.2, 1.0)

    avg_len = _safe_ratio(s.get("total_text_length_human", 0), human_count)
    detail_level = min(avg_len / 500, 1.0)

    # Code detail density: code_pct weighted by message detail
    code_detail = code_pct * detail_level

    subs = [
        _sub("Code in messages", code_pct, code_pct, 0.40, "1.0 = every message has code"),
        _sub("Code detail density", code_detail, min(code_detail / 0.5, 1.0), 0.25, "code_pct × detail_level"),
        _sub(
            "Code+correction overlap",
            code_correction_overlap,
            code_correction_overlap,
            0.20,
            "Corrections with code context",
        ),
        _sub("Detail level", avg_len, detail_level, 0.15, "Avg message length / 500"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if code_pct < 0.1:
        hint = "Very few messages include code — sharing code snippets helps Claude understand exact context."
    elif detail_level < 0.3:
        hint = "Messages are short — more detailed code messages improve collaboration quality."

    return DimensionScore(
        key="code_literacy",
        name="Code Literacy",
        category="technical",
        score=round(score, 1),
        explanation=f"{code_pct:.0%} messages with code, code detail density {code_detail:.2f}",
        sub_scores=subs,
        guide="How code-aware are your messages? Goes up with code snippets and detailed technical messages. Goes down with non-technical or generic requests.",
        improvement_hint=hint,
    )


def score_architectural_stewardship(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    guidance_ratio = _safe_ratio(s.get("intervention_guidance", 0), human_count)
    total_edits = s.get("total_edits", 0) or 1
    correction_rate = _safe_ratio(s.get("intervention_correction", 0), human_count)

    structured_edits = 0
    if not tc.empty and "edit_category" in tc.columns:
        structured_cats = {"refactor", "type_annotation", "error_handling"}
        structured_edits = int(tc["edit_category"].isin(structured_cats).sum())
    structured_pct = _safe_ratio(structured_edits, total_edits)

    guidance_score = min(guidance_ratio / 0.3, 1.0)
    struct_score = min(structured_pct / 0.3, 1.0)
    correction_penalty = 1.0 - min(correction_rate / 0.3, 1.0)

    subs = [
        _sub("Guidance ratio", guidance_ratio, guidance_score, 0.35, "Architectural guidance frequency"),
        _sub("Structured edits", structured_pct, struct_score, 0.35, "Refactor/type/error handling edits"),
        _sub("Low correction rate", correction_rate, correction_penalty, 0.30, "Low corrections = clean architecture"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if guidance_ratio < 0.1:
        hint = "Low guidance ratio — providing architectural direction helps maintain code quality."
    elif structured_pct < 0.1:
        hint = "Few structured edits (refactoring, types, error handling) — these improve codebase health."

    return DimensionScore(
        key="architectural_stewardship",
        name="Architectural Stewardship",
        category="technical",
        score=round(score, 1),
        explanation=f"{guidance_ratio:.0%} guidance, {structured_pct:.0%} structured edits, {correction_rate:.0%} correction rate",
        sub_scores=subs,
        guide="Do you guide system-wide design? Goes up with architectural guidance and structured edits. Goes down with narrow tactical fixes or high correction rates.",
        improvement_hint=hint,
    )


def score_debugging_collaboration(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    total_tool_calls = s.get("total_tool_calls", 0) or 1
    rbw_total = s.get("writes_total_count", 0) or 1
    rbw_pct = _safe_ratio(s.get("writes_with_prior_read_count", 0), rbw_total)
    total_reads = s.get("total_reads", 0)
    read_ratio = _safe_ratio(total_reads, total_tool_calls)

    grep_count = 0
    if not tc.empty and "tool_name" in tc.columns:
        grep_count = int((tc["tool_name"] == "Grep").sum())

    path_pct = _safe_ratio(s.get("human_with_file_paths_count", 0), human_count)
    question_pct = _safe_ratio(s.get("human_questions_count", 0), human_count)
    diagnostic_score = (path_pct + question_pct) / 2

    rbw_score = rbw_pct
    read_score = min(read_ratio / 0.3, 1.0)
    grep_score = min(grep_count / human_count / 0.3, 1.0)

    subs = [
        _sub("Read-before-write", rbw_pct, rbw_score, 0.30, "1.0 = always reads before writing"),
        _sub("Read ratio", read_ratio, read_score, 0.25, "30% reads = thorough investigation"),
        _sub("Grep searches", grep_count, grep_score, 0.25, "5+ grep searches = deep exploration"),
        _sub("Diagnostic messages", diagnostic_score, diagnostic_score, 0.20, "Paths + questions in messages"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if rbw_pct < 0.5:
        hint = f"Read-before-write is {rbw_pct:.0%} — reading context before editing prevents mistakes."
    elif grep_count < 3:
        hint = "Few grep searches — searching for patterns helps locate related code."

    return DimensionScore(
        key="debugging_collaboration",
        name="Debugging Collaboration",
        category="technical",
        score=round(score, 1),
        explanation=f"{rbw_pct:.0%} read-before-write, {read_ratio:.0%} read ratio, {grep_count} grep searches",
        sub_scores=subs,
        guide="How effectively do you debug with Claude? Goes up with read-before-write discipline and systematic investigation. Goes down with write-only approaches.",
        improvement_hint=hint,
    )


def score_token_efficiency(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    """Technical: Token Efficiency (NEW) — how efficiently tokens are used."""
    human_count = s.get("human_msg_count", 0) or 1
    input_tokens = s.get("total_input_tokens", 0)
    output_tokens = s.get("total_output_tokens", 0)
    thinking_length = s.get("total_thinking_length", 0)
    total_tool_calls = s.get("total_tool_calls", 0)
    total_errors = s.get("total_errors", 0)

    # Guard: return neutral if no token data
    if input_tokens == 0 and output_tokens == 0:
        return DimensionScore(
            key="token_efficiency",
            name="Token Efficiency",
            category="technical",
            score=5.0,
            explanation="No token data available",
            guide="How efficiently does the session use tokens? Goes up with balanced output/input ratio and good tool density. Goes down with verbose or error-heavy sessions.",
            improvement_hint="",
        )

    # Output-per-input ratio (higher = more efficient)
    oi_ratio = _safe_ratio(output_tokens, input_tokens)
    oi_score = min(oi_ratio / 0.3, 1.0)

    # Thinking-to-output ratio (some thinking is good, too much is wasteful)
    to_ratio = _safe_ratio(thinking_length, output_tokens) if output_tokens > 0 else 0
    # Sweet spot: 0.1-0.4 thinking ratio
    if to_ratio < 0.1:
        to_score = to_ratio / 0.1
    elif to_ratio <= 0.4:
        to_score = 1.0
    else:
        to_score = max(1.0 - (to_ratio - 0.4) / 0.6, 0.0)

    # Tool calls per output token (more tools per token = efficient)
    # Guard: cap tool_density for small sessions (<1K output tokens) to prevent inflation
    tool_density = _safe_ratio(total_tool_calls, max(output_tokens, 1000) / 1000) if output_tokens > 0 else 0
    tool_score = min(tool_density / 5, 1.0)

    # Error rate per token (lower = better)
    error_rate = _safe_ratio(total_errors, total_tool_calls) if total_tool_calls > 0 else 0
    error_score = 1.0 - min(error_rate / 0.2, 1.0)

    subs = [
        _sub("Output/input ratio", oi_ratio, oi_score, 0.35, "Higher = more output per input token"),
        _sub("Thinking efficiency", to_ratio, to_score, 0.30, "Sweet spot 10-40% thinking"),
        _sub("Tool density", tool_density, tool_score, 0.20, "Tool calls per 1K output tokens"),
        _sub("Error rate", error_rate, error_score, 0.15, "Lower error rate = better"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if oi_score < 0.3:
        hint = "Low output-per-input ratio — large context windows with little output suggest inefficient token use."
    elif error_rate > 0.15:
        hint = (
            f"Error rate of {error_rate:.0%} per tool call — more precise instructions reduce wasted tokens on retries."
        )

    return DimensionScore(
        key="token_efficiency",
        name="Token Efficiency",
        category="technical",
        score=round(score, 1),
        explanation=f"Output/input {oi_ratio:.2f}, thinking {to_ratio:.0%}, {total_tool_calls} tools, error rate {error_rate:.0%}",
        sub_scores=subs,
        guide="How efficiently tokens translate to useful output. Output-per-input ratio, thinking efficiency, tool density, and error rate.",
        improvement_hint=hint,
    )


# AUTONOMY


def score_strategic_delegation(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    avg_autonomy = s.get("avg_autonomy_run_length", 0)
    approval_ratio = _safe_ratio(s.get("intervention_approval", 0), human_count)
    avg_input_len = _safe_ratio(s.get("total_text_length_human", 0), human_count)

    if avg_autonomy <= 0:
        autonomy_score = 0.1
    elif avg_autonomy <= 3:
        # Smooth ramp: 0.1 at 0, reaches 1.0 at 3
        autonomy_score = 0.1 + (avg_autonomy / 3) * 0.9
    elif avg_autonomy <= 8:
        autonomy_score = 1.0
    elif avg_autonomy <= 15:
        autonomy_score = 1.0 - (avg_autonomy - 8) / 7 * 0.3
    else:
        autonomy_score = 0.5

    engagement_score = 1.0 - min(approval_ratio / 0.7, 1.0)
    input_score = min(avg_input_len / 200, 1.0)

    subs = [
        _sub("Autonomy run length", avg_autonomy, autonomy_score, 0.45, "Optimal 3-8 turns between inputs"),
        _sub("Engagement (not rubber-stamping)", approval_ratio, engagement_score, 0.30, "Low approval = engaged"),
        _sub("Meaningful input length", avg_input_len, input_score, 0.25, "200+ chars = substantive input"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if approval_ratio > 0.5:
        hint = f"{approval_ratio:.0%} of messages are approvals — try giving detailed instructions instead of 'ok'."
    elif avg_autonomy < 2:
        hint = f"Avg {avg_autonomy:.1f} turns between inputs — trust Claude with longer autonomy runs."

    return DimensionScore(
        key="strategic_delegation",
        name="Strategic Delegation",
        category="autonomy",
        score=round(score, 1),
        explanation=f"avg {avg_autonomy:.1f} turns between inputs, {approval_ratio:.0%} approval rate",
        sub_scores=subs,
        guide="Do you give Claude the right amount of autonomy? Goes up with 3-8 turn autonomous runs and meaningful input. Goes down with micromanaging or rubber-stamping.",
        improvement_hint=hint,
    )


def score_tool_orchestration(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    unique_tools = s.get("unique_tools", []) or []
    if isinstance(unique_tools, str):
        unique_tools = [t.strip() for t in unique_tools.split(",") if t.strip()]
    tool_diversity = len(unique_tools) if isinstance(unique_tools, list) else 0

    total_tool_calls = s.get("total_tool_calls", 0)
    sidechain_count = s.get("sidechain_count", 0)

    agent_count = 0
    skill_count = 0
    system_investment_count = 0
    if not tc.empty and "tool_name" in tc.columns:
        agent_count = int((tc["tool_name"] == "Task").sum())
        skill_count = int((tc["tool_name"] == "Skill").sum())
        # System investment: tool_calls touching ~/.claude/ paths
        if "file_path" in tc.columns:
            system_investment_count = int(tc["file_path"].fillna("").str.contains(r"\.claude/", regex=True).sum())

    diversity_score = min(tool_diversity / 5, 1.0)
    agent_skill_score = min((agent_count + skill_count) / 5, 1.0)
    system_score = min(system_investment_count / 5, 1.0)
    sidechain_score = min(sidechain_count / 5, 1.0)
    volume_score = min(total_tool_calls / 25, 1.0)

    subs = [
        _sub("Tool diversity", tool_diversity, diversity_score, 0.25, "5+ unique tools = excellent"),
        _sub("Agent/skill usage", agent_count + skill_count, agent_skill_score, 0.25, "5+ agent/skill calls"),
        _sub("System investment", system_investment_count, system_score, 0.20, "Touches to ~/.claude/ configs"),
        _sub("Sidechains", sidechain_count, sidechain_score, 0.15, "5+ sidechains = orchestrated"),
        _sub("Tool volume", total_tool_calls, volume_score, 0.15, "25+ tool calls = productive"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if tool_diversity < 4:
        hint = f"Only {tool_diversity} unique tools — try using more tool types for richer workflows."
    elif agent_skill_score < 0.3:
        hint = "Few agent/skill calls — delegating to agents improves orchestration."

    return DimensionScore(
        key="tool_orchestration",
        name="Tool Orchestration",
        category="autonomy",
        score=round(score, 1),
        explanation=f"{tool_diversity} unique tools, agents: {agent_count}, skills: {skill_count}, system: {system_investment_count}, {sidechain_count} sidechains",
        sub_scores=subs,
        guide="How diverse and effective is tool usage? Goes up with 8+ tool types, agent delegation, and high tool volume. Goes down with repetitive single-tool patterns.",
        improvement_hint=hint,
    )


def score_trust_calibration(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    human_count = s.get("human_msg_count", 0) or 1
    total_tool_calls = s.get("total_tool_calls", 0)
    correction_count = s.get("intervention_correction", 0)
    avg_autonomy = s.get("avg_autonomy_run_length", 0)

    complexity = min(total_tool_calls / 50, 1.0)

    correction_rate = _safe_ratio(correction_count, human_count)
    expected_correction = complexity * 0.15
    correction_diff = max(correction_rate - expected_correction, 0)
    correction_score = 1.0 - min(correction_diff / 0.2, 1.0)

    test_count = 0
    if not tc.empty and "is_test_command" in tc.columns:
        test_count = int(tc["is_test_command"].sum())
    test_score = min(test_count / 3, 1.0) if complexity > 0.3 else 0.5

    if complexity > 0.5:
        autonomy_match = min(avg_autonomy / 5, 1.0)
    else:
        autonomy_match = 1.0 - min(abs(avg_autonomy - 3) / 5, 1.0)

    subs = [
        _sub("Correction calibration", correction_diff, correction_score, 0.45, "Correction rate matches complexity"),
        _sub("Test validation", test_count, test_score, 0.30, "Tests for complex sessions"),
        _sub("Autonomy matching", avg_autonomy, autonomy_match, 0.25, "Autonomy appropriate to complexity"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if correction_rate > expected_correction + 0.15:
        hint = f"Correction rate ({correction_rate:.0%}) is high for session complexity — try clearer upfront instructions."
    elif test_count == 0 and complexity > 0.3:
        hint = "No test validation in a complex session — tests help verify Claude's work."

    return DimensionScore(
        key="trust_calibration",
        name="Trust Calibration",
        category="autonomy",
        score=round(score, 1),
        explanation=f"complexity {complexity:.0%}, correction rate {correction_rate:.0%}, {test_count} test runs",
        sub_scores=subs,
        guide="Is your intervention level calibrated to task complexity? Goes up when correction rate matches complexity. Goes down when you over- or under-correct.",
        improvement_hint=hint,
    )


def score_session_productivity(s: dict, tc: pd.DataFrame, hm: pd.DataFrame) -> DimensionScore:
    """Autonomy: Session Productivity (NEW) — tangible code output per interaction."""
    human_count = s.get("human_msg_count", 0) or 1
    total_edits = s.get("total_edits", 0)
    total_writes = s.get("total_writes", 0) if "total_writes" in s else 0
    total_errors = s.get("total_errors", 0)
    total_tool_calls = s.get("total_tool_calls", 0) or 1

    # Quality-adjusted writes per human message
    writes_per_msg = _safe_ratio(total_edits + total_writes, human_count)
    error_rate = _safe_ratio(total_errors, total_tool_calls)
    writes_score = min(writes_per_msg / 2, 1.0) * (1 - error_rate)

    # Edit magnitude (unique files touched as proxy)
    files_touched = s.get("unique_files_touched", 0)
    edit_magnitude = min(files_touched / 10, 1.0)

    # Files per human message
    files_per_msg = _safe_ratio(files_touched, human_count)
    fpm_score = min(files_per_msg / 2, 1.0)

    # Completion signals: detect git commits and passing tests from tool_calls
    completion_signals = 0
    if not tc.empty and "tool_name" in tc.columns:
        # Bash commands that might be git commits or test passes
        bash_calls = tc[tc["tool_name"] == "Bash"]
        if not bash_calls.empty:
            for col in ["bash_command", "command"]:
                if col in bash_calls.columns:
                    commands = bash_calls[col].fillna("").str.lower()
                    completion_signals += int(commands.str.contains("git commit").sum())
                    completion_signals += int(
                        commands.str.contains(r"(npm|yarn|pnpm)\s+(test|run\s+test)", regex=True).sum()
                    )
                    completion_signals += int(commands.str.contains(r"pytest|vitest|jest", regex=True).sum())
                    break
    completion_score = min(completion_signals / 3, 1.0)

    subs = [
        _sub("Writes per message", writes_per_msg, writes_score, 0.30, "2+ writes/msg = productive"),
        _sub("Edit magnitude", files_touched, edit_magnitude, 0.25, "10+ files = large edit scope"),
        _sub("Files per message", files_per_msg, fpm_score, 0.20, "2+ files/msg = efficient"),
        _sub("Completion signals", completion_signals, completion_score, 0.25, "Git commits + passing tests"),
    ]

    raw = _raw_to_score(sum(sub.contribution for sub in subs))
    score = _clamp(_dampen(raw, human_count))

    hint = ""
    if writes_per_msg < 0.5:
        hint = f"Low writes per message ({writes_per_msg:.1f}) — sessions with more code output are more productive."
    elif completion_signals == 0:
        hint = "No completion signals (git commits, test runs) — committing and testing marks progress."

    return DimensionScore(
        key="session_productivity",
        name="Session Productivity",
        category="autonomy",
        score=round(score, 1),
        explanation=f"{writes_per_msg:.1f} writes/msg, {files_touched} files, {completion_signals} completion signals",
        sub_scores=subs,
        guide="How much concrete output does the session produce? Goes up with edits, file changes, commits, and test runs. Goes down in planning-only or stalled sessions.",
        improvement_hint=hint,
    )


# ── Orchestration ───────────────────────────────────────────────

ALL_SCORERS = [
    # Communication (4)
    score_context_precision,
    score_semantic_density,
    score_iterative_refinement,
    score_conversation_balance,
    # Strategy (4)
    score_task_decomposition,
    score_validation_rigor,
    score_error_resilience,
    score_planning_depth,
    # Technical (4)
    score_code_literacy,
    score_architectural_stewardship,
    score_debugging_collaboration,
    score_token_efficiency,
    # Autonomy (4)
    score_strategic_delegation,
    score_tool_orchestration,
    score_trust_calibration,
    score_session_productivity,
]

CATEGORY_ORDER = ["communication", "strategy", "technical", "autonomy"]


def compute_session_profile(
    session_row: dict,
    tool_calls_df: pd.DataFrame,
    human_msgs_df: pd.DataFrame,
) -> ConversationProfile:
    """Compute a 16-dimension profile for a single session."""
    sid = session_row.get("session_id", "")

    # Filter tool_calls and human_msgs to this session
    tc = tool_calls_df[tool_calls_df["session_id"] == sid] if not tool_calls_df.empty else pd.DataFrame()
    hm = human_msgs_df[human_msgs_df["session_id"] == sid] if not human_msgs_df.empty else pd.DataFrame()

    return _compute_session_profile_pregrouped(session_row, tc, hm)


def compute_all_profiles(
    session_stats: pd.DataFrame,
    tool_calls: pd.DataFrame,
    human_msgs: pd.DataFrame,
    use_cache: bool = True,
    progress_callback: Callable[[float, str], None] | None = None,
) -> list[ConversationProfile]:
    """Compute profiles for all sessions.

    Args:
        progress_callback: Optional callback(fraction, message) for progress reporting.
    """
    if session_stats.empty:
        return []

    if use_cache:
        cached = _load_profile_cache()
        if cached:
            return cached

    # Pre-group by session_id for O(1) lookup instead of O(N) filter per session
    tc_groups = dict(list(tool_calls.groupby("session_id"))) if not tool_calls.empty else {}
    hm_groups = dict(list(human_msgs.groupby("session_id"))) if not human_msgs.empty else {}
    empty_df = pd.DataFrame()

    total = len(session_stats)
    profiles = []
    for idx, (_, row) in enumerate(session_stats.iterrows()):
        sid = row.get("session_id", "")
        tc = tc_groups.get(sid, empty_df)
        hm = hm_groups.get(sid, empty_df)
        profile = _compute_session_profile_pregrouped(row.to_dict(), tc, hm)
        profiles.append(profile)

        if progress_callback and idx % 5 == 0:
            progress_callback((idx + 1) / total, f"Scoring session {idx + 1}/{total}...")

    if use_cache:
        _save_profile_cache(profiles)

    return profiles


def _compute_session_profile_pregrouped(
    session_row: dict,
    tc: pd.DataFrame,
    hm: pd.DataFrame,
) -> ConversationProfile:
    """Compute profile for a single session with pre-filtered DataFrames."""
    dimensions = [scorer(session_row, tc, hm) for scorer in ALL_SCORERS]

    cat_scores: dict[str, list[float]] = {}
    for d in dimensions:
        cat_scores.setdefault(d.category, []).append(d.score)
    category_scores = {cat: round(sum(vals) / len(vals), 1) for cat, vals in cat_scores.items()}

    overall = round(sum(d.score for d in dimensions) / len(dimensions), 1) if dimensions else 5.0

    date_val = session_row.get("date", "")
    if hasattr(date_val, "strftime"):
        date_val = date_val.strftime("%Y-%m-%d")

    return ConversationProfile(
        session_id=session_row.get("session_id", ""),
        project=session_row.get("project", ""),
        date=str(date_val),
        dimensions=dimensions,
        overall_score=overall,
        category_scores=category_scores,
    )


def aggregate_profiles(profiles: list[ConversationProfile]) -> ConversationProfile:
    """Aggregate multiple profiles into one summary profile."""
    if not profiles:
        return ConversationProfile()

    # Average each dimension across profiles
    dim_scores: dict[str, list[DimensionScore]] = {}
    for p in profiles:
        for d in p.dimensions:
            dim_scores.setdefault(d.key, []).append(d)

    aggregated_dims = []
    for key, scores in dim_scores.items():
        # Average sub_scores by position first
        avg_subs: list[SubScore] = []
        if scores[0].sub_scores:
            for i in range(len(scores[0].sub_scores)):
                matching = [s.sub_scores[i] for s in scores if i < len(s.sub_scores)]
                if matching:
                    avg_subs.append(
                        SubScore(
                            name=matching[0].name,
                            raw_value=round(sum(m.raw_value for m in matching) / len(matching), 4),
                            normalized=round(sum(m.normalized for m in matching) / len(matching), 4),
                            weight=matching[0].weight,
                            contribution=round(sum(m.contribution for m in matching) / len(matching), 4),
                            threshold=matching[0].threshold,
                        )
                    )

        # Average contribution_sum then apply _raw_to_score (avoids nonlinear averaging of final scores)
        if avg_subs:
            avg_contribution_sum = sum(sub.contribution for sub in avg_subs)
            avg_score = round(_clamp(_raw_to_score(avg_contribution_sum)), 1)
        else:
            avg_score = round(sum(s.score for s in scores) / len(scores), 1)

        # Regenerate improvement hint from averaged data
        hint = ""
        if avg_subs:
            weakest = min(avg_subs, key=lambda s: s.normalized)
            if weakest.normalized < 0.3:
                hint = f"Focus on '{weakest.name}' — currently averaging {weakest.normalized:.0%} across sessions."

        aggregated_dims.append(
            DimensionScore(
                key=key,
                name=scores[0].name,
                category=scores[0].category,
                score=avg_score,
                explanation=f"Average across {len(scores)} sessions",
                sub_scores=avg_subs,
                guide=scores[0].guide,
                improvement_hint=hint,
            )
        )

    # Preserve dimension order from ALL_SCORERS
    key_order = [s.__name__.replace("score_", "") for s in ALL_SCORERS]
    aggregated_dims.sort(key=lambda d: key_order.index(d.key) if d.key in key_order else 99)

    cat_scores: dict[str, list[float]] = {}
    for d in aggregated_dims:
        cat_scores.setdefault(d.category, []).append(d.score)
    category_scores = {cat: round(sum(vals) / len(vals), 1) for cat, vals in cat_scores.items()}

    overall = round(sum(d.score for d in aggregated_dims) / len(aggregated_dims), 1) if aggregated_dims else 5.0

    return ConversationProfile(
        dimensions=aggregated_dims,
        overall_score=overall,
        category_scores=category_scores,
    )


def get_tier(score: float) -> tuple[str, str]:
    """Return (tier_name, color) for a score."""
    if score >= 8.5:
        return "Expert", "#22c55e"
    if score >= 7.0:
        return "Advanced", "#14b8a6"
    if score >= 5.5:
        return "Proficient", "#6366f1"
    if score >= 4.0:
        return "Developing", "#f59e0b"
    return "Novice", "#ef4444"


CATEGORY_COLORS = {
    "communication": "#6366f1",
    "strategy": "#14b8a6",
    "technical": "#f59e0b",
    "autonomy": "#8b5cf6",
}

CATEGORY_ICONS = {
    "communication": "\U0001f5e3\ufe0f",
    "strategy": "\U0001f4d0",
    "technical": "\U0001f527",
    "autonomy": "\U0001f916",
}
