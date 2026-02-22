# Claudealytics

[![CI](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml/badge.svg)](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Analytics dashboard for Claude Code power users. Mine your local conversation history to understand usage patterns, track costs, and find optimization opportunities.

All analysis runs locally — no data leaves your machine.

## Screenshots

| Overview | Sessions | Agents & Skills |
|----------|----------|-----------------|
| ![Overview](docs/screenshots/overview.png) | ![Sessions](docs/screenshots/sessions.png) | ![Agents & Skills](docs/screenshots/agents_skills.png) |

## Install

```bash
pip install claudealytics
```

Or install from source:

```bash
git clone https://github.com/sergei1503/claudealytics.git
cd claudealytics
uv sync
```

## Quick Start

```bash
claudealytics dashboard
```

Open http://localhost:8501 in your browser.

## CLI Commands

```bash
claudealytics dashboard    # Launch interactive dashboard
claudealytics optimize     # Run optimization analysis (markdown report)
claudealytics scan         # Infrastructure scan (agents, skills, routing)
claudealytics stats        # Quick terminal summary
```

## Dashboard Tabs

- **Overview** — KPI cards (sessions, messages, agent invocations) and daily activity chart
- **Token Usage** — Token consumption breakdown by model, input/output/cache split
- **Sessions** — Session duration patterns and tool call frequency
- **Agents & Skills** — Usage frequency, trends, and unmapped detection
- **Config Health** — Size metrics, history tracking, quality issues, LLM-powered reviews
- **Optimization** — Data-driven recommendations for improving your setup

## How It Works

Claudealytics reads local Claude Code data — no external API calls required.

| Source | Location | Purpose |
|--------|----------|---------|
| Execution logs | `~/.claude/execution-logs/` | Recent agent/skill executions |
| Conversation archives | `~/.claude/projects/*/` | Historical tool usage patterns |
| Agent definitions | `~/.claude/agents/` | Configured agents and tools |
| Skill definitions | `~/.claude/skills/` | Available skills |
| Stats cache | `~/.claude/stats-cache.json` | Pre-aggregated usage statistics |
| CLAUDE.md files | `~/.claude/CLAUDE.md` + project dirs | Routing rules and configuration |

## Development

```bash
uv sync --extra dev --extra test
uv run pytest -v
uv run ruff check src/ tests/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## License

MIT — see [LICENSE](LICENSE) for details.
