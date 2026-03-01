"""Sample human-assistant turn pairs from conversation JSONL files.

Extracts representative message pairs for LLM-based profile scoring.
Uses strategic sampling to capture beginning, middle, and end of conversations.
"""

from __future__ import annotations

import json
from pathlib import Path


def _get_all_jsonl_files() -> list[Path]:
    """Get all JSONL files from ~/.claude/projects/."""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []
    files = []
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            files.extend(project_dir.rglob("*.jsonl"))
    return files


def _extract_text(content) -> str:
    """Extract text from various message content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return ""


def sample_turns(session_id: str, max_pairs: int = 10, max_chars: int = 1500) -> list[dict]:
    """Sample human-assistant turn pairs for a given session_id.

    Returns list of dicts with keys: human, assistant, turn_index.

    Sampling strategy:
    - <=8 pairs: use all
    - <=20 pairs: first 2, last 2, 4 evenly spaced from middle
    - >20 pairs: first 2, last 2, 6 evenly spaced from middle
    """
    # Find the JSONL file containing this session
    all_files = _get_all_jsonl_files()
    target_file = None
    for f in all_files:
        if f.stem == session_id or session_id in f.stem:
            target_file = f
            break

    if not target_file:
        # Search inside files for matching session_id
        for f in all_files:
            try:
                with open(f) as fh:
                    first_line = fh.readline()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("sessionId") == session_id:
                            target_file = f
                            break
            except (json.JSONDecodeError, OSError):
                continue

    if not target_file:
        return []

    # Extract all human-assistant pairs
    pairs = []
    messages = []
    try:
        with open(target_file) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role")
                if role in ("human", "user"):
                    text = _extract_text(entry.get("message", entry.get("content", "")))
                    if text.strip():
                        messages.append({"role": "human", "text": text})
                elif role == "assistant":
                    text = _extract_text(entry.get("message", entry.get("content", "")))
                    if text.strip():
                        messages.append({"role": "assistant", "text": text})
    except OSError:
        return []

    # Build pairs from consecutive human→assistant messages
    i = 0
    while i < len(messages) - 1:
        if messages[i]["role"] == "human" and messages[i + 1]["role"] == "assistant":
            pairs.append(
                {
                    "human": messages[i]["text"][:max_chars],
                    "assistant": messages[i + 1]["text"][:max_chars],
                    "turn_index": len(pairs),
                }
            )
            i += 2
        else:
            i += 1

    if not pairs:
        return []

    # Apply sampling strategy
    total = len(pairs)
    if total <= max_pairs:
        return pairs

    if total <= 20:
        middle_count = 4
    else:
        middle_count = 6

    # First 2 + last 2 + middle samples
    first = pairs[:2]
    last = pairs[-2:]

    middle_pool = pairs[2:-2]
    if middle_pool and middle_count > 0:
        step = max(1, len(middle_pool) // (middle_count + 1))
        middle = [middle_pool[i * step] for i in range(1, middle_count + 1) if i * step < len(middle_pool)]
    else:
        middle = []

    sampled = first + middle + last
    # Re-index
    for idx, pair in enumerate(sampled):
        pair["turn_index"] = idx

    return sampled[:max_pairs]
