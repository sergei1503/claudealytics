"""Composite Platform Health Score computed from usage data."""

from __future__ import annotations

from claudealytics.models.schemas import HealthScoreResult, HealthSubScore


def _clamp(v: float, lo: float = 0, hi: float = 100) -> int:
    return int(max(lo, min(hi, round(v))))


def _score_cache_efficiency(data: dict) -> HealthSubScore:
    cache = data.get("cache", {})
    hit_rate = cache.get("hit_rate")
    if hit_rate is None:
        return HealthSubScore(name="cache_efficiency", label="Cache Efficiency", weight=0.20)

    score = _clamp((hit_rate / 80) * 100)
    return HealthSubScore(
        name="cache_efficiency", label="Cache Efficiency",
        score=score, weight=0.20,
        explanation=f"Hit rate {hit_rate:.1f}%",
    )


def _score_error_rate(data: dict) -> HealthSubScore:
    content = data.get("content", {})
    total_errors = content.get("total_errors")
    total_tool_calls = content.get("total_tool_calls")
    if total_errors is None or total_tool_calls is None or total_tool_calls == 0:
        return HealthSubScore(name="error_rate", label="Error Rate", weight=0.15)

    error_pct = (total_errors / total_tool_calls) * 100
    if error_pct <= 5:
        score = 100 - (error_pct / 5) * 25
    else:
        score = 75 - ((error_pct - 5) / 15) * 75
    return HealthSubScore(
        name="error_rate", label="Error Rate",
        score=_clamp(score), weight=0.15,
        explanation=f"{error_pct:.1f}% across {total_tool_calls:,} calls",
    )


def _score_read_before_write(data: dict) -> HealthSubScore:
    content = data.get("content", {})
    writes_total = content.get("writes_total_count")
    writes_with_read = content.get("writes_with_prior_read_count")
    if writes_total is None or writes_total == 0:
        return HealthSubScore(name="read_before_write", label="Read Before Write", weight=0.15)

    pct = (writes_with_read / writes_total) * 100
    return HealthSubScore(
        name="read_before_write", label="Read Before Write",
        score=_clamp(pct), weight=0.15,
        explanation=f"{pct:.0f}% preceded by read",
    )


def _score_token_efficiency(data: dict) -> HealthSubScore:
    activity = data.get("activity", {})
    model_usage = activity.get("model_usage", {})
    if not model_usage:
        return HealthSubScore(name="token_efficiency", label="Token Efficiency", weight=0.10)

    total_input = sum(m.get("input_tokens", 0) + m.get("cache_read_tokens", 0) for m in model_usage.values())
    total_output = sum(m.get("output_tokens", 0) for m in model_usage.values())
    if total_input == 0:
        return HealthSubScore(name="token_efficiency", label="Token Efficiency", weight=0.10)

    ratio = total_output / total_input
    if 0.15 <= ratio <= 0.60:
        score = 100
    elif ratio < 0.15:
        score = (ratio / 0.15) * 100
    else:
        score = max(0, 100 - ((ratio - 0.60) / 0.90) * 100)
    return HealthSubScore(
        name="token_efficiency", label="Token Efficiency",
        score=_clamp(score), weight=0.10,
        explanation=f"Ratio {ratio:.2f}",
    )


def _score_model_balance(data: dict) -> HealthSubScore:
    activity = data.get("activity", {})
    model_usage = activity.get("model_usage", {})
    if not model_usage:
        return HealthSubScore(name="model_balance", label="Model Balance", weight=0.10)

    total_tokens = sum(m.get("total_tokens", 0) for m in model_usage.values())
    if total_tokens == 0:
        return HealthSubScore(name="model_balance", label="Model Balance", weight=0.10)

    opus_tokens = sonnet_tokens = haiku_tokens = 0
    for model, usage in model_usage.items():
        t = usage.get("total_tokens", 0)
        ml = model.lower()
        if "opus" in ml:
            opus_tokens += t
        elif "sonnet" in ml:
            sonnet_tokens += t
        elif "haiku" in ml:
            haiku_tokens += t

    opus_pct = opus_tokens / total_tokens
    sonnet_pct = sonnet_tokens / total_tokens
    haiku_pct = haiku_tokens / total_tokens

    models_used = sum(1 for p in [opus_pct, sonnet_pct, haiku_pct] if p > 0.01)
    if models_used == 1:
        score = 40
    elif models_used == 2:
        score = 70
    else:
        score = 85

    if haiku_pct > 0.05:
        score = min(100, score + 15)

    max_pct = max(opus_pct, sonnet_pct, haiku_pct)
    if max_pct > 0.90:
        score = min(score, 30)

    premium_pct = (opus_tokens + sonnet_tokens) / total_tokens * 100
    return HealthSubScore(
        name="model_balance", label="Model Balance",
        score=_clamp(score), weight=0.10,
        explanation=f"{premium_pct:.0f}% on premium models",
    )


