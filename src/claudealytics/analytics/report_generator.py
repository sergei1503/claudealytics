"""Platform report generator with LLM synthesis."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from claudealytics.models.schemas import FullReport, StatsCache

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
REPORT_CACHE = CACHE_DIR / "full-report.json"
REPORTS_DIR = CACHE_DIR / "reports"
DEFAULT_MODEL = "claude-opus-4-6"


def collect_platform_data(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
) -> dict:
    data: dict = {}
    activity: dict = {}
    if stats:
        activity["total_sessions"] = stats.totalSessions
        activity["total_messages"] = stats.totalMessages
        activity["first_session_date"] = stats.firstSessionDate or ""
        activity["last_computed_date"] = stats.lastComputedDate or ""
        if stats.longestSession and stats.longestSession.duration > 0:
            activity["longest_session_minutes"] = stats.longestSession.duration // 60
            activity["longest_session_messages"] = stats.longestSession.messageCount
        if stats.hourCounts:
            top_hours = sorted(stats.hourCounts.items(), key=lambda x: x[1], reverse=True)[:5]
            activity["peak_hours"] = {h: c for h, c in top_hours}
        if stats.modelUsage:
            model_data = {}
            total_cost = 0.0
            for model, usage in stats.modelUsage.items():
                total_tokens = usage.inputTokens + usage.outputTokens
                model_data[model] = {
                    "total_tokens": total_tokens,
                    "input_tokens": usage.inputTokens,
                    "output_tokens": usage.outputTokens,
                    "cache_read_tokens": usage.cacheReadInputTokens,
                    "cost_usd": round(usage.costUSD, 2),
                }
                total_cost += usage.costUSD
            activity["model_usage"] = model_data
            activity["total_cost_usd"] = round(total_cost, 2)
            if model_data:
                top_model = max(model_data.items(), key=lambda x: x[1]["cost_usd"])
                activity["top_model_by_cost"] = top_model[0]
    data["activity"] = activity

    tokens: dict = {}
    try:
        from claudealytics.analytics.parsers.token_miner import mine_daily_tokens
        token_df = mine_daily_tokens(use_cache=True)
        if not token_df.empty and "date" in token_df.columns:
            # Build by_model: model_name -> total tokens from mined data
            if "model" in token_df.columns:
                token_cols = [c for c in ["input_tokens", "output_tokens", "cache_read_input_tokens",
                                          "cache_creation_input_tokens"] if c in token_df.columns]
                model_totals = token_df.groupby("model")[token_cols].sum()
                by_model = {}
                for model_name in model_totals.index:
                    by_model[model_name] = int(model_totals.loc[model_name].sum())
                tokens["by_model"] = by_model
                tokens["total"] = sum(by_model.values())

                recent_dates = token_df["date"].drop_duplicates().nlargest(7)
                recent = token_df[token_df["date"].isin(recent_dates)]
                if token_cols:
                    daily_totals = recent.groupby("date")[token_cols].sum().sum(axis=1)
                    tokens["avg_daily_7d"] = int(daily_totals.mean()) if not daily_totals.empty else 0

            if "input_tokens" in token_df.columns and "output_tokens" in token_df.columns:
                tokens["total_input"] = int(token_df["input_tokens"].sum())
                tokens["total_output"] = int(token_df["output_tokens"].sum())
    except Exception:
        pass
    data["tokens"] = tokens

    # Enrich activity with mined data when stats-cache is incomplete
    if tokens.get("by_model") and not activity.get("top_model_by_cost"):
        try:
            from claudealytics.analytics.cost_calculator import _get_pricing
            model_costs: dict[str, float] = {}
            for model_name, total_tokens in tokens["by_model"].items():
                pricing = _get_pricing(model_name)
                # Approximate: split tokens 50/50 input/output
                avg_price = (pricing["input"] + pricing["output"]) / 2
                model_costs[model_name] = (total_tokens / 1_000_000) * avg_price
            if model_costs:
                activity["top_model_by_cost"] = max(model_costs, key=model_costs.get)
                if not activity.get("model_usage"):
                    activity["model_usage"] = {
                        m: {"total_tokens": tokens["by_model"][m], "cost_usd": round(c, 2)}
                        for m, c in sorted(model_costs.items(), key=lambda x: x[1], reverse=True)
                    }
                    activity["total_cost_usd"] = round(sum(model_costs.values()), 2)
        except Exception:
            pass

    cache: dict = {}
    try:
        from claudealytics.analytics.parsers.token_miner import mine_session_cache
        from claudealytics.analytics.cache_analyzer import project_cache_summary
        session_df = mine_session_cache(use_cache=True)
        if not session_df.empty:
            total_input = int(session_df["input_tokens"].sum()) if "input_tokens" in session_df.columns else 0
            total_cache = int(session_df["cache_read_input_tokens"].sum()) if "cache_read_input_tokens" in session_df.columns else 0
            total_creation = int(session_df["cache_creation_input_tokens"].sum()) if "cache_creation_input_tokens" in session_df.columns else 0
            cache["total_input_tokens"] = total_input
            cache["total_cache_read"] = total_cache
            cache["total_cache_creation"] = total_creation
            cache["hit_rate"] = round((total_cache / max(total_input + total_cache + total_creation, 1)) * 100, 1)

            try:
                proj_df = project_cache_summary(session_df)
                if not proj_df.empty:
                    top_projects = {}
                    for _, row in proj_df.head(10).iterrows():
                        top_projects[row.get("project", "unknown")] = round(row.get("cache_hit_rate", 0), 1)
                    cache["top_projects"] = top_projects
            except Exception:
                pass
    except Exception:
        pass
    data["cache"] = cache

    content_data: dict = {}
    try:
        from claudealytics.analytics.parsers.content_miner import mine_content
        content = mine_content(use_cache=True)
        if content:
            if "session_stats" in content and not content["session_stats"].empty:
                ss = content["session_stats"]
                content_data["sessions_analyzed"] = len(ss)
                if "message_count" in ss.columns:
                    content_data["avg_messages_per_session"] = round(ss["message_count"].mean(), 1)
                if "tool_call_count" in ss.columns:
                    content_data["avg_tool_calls_per_session"] = round(ss["tool_call_count"].mean(), 1)

            if "error_results" in content and not content["error_results"].empty:
                err_df = content["error_results"]
                content_data["total_errors"] = len(err_df)
                if "error_type" in err_df.columns:
                    content_data["errors_by_type"] = err_df["error_type"].value_counts().head(5).to_dict()

            if "tool_calls" in content and not content["tool_calls"].empty:
                tc = content["tool_calls"]
                content_data["total_tool_calls"] = len(tc)
                if "tool_name" in tc.columns:
                    content_data["top_tools"] = tc["tool_name"].value_counts().head(10).to_dict()

            if "session_stats" in content and not content["session_stats"].empty:
                ss = content["session_stats"]
                for col in ("writes_total_count", "writes_with_prior_read_count",
                            "intervention_correction", "intervention_approval",
                            "intervention_guidance", "intervention_new_instruction"):
                    if col in ss.columns:
                        content_data[col] = int(ss[col].sum())
                if "avg_autonomy_run_length" in ss.columns:
                    content_data["avg_autonomy_run_length"] = round(float(ss["avg_autonomy_run_length"].mean()), 2)

                # 7-day recent metrics for health scoring
                if "date" in ss.columns:
                    import pandas as pd
                    recent_cutoff = pd.Timestamp.now() - pd.Timedelta(days=7)
                    recent_ss = ss[ss["date"] >= recent_cutoff]
                    if not recent_ss.empty:
                        # Autonomy ratio: assistant_msgs / total_msgs per session, averaged
                        if "human_msg_count" in recent_ss.columns and "assistant_msg_count" in recent_ss.columns:
                            total_msgs = recent_ss["human_msg_count"] + recent_ss["assistant_msg_count"]
                            ratios = (recent_ss["assistant_msg_count"] / total_msgs).where(total_msgs > 0, 0)
                            content_data["recent_autonomy_ratio"] = round(float(ratios.mean()), 3)
                        # Read-before-write percentage
                        if "writes_total_count" in recent_ss.columns and "writes_with_prior_read_count" in recent_ss.columns:
                            recent_writes = int(recent_ss["writes_total_count"].sum())
                            recent_rbw = int(recent_ss["writes_with_prior_read_count"].sum())
                            if recent_writes > 0:
                                content_data["recent_rbw_pct"] = round(recent_rbw / recent_writes * 100, 1)
    except Exception:
        pass
    data["content"] = content_data

    agents_skills: dict = {}
    try:
        from claudealytics.analytics.parsers.conversation_enricher import mine_tool_usage_stats
        from claudealytics.analytics.aggregators.usage_aggregator import build_canonical_map
        tool_stats = mine_tool_usage_stats(use_cache=True)

        if tool_stats.agents:
            canon = build_canonical_map(list(tool_stats.agents.keys()))
            merged_agents: dict[str, int] = {}
            for name, count in tool_stats.agents.items():
                canonical = canon.get(name, name)
                merged_agents[canonical] = merged_agents.get(canonical, 0) + count
            agents_skills["agents"] = dict(sorted(merged_agents.items(), key=lambda x: x[1], reverse=True))
            agents_skills["unique_agents"] = len(merged_agents)
            agents_skills["total_agent_uses"] = sum(merged_agents.values())

        if tool_stats.skills:
            canon = build_canonical_map(list(tool_stats.skills.keys()))
            merged_skills: dict[str, int] = {}
            for name, count in tool_stats.skills.items():
                canonical = canon.get(name, name)
                merged_skills[canonical] = merged_skills.get(canonical, 0) + count
            agents_skills["skills"] = dict(sorted(merged_skills.items(), key=lambda x: x[1], reverse=True))
            agents_skills["unique_skills"] = len(merged_skills)
            agents_skills["total_skill_uses"] = sum(merged_skills.values())

        agents_skills["total_conversations"] = tool_stats.total_conversations
        if tool_stats.date_range[0]:
            agents_skills["date_range"] = list(tool_stats.date_range)
    except Exception:
        pass
    data["agents_skills"] = agents_skills

    optimization: dict = {}
    try:
        from claudealytics.scanner.agent_scanner import scan_agents
        from claudealytics.scanner.skill_scanner import scan_skills
        from claudealytics.analytics.optimization_analyzer import (
            analyze_unused_agents, analyze_unused_skills,
            analyze_duplicate_guidance, analyze_agent_efficiency,
        )
        from claudealytics.scanner.claude_md_scanner import scan_claude_md_files

        agents = scan_agents()
        skills = scan_skills()
        claude_md_files, _ = scan_claude_md_files()

        unused_agents = analyze_unused_agents(agents, agent_execs)
        unused_skills = analyze_unused_skills(skills, skill_execs)
        duplicates = analyze_duplicate_guidance(claude_md_files)
        efficiency = analyze_agent_efficiency(agent_execs)

        optimization["total_defined_agents"] = len(agents)
        optimization["total_defined_skills"] = len(skills)
        optimization["unused_agents"] = len(unused_agents)
        optimization["unused_agents_list"] = [issue.title for issue in unused_agents[:10]]
        optimization["unused_skills"] = len(unused_skills)
        optimization["unused_skills_list"] = [issue.title for issue in unused_skills[:10]]
        optimization["duplicate_guidance_issues"] = len(duplicates)
        optimization["efficiency_issues"] = len(efficiency)
    except Exception:
        pass
    data["optimization"] = optimization

    config_health: dict = {}
    try:
        from claudealytics.analytics.config_analyzer import load_cached_analysis
        analysis = load_cached_analysis()
        if analysis:
            all_issues = analysis.quality_issues + analysis.consistency_issues
            high = sum(1 for i in all_issues if i.severity == "high")
            medium = sum(1 for i in all_issues if i.severity == "medium")
            low = sum(1 for i in all_issues if i.severity == "low")
            issue_score = max(0, 100 - high * 10 - medium * 3 - low * 1)
            avg_clarity = None
            if analysis.llm_reviews:
                scores = [r.clarity_score for r in analysis.llm_reviews.values() if r.clarity_score > 0]
                if scores:
                    avg_clarity = round(sum(scores) / len(scores))
            if avg_clarity is not None:
                health = round(0.5 * issue_score + 0.5 * avg_clarity)
            else:
                health = issue_score
            config_health["health_score"] = health
            config_health["issues_high"] = high
            config_health["issues_medium"] = medium
            config_health["issues_low"] = low
            config_health["last_analyzed"] = analysis.timestamp

            if analysis.llm_reviews:
                scores = [r.clarity_score for r in analysis.llm_reviews.values() if r.clarity_score > 0]
                if scores:
                    config_health["avg_clarity_score"] = round(sum(scores) / len(scores))
                    config_health["files_reviewed"] = len(scores)
    except Exception:
        pass
    data["config_health"] = config_health

    return data


def summarize_platform_data(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
) -> str:
    data = collect_platform_data(stats, agent_execs, skill_execs)
    sections: list[str] = []

    section = ["## Activity Overview"]
    activity = data.get("activity", {})
    if activity:
        if "total_sessions" in activity:
            section.append(f"- Total sessions: {activity['total_sessions']:,}")
        if "total_messages" in activity:
            section.append(f"- Total messages: {activity['total_messages']:,}")
        if activity.get("first_session_date"):
            section.append(f"- First session: {activity['first_session_date']}")
        if activity.get("last_computed_date"):
            section.append(f"- Data through: {activity['last_computed_date']}")
        if "longest_session_minutes" in activity:
            section.append(
                f"- Longest session: {activity['longest_session_minutes']} min "
                f"({activity.get('longest_session_messages', 0)} messages)"
            )
        if "peak_hours" in activity:
            peaks = ", ".join(f"{h}:00 ({c} msgs)" for h, c in activity["peak_hours"].items())
            section.append(f"- Peak hours: {peaks}")
        if "model_usage" in activity:
            section.append("\n### Model Usage")
            for model, usage in sorted(activity["model_usage"].items(), key=lambda x: x[1]["cost_usd"], reverse=True):
                section.append(
                    f"- **{model}**: {usage['total_tokens']:,} tokens, ${usage['cost_usd']:.2f} cost, "
                    f"cache read: {usage['cache_read_tokens']:,}"
                )
        if "total_cost_usd" in activity:
            section.append(f"\n- **Total cost: ${activity['total_cost_usd']:.2f}**")
    else:
        section.append("No stats data available.")
    sections.append("\n".join(section))

    section = ["## Token Trends"]
    tokens = data.get("tokens", {})
    if tokens.get("by_model"):
        section.append("### Total Tokens by Model")
        for model, total in sorted(tokens["by_model"].items(), key=lambda x: x[1], reverse=True)[:10]:
            section.append(f"- {model}: {total:,}")
        if "avg_daily_7d" in tokens:
            section.append(f"\n- Average daily tokens (last 7 days): {tokens['avg_daily_7d']:,}")
    else:
        section.append("No token data available.")
    sections.append("\n".join(section))

    section = ["## Cache Performance"]
    cache = data.get("cache", {})
    if "hit_rate" in cache:
        section.append(f"- Overall cache hit rate: {cache['hit_rate']:.1f}%")
        section.append(f"- Total cache read tokens: {cache.get('total_cache_read', 0):,}")
        if "top_projects" in cache:
            section.append("\n### Top Projects by Cache Usage")
            for project, rate in cache["top_projects"].items():
                section.append(f"- {project}: hit rate {rate:.0f}%")
    else:
        section.append("No cache data available.")
    sections.append("\n".join(section))

    section = ["## Session & Content Statistics"]
    content = data.get("content", {})
    if content:
        if "sessions_analyzed" in content:
            section.append(f"- Sessions analyzed: {content['sessions_analyzed']}")
        if "avg_messages_per_session" in content:
            section.append(f"- Average messages per session: {content['avg_messages_per_session']:.1f}")
        if "avg_tool_calls_per_session" in content:
            section.append(f"- Average tool calls per session: {content['avg_tool_calls_per_session']:.1f}")
        if "total_errors" in content:
            section.append(f"\n### Errors: {content['total_errors']} total error events")
            for err_type, count in content.get("errors_by_type", {}).items():
                section.append(f"- {err_type}: {count}")
        if "total_tool_calls" in content:
            section.append(f"\n### Tool Calls: {content['total_tool_calls']} total")
            for tool, count in content.get("top_tools", {}).items():
                section.append(f"- {tool}: {count}")
    else:
        section.append("No content data available.")
    sections.append("\n".join(section))

    section = ["## Agent & Skill Ecosystem"]
    as_data = data.get("agents_skills", {})
    if as_data.get("agents"):
        section.append(
            f"### Agents ({as_data.get('unique_agents', 0)} unique, "
            f"{as_data.get('total_agent_uses', 0)} total uses)"
        )
        for agent, count in list(as_data["agents"].items())[:15]:
            section.append(f"- {agent}: {count}")
    else:
        section.append("No agent usage data.")
    if as_data.get("skills"):
        section.append(
            f"\n### Skills ({as_data.get('unique_skills', 0)} unique, "
            f"{as_data.get('total_skill_uses', 0)} total uses)"
        )
        for skill, count in list(as_data["skills"].items())[:15]:
            section.append(f"- {skill}: {count}")
    else:
        section.append("No skill usage data.")
    if "total_conversations" in as_data:
        section.append(f"\n- Total conversations scanned: {as_data['total_conversations']}")
    if as_data.get("date_range"):
        section.append(f"- Date range: {as_data['date_range'][0]} to {as_data['date_range'][1]}")
    sections.append("\n".join(section))

    section = ["## Optimization Analysis"]
    opt = data.get("optimization", {})
    if opt:
        section.append(f"- Unused agents: {opt.get('unused_agents', 0)}")
        for title in opt.get("unused_agents_list", []):
            section.append(f"  - {title}")
        section.append(f"- Unused skills: {opt.get('unused_skills', 0)}")
        for title in opt.get("unused_skills_list", []):
            section.append(f"  - {title}")
        section.append(f"- Duplicate guidance issues: {opt.get('duplicate_guidance_issues', 0)}")
        section.append(f"- Efficiency issues: {opt.get('efficiency_issues', 0)}")
    else:
        section.append("Optimization data could not be loaded.")
    sections.append("\n".join(section))

    section = ["## Configuration Health"]
    ch = data.get("config_health", {})
    if ch:
        section.append(f"- Health score: {ch.get('health_score', 0)}/100")
        section.append(
            f"- Issues: {ch.get('issues_high', 0)} high, "
            f"{ch.get('issues_medium', 0)} medium, {ch.get('issues_low', 0)} low"
        )
        if "last_analyzed" in ch:
            section.append(f"- Last analyzed: {ch['last_analyzed']}")
        if "avg_clarity_score" in ch:
            section.append(f"- Average clarity score: {ch['avg_clarity_score']}/100")
            section.append(f"- Files reviewed: {ch.get('files_reviewed', 0)}")
    else:
        section.append("No config analysis available (run Config Analysis to populate).")
    sections.append("\n".join(section))

    section = ["## Composite Platform Health Score"]
    try:
        from claudealytics.analytics.aggregators.health_score_aggregator import compute_health_score
        health = compute_health_score(data)
        section.append(f"- **Overall: {health.overall_score}/100** ({health.active_count}/{health.total_count} metrics)")
        for sub in health.sub_scores:
            score_str = f"{sub.score}/100" if sub.score is not None else "N/A"
            section.append(f"- {sub.label}: {score_str} — {sub.explanation}")
    except Exception:
        section.append("Could not compute health score.")
    sections.append("\n".join(section))

    return "\n\n".join(sections)


def export_platform_json(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
) -> dict:
    return collect_platform_data(stats, agent_execs, skill_execs)


def _ensure_config_analysis(
    progress_callback: Callable[[float, str], None] | None = None,
) -> None:
    try:
        from claudealytics.analytics.config_analyzer import load_cached_analysis, run_full_analysis
        cached = load_cached_analysis()
        if cached is None:
            if progress_callback:
                progress_callback(0.06, "Running config analysis (first time)...")

            def _config_progress(pct, text):
                if progress_callback:
                    progress_callback(0.06 + pct * 0.08, f"Config analysis: {text}")

            run_full_analysis(progress_callback=_config_progress)
    except Exception:
        pass


def generate_full_report(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
    progress_callback: Callable[[float, str], None] | None = None,
) -> FullReport:
    import shutil

    start = time.time()
    timestamp = datetime.now(timezone.utc).isoformat()

    if progress_callback:
        progress_callback(0.05, "Checking config analysis...")

    _ensure_config_analysis(progress_callback)

    if progress_callback:
        progress_callback(0.15, "Collecting platform data...")

    platform_data = collect_platform_data(stats, agent_execs, skill_execs)
    data_summary = summarize_platform_data(stats, agent_execs, skill_execs)

    if progress_callback:
        progress_callback(0.25, "Data collected. Generating report with Opus...")

    if not shutil.which("claude"):
        return FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
            data_json=platform_data,
            error="'claude' CLI not found in PATH",
            generation_duration_seconds=round(time.time() - start, 1),
        )

    prompt = (
        "You are analyzing a Claude Code platform usage report. Based on the data below, "
        "write an actionable report that helps the user understand their metrics, "
        "reduce friction, lower costs, and improve results.\n\n"
        "Structure your report with these sections:\n"
        "1. **Executive Summary** — 3-5 key findings with concrete numbers\n"
        "2. **Key Metrics Explained** — What the numbers mean in practice, "
        "which are healthy vs concerning, and what to watch\n"
        "3. **Cost Optimization** — Token usage, cache performance, model mix. "
        "Quantify savings opportunities in dollars where possible\n"
        "4. **Workflow Friction Points** — Error patterns, cache-breaking sessions, "
        "underused agents/skills that add config overhead\n"
        "5. **Configuration Health** — Quality issues, complexity, improvement areas\n"
        "6. **Action Plan** — Top 5 prioritized recommendations, each with: "
        "what to do, expected impact, and effort level (quick/medium/significant)\n\n"
        "Guidelines:\n"
        "- Be specific and data-driven — cite numbers from the data\n"
        "- Focus on actionable insights, not just observations\n"
        "- Quantify impact where possible (tokens saved, dollars saved, time saved)\n"
        "- Keep recommendations concrete: 'do X' not 'consider X'\n"
        "- Use markdown formatting (headers, bold, bullet points)\n"
        "- If a data section is empty, note it briefly and move on\n\n"
        "---\n\n"
        f"{data_summary}"
    )

    model = os.environ.get("CLAUDE_INSIGHTS_REPORT_MODEL", DEFAULT_MODEL)

    try:
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        cmd = ["claude", "--print", "--allowedTools", "", "--model", model]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=clean_env,
        )

        elapsed = round(time.time() - start, 1)

        if result.returncode != 0:
            error_detail = (result.stderr or result.stdout or "unknown error")[:500]
            report = FullReport(
                timestamp=timestamp,
                data_summary=data_summary,
                data_json=platform_data,
                model_used=model,
                error=f"CLI exit code {result.returncode}: {error_detail}",
                generation_duration_seconds=elapsed,
            )
        else:
            report_text = result.stdout.strip() if result.stdout else ""
            report = FullReport(
                timestamp=timestamp,
                report_markdown=report_text,
                data_summary=data_summary,
                data_json=platform_data,
                model_used=model,
                generation_duration_seconds=elapsed,
            )

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 1)
        report = FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
            data_json=platform_data,
            model_used=model,
            error="Report generation timed out after 180s",
            generation_duration_seconds=elapsed,
        )
    except Exception as e:
        elapsed = round(time.time() - start, 1)
        report = FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
            data_json=platform_data,
            model_used=model,
            error=f"{type(e).__name__}: {str(e)[:200]}",
            generation_duration_seconds=elapsed,
        )

    if progress_callback:
        progress_callback(0.95, "Saving report...")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_CACHE.write_text(report.model_dump_json(indent=2))
    _save_report_snapshot(report)

    if progress_callback:
        progress_callback(1.0, "Report complete")

    return report


def _save_report_snapshot(report: FullReport) -> Path | None:
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        snapshot_path = REPORTS_DIR / f"report-{ts}.json"
        snapshot_path.write_text(report.model_dump_json(indent=2))
        return snapshot_path
    except Exception:
        return None


def load_cached_report() -> FullReport | None:
    if not REPORT_CACHE.exists():
        return None
    try:
        data = json.loads(REPORT_CACHE.read_text())
        return FullReport.model_validate(data)
    except Exception:
        return None


def list_report_snapshots() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []
    snapshots = []
    for f in sorted(REPORTS_DIR.glob("report-*.json"), reverse=True):
        name = f.stem
        ts_part = name.replace("report-", "")
        snapshots.append({
            "path": str(f),
            "filename": f.name,
            "timestamp": ts_part,
        })
    return snapshots


def load_report_snapshot(path: str) -> FullReport | None:
    try:
        data = json.loads(Path(path).read_text())
        return FullReport.model_validate(data)
    except Exception:
        return None
