# Claudealytics

[![CI](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml/badge.svg)](https://github.com/sergei1503/claudealytics/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/claudealytics)](https://pypi.org/project/claudealytics/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**See how you work with Claude Code.** Get an 8-dimension collaboration score, compare with other developers on [guilder.dev](https://guilder.dev/community), and track how your AI workflow improves over time.

All analysis runs locally — only your scores are published.

<!-- TODO: Replace with actual terminal GIF once recorded with vhs -->
<!-- <p align="center">
  <img src="docs/demo.gif" alt="claudealytics publish demo" width="720">
</p> -->

## Get Your Score in 30 Seconds

```bash
uvx claudealytics publish
```

That's it. No API keys, no sign-up, no config. One command that:
1. Analyzes your local Claude Code data (`~/.claude/`)
2. Computes your 8-dimension collaboration score
3. Opens a browser where you claim your profile on [guilder.dev](https://guilder.dev)

Already have Python package managers? These work too:
```bash
pipx run claudealytics publish    # via pipx
pip install claudealytics && claudealytics publish  # traditional
```

## What Gets Scored

Your collaboration style across 8 dimensions, grouped into 4 categories:

| Category | Dimensions | What it measures |
|----------|-----------|-----------------|
| **Technical** | Cache Efficiency, Error Rate | How well you leverage caching, how cleanly sessions run |
| **Strategy** | Read Before Write, Token Efficiency, Model Balance | Do you read before editing? Use models efficiently? |
| **Communication** | Config Health | How well-structured your Claude setup is |
| **Autonomy** | Autonomy & Efficiency, Agent & Skill Utilization | How independently Claude works for you, how much you use agents/skills |

Scores combine into an overall rating (0-100) with a radar chart showing your strengths.

## The Leaderboard

Claimed profiles appear on [guilder.dev/community](https://guilder.dev/community) — a public leaderboard for AI-native developers. See how your workflow compares, discover what top developers do differently.

## Local Dashboard

Want deeper analytics? The full Streamlit dashboard gives you token breakdowns, cost tracking, session insights, and more:

```bash
pip install 'claudealytics[dashboard]'
claudealytics dashboard
```

<p align="center">
  <a href="#screenshots"><img src="docs/screenshots/report.png" width="24%" alt="Report"></a>
  <a href="#screenshots"><img src="docs/screenshots/daily_input_tokens.png" width="24%" alt="Token Usage"></a>
  <a href="#screenshots"><img src="docs/screenshots/complexity.png" width="24%" alt="Complexity"></a>
  <a href="#screenshots"><img src="docs/screenshots/agent_usage.png" width="24%" alt="Agent Usage"></a>
</p>

<details>
<summary>More screenshots</summary>

| | |
|---|---|
| ![Report](docs/screenshots/report.png) **Report** — LLM-scored health assessment | ![Config Health](docs/screenshots/config_health.png) **Config Health** |
| ![Daily Tokens](docs/screenshots/daily_input_tokens.png) **Daily Input Tokens** | ![Cache Hit Rate](docs/screenshots/cache_hit_rate.png) **Cache Hit Rate** |
| ![Tool Calls](docs/screenshots/daily_tool_calls.png) **Daily Tool Calls** | ![Tool Types](docs/screenshots/tool_usage_type.png) **Tool Usage by Type** |
| ![RBW](docs/screenshots/read_before_write.png) **Read-Before-Write** | ![Complexity](docs/screenshots/complexity.png) **Complexity Over Time** |
| ![Languages](docs/screenshots/language_trend.png) **Language Trend** | ![Ecosystem](docs/screenshots/ecosystem_signals.png) **Ecosystem Signals** |

</details>

## All CLI Commands

```bash
claudealytics publish             # Publish your score to guilder.dev
claudealytics stats               # Quick terminal summary
claudealytics scan                # Infrastructure scan (agents, skills, routing)
claudealytics optimize            # Optimization analysis (markdown report)
claudealytics export-json         # Export raw data as JSON
claudealytics dashboard           # Launch full Streamlit dashboard (requires [dashboard] extra)
```

## How It Works

Claudealytics reads local Claude Code data — no external API calls for analysis.

| Source | Location | What's analyzed |
|--------|----------|----------------|
| Stats cache | `~/.claude/stats-cache.json` | Usage statistics |
| Conversations | `~/.claude/projects/*/` | Tool usage, content patterns |
| Execution logs | `~/.claude/execution-logs/` | Agent/skill executions |
| Config files | `~/.claude/agents/`, `~/.claude/skills/`, `CLAUDE.md` | Setup quality |

When you run `publish`, computed scores (not raw data) are sent to guilder.dev. Your conversations, file contents, and personal data never leave your machine.

## Development

```bash
git clone https://github.com/sergei1503/claudealytics.git
cd claudealytics
uv sync --extra dev --extra test --extra dashboard
uv run pytest -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## License

MIT — see [LICENSE](LICENSE) for details.
