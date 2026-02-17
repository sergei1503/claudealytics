"""CLI entry point for claude-insights."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="claude-insights",
    help="Infrastructure scanner and usage analytics for Claude Code",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scan(
    output: Path = typer.Option(
        Path("scan-report.md"),
        "--output", "-o",
        help="Output file for the scan report",
    ),
):
    """Scan Claude Code infrastructure for issues and generate a report."""
    from claude_insights.scanner.agent_scanner import scan_agents
    from claude_insights.scanner.skill_scanner import scan_skills
    from claude_insights.scanner.claude_md_scanner import scan_claude_md_files
    from claude_insights.scanner.cross_reference import cross_reference
    from claude_insights.scanner.report_generator import generate_report
    from claude_insights.analytics.parsers.execution_log_parser import (
        parse_agent_executions,
        parse_skill_executions,
    )
    from claude_insights.analytics.aggregators.usage_aggregator import (
        agent_usage_counts,
        skill_usage_counts,
        agent_last_used,
        skill_last_used,
    )
    from claude_insights.models.schemas import ScanReport

    with console.status("[bold green]Scanning infrastructure..."):
        # Scan components
        agents = scan_agents()
        skills = scan_skills()
        claude_md_files, claude_md_issues = scan_claude_md_files()

        # Parse execution logs for usage data
        agent_execs = parse_agent_executions()
        skill_execs = parse_skill_executions()

        # Enrich agents/skills with usage data
        a_counts = agent_usage_counts(agent_execs)
        s_counts = skill_usage_counts(skill_execs)
        a_last = agent_last_used(agent_execs)
        s_last = skill_last_used(skill_execs)

        for agent in agents:
            agent.execution_count = a_counts.get(agent.name, 0)
            agent.last_used = a_last.get(agent.name, "")

        for skill in skills:
            skill.execution_count = s_counts.get(skill.name, 0)
            skill.last_used = s_last.get(skill.name, "")

        # Cross-reference routing tables
        global_claude_md = Path.home() / ".claude" / "CLAUDE.md"
        xref_issues = []
        if global_claude_md.exists():
            content = global_claude_md.read_text()
            xref_issues = cross_reference(agents, skills, content)

        # Detect unused agents/skills (defined but never executed)
        unused_issues = []
        for agent in agents:
            if agent.execution_count == 0:
                unused_issues.append(
                    __import__("claude_insights.models.schemas", fromlist=["ScanIssue"]).ScanIssue(
                        severity="low",
                        category="unused",
                        message=f"Agent '{agent.name}' has never been executed",
                        file=agent.file_path,
                        suggestion="Consider if this agent is still needed",
                    )
                )

        # Build report
        all_issues = claude_md_issues + xref_issues + unused_issues
        report = ScanReport(
            timestamp=datetime.now().isoformat(),
            agents=agents,
            skills=skills,
            issues=all_issues,
            total_agents=len(agents),
            total_skills=len(skills),
            total_claude_md_files=len(claude_md_files),
        )

        report_md = generate_report(report)

    # Write report
    output.write_text(report_md)
    console.print(f"\n[bold green]✅ Scan complete![/]")
    console.print(f"   Found [bold]{len(all_issues)}[/] issues ({len([i for i in all_issues if i.severity == 'high'])} high, {len([i for i in all_issues if i.severity == 'medium'])} medium, {len([i for i in all_issues if i.severity == 'low'])} low)")
    console.print(f"   Report saved to: [bold]{output}[/]")

    # Print summary table
    table = Table(title="Infrastructure Summary")
    table.add_column("Component", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_row("Agents", str(len(agents)))
    table.add_row("Skills", str(len(skills)))
    table.add_row("CLAUDE.md files", str(len(claude_md_files)))
    table.add_row("Issues", str(len(all_issues)))
    console.print(table)


@app.command()
def stats():
    """Show quick usage statistics in the terminal."""
    from claude_insights.analytics.parsers.stats_cache_parser import parse_stats_cache
    from claude_insights.analytics.aggregators.token_aggregator import model_usage_summary
    from claude_insights.analytics.cost_calculator import estimate_model_costs, total_estimated_cost

    with console.status("[bold green]Loading stats..."):
        stats_data = parse_stats_cache()

    # Summary KPIs
    table = Table(title="Claude Code Usage Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_row("Total Sessions", f"{stats_data.totalSessions:,}")
    table.add_row("Total Messages", f"{stats_data.totalMessages:,}")
    table.add_row("First Session", stats_data.firstSessionDate[:10] if stats_data.firstSessionDate else "—")
    table.add_row("Last Computed", stats_data.lastComputedDate)
    table.add_row("Days Active", str(len(stats_data.dailyActivity)))
    table.add_row("Est. Total Cost", f"${total_estimated_cost(stats_data):,.2f}")
    console.print(table)

    # Model breakdown
    model_table = Table(title="Token Usage by Model")
    model_table.add_column("Model", style="cyan")
    model_table.add_column("Input", justify="right")
    model_table.add_column("Output", justify="right")
    model_table.add_column("Cache Read", justify="right")
    model_table.add_column("Est. Cost", justify="right", style="yellow")

    costs_df = estimate_model_costs(stats_data)
    for _, row in costs_df.iterrows():
        model_usage = stats_data.modelUsage.get(row["model"])
        if model_usage:
            model_table.add_row(
                _short_model(row["model"]),
                f"{model_usage.inputTokens:,}",
                f"{model_usage.outputTokens:,}",
                f"{model_usage.cacheReadInputTokens:,}",
                f"${row['total_cost']:,.2f}",
            )
    console.print(model_table)


@app.command()
def dashboard(
    port: int = typer.Option(8501, "--port", "-p", help="Port to run dashboard on"),
):
    """Launch the interactive Streamlit dashboard."""
    import sys
    import subprocess

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    console.print(f"[bold green]🚀 Launching dashboard on port {port}...[/]")
    console.print(f"   Open http://localhost:{port} in your browser\n")

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(dashboard_path),
         "--server.port", str(port), "--server.headless", "true"],
    )


def _short_model(model: str) -> str:
    if "opus-4-6" in model:
        return "Opus 4.6"
    if "opus-4-5" in model:
        return "Opus 4.5"
    if "opus-4-1" in model:
        return "Opus 4.1"
    if "sonnet-4-5" in model:
        return "Sonnet 4.5"
    if "sonnet-4-1" in model:
        return "Sonnet 4.1"
    if "haiku" in model:
        return "Haiku 3.5"
    return model


if __name__ == "__main__":
    app()
