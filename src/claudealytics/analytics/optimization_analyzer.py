"""
Analyze Claude configuration for optimization opportunities.

This module examines agents, skills, routing rules, and usage patterns
to identify inefficiencies, redundancies, and improvement opportunities.
"""

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from claudealytics.scanner.agent_scanner import scan_agents
from claudealytics.scanner.skill_scanner import scan_skills
from claudealytics.scanner.claude_md_scanner import scan_claude_md_files
from claudealytics.analytics.parsers.conversation_enricher import mine_tool_usage_stats
from claudealytics.analytics.parsers.execution_log_parser import (
    parse_agent_executions,
    parse_skill_executions,
)
from claudealytics.analytics.data_merger import (
    merge_agent_executions,
    merge_skill_executions,
)


class OptimizationIssue(BaseModel):
    """Represents an optimization opportunity."""
    severity: str  # "critical", "warning", "info"
    category: str  # "unused", "duplicate", "inefficient", "indexing"
    title: str
    description: str
    impact: str  # What happens if not fixed
    recommendation: str  # How to fix
    files: List[str] = []  # Affected files


def analyze_unused_agents(agent_info, agent_executions) -> List[OptimizationIssue]:
    """Find agents defined but never invoked."""
    issues = []

    # Build set of executed agent names
    executed_agents = {exec.agent_type for exec in agent_executions}

    for agent in agent_info:
        if agent.name not in executed_agents:
            issues.append(OptimizationIssue(
                severity="info",
                category="unused",
                title=f"Unused agent: {agent.name}",
                description=f"Agent '{agent.name}' is defined but has never been executed",
                impact="Increases cognitive load when Claude scans available agents",
                recommendation="Consider removing if no longer needed, or document why it's kept",
                files=[agent.file_path]
            ))

    return issues


def analyze_unused_skills(skill_info, skill_executions) -> List[OptimizationIssue]:
    """Find skills defined but never invoked."""
    issues = []

    # Build set of executed skill names
    executed_skills = {exec.skill_name for exec in skill_executions}

    for skill in skill_info:
        if skill.name not in executed_skills:
            issues.append(OptimizationIssue(
                severity="info",
                category="unused",
                title=f"Unused skill: {skill.name}",
                description=f"Skill '{skill.name}' is defined but has never been executed",
                impact="Increases cognitive load when Claude scans available skills",
                recommendation="Consider removing if no longer needed, or document why it's kept",
                files=[skill.file_path]
            ))

    return issues


def analyze_duplicate_guidance(claude_md_files) -> List[OptimizationIssue]:
    """Find conflicting or redundant routing rules in CLAUDE.md files."""
    issues = []

    # Track routing patterns across files
    agent_routes = defaultdict(list)  # agent_name -> [(file, pattern)]
    skill_routes = defaultdict(list)  # skill_name -> [(file, pattern)]

    for md_file in claude_md_files:
        md_file = str(md_file)  # Convert Path to string
        content = Path(md_file).read_text()

        # Find agent routing patterns (look for Task(subagent_type="..."))
        agent_pattern = r'Task\(subagent_type="([^"]+)"'
        for match in re.finditer(agent_pattern, content):
            agent_name = match.group(1)
            agent_routes[agent_name].append((md_file, match.group(0)))

        # Find skill routing patterns (look for Skill(skill="..."))
        skill_pattern = r'Skill\(skill="([^"]+)"'
        for match in re.finditer(skill_pattern, content):
            skill_name = match.group(1)
            skill_routes[skill_name].append((md_file, match.group(0)))

    # Check for agents mapped in multiple places
    for agent_name, locations in agent_routes.items():
        if len(locations) > 1:
            files = list(set([loc[0] for loc in locations]))
            issues.append(OptimizationIssue(
                severity="warning",
                category="duplicate",
                title=f"Agent '{agent_name}' routed in multiple files",
                description=f"Agent is referenced in {len(files)} different CLAUDE.md files",
                impact="May cause inconsistent behavior depending on which file Claude reads",
                recommendation="Consolidate routing rules to a single location",
                files=files
            ))

    # Check for skills mapped in multiple places
    for skill_name, locations in skill_routes.items():
        if len(locations) > 1:
            files = list(set([loc[0] for loc in locations]))
            issues.append(OptimizationIssue(
                severity="warning",
                category="duplicate",
                title=f"Skill '{skill_name}' routed in multiple files",
                description=f"Skill is referenced in {len(files)} different CLAUDE.md files",
                impact="May cause inconsistent behavior depending on which file Claude reads",
                recommendation="Consolidate routing rules to a single location",
                files=files
            ))

    return issues


