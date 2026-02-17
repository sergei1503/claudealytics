"""
Merge and deduplicate tool execution data from multiple sources.

Combines data from:
1. Execution logs (~/.claude/execution-logs/) - recent, has outcome_preview
2. Conversation archives (~/.claude/projects/) - historical, goes back to Jan 2025
"""

from typing import List, Dict, Tuple, Set
from datetime import datetime

from claude_insights.models.schemas import AgentExecution, SkillExecution


def _create_dedup_key(timestamp: str, session_id: str, name: str) -> str:
    """
    Create a deduplication key from execution metadata.

    Truncates timestamp to second precision to handle minor differences.
    """
    # Truncate to second precision (YYYY-MM-DD HH:MM:SS)
    timestamp_truncated = timestamp[:19] if len(timestamp) >= 19 else timestamp
    return f"{timestamp_truncated}|{session_id}|{name}"


def merge_agent_executions(
    log_execs: List[AgentExecution],
    conv_execs: List[dict]
) -> List[AgentExecution]:
    """
    Merge agent executions from logs and conversations, deduplicating.

    Execution log entries take precedence as they have outcome_preview.
    """
    # Track seen executions to avoid duplicates
    seen_keys: Set[str] = set()
    merged: List[AgentExecution] = []

    # Add all log executions first (they have priority)
    for exec in log_execs:
        key = _create_dedup_key(exec.timestamp, exec.session_id, exec.agent_type)
        seen_keys.add(key)
        merged.append(exec)

    # Add conversation executions that aren't duplicates
    for conv_exec in conv_execs:
        # Convert dict to AgentExecution
        agent_exec = AgentExecution(
            timestamp=conv_exec["timestamp"],
            session_id=conv_exec["session_id"],
            agent_type=conv_exec["agent_type"],
            prompt=conv_exec.get("prompt", "")[:500],  # Truncate long prompts
            outcome_preview="",  # Not available from conversations
            status=conv_exec.get("status", "unknown"),
            total_tokens=0,  # Not available from conversations
            model=conv_exec.get("model", "unknown")
        )

        key = _create_dedup_key(agent_exec.timestamp, agent_exec.session_id, agent_exec.agent_type)
        if key not in seen_keys:
            seen_keys.add(key)
            merged.append(agent_exec)

    # Sort by timestamp (newest first)
    merged.sort(key=lambda x: x.timestamp, reverse=True)

    return merged


def merge_skill_executions(
    log_execs: List[SkillExecution],
    conv_execs: List[dict]
) -> List[SkillExecution]:
    """
    Merge skill executions from logs and conversations, deduplicating.

    Execution log entries take precedence as they have outcome_preview.
    """
    # Track seen executions to avoid duplicates
    seen_keys: Set[str] = set()
    merged: List[SkillExecution] = []

    # Add all log executions first (they have priority)
    for exec in log_execs:
        key = _create_dedup_key(exec.timestamp, exec.session_id, exec.skill_name)
        seen_keys.add(key)
        merged.append(exec)

    # Add conversation executions that aren't duplicates
    for conv_exec in conv_execs:
        # Convert dict to SkillExecution
        skill_exec = SkillExecution(
            timestamp=conv_exec["timestamp"],
            session_id=conv_exec["session_id"],
            skill_name=conv_exec["skill_name"],
            args=conv_exec.get("args", ""),
            outcome_preview="",  # Not available from conversations
            status=conv_exec.get("status", "unknown")
        )

        key = _create_dedup_key(skill_exec.timestamp, skill_exec.session_id, skill_exec.skill_name)
        if key not in seen_keys:
            seen_keys.add(key)
            merged.append(skill_exec)

    # Sort by timestamp (newest first)
    merged.sort(key=lambda x: x.timestamp, reverse=True)

    return merged