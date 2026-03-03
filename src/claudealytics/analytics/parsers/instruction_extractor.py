"""Extract human instructions from recent sessions for batch LLM scoring.

Filters sessions to last N days, extracts human message text (stripping code
blocks and tool outputs), and returns structured SessionInstructions objects.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from claudealytics.analytics.parsers.conversation_parser import PROJECTS_DIR, iter_sessions
from claudealytics.analytics.parsers.message_sampler import _extract_text
from claudealytics.models.schemas import SessionInstructions

# Max chars per message (we only need intent, not full code blocks)
MAX_MSG_CHARS = 500

# Regex to strip fenced code blocks
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
# Regex to strip inline code
_INLINE_CODE_RE = re.compile(r"`[^`]+`")


def _strip_code_and_noise(text: str) -> str:
    """Remove code blocks, tool outputs, and other noise — keep natural language."""
    # Strip fenced code blocks
    text = _CODE_BLOCK_RE.sub("[code]", text)
    # Strip inline code
    text = _INLINE_CODE_RE.sub("[code]", text)
    # Strip XML-like tool tags (e.g. <tool_use>, <result>, etc.)
    text = re.sub(r"<[^>]+>[\s\S]*?</[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_human_messages(filepath: Path) -> list[str]:
    """Extract all human message texts from a JSONL conversation file."""
    messages = []
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", entry.get("role", ""))
                if entry_type not in ("human", "user"):
                    continue

                msg = entry.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else msg
                text = _extract_text(content)
                if not text.strip():
                    continue

                # Clean and truncate
                cleaned = _strip_code_and_noise(text)
                if cleaned:
                    messages.append(cleaned[:MAX_MSG_CHARS])
    except OSError:
        pass
    return messages


def extract_weekly_instructions(
    days: int = 7,
    projects_dir: Path = PROJECTS_DIR,
    save_cache: bool = False,
) -> list[SessionInstructions]:
    """Extract human instructions from the last N days of sessions.

    Args:
        days: Number of days to look back (default 7).
        projects_dir: Path to ~/.claude/projects/.
        save_cache: If True, write results to ~/.cache/claudealytics/weekly-instructions.json.

    Returns:
        List of SessionInstructions, one per session, sorted by date.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sessions = iter_sessions(projects_dir=projects_dir, date_from=cutoff)

    results: list[SessionInstructions] = []

    for session in sessions:
        # Find the JSONL file for this session
        filepath = _find_session_file(session.session_id, projects_dir)
        if not filepath:
            continue

        messages = _extract_human_messages(filepath)
        if not messages:
            continue

        word_count = sum(len(m.split()) for m in messages)

        results.append(
            SessionInstructions(
                session_id=session.session_id,
                project=session.project,
                date=session.date,
                instructions=messages,
                message_count=len(messages),
                total_word_count=word_count,
            )
        )

    results.sort(key=lambda s: s.date)

    if save_cache and results:
        _save_to_cache(results)

    return results


def _find_session_file(session_id: str, projects_dir: Path) -> Path | None:
    """Find the JSONL file for a given session ID."""
    for filepath in projects_dir.glob("**/*.jsonl"):
        if filepath.stem == session_id:
            return filepath
    # Fallback: search by session ID inside files
    for filepath in projects_dir.glob("**/*.jsonl"):
        if filepath.name.startswith("agent-"):
            continue
        try:
            with open(filepath) as f:
                first_line = f.readline()
                if first_line:
                    data = json.loads(first_line)
                    if data.get("sessionId") == session_id:
                        return filepath
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _save_to_cache(results: list[SessionInstructions]) -> None:
    """Write extracted instructions to cache for inspection."""
    cache_dir = Path.home() / ".cache" / "claudealytics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "weekly-instructions.json"
    data = [r.model_dump() for r in results]
    with open(cache_path, "w") as f:
        json.dump(data, f, indent=2)
