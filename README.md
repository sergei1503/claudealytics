# Claudealytics

[![CI](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml/badge.svg)](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Analytics dashboard for Claude Code power users. Mine your local conversation history to understand usage patterns, track costs, and optimize your setup.

All analysis runs locally — no data leaves your machine.

![Overview](docs/screenshots/overview.png)

## Quick Start

```bash
pip install claudealytics
claudealytics dashboard
```

## Dashboard Tabs

| Tab | What it shows |
|-----|---------------|
| **Overview** | KPI cards, daily activity, model distribution |
| **Report** | LLM-generated platform analysis with action plan |
| **Token Usage** | Input/output/cache breakdown by model over time |
| **Cache Analysis** | Hit rates, reuse multipliers, cost savings, cache-breaking sessions |
| **Sessions** | Duration patterns, tool call frequency, hourly heatmap |
| **Conversation Analysis** | Human interventions, assistant behavior, agentic loops, file activity, errors |
| **Tech Stack** | Language distribution, frameworks, libraries, testing discipline, research patterns |
| **Agents & Skills** | Usage frequency, trends, definitions inventory, unmapped detection |
| **Costs** | Estimated spend by model with daily/weekly breakdown |
| **Config Health** | File sizes, growth history, quality issues |

<details>
<summary>Screenshots</summary>

| Token Usage | Conversation Analysis |
|-------------|----------------------|
| ![Token Usage](docs/screenshots/token_usage.png) | ![Conversation Analysis](docs/screenshots/conversation_analysis.png) |

| Costs | Cache Analysis |
|-------|----------------|
| ![Costs](docs/screenshots/costs.png) | ![Cache Analysis](docs/screenshots/cache_analysis.png) |

See [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) for all 10 tabs.

</details>

## How It Works

Claudealytics reads local Claude Code data — no external API calls required for the dashboard (the Report tab optionally uses `claude` CLI for LLM synthesis).

| Source | Location | Purpose |
|--------|----------|---------|
| Stats cache | `~/.claude/stats-cache.json` | Pre-aggregated usage statistics |
| Conversation archives | `~/.claude/projects/*/` | Historical tool usage, content mining |
| Execution logs | `~/.claude/execution-logs/` | Recent agent/skill executions |
| Agent/skill definitions | `~/.claude/agents/`, `~/.claude/skills/` | Configuration inventory |
| CLAUDE.md files | `~/.claude/CLAUDE.md` + project dirs | Routing rules and configuration |

## CLI Commands

```bash
claudealytics dashboard           # Launch interactive dashboard
claudealytics scan                # Infrastructure scan (agents, skills, routing)
claudealytics optimize            # Optimization analysis (markdown report)
claudealytics stats               # Quick terminal summary
claudealytics tools               # Check external tool versions
```

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
