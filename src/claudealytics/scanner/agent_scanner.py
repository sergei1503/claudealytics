"""Scan and parse agent definition files."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from claudealytics.models.schemas import AgentInfo

AGENTS_DIR = Path.home() / ".claude" / "agents"


def parse_agent_file(filepath: Path) -> AgentInfo | None:
    """Parse a single agent .md file with YAML frontmatter."""
    try:
        post = frontmatter.load(str(filepath))
        meta = post.metadata

        return AgentInfo(
            name=meta.get("name", filepath.stem),
            file_path=str(filepath),
            description=meta.get("description", ""),
            tools=meta.get("tools", []) or [],
            model=meta.get("model", ""),
        )
    except Exception:
        # Fallback: treat filename as agent name
        return AgentInfo(
            name=filepath.stem,
            file_path=str(filepath),
        )


def scan_agents(agents_dir: Path = AGENTS_DIR) -> list[AgentInfo]:
    """Scan all agent files and return parsed info."""
    if not agents_dir.exists():
        return []

    agents = []
    for filepath in sorted(agents_dir.glob("*.md")):
        info = parse_agent_file(filepath)
        if info:
            agents.append(info)

    return agents
