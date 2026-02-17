# Claude Setup Insights 🔍

A powerful analytics tool for Claude Code users to understand their usage patterns, optimize their configuration, and identify improvement opportunities.

## 🎯 Features

### Dashboard Analytics
- **Interactive Streamlit Dashboard** with 6 comprehensive tabs
- **Historical Data Mining** - Analyzes conversation archives going back months
- **Usage Patterns** - Identifies your most-used agents and skills
- **Cost Analysis** - Tracks token usage and estimates costs by model
- **Optimization Recommendations** - Data-driven suggestions for improving your setup

### Key Capabilities
- 📊 **Usage Statistics** - Track agent/skill invocations over time
- 🗑️ **Unused Component Detection** - Find agents/skills that are never used
- ⚡ **Performance Insights** - Identify high-frequency patterns for optimization
- 💰 **Cost Tracking** - Monitor token usage and spending by model
- 🎯 **Configuration Analysis** - Detect duplicates, conflicts, and inefficiencies

## 🚀 Installation

```bash
# Clone the repository
git clone https://github.com/sergei1503/claude_setup_insights.git
cd claude_setup_insights

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## 📖 Usage

### Quick Start

```bash
# Run optimization analysis
uv run claude-insights optimize

# Launch interactive dashboard
uv run claude-insights dashboard

# Generate infrastructure scan report
uv run claude-insights scan
```

### Commands

#### `optimize` - Configuration Analysis
Analyzes your Claude configuration for optimization opportunities:
```bash
uv run claude-insights optimize --output report.md
```

Identifies:
- Unused agents and skills
- Duplicate routing rules
- Inefficient model usage
- High-frequency patterns that could benefit from caching

#### `dashboard` - Interactive Analytics
Launch the Streamlit dashboard:
```bash
uv run claude-insights dashboard --port 8501
```

Features 6 tabs:
- **Overview** - System-wide metrics and activity patterns
- **Token Usage** - Token consumption by model over time
- **Sessions** - Session duration and patterns
- **Agents & Skills** - Usage frequency and trends
- **Costs** - Estimated spending breakdown
- **Optimization** - Interactive improvement recommendations

#### `scan` - Infrastructure Report
Scan your Claude Code setup for issues:
```bash
uv run claude-insights scan --output scan.md
```

Options:
- `--no-conversations` - Skip mining conversation archives (faster)

#### `stats` - Terminal Summary
Quick statistics in your terminal:
```bash
uv run claude-insights stats
```

## 🏗️ Architecture

### Data Sources
The tool analyzes multiple data sources:

| Source | Location | Purpose |
|--------|----------|---------|
| Execution logs | `~/.claude/execution-logs/` | Recent agent/skill executions with outcomes |
| Conversation archives | `~/.claude/projects/*/` | Historical tool usage (Task/Skill invocations) |
| Agent definitions | `~/.claude/agents/` | Configured agents and their tools |
| Skill definitions | `~/.claude/skills/` | Available skills and descriptions |
| Stats cache | `~/.claude/stats-cache.json` | Pre-aggregated usage statistics |
| CLAUDE.md files | `~/.claude/CLAUDE.md` + project dirs | Routing rules and configuration |

### Caching Strategy
Two-tier caching for performance:
1. **Index Cache** - Maps conversation files to line numbers with tool usage
2. **Stats Cache** - Pre-aggregated counts and statistics

This keeps memory usage minimal while analyzing thousands of conversations.

## 📊 Understanding the Metrics

### Agent/Skill Usage
- **Execution Count** - Number of times invoked
- **Usage Over Time** - Daily/weekly patterns
- **Last Used** - Most recent invocation

### Optimization Scores
- 🚨 **Critical** - Issues causing errors or confusion
- ⚠️ **Warning** - Efficiency or clarity problems
- ℹ️ **Info** - Improvement opportunities

### Cost Estimation
Based on Anthropic API pricing:
- Input tokens at standard rates
- Output tokens at standard rates
- Cache reads at 10% of input price
- Cache creation at 125% of input price

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup
```bash
# Install in development mode
uv sync

# Run tests
uv run pytest

# Format code
uv run ruff format src/
```

## 📝 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

Built as part of the [50 Days of Credits Journey](https://github.com/sergei1503) - Day 17

This tool helps Claude Code users understand and optimize their AI assistant configuration based on real usage patterns.

## 🔒 Privacy Note

This tool only analyzes local Claude Code data on your machine. No data is sent to external servers. The conversation mining is done locally to extract usage patterns while preserving privacy.

## 🐛 Known Issues

- Stats cache may not cover your full usage history if Claude Code was recently installed
- Token/cost data is estimated based on public API pricing
- Some built-in agents may not have configuration files to analyze

## 🚧 Roadmap

- [ ] Export optimization recommendations to Claude-compatible format
- [ ] Add trend analysis for usage patterns
- [ ] Support for team usage analytics
- [ ] Performance benchmarking between agents
- [ ] Custom optimization rules

---

Made with ❤️ for the Claude Code community