def analyze_agent_efficiency(agent_executions) -> List[OptimizationIssue]:
    """Identify inefficient agent usage patterns."""
    issues = []

    # Track agent performance metrics
    agent_metrics = defaultdict(lambda: {"count": 0, "models": Counter()})

    for execution in agent_executions:
        agent_type = execution.agent_type
        agent_metrics[agent_type]["count"] += 1
        if hasattr(execution, "model") and execution.model:
            agent_metrics[agent_type]["models"][execution.model] += 1

    # Check for expensive model overuse
    for agent_type, metrics in agent_metrics.items():
        model_counts = metrics["models"]
        if model_counts:
            # Check if opus is used for simple tasks
            opus_usage = sum(count for model, count in model_counts.items() if "opus" in model.lower())
            total_usage = sum(model_counts.values())

            if agent_type in ["Explore", "Search", "Grep", "Glob"] and opus_usage > total_usage * 0.5:
                issues.append(OptimizationIssue(
                    severity="warning",
                    category="inefficient",
                    title=f"Expensive model for simple agent: {agent_type}",
                    description=f"Agent '{agent_type}' uses Opus {opus_usage}/{total_usage} times for simple search tasks",
                    impact="Higher costs without meaningful benefit for straightforward operations",
                    recommendation="Use Haiku or Sonnet for search/exploration tasks",
                    files=[]
                ))

    # Check for agents that are rarely successful
    # (This would require tracking success/failure, which isn't in current data)

    return issues


def analyze_skill_overlap(skill_info) -> List[OptimizationIssue]:
    """Find skills with overlapping functionality."""
    issues = []

    # Simple keyword-based overlap detection
    skill_keywords = {}
    for skill in skill_info:
        # Extract keywords from description
        desc_lower = skill.description.lower()
        keywords = set(re.findall(r'\b\w+\b', desc_lower))
        # Filter out common words
        keywords -= {"the", "a", "an", "is", "are", "and", "or", "for", "to", "from", "with", "when", "this", "that", "use"}
        skill_keywords[skill.name] = keywords

    # Find skills with significant overlap
    skills = list(skill_keywords.keys())
    for i, skill1 in enumerate(skills):
        for skill2 in skills[i+1:]:
            keywords1 = skill_keywords[skill1]
            keywords2 = skill_keywords[skill2]

            if len(keywords1) > 5 and len(keywords2) > 5:
                overlap = keywords1 & keywords2
                overlap_ratio = len(overlap) / min(len(keywords1), len(keywords2))

                if overlap_ratio > 0.5:
                    issues.append(OptimizationIssue(
                        severity="info",
                        category="duplicate",
                        title=f"Potential overlap: {skill1} and {skill2}",
                        description=f"Skills share {len(overlap)} keywords ({overlap_ratio:.0%} similarity)",
                        impact="May confuse Claude about which skill to use",
                        recommendation="Consider merging skills or clarifying their distinct purposes",
                        files=[]
                    ))

    return issues


def suggest_indexing_opportunities(conversation_stats) -> List[OptimizationIssue]:
    """Identify what could be pre-indexed for faster access."""
    issues = []

    # Analyze most frequently used agents
    top_agents = sorted(conversation_stats.agents.items(), key=lambda x: x[1], reverse=True)[:5]

    for agent_name, count in top_agents:
        if count > 50:  # High frequency threshold
            if agent_name == "Explore":
                issues.append(OptimizationIssue(
                    severity="info",
                    category="indexing",
                    title=f"High-frequency exploration pattern",
                    description=f"Explore agent used {count} times - consider pre-indexing",
                    impact="Repeated exploration of same codebase patterns",
                    recommendation="Create a codebase index file with common patterns pre-computed",
                    files=[]
                ))
            elif agent_name in ["Search", "Grep"]:
                issues.append(OptimizationIssue(
                    severity="info",
                    category="indexing",
                    title=f"Frequent search operations",
                    description=f"{agent_name} agent used {count} times",
                    impact="Repeated searches for similar patterns",
                    recommendation="Consider creating a search index or using ripgrep with persistent cache",
                    files=[]
                ))

    return issues


