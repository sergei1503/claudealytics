"""Full platform report generator: data summarization + Opus LLM synthesis."""

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
DEFAULT_MODEL = "claude-opus-4-6"


def summarize_platform_data(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
) -> str:
    """Collect and summarize all platform data into a text digest (~2000-4000 words).

    Pure Python — no LLM calls. Each section handles empty data gracefully.
    """
    sections: list[str] = []

    # ── 1. Activity Overview (from StatsCache) ──
    section = ["## Activity Overview"]
    if stats:
        section.append(f"- Total sessions: {stats.totalSessions:,}")
        section.append(f"- Total messages: {stats.totalMessages:,}")
        if stats.firstSessionDate:
            section.append(f"- First session: {stats.firstSessionDate}")
        if stats.lastComputedDate:
            section.append(f"- Data through: {stats.lastComputedDate}")
        if stats.longestSession and stats.longestSession.duration > 0:
            dur_min = stats.longestSession.duration // 60
            section.append(f"- Longest session: {dur_min} min ({stats.longestSession.messageCount} messages)")

        # Peak hours
        if stats.hourCounts:
            top_hours = sorted(stats.hourCounts.items(), key=lambda x: x[1], reverse=True)[:5]
            peaks = ", ".join(f"{h}:00 ({c} msgs)" for h, c in top_hours)
            section.append(f"- Peak hours: {peaks}")

        # Model usage summary
        if stats.modelUsage:
            section.append("\n### Model Usage")
            for model, usage in sorted(stats.modelUsage.items(), key=lambda x: x[1].costUSD, reverse=True):
                total_tokens = usage.inputTokens + usage.outputTokens
                section.append(
                    f"- **{model}**: {total_tokens:,} tokens, ${usage.costUSD:.2f} cost, "
                    f"cache read: {usage.cacheReadInputTokens:,}"
                )

        # Recent daily activity (last 14 days)
        if stats.dailyActivity:
            recent = stats.dailyActivity[-14:]
            section.append("\n### Recent Daily Activity (last 14 days)")
            for day in recent:
                section.append(f"- {day.date}: {day.messageCount} msgs, {day.sessionCount} sessions")
    else:
        section.append("No stats data available.")
    sections.append("\n".join(section))

    # ── 2. Token Trends (from TokenMiner) ──
    section = ["## Token Trends"]
    try:
        from claudealytics.analytics.parsers.token_miner import mine_daily_tokens
        token_df = mine_daily_tokens(use_cache=True)
        if not token_df.empty and "date" in token_df.columns:
            total_by_model = {}
            model_cols = [c for c in token_df.columns if c != "date"]
            for col in model_cols:
                total_by_model[col] = int(token_df[col].sum())
            section.append("### Total Tokens by Model")
            for model, total in sorted(total_by_model.items(), key=lambda x: x[1], reverse=True)[:10]:
                section.append(f"- {model}: {total:,}")

            # Recent trend
            recent = token_df.tail(7)
            daily_totals = recent[model_cols].sum(axis=1)
            avg_daily = int(daily_totals.mean())
            section.append(f"\n- Average daily tokens (last 7 days): {avg_daily:,}")
        else:
            section.append("No token data available.")
    except Exception:
        section.append("Token data could not be loaded.")
    sections.append("\n".join(section))

    # ── 3. Cache Performance ──
    section = ["## Cache Performance"]
    try:
        from claudealytics.analytics.parsers.token_miner import mine_session_cache
        from claudealytics.analytics.cache_analyzer import compute_daily_cache_metrics, project_cache_summary
        session_df = mine_session_cache(use_cache=True)
        if not session_df.empty:
            total_input = int(session_df["input_tokens"].sum()) if "input_tokens" in session_df.columns else 0
            total_cache = int(session_df["cache_read_tokens"].sum()) if "cache_read_tokens" in session_df.columns else 0
            hit_rate = (total_cache / max(total_input + total_cache, 1)) * 100
            section.append(f"- Overall cache hit rate: {hit_rate:.1f}%")
            section.append(f"- Total cache read tokens: {total_cache:,}")

            # Per-project summary (top 10)
            try:
                proj_df = project_cache_summary(session_df)
                if not proj_df.empty:
                    section.append("\n### Top Projects by Cache Usage")
                    for _, row in proj_df.head(10).iterrows():
                        section.append(f"- {row.get('project', 'unknown')}: hit rate {row.get('cache_hit_rate', 0):.0f}%")
            except Exception:
                pass
        else:
            section.append("No cache session data available.")
    except Exception:
        section.append("Cache data could not be loaded.")
    sections.append("\n".join(section))

    # ── 4. Session & Content Stats ──
    section = ["## Session & Content Statistics"]
    try:
        from claudealytics.analytics.parsers.content_miner import mine_content
        content = mine_content(use_cache=True)
        if content:
            # Session stats
            if "session_stats" in content and not content["session_stats"].empty:
                ss = content["session_stats"]
                section.append(f"- Sessions analyzed: {len(ss)}")
                if "message_count" in ss.columns:
                    section.append(f"- Average messages per session: {ss['message_count'].mean():.1f}")
                if "tool_call_count" in ss.columns:
                    section.append(f"- Average tool calls per session: {ss['tool_call_count'].mean():.1f}")

            # Errors
            if "error_results" in content and not content["error_results"].empty:
                err_df = content["error_results"]
                section.append(f"\n### Errors: {len(err_df)} total error events")
                if "error_type" in err_df.columns:
                    top_errors = err_df["error_type"].value_counts().head(5)
                    for err_type, count in top_errors.items():
                        section.append(f"- {err_type}: {count}")

            # Tool calls
            if "tool_calls" in content and not content["tool_calls"].empty:
                tc = content["tool_calls"]
                section.append(f"\n### Tool Calls: {len(tc)} total")
                if "tool_name" in tc.columns:
                    top_tools = tc["tool_name"].value_counts().head(10)
                    for tool, count in top_tools.items():
                        section.append(f"- {tool}: {count}")
        else:
            section.append("No content data available.")
    except Exception:
        section.append("Content data could not be loaded.")
    sections.append("\n".join(section))

    # ── 5. Agent & Skill Usage ──
    section = ["## Agent & Skill Ecosystem"]
    try:
        from claudealytics.analytics.parsers.conversation_enricher import mine_tool_usage_stats
        tool_stats = mine_tool_usage_stats(use_cache=True)

        if tool_stats.agents:
            section.append(f"### Agents ({len(tool_stats.agents)} unique, {sum(tool_stats.agents.values())} total uses)")
            for agent, count in sorted(tool_stats.agents.items(), key=lambda x: x[1], reverse=True)[:15]:
                section.append(f"- {agent}: {count}")
        else:
            section.append("No agent usage data.")

        if tool_stats.skills:
            section.append(f"\n### Skills ({len(tool_stats.skills)} unique, {sum(tool_stats.skills.values())} total uses)")
            for skill, count in sorted(tool_stats.skills.items(), key=lambda x: x[1], reverse=True)[:15]:
                section.append(f"- {skill}: {count}")
        else:
            section.append("No skill usage data.")

        section.append(f"\n- Total conversations scanned: {tool_stats.total_conversations}")
        if tool_stats.date_range[0]:
            section.append(f"- Date range: {tool_stats.date_range[0]} to {tool_stats.date_range[1]}")
    except Exception:
        section.append("Tool usage data could not be loaded.")
    sections.append("\n".join(section))

    # ── 6. Optimization Issues ──
    section = ["## Optimization Analysis"]
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

        section.append(f"- Unused agents: {len(unused_agents)}")
        if unused_agents:
            for issue in unused_agents[:10]:
                section.append(f"  - {issue.title}")
        section.append(f"- Unused skills: {len(unused_skills)}")
        if unused_skills:
            for issue in unused_skills[:10]:
                section.append(f"  - {issue.title}")
        section.append(f"- Duplicate guidance issues: {len(duplicates)}")
        section.append(f"- Efficiency issues: {len(efficiency)}")
        if efficiency:
            for issue in efficiency[:5]:
                section.append(f"  - {issue.title}: {issue.impact}")
    except Exception:
        section.append("Optimization data could not be loaded.")
    sections.append("\n".join(section))

    # ── 7. Config Health (cached analysis if available) ──
    section = ["## Configuration Health"]
    try:
        from claudealytics.analytics.config_analyzer import load_cached_analysis
        analysis = load_cached_analysis()
        if analysis:
            all_issues = analysis.quality_issues + analysis.consistency_issues
            high = sum(1 for i in all_issues if i.severity == "high")
            medium = sum(1 for i in all_issues if i.severity == "medium")
            low = sum(1 for i in all_issues if i.severity == "low")
            health = max(0, 100 - high * 15 - medium * 5 - low * 1)
            section.append(f"- Health score: {health}/100")
            section.append(f"- Issues: {high} high, {medium} medium, {low} low")
            section.append(f"- Last analyzed: {analysis.timestamp}")

            if analysis.llm_reviews:
                scores = [r.clarity_score for r in analysis.llm_reviews.values() if r.clarity_score > 0]
                if scores:
                    section.append(f"- Average clarity score: {sum(scores)/len(scores):.0f}/100")
                    section.append(f"- Files reviewed: {len(scores)}")
        else:
            section.append("No config analysis available (run Config Analysis to populate).")
    except Exception:
        section.append("Config health data could not be loaded.")
    sections.append("\n".join(section))

    return "\n\n".join(sections)


