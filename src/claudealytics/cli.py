from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="claudealytics",
    help="Infrastructure scanner and usage analytics for Claude Code",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scan(
    output: Path = typer.Option(
        Path("scan-report.md"),
        "--output",
        "-o",
        help="Output file for the scan report",
    ),
    no_conversations: bool = typer.Option(
        False,
        "--no-conversations",
        help="Skip mining conversation archives (faster, but less complete)",
    ),
):
    """Scan Claude Code infrastructure for issues and generate a report."""
    from claudealytics.analytics.aggregators.usage_aggregator import (
        agent_last_used,
        agent_usage_counts,
        skill_last_used,
        skill_usage_counts,
    )
    from claudealytics.analytics.data_merger import (
        merge_agent_executions,
        merge_skill_executions,
    )
    from claudealytics.analytics.parsers.conversation_enricher import mine_tool_usage_stats
    from claudealytics.analytics.parsers.execution_log_parser import (
        parse_agent_executions,
        parse_skill_executions,
    )
    from claudealytics.models.schemas import ScanReport
    from claudealytics.scanner.agent_scanner import scan_agents
    from claudealytics.scanner.claude_md_scanner import scan_claude_md_files
    from claudealytics.scanner.cross_reference import cross_reference
    from claudealytics.scanner.report_generator import generate_report
    from claudealytics.scanner.skill_scanner import scan_skills

    with console.status("[bold green]Scanning infrastructure..."):
        agents = scan_agents()
        skills = scan_skills()
        claude_md_files, claude_md_issues = scan_claude_md_files()

        log_agent_execs = parse_agent_executions()
        log_skill_execs = parse_skill_executions()

        if not no_conversations:
            console.print("[dim]Mining conversation archives for historical data...[/]")
            conv_stats = mine_tool_usage_stats(use_cache=True)

            conv_agent_execs = [
                {"timestamp": "", "session_id": "", "agent_type": agent_name, "prompt": "", "status": "unknown"}
                for agent_name, count in conv_stats.agents.items()
                for _ in range(min(count, 10))
            ]
            conv_skill_execs = [
                {"timestamp": "", "session_id": "", "skill_name": skill_name, "args": "", "status": "unknown"}
                for skill_name, count in conv_stats.skills.items()
                for _ in range(min(count, 10))
            ]

            agent_execs = merge_agent_executions(log_agent_execs, conv_agent_execs)
            skill_execs = merge_skill_executions(log_skill_execs, conv_skill_execs)

            a_counts = conv_stats.agents
            s_counts = conv_stats.skills
        else:
            agent_execs = log_agent_execs
            skill_execs = log_skill_execs
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

        xref_issues = []
        global_claude_md = Path.home() / ".claude" / "CLAUDE.md"
        if global_claude_md.exists():
            xref_issues = cross_reference(agents, skills, global_claude_md.read_text())

        unused_issues = []
        for agent in agents:
            if agent.execution_count == 0:
                unused_issues.append(
                    __import__("claudealytics.models.schemas", fromlist=["ScanIssue"]).ScanIssue(
                        severity="low",
                        category="unused",
                        message=f"Agent '{agent.name}' has never been executed",
                        file=agent.file_path,
                        suggestion="Consider if this agent is still needed",
                    )
                )

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

    output.write_text(report_md)
    console.print("\n[bold green]✅ Scan complete![/]")
    high_ct = len([i for i in all_issues if i.severity == "high"])
    med_ct = len([i for i in all_issues if i.severity == "medium"])
    low_ct = len([i for i in all_issues if i.severity == "low"])
    console.print(f"   Found [bold]{len(all_issues)}[/] issues ({high_ct} high, {med_ct} medium, {low_ct} low)")
    console.print(f"   Report saved to: [bold]{output}[/]")

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
    from claudealytics.analytics.cost_calculator import estimate_model_costs, total_estimated_cost
    from claudealytics.analytics.parsers.stats_cache_parser import parse_stats_cache

    with console.status("[bold green]Loading stats..."):
        stats_data = parse_stats_cache()

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
def optimize(
    output: Path = typer.Option(
        Path("optimization-report.md"),
        "--output",
        "-o",
        help="Output file for the optimization report",
    ),
    include_conversations: bool = typer.Option(
        True,
        "--include-conversations/--no-conversations",
        help="Include conversation analysis for deeper insights",
    ),
):
    """Analyze Claude configuration for optimization opportunities."""
    from claudealytics.analytics.optimization_analyzer import generate_optimization_report

    with console.status("[bold green]Analyzing configuration for optimizations..."):
        report = generate_optimization_report(include_conversations)

    critical_count = report.count("🚨 Critical")
    quick_wins = report.count("⚡ Quick Win")
    opportunities = report.count("💡 Opportunity")

    output.write_text(report)
    console.print(
        Panel.fit(
            f"[bold green]✅ Optimization report generated[/bold green]\n"
            f"📄 Output: {output}\n"
            f"Found {critical_count} critical issues, {quick_wins} quick wins, {opportunities} opportunities",
            title="Optimization Analysis Complete",
        )
    )


