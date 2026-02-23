"""Parse Claude Code execution log JSONL files.

The execution logs have a quirk: the `outcome_preview` field contains
unescaped nested JSON, which breaks standard JSON parsing. We handle
this by extracting the fields before the problematic field using regex.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from claudealytics.models.schemas import AgentExecution, SkillExecution

EXECUTION_LOGS_DIR = Path.home() / ".claude" / "execution-logs"

# Regex to extract fields from agent execution lines without relying on full JSON parse
_AGENT_RE = re.compile(
    r'"timestamp"\s*:\s*"([^"]+)".*?'
    r'"session_id"\s*:\s*"([^"]*)".*?'
    r'"type"\s*:\s*"([^"]*)".*?'
    r'"agent"\s*:\s*"([^"]*)".*?'
    r'"description"\s*:\s*"([^"]*)"'
)

_SKILL_RE = re.compile(
    r'"timestamp"\s*:\s*"([^"]+)".*?'
    r'"session_id"\s*:\s*"([^"]*)".*?'
    r'"type"\s*:\s*"([^"]*)".*?'
    r'"skill"\s*:\s*"([^"]*)".*?'
    r'"args"\s*:\s*"([^"]*)"'
)


def parse_agent_executions(
    path: Path | None = None,
) -> list[AgentExecution]:
    """Parse agent-executions.jsonl into a list of AgentExecution models."""
    path = path or EXECUTION_LOGS_DIR / "agent-executions.jsonl"
    if not path.exists():
        return []

    executions: list[AgentExecution] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Try standard JSON first
            try:
                raw = json.loads(line)
                executions.append(AgentExecution.model_validate(raw))
                continue
            except (json.JSONDecodeError, Exception):
                pass

            # Fallback: regex extraction for malformed JSON
            match = _AGENT_RE.search(line)
            if match:
                executions.append(
                    AgentExecution(
                        timestamp=match.group(1),
                        session_id=match.group(2),
                        type=match.group(3),
                        agent=match.group(4),
                        description=match.group(5),
                    )
                )

    return executions


def parse_skill_executions(
    path: Path | None = None,
) -> list[SkillExecution]:
    """Parse skill-executions.jsonl into a list of SkillExecution models."""
    path = path or EXECUTION_LOGS_DIR / "skill-executions.jsonl"
    if not path.exists():
        return []

    executions: list[SkillExecution] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Try standard JSON first
            try:
                raw = json.loads(line)
                executions.append(SkillExecution.model_validate(raw))
                continue
            except (json.JSONDecodeError, Exception):
                pass

            # Fallback: regex extraction
            match = _SKILL_RE.search(line)
            if match:
                executions.append(
                    SkillExecution(
                        timestamp=match.group(1),
                        session_id=match.group(2),
                        type=match.group(3),
                        skill=match.group(4),
                        args=match.group(5),
                    )
                )

    return executions