def _score_config_health(data: dict) -> HealthSubScore:
    ch = data.get("config_health", {})
    health = ch.get("health_score")
    if health is None:
        return HealthSubScore(
            name="config_health", label="Config Health", weight=0.10,
            explanation="Run analysis to enable",
        )
    return HealthSubScore(
        name="config_health", label="Config Health",
        score=_clamp(health), weight=0.10,
        explanation=f"{ch.get('issues_high', 0)} high, {ch.get('issues_medium', 0)} medium issues",
    )


def _score_autonomy(data: dict) -> HealthSubScore:
    content = data.get("content", {})
    avg_run = content.get("avg_autonomy_run_length")
    if avg_run is None:
        return HealthSubScore(name="autonomy", label="Autonomy & Efficiency", weight=0.10)

    run_score = _clamp((avg_run / 6) * 100)

    total_interventions = (
        content.get("intervention_correction", 0)
        + content.get("intervention_approval", 0)
        + content.get("intervention_guidance", 0)
        + content.get("intervention_new_instruction", 0)
    )
    corrections = content.get("intervention_correction", 0)
    if total_interventions > 0:
        correction_pct = corrections / total_interventions
        correction_penalty = correction_pct * 30
        run_score = _clamp(run_score - correction_penalty)

    return HealthSubScore(
        name="autonomy", label="Autonomy & Efficiency",
        score=run_score, weight=0.10,
        explanation=f"{avg_run:.1f} msgs between interventions",
    )


def _score_agent_utilization(data: dict) -> HealthSubScore:
    as_data = data.get("agents_skills", {})
    opt = data.get("optimization", {})

    used_agents = as_data.get("unique_agents", 0)
    used_skills = as_data.get("unique_skills", 0)
    unused_agents = opt.get("unused_agents", 0)
    unused_skills = opt.get("unused_skills", 0)

    total_defined = (used_agents + unused_agents) + (used_skills + unused_skills)
    total_used = used_agents + used_skills

    if total_defined == 0:
        return HealthSubScore(name="agent_utilization", label="Agent & Skill Utilization", weight=0.10)

    pct = (total_used / total_defined) * 100
    unused_count = unused_agents + unused_skills
    return HealthSubScore(
        name="agent_utilization", label="Agent & Skill Utilization",
        score=_clamp(pct), weight=0.10,
        explanation=f"{unused_count} unused" if unused_count > 0 else "All in use",
    )


def compute_health_score(platform_data: dict) -> HealthScoreResult:
    scorers = [
        _score_cache_efficiency,
        _score_error_rate,
        _score_read_before_write,
        _score_token_efficiency,
        _score_model_balance,
        _score_config_health,
        _score_autonomy,
        _score_agent_utilization,
    ]

    sub_scores = [fn(platform_data) for fn in scorers]
    active = [s for s in sub_scores if s.score is not None]

    if not active:
        return HealthScoreResult(
            overall_score=0,
            sub_scores=sub_scores,
            active_count=0,
            total_count=len(sub_scores),
        )

    total_active_weight = sum(s.weight for s in active) or 1.0
    weighted_sum = sum(s.score * (s.weight / total_active_weight) for s in active)

    return HealthScoreResult(
        overall_score=_clamp(weighted_sum),
        sub_scores=sub_scores,
        active_count=len(active),
        total_count=len(sub_scores),
    )
