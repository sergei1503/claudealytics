"""Generate markdown scan reports."""

from __future__ import annotations

from datetime import datetime

from claudealytics.models.schemas import AgentInfo, ScanIssue, ScanReport, SkillInfo


def generate_report(report: ScanReport) -> str:
    """Generate a formatted markdown report from scan results."""
    lines = [
        "# Claude Code Infrastructure Scan Report",
        f"\n_Generated: {report.timestamp}_\n",
        "## Summary\n",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Agents | {report.total_agents} |",
        f"| Skills | {report.total_skills} |",
        f"| CLAUDE.md files | {report.total_claude_md_files} |",
        f"| Issues found | {len(report.issues)} |",
        "",
    ]

    # Issues by severity
    high = [i for i in report.issues if i.severity == "high"]
    medium = [i for i in report.issues if i.severity == "medium"]
    low = [i for i in report.issues if i.severity == "low"]

    if high:
        lines.append("## 🔴 High Priority Issues\n")
        for issue in high:
            lines.append(f"- **[{issue.category}]** {issue.message}")
            if issue.file:
                lines.append(f"  - File: `{issue.file}`")
            if issue.suggestion:
                lines.append(f"  - 💡 {issue.suggestion}")
        lines.append("")

    if medium:
        lines.append("## 🟡 Medium Priority Issues\n")
        for issue in medium:
            lines.append(f"- **[{issue.category}]** {issue.message}")
            if issue.file:
                lines.append(f"  - File: `{issue.file}`")
            if issue.suggestion:
                lines.append(f"  - 💡 {issue.suggestion}")
        lines.append("")

    if low:
        lines.append("## 🟢 Low Priority Issues\n")
        for issue in low:
            lines.append(f"- **[{issue.category}]** {issue.message}")
            if issue.file:
                lines.append(f"  - File: `{issue.file}`")
            if issue.suggestion:
                lines.append(f"  - 💡 {issue.suggestion}")
        lines.append("")

    if not report.issues:
        lines.append("## ✅ No Issues Found\n")
        lines.append("Everything looks clean!\n")

    # Agent inventory
    lines.append("## Agent Inventory\n")
    lines.append("| Agent | Executions | Last Used |")
    lines.append("|-------|-----------|-----------|")
    for agent in sorted(report.agents, key=lambda a: a.execution_count, reverse=True):
        last = agent.last_used[:10] if agent.last_used else "never"
        lines.append(f"| {agent.name} | {agent.execution_count} | {last} |")
    lines.append("")

    # Skill inventory
    lines.append("## Skill Inventory\n")
    lines.append("| Skill | Invocable | Executions | Last Used |")
    lines.append("|-------|-----------|-----------|-----------|")
    for skill in sorted(report.skills, key=lambda s: s.execution_count, reverse=True):
        last = skill.last_used[:10] if skill.last_used else "never"
        invocable = "✅" if skill.user_invocable else "—"
        lines.append(f"| {skill.name} | {invocable} | {skill.execution_count} | {last} |")
    lines.append("")

    return "\n".join(lines)