def generate_full_report(
    stats: StatsCache | None,
    agent_execs: list,
    skill_execs: list,
    progress_callback: Callable[[float, str], None] | None = None,
) -> FullReport:
    """Generate a comprehensive platform report using Opus LLM synthesis.

    Collects all platform data, then sends to claude CLI for structured analysis.
    """
    import shutil

    start = time.time()
    timestamp = datetime.now(timezone.utc).isoformat()

    if progress_callback:
        progress_callback(0.05, "Collecting platform data...")

    data_summary = summarize_platform_data(stats, agent_execs, skill_execs)

    if progress_callback:
        progress_callback(0.2, "Data collected. Generating report with Opus...")

    # Check claude CLI availability
    if not shutil.which("claude"):
        return FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
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
                model_used=model,
                generation_duration_seconds=elapsed,
            )

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 1)
        report = FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
            model_used=model,
            error="Report generation timed out after 180s",
            generation_duration_seconds=elapsed,
        )
    except Exception as e:
        elapsed = round(time.time() - start, 1)
        report = FullReport(
            timestamp=timestamp,
            data_summary=data_summary,
            model_used=model,
            error=f"{type(e).__name__}: {str(e)[:200]}",
            generation_duration_seconds=elapsed,
        )

    if progress_callback:
        progress_callback(0.95, "Saving report...")

    # Cache result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_CACHE.write_text(report.model_dump_json(indent=2))

    if progress_callback:
        progress_callback(1.0, "Report complete")

    return report


def load_cached_report() -> FullReport | None:
    """Load cached full report from disk, or None if not available."""
    if not REPORT_CACHE.exists():
        return None
    try:
        data = json.loads(REPORT_CACHE.read_text())
        return FullReport.model_validate(data)
    except Exception:
        return None
