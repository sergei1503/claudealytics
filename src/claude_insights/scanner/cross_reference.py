"""Cross-reference routing tables against actual files.

Compares what CLAUDE.md routing tables reference against what actually
exists in ~/.claude/agents/ and ~/.claude/skills/, finding orphans and
missing references.
"""

from __future__ import annotations

import re
from pathlib import Path

from claude_insights.models.schemas import AgentInfo, ScanIssue, SkillInfo

CLAUDE_HOME = Path.home() / ".claude"

# Placeholder/example values that appear in CLAUDE.md templates
_PLACEHOLDER_PATTERNS = {"<name>", "...", "<something>", "X", "Y", "Z"}


def _is_placeholder(name: str) -> bool:
    """Check if a name is a placeholder/example rather than a real reference."""
    return name in _PLACEHOLDER_PATTERNS or name.startswith("<") or len(name) <= 2


def _extract_routing_agents(content: str) -> list[str]:
    """Extract agent names referenced in CLAUDE.md routing/quick-reference tables.

    Only matches explicit Task(subagent_type="...") patterns to avoid
    false positives from skill names, paths, emails, etc.
    """
    agents = set()

    # Match subagent_type="X" patterns — the authoritative way agents are referenced
    for match in re.finditer(r'subagent_type\s*[=:]\s*["\']([^"\']+)["\']', content):
        agents.add(match.group(1))

    return list(agents)


def _extract_routing_skills(content: str) -> list[str]:
    """Extract skill names referenced in CLAUDE.md routing tables.

    Matches Skill(skill="...") and /skill-name patterns.
    """
    skills = set()

    # Match Skill(skill="X") patterns
    for match in re.finditer(r'[Ss]kill\s*\(\s*skill\s*=\s*["\']([^"\']+)["\']', content):
        skills.add(match.group(1))

    # Match /skill-name patterns (slash commands)
    for match in re.finditer(r'`/([a-z][a-z0-9-]+)`', content):
        skills.add(match.group(1))

    return list(skills)


def cross_reference(
    agents: list[AgentInfo],
    skills: list[SkillInfo],
    claude_md_content: str,
) -> list[ScanIssue]:
    """Check routing references against actual files."""
    issues: list[ScanIssue] = []

    actual_agent_names = {a.name for a in agents}
    actual_skill_names = {s.name for s in skills}

    referenced_agents = [a for a in _extract_routing_agents(claude_md_content) if not _is_placeholder(a)]
    referenced_skills = [s for s in _extract_routing_skills(claude_md_content) if not _is_placeholder(s)]

    # Built-in agents that don't need files
    builtin_agents = {"Explore", "Plan", "general-purpose", "Bash"}

    # Build a normalized lookup: map lowered/hyphenated name to actual agent name
    def _normalize(name: str) -> str:
        return name.lower().replace(" ", "-").replace("_", "-")

    actual_agent_normalized = {_normalize(a.name): a.name for a in agents}
    actual_skill_normalized = {_normalize(s.name): s.name for s in skills}

    # Track which actual agents/skills are matched by references
    matched_agents: set[str] = set()
    matched_skills: set[str] = set()

    # Check for referenced agents that don't exist as files
    for ref in referenced_agents:
        norm = _normalize(ref)
        if ref in actual_agent_names or norm in actual_agent_normalized:
            matched_agents.add(ref)
            if norm in actual_agent_normalized:
                matched_agents.add(actual_agent_normalized[norm])
        elif ref not in builtin_agents and norm not in {_normalize(b) for b in builtin_agents}:
            issues.append(ScanIssue(
                severity="medium",
                category="missing",
                message=f"Agent '{ref}' referenced in CLAUDE.md but no agent file found",
                file=str(CLAUDE_HOME / "CLAUDE.md"),
                suggestion=f"Create {CLAUDE_HOME}/agents/{ref}.md or remove from routing table",
            ))
        else:
            matched_agents.add(ref)

    # Check for agent files not referenced anywhere
    ref_normalized = {_normalize(r) for r in referenced_agents}
    for agent in agents:
        if agent.name in matched_agents or _normalize(agent.name) in ref_normalized:
            continue
        if agent.name in builtin_agents:
            continue
        issues.append(ScanIssue(
            severity="low",
            category="orphan",
            message=f"Agent file '{agent.name}' exists but not referenced in CLAUDE.md",
            file=agent.file_path,
            suggestion="Add to Quick Reference table in CLAUDE.md or remove if unused",
        ))

    # Check for referenced skills that don't exist
    for ref in referenced_skills:
        norm = _normalize(ref)
        if ref in actual_skill_names or norm in actual_skill_normalized:
            matched_skills.add(ref)
            if norm in actual_skill_normalized:
                matched_skills.add(actual_skill_normalized[norm])
        else:
            issues.append(ScanIssue(
                severity="medium",
                category="missing",
                message=f"Skill '{ref}' referenced in CLAUDE.md but no skill directory found",
                file=str(CLAUDE_HOME / "CLAUDE.md"),
                suggestion=f"Create {CLAUDE_HOME}/skills/{ref}/SKILL.md or remove from routing table",
            ))

    # Check for skill directories not referenced
    skill_ref_normalized = {_normalize(r) for r in referenced_skills}
    for skill in skills:
        if skill.name in matched_skills or _normalize(skill.name) in skill_ref_normalized:
            continue
        issues.append(ScanIssue(
            severity="low",
            category="orphan",
            message=f"Skill '{skill.name}' exists but not referenced in CLAUDE.md",
            file=skill.file_path,
            suggestion="Add to Skills table in CLAUDE.md or remove if unused",
        ))

    return issues
