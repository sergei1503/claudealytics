"""Streaming JSONL parser for Claude Code conversation files.

Handles ~1GB+ of conversation data by streaming line-by-line rather than
loading entire files into memory. Reuses session duration logic from
the existing claude_session_stats.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from claude_insights.models.schemas import SessionInfo

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _parse_iso(ts: str) -> datetime:
    """Parse ISO timestamp, handling Z suffix."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_session_info(filepath: Path) -> SessionInfo | None:
    """Extract session metadata from a single conversation JSONL file.

    Streams through the file to find first/last timestamps without
    loading the full file into memory.
    """
    try:
        first_ts = None
        last_ts = None
        message_count = 0

        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "timestamp" in data:
                    ts = data["timestamp"]
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                # Count user/assistant messages
                if data.get("type") in ("human", "assistant"):
                    message_count += 1

        if not first_ts or not last_ts:
            return None

        start = _parse_iso(first_ts)
        end = _parse_iso(last_ts)
        duration_mins = (end - start).total_seconds() / 60

        # Skip sessions < 1 min or > 8 hours (likely errors)
        if duration_mins < 1 or duration_mins > 480:
            return None

        # Derive project from path: ~/.claude/projects/<project-name>/session.jsonl
        project = ""
        parts = filepath.parts
        try:
            proj_idx = parts.index("projects")
            if proj_idx + 1 < len(parts):
                project = parts[proj_idx + 1]
        except ValueError:
            pass

        return SessionInfo(
            session_id=filepath.stem,
            project=project,
            date=start.strftime("%Y-%m-%d"),
            start_time=start,
            end_time=end,
            duration_minutes=round(duration_mins, 1),
            message_count=message_count,
        )
    except Exception:
        return None


def iter_sessions(
    projects_dir: Path = PROJECTS_DIR,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[SessionInfo]:
    """Iterate all conversation files and extract session info.

    Args:
        projects_dir: Path to ~/.claude/projects/
        date_from: Optional start date filter (YYYY-MM-DD)
        date_to: Optional end date filter (YYYY-MM-DD)
    """
    if not projects_dir.exists():
        return []

    sessions: list[SessionInfo] = []

    for filepath in projects_dir.glob("**/*.jsonl"):
        # Skip empty files and agent subconversations
        if filepath.stat().st_size == 0:
            continue
        if filepath.name.startswith("agent-"):
            continue

        info = get_session_info(filepath)
        if info is None:
            continue

        # Apply date filters
        if date_from and info.date < date_from:
            continue
        if date_to and info.date > date_to:
            continue

        sessions.append(info)

    # Sort by date
    sessions.sort(key=lambda s: s.date)
    return sessions
