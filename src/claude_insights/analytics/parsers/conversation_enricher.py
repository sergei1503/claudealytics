"""
Efficient extraction of tool usage data from conversation JSONL files.

This module mines historical tool usage (Task/Skill invocations) from the
~/.claude/projects/ conversation archives. Uses a two-tier caching strategy
to avoid repeatedly parsing thousands of JSONL files.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from functools import lru_cache

from pydantic import BaseModel


class ToolUsageStats(BaseModel):
    """Aggregated statistics for tool usage - lightweight data structure."""
    agents: Dict[str, int]  # agent_name -> count
    skills: Dict[str, int]  # skill_name -> count
    daily_agents: Dict[str, Dict[str, int]]  # date -> agent -> count
    daily_skills: Dict[str, Dict[str, int]]  # date -> skill -> count
    total_conversations: int
    date_range: Tuple[str, str]  # (earliest, latest)


class ConversationToolData(BaseModel):
    """Detailed tool execution data for debugging/inspection."""
    agent_executions: List[dict]
    skill_executions: List[dict]


class ConversationEnricher:
    """Efficiently mines tool usage from conversation JSONL files."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.projects_dir = Path.home() / ".claude" / "projects"
        self.cache_dir = cache_dir or Path.home() / ".cache" / "claude-insights"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.index_cache_path = self.cache_dir / "tool-index.json"
        self.stats_cache_path = self.cache_dir / "tool-stats.json"

    def _get_conversation_files(self) -> List[Path]:
        """Get all conversation JSONL files (including agent subdir files) sorted by modification time."""
        if not self.projects_dir.exists():
            return []

        files = []
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                # Recurse to pick up agent-*.jsonl in subdirectories
                files.extend(project_dir.rglob("*.jsonl"))

        return sorted(files, key=lambda f: f.stat().st_mtime)

    def _build_tool_index(self, force_rebuild: bool = False) -> Dict[str, List[int]]:
        """Build index mapping files to line numbers containing tool_use blocks."""
        # Check cache
        if not force_rebuild and self.index_cache_path.exists():
            try:
                with open(self.index_cache_path) as f:
                    cached = json.load(f)
                    # Validate cache is recent (within 1 hour)
                    if cached.get("timestamp", 0) > datetime.now().timestamp() - 3600:
                        return cached.get("index", {})
            except (json.JSONDecodeError, KeyError):
                pass

        index = {}
        for file_path in self._get_conversation_files():
            line_numbers = []
            try:
                with open(file_path) as f:
                    for line_no, line in enumerate(f, 1):
                        if '"tool_use"' in line:  # Quick string check before JSON parse
                            try:
                                data = json.loads(line.strip())
                                # Handle the nested message structure
                                msg = data.get("message", {})
                                if msg.get("type") == "message" and msg.get("role") == "assistant":
                                    content = msg.get("content", [])
                                    if isinstance(content, list):
                                        for block in content:
                                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                                # Check if it's a Task or Skill tool
                                                tool_name = block.get("name", "")
                                                if tool_name in ["Task", "Skill"]:
                                                    line_numbers.append(line_no)
                                                    break
                            except json.JSONDecodeError:
                                continue
            except (IOError, OSError):
                continue

            if line_numbers:
                index[str(file_path)] = line_numbers

        # Save cache
        cache_data = {
            "timestamp": datetime.now().timestamp(),
            "index": index
        }
        with open(self.index_cache_path, "w") as f:
            json.dump(cache_data, f)

        return index

    def mine_tool_usage_stats(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        use_cache: bool = True
    ) -> ToolUsageStats:
        """
        Extract aggregated tool usage statistics.

        Returns pre-computed statistics rather than raw execution arrays,
        keeping memory usage minimal even with thousands of conversations.
        """
        # Check stats cache
        if use_cache and self.stats_cache_path.exists():
            try:
                with open(self.stats_cache_path) as f:
                    cached = json.load(f)
                    if cached.get("timestamp", 0) > datetime.now().timestamp() - 3600:
                        return ToolUsageStats(**cached["stats"])
            except (json.JSONDecodeError, KeyError):
                pass

        # Build index first
        index = self._build_tool_index()

        # Initialize counters
        agent_counts = Counter()
        skill_counts = Counter()
        daily_agents = defaultdict(Counter)
        daily_skills = defaultdict(Counter)

        earliest_date = None
        latest_date = None
        total_conversations = 0

        # Process only files with tool usage
        for file_path_str, line_numbers in index.items():
            file_path = Path(file_path_str)
            if not file_path.exists():
                continue

            total_conversations += 1

            # Extract only the lines we need
            with open(file_path) as f:
                lines = f.readlines()
                for line_no in line_numbers:
                    if line_no <= len(lines):
                        try:
                            data = json.loads(lines[line_no - 1])

                            # Extract timestamp from root level
                            timestamp_str = data.get("timestamp", "")
                            if timestamp_str:
                                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                                date_str = timestamp.date().isoformat()

                                # Update date range
                                if earliest_date is None or date_str < earliest_date:
                                    earliest_date = date_str
                                if latest_date is None or date_str > latest_date:
                                    latest_date = date_str

                                # Apply date filters
                                if date_from and timestamp < date_from:
                                    continue
                                if date_to and timestamp > date_to:
                                    continue

                                # Extract tool usage from nested message
                                msg = data.get("message", {})
                                content = msg.get("content", [])
                                if isinstance(content, list):
                                    for block in content:
                                        if isinstance(block, dict) and block.get("type") == "tool_use":
                                            tool_name = block.get("name", "")

                                            if tool_name == "Task":
                                                # Agent invocation
                                                input_data = block.get("input", {})
                                                agent_type = input_data.get("subagent_type", "unknown")
                                                agent_counts[agent_type] += 1
                                                daily_agents[date_str][agent_type] += 1

                                            elif tool_name == "Skill":
                                                # Skill invocation
                                                input_data = block.get("input", {})
                                                skill_name = input_data.get("skill", "unknown")
                                                skill_counts[skill_name] += 1
                                                daily_skills[date_str][skill_name] += 1

                        except (json.JSONDecodeError, KeyError):
                            continue

        stats = ToolUsageStats(
            agents=dict(agent_counts),
            skills=dict(skill_counts),
            daily_agents={k: dict(v) for k, v in daily_agents.items()},
            daily_skills={k: dict(v) for k, v in daily_skills.items()},
            total_conversations=total_conversations,
            date_range=(earliest_date or "", latest_date or "")
        )

        # Cache the stats
        if use_cache:
            cache_data = {
                "timestamp": datetime.now().timestamp(),
                "stats": stats.model_dump()
            }
            with open(self.stats_cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)

        return stats

    def extract_tool_usage_detailed(self, limit: int = 100) -> ConversationToolData:
        """
        Extract detailed tool execution data for debugging/inspection.

        Use sparingly - this loads actual execution objects into memory.
        """
        index = self._build_tool_index()

        agent_executions = []
        skill_executions = []

        for file_path_str, line_numbers in index.items():
            if len(agent_executions) + len(skill_executions) >= limit:
                break

            file_path = Path(file_path_str)
            if not file_path.exists():
                continue

            # Extract session ID from file path
            session_id = file_path.stem  # UUID part of filename

            with open(file_path) as f:
                lines = f.readlines()
                for line_no in line_numbers:
                    if line_no <= len(lines):
                        try:
                            data = json.loads(lines[line_no - 1])
                            timestamp = data.get("timestamp", "")  # Get timestamp from root
                            msg = data.get("message", {})  # Get nested message
                            content = msg.get("content", [])

                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "tool_use":
                                        tool_name = block.get("name", "")
                                        input_data = block.get("input", {})

                                        if tool_name == "Task":
                                            agent_executions.append({
                                                "timestamp": timestamp,
                                                "session_id": session_id,
                                                "agent_type": input_data.get("subagent_type", "unknown"),
                                                "prompt": input_data.get("prompt", "")[:200],
                                                "status": "unknown"  # Can't determine from invocation alone
                                            })

                                        elif tool_name == "Skill":
                                            skill_executions.append({
                                                "timestamp": timestamp,
                                                "session_id": session_id,
                                                "skill_name": input_data.get("skill", "unknown"),
                                                "args": input_data.get("args", ""),
                                                "status": "unknown"
                                            })

                        except (json.JSONDecodeError, KeyError):
                            continue

        return ConversationToolData(
            agent_executions=agent_executions[:limit//2],
            skill_executions=skill_executions[:limit//2]
        )

    def clear_cache(self):
        """Clear all cache files."""
        if self.index_cache_path.exists():
            self.index_cache_path.unlink()
        if self.stats_cache_path.exists():
            self.stats_cache_path.unlink()


# Convenience functions for direct usage
def mine_tool_usage_stats(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    use_cache: bool = True
) -> ToolUsageStats:
    """Mine aggregated tool usage statistics from conversations."""
    enricher = ConversationEnricher()
    return enricher.mine_tool_usage_stats(date_from, date_to, use_cache)


def extract_tool_usage_detailed(limit: int = 100) -> ConversationToolData:
    """Extract detailed tool execution data for debugging."""
    enricher = ConversationEnricher()
    return enricher.extract_tool_usage_detailed(limit)