def generate_optimization_report(include_conversations: bool = True) -> str:
    """Generate a comprehensive optimization report in Markdown format."""

    # Scan infrastructure
    agents = scan_agents()
    skills = scan_skills()
    claude_md_files, _ = scan_claude_md_files()

    # Get execution data
    log_agents = parse_agent_executions()
    log_skills = parse_skill_executions()

    if include_conversations:
        # Get historical usage stats
        conv_stats = mine_tool_usage_stats(use_cache=True)

        # Create lightweight execution objects for analysis
        conv_agent_execs = [
            type("Exec", (), {
                "agent_type": agent_name,
                "model": "unknown",
                "timestamp": "",
                "session_id": ""
            })()
            for agent_name, count in conv_stats.agents.items()
            for _ in range(min(count, 5))  # Sample for analysis
        ]

        # Merge with log data
        all_agent_execs = log_agents + conv_agent_execs
        all_skill_execs = log_skills

        stats_summary = f"""
### 📊 Usage Statistics

- **Total conversations analyzed:** {conv_stats.total_conversations:,}
- **Date range:** {conv_stats.date_range[0]} to {conv_stats.date_range[1]}
- **Unique agents used:** {len(conv_stats.agents)}
- **Unique skills used:** {len(conv_stats.skills)}
- **Most used agent:** {max(conv_stats.agents.items(), key=lambda x: x[1])[0] if conv_stats.agents else 'N/A'} ({max(conv_stats.agents.values()) if conv_stats.agents else 0} times)
- **Most used skill:** {max(conv_stats.skills.items(), key=lambda x: x[1])[0] if conv_stats.skills else 'N/A'} ({max(conv_stats.skills.values()) if conv_stats.skills else 0} times)
"""
    else:
        all_agent_execs = log_agents
        all_skill_execs = log_skills
        stats_summary = ""

    # Run all analyses
    all_issues = []

    unused_agents = analyze_unused_agents(agents, all_agent_execs)
    all_issues.extend(unused_agents)

    unused_skills = analyze_unused_skills(skills, all_skill_execs)
    all_issues.extend(unused_skills)

    duplicates = analyze_duplicate_guidance(claude_md_files)
    all_issues.extend(duplicates)

    efficiency = analyze_agent_efficiency(all_agent_execs)
    all_issues.extend(efficiency)

    overlaps = analyze_skill_overlap(skills)
    all_issues.extend(overlaps)

    if include_conversations:
        indexing = suggest_indexing_opportunities(conv_stats)
        all_issues.extend(indexing)

    # Group issues by severity
    critical_issues = [i for i in all_issues if i.severity == "critical"]
    warning_issues = [i for i in all_issues if i.severity == "warning"]
    info_issues = [i for i in all_issues if i.severity == "info"]

    # Generate markdown report
    report = f"""# Claude Configuration Optimization Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Executive Summary

Found **{len(all_issues)} optimization opportunities**:
- 🚨 Critical issues: {len(critical_issues)}
- ⚠️ Warnings: {len(warning_issues)}
- ℹ️ Informational: {len(info_issues)}

{stats_summary}

## Optimization Opportunities

"""

    # Add critical issues section
    if critical_issues:
        report += "### 🚨 Critical Issues\n\n"
        report += "_These issues should be addressed immediately as they may cause errors or confusion._\n\n"
        for issue in critical_issues:
            report += f"#### {issue.title}\n\n"
            report += f"**Description:** {issue.description}\n\n"
            report += f"**Impact:** {issue.impact}\n\n"
            report += f"**Recommendation:** {issue.recommendation}\n\n"
            if issue.files:
                report += f"**Files:** {', '.join(issue.files)}\n\n"
            report += "---\n\n"

    # Add warnings section
    if warning_issues:
        report += "### ⚠️ Warnings\n\n"
        report += "_These issues affect efficiency or clarity but aren't blocking._\n\n"
        for issue in warning_issues:
            report += f"#### {issue.title}\n\n"
            report += f"**Description:** {issue.description}\n\n"
            report += f"**Impact:** {issue.impact}\n\n"
            report += f"**Recommendation:** {issue.recommendation}\n\n"
            if issue.files:
                report += f"**Files:** {', '.join(issue.files)}\n\n"
            report += "---\n\n"

    # Add quick wins section (unused items)
    unused_items = [i for i in info_issues if i.category == "unused"]
    if unused_items:
        report += "### ⚡ Quick Wins - Unused Components\n\n"
        report += "_These components can be safely removed to reduce cognitive load._\n\n"

        unused_agent_list = [i for i in unused_items if "agent" in i.title.lower()]
        unused_skill_list = [i for i in unused_items if "skill" in i.title.lower()]

        if unused_agent_list:
            report += "**Unused Agents:**\n"
            for issue in unused_agent_list:
                agent_name = issue.title.replace("Unused agent: ", "")
                report += f"- `{agent_name}` ({issue.files[0] if issue.files else 'unknown location'})\n"
            report += "\n"

        if unused_skill_list:
            report += "**Unused Skills:**\n"
            for issue in unused_skill_list:
                skill_name = issue.title.replace("Unused skill: ", "")
                report += f"- `{skill_name}` ({issue.files[0] if issue.files else 'unknown location'})\n"
            report += "\n"

    # Add other info issues
    other_info = [i for i in info_issues if i.category != "unused"]
    if other_info:
        report += "### 💡 Additional Optimization Opportunities\n\n"
        for issue in other_info:
            report += f"#### {issue.title}\n\n"
            report += f"**Description:** {issue.description}\n\n"
            report += f"**Recommendation:** {issue.recommendation}\n\n"
            report += "---\n\n"

    # Add summary and next steps
    report += f"""## Summary & Next Steps

### Immediate Actions
1. Review and remove unused agents/skills ({len(unused_items)} items)
2. Resolve duplicate routing rules ({len(duplicates)} conflicts)
3. Optimize expensive model usage ({len(efficiency)} inefficiencies)

### Longer-term Improvements
1. Consider merging overlapping skills ({len(overlaps)} potential merges)
2. Implement indexing for frequently accessed patterns
3. Establish naming conventions to prevent future duplicates

### Maintenance Recommendations
- Run `claudealytics optimize` weekly to catch new issues early
- Document why unused components are kept (if intentional)
- Review agent model assignments quarterly for cost optimization

---
_Generated by claudealytics v0.1.0_
"""

    return report