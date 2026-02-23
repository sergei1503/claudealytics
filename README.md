# Claudealytics

[![CI](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml/badge.svg)](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Analytics dashboard for Claude Code power users. Mine your local conversation history to understand usage patterns, track costs, and optimize your workflow. All analysis runs locally.

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

## From Insight to Action

The report doesn't just show numbers — it surfaces concrete improvements you can make to your Claude Code setup. Here are real examples of changes driven by Claudealytics findings:

| Insight | What Changed |
|---------|-------------|
| 4 agent files had broken YAML frontmatter | Fixed frontmatter format so the parser reads them correctly |
| "Missing name/description" flagged as medium severity | Downgraded to low — agents work fine without these cosmetic fields |
| 11 unused agents/skills adding context overhead | Identified candidates for removal, reducing prompt bloat |
| 79% read-before-write discipline (target: 90%+) | Highlighted sessions where blind writes happen — focus area for workflow improvement |
| Config health score formula was too harsh | Rebalanced to blend issue severity with LLM clarity scores (50/50) |
| Top model by cost missing from report | Added fallback to derive model costs from mined JSONL data when stats-cache is incomplete |

The **Platform Health Score** (8 sub-scores, weighted composite) gives you a single number to track over time. Each sub-score links to a specific lever:

- **Cache Efficiency** — if low, check for cache-busting patterns in long sessions
- **Error Rate** — surface the top error types and which tools fail most
- **Read Before Write** — catch blind overwrites before they cause bugs
- **Token Efficiency** — flag sessions with unusually high output ratios
- **Model Balance** — identify tasks that could shift from Opus to Haiku
- **Config Health** — find broken references, unused configs, and stale instructions
- **Autonomy** — measure how often Claude works independently vs. needing guidance
- **Agent Utilization** — prune unused agents that add overhead without value

## Screenshots

<table>
<tr>
<td width="50%"><img src="docs/screenshots/report.png" alt="Report"><br><strong>Report</strong> — LLM-scored health assessment</td>
<td width="50%"><img src="docs/screenshots/config_health.png" alt="Config Health"><br><strong>Config Health</strong> — File sizes and quality issues</td>
</tr>
<tr>
<td><img src="docs/screenshots/daily_input_tokens.png" alt="Daily Input Tokens"><br><strong>Daily Input Tokens</strong> — Token consumption by model</td>
<td><img src="docs/screenshots/cache_hit_rate.png" alt="Cache Hit Rate"><br><strong>Cache Hit Rate</strong> — Daily cache efficiency</td>
</tr>
<tr>
<td><img src="docs/screenshots/daily_tool_calls.png" alt="Daily Tool Calls"><br><strong>Daily Tool Calls</strong> — Tool usage over time</td>
<td><img src="docs/screenshots/tool_usage_type.png" alt="Tool Usage by Type"><br><strong>Tool Usage by Type</strong> — Read/write/execute breakdown</td>
</tr>
<tr>
<td><img src="docs/screenshots/read_before_write.png" alt="Read-Before-Write"><br><strong>Read-Before-Write</strong> — Code discipline tracking</td>
<td><img src="docs/screenshots/complexity.png" alt="Complexity Over Time"><br><strong>Complexity Over Time</strong> — Session complexity trends</td>
</tr>
<tr>
<td><img src="docs/screenshots/language_trend.png" alt="Language Trend"><br><strong>Language Trend</strong> — Language distribution over time</td>
<td><img src="docs/screenshots/ecosystem_signals.png" alt="Ecosystem Signals"><br><strong>Ecosystem Signals</strong> — Framework and tool detection</td>
</tr>
<tr>
<td colspan="2" align="center"><img src="docs/screenshots/agent_usage.png" alt="Agent Usage Over Time" width="60%"><br><strong>Agent Usage Over Time</strong> — Agent invocation trends</td>
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