@app.command(name="export-json")
def export_json(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file (default: print to stdout)",
    ),
    pretty: bool = typer.Option(
        True,
        "--pretty/--compact",
        help="Pretty-print JSON output",
    ),
):
    """Export structured platform data as JSON."""
    import json

    from claudealytics.analytics.parsers.execution_log_parser import (
        parse_agent_executions,
        parse_skill_executions,
    )
    from claudealytics.analytics.parsers.stats_cache_parser import parse_stats_cache
    from claudealytics.analytics.report_generator import export_platform_json

    with console.status("[bold green]Collecting platform data..."):
        stats_data = parse_stats_cache()
        agent_execs = parse_agent_executions()
        skill_execs = parse_skill_executions()
        data = export_platform_json(stats_data, agent_execs, skill_execs)

    indent = 2 if pretty else None
    json_str = json.dumps(data, indent=indent, default=str)

    if output:
        output.write_text(json_str)
        console.print(f"[bold green]Exported platform data to {output}[/]")
    else:
        print(json_str)


@app.command()
def dashboard(
    port: int = typer.Option(8501, "--port", "-p", help="Port to run dashboard on"),
):
    """Launch the interactive Streamlit dashboard."""
    import subprocess
    import sys

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"

    console.print(f"[bold green]🚀 Launching dashboard on port {port}...[/]")
    console.print(f"   Open http://localhost:{port} in your browser\n")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_path),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
    )


@app.command()
def tools():
    """Check version status of external CLI tools."""
    from claudealytics.scanner.tool_version_scanner import scan_tool_versions

    with console.status("[bold green]Checking tool versions..."):
        results = scan_tool_versions()

    STATUS_DISPLAY = {
        "up_to_date": "[green]✓ up to date[/]",
        "update_available": "[yellow]↑ update available[/]",
        "not_installed": "[red]✗ not installed[/]",
        "unknown": "[dim]? unknown[/]",
    }

    table = Table(title="External Tool Versions")
    table.add_column("Tool", style="cyan")
    table.add_column("Installed", justify="right")
    table.add_column("Latest", justify="right")
    table.add_column("Status", justify="center")

    for r in results:
        table.add_row(
            r.name,
            r.installed_version or "[dim]—[/]",
            r.latest_version or "[dim]—[/]",
            STATUS_DISPLAY.get(r.status, r.status),
        )

    console.print(table)

    outdated = [r for r in results if r.status == "update_available"]
    missing = [r for r in results if r.status == "not_installed"]
    if outdated:
        console.print(f"\n[yellow]{len(outdated)} tool(s) have updates available[/]")
    if missing:
        console.print(f"[red]{len(missing)} tool(s) not installed[/]")
    if not outdated and not missing:
        console.print("\n[green]All tools up to date![/]")


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
