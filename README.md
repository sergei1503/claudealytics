# Claudealytics

[![CI](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml/badge.svg)](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Analytics dashboard for Claude Code power users. Mine your local conversation history to understand usage patterns, track costs, and optimize your workflow.

> **Privacy first** — all analysis runs locally. No data leaves your machine.

## Quick Start

```bash
pip install claudealytics
claudealytics dashboard
```

## What You Get

- **LLM-generated report** with a scored health assessment across 8 dimensions
- **Token & cache analytics** — input/output breakdown by model, cache hit rates, cost savings
- **Session insights** — tool call patterns, duration trends, hourly heatmaps
- **Conversation analysis** — agentic loops, read-before-write discipline, complexity scoring
- **Tech stack profiling** — language distribution, ecosystem signals, testing discipline
- **Agent & skill tracking** — usage frequency, trends, inventory, unmapped detection
- **Config health** — file sizes, growth history, quality issues

## Screenshots

<table>
<tr>
<td width="50%"><strong>Report</strong><br>LLM-scored health assessment<br><img src="docs/screenshots/report.png" alt="Report"></td>
<td width="50%"><strong>Config Health</strong><br>File sizes and quality issues<br><img src="docs/screenshots/config_health.png" alt="Config Health"></td>
</tr>
<tr>
<td><strong>Daily Input Tokens</strong><br>Token consumption by model<br><img src="docs/screenshots/daily_input_tokens.png" alt="Daily Input Tokens"></td>
<td><strong>Cache Hit Rate</strong><br>Daily cache efficiency<br><img src="docs/screenshots/cache_hit_rate.png" alt="Cache Hit Rate"></td>
</tr>
<tr>
<td><strong>Daily Tool Calls</strong><br>Tool usage over time<br><img src="docs/screenshots/daily_tool_calls.png" alt="Daily Tool Calls"></td>
<td><strong>Tool Usage by Type</strong><br>Read/write/execute breakdown<br><img src="docs/screenshots/tool_usage_type.png" alt="Tool Usage by Type"></td>
</tr>
<tr>
<td><strong>Read-Before-Write</strong><br>Code discipline tracking<br><img src="docs/screenshots/read_before_write.png" alt="Read-Before-Write Discipline"></td>
<td><strong>Complexity Over Time</strong><br>Session complexity trends<br><img src="docs/screenshots/complexity.png" alt="Complexity Over Time"></td>
</tr>
<tr>
<td><strong>Language Trend</strong><br>Language distribution over time<br><img src="docs/screenshots/language_trend.png" alt="Language Trend"></td>
<td><strong>Ecosystem Signals</strong><br>Framework and tool detection<br><img src="docs/screenshots/ecosystem_signals.png" alt="Ecosystem Signals"></td>
</tr>
<tr>
<td colspan="2" align="center"><strong>Agent Usage Over Time</strong><br>Agent invocation trends<br><img src="docs/screenshots/agent_usage.png" alt="Agent Usage Over Time" width="60%"></td>
</tr>
</table>

## CLI Commands

```bash
claudealytics dashboard           # Launch interactive dashboard
claudealytics scan                # Infrastructure scan (agents, skills, routing)
claudealytics optimize            # Optimization analysis (markdown report)
claudealytics stats               # Quick terminal summary
claudealytics tools               # Check external tool versions
```

## How It Works

Claudealytics reads local Claude Code data — no external API calls required (the Report tab optionally uses `claude` CLI for LLM synthesis).

| Source | Location | Purpose |
|--------|----------|---------|
| Stats cache | `~/.claude/stats-cache.json` | Pre-aggregated usage statistics |
| Conversation archives | `~/.claude/projects/*/` | Historical tool usage, content mining |
| Execution logs | `~/.claude/execution-logs/` | Recent agent/skill executions |
| Agent/skill definitions | `~/.claude/agents/`, `~/.claude/skills/` | Configuration inventory |
| CLAUDE.md files | `~/.claude/CLAUDE.md` + project dirs | Routing rules and configuration |

## Development

```bash
git clone https://github.com/sergei1503/claudealytics.git
cd claudealytics
uv sync --extra dev --extra test
uv run pytest -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## License

MIT — see [LICENSE](LICENSE) for details.
