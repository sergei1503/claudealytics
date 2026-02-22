"""Scan and validate CLAUDE.md files across the configuration ecosystem."""

from __future__ import annotations

import re
from pathlib import Path

from claudealytics.models.schemas import ScanIssue

CLAUDE_HOME = Path.home() / ".claude"

# Known project paths from the Base_Vault CLAUDE.md
KNOWN_PROJECT_REPOS = [
    Path.home() / "repos" / "sites" / "guilder",
    Path.home() / "repos" / "sites" / "nomemoo",
    Path.home() / "repos" / "ai-call-moderator",
    Path.home() / "repos" / "financial-planner",
    Path.home() / "repos" / "vierally",
    Path.home() / "repos" / "zen-math-prototype",
    Path.home() / "repos" / "domain-accelerator",
    Path.home() / "repos" / "scientific_research",
    Path.home() / "Documents" / "Base_Vault",
]


def find_claude_md_files() -> list[Path]:
    """Find all CLAUDE.md files in the ecosystem."""
    files = []

    # Global CLAUDE.md
    global_md = CLAUDE_HOME / "CLAUDE.md"
    if global_md.exists():
        files.append(global_md)

    # Per-project CLAUDE.md files
    for repo in KNOWN_PROJECT_REPOS:
        candidates = [
            repo / ".claude" / "CLAUDE.md",
            repo / "CLAUDE.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                files.append(candidate)

    return files


def _extract_table_entries(content: str, header_pattern: str) -> list[str]:
    """Extract entries from a markdown table following a header."""
    lines = content.split("\n")
    in_table = False
    entries = []

    for line in lines:
        if header_pattern.lower() in line.lower():
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("|") and not line.strip().startswith("|---"):
                # Extract first column after the leading |
                cols = [c.strip() for c in line.split("|") if c.strip()]
                if cols:
                    # Clean backticks and formatting
                    entry = cols[0].strip("`").strip("*").strip()
                    if entry and entry.lower() not in ("name", "agent", "skill", "profile", "tool", "request", "role"):
                        entries.append(entry)
            elif not line.strip().startswith("|") and line.strip():
                in_table = False

    return entries


def scan_claude_md_files() -> tuple[list[Path], list[ScanIssue]]:
    """Scan all CLAUDE.md files and check for issues."""
    files = find_claude_md_files()
    issues: list[ScanIssue] = []

    for filepath in files:
        try:
            content = filepath.read_text()
        except Exception:
            issues.append(ScanIssue(
                severity="high",
                category="error",
                message=f"Cannot read CLAUDE.md file",
                file=str(filepath),
            ))
            continue

        # Check for required sections in global CLAUDE.md
        if filepath == CLAUDE_HOME / "CLAUDE.md":
            required_sections = ["Stack Profiles", "Routing Protocol", "Quick Reference"]
            for section in required_sections:
                if section not in content:
                    issues.append(ScanIssue(
                        severity="medium",
                        category="missing",
                        message=f"Missing expected section: {section}",
                        file=str(filepath),
                        suggestion=f"Add a '## {section}' section",
                    ))

        # Check for profile declaration in project CLAUDE.md files
        if filepath != CLAUDE_HOME / "CLAUDE.md":
            if "## Profile" not in content and "**Stack:**" not in content:
                issues.append(ScanIssue(
                    severity="low",
                    category="inconsistency",
                    message="Project CLAUDE.md missing stack profile declaration",
                    file=str(filepath),
                    suggestion="Add a ## Profile section with **Stack:** declaration",
                ))

    return files, issues
