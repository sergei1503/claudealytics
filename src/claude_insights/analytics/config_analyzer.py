"""In-depth config analysis: quality, complexity, consistency, and LLM review."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from claude_insights.models.schemas import (
    ConfigAnalysisResult,
    ConfigComplexityMetrics,
    ConfigLLMReview,
    ConfigQualityIssue,
)
from claude_insights.scanner.agent_scanner import AGENTS_DIR, scan_agents
from claude_insights.scanner.claude_md_scanner import CLAUDE_HOME, find_claude_md_files
from claude_insights.scanner.cross_reference import cross_reference
from claude_insights.scanner.skill_scanner import SKILLS_DIR, scan_skills

CACHE_DIR = Path.home() / ".cache" / "claude-insights"
ANALYSIS_CACHE = CACHE_DIR / "config-analysis.json"


# ── Quality Checks ─────────────────────────────────────────────────

def analyze_quality(files: list[tuple[Path, str]]) -> list[ConfigQualityIssue]:
    """Run quality checks on config files."""
    issues: list[ConfigQualityIssue] = []

    for path, content in files:
        path_str = str(path)

        # Agent files: check frontmatter
        if AGENTS_DIR in path.parents:
            try:
                post = frontmatter.loads(content)
                meta = post.metadata
                for field in ("name", "description", "tools"):
                    if not meta.get(field):
                        issues.append(ConfigQualityIssue(
                            file_path=path_str,
                            issue_type="missing_frontmatter",
                            severity="medium",
                            message=f"Agent missing '{field}' in frontmatter",
                            suggestion=f"Add '{field}' to the YAML frontmatter",
                        ))
            except Exception:
                issues.append(ConfigQualityIssue(
                    file_path=path_str,
                    issue_type="missing_frontmatter",
                    severity="high",
                    message="Cannot parse YAML frontmatter",
                    suggestion="Ensure the file starts with valid --- YAML --- frontmatter",
                ))

        # Skill files: check frontmatter
        elif SKILLS_DIR in path.parents:
            try:
                post = frontmatter.loads(content)
                meta = post.metadata
                for field in ("name", "description"):
                    if not meta.get(field):
                        issues.append(ConfigQualityIssue(
                            file_path=path_str,
                            issue_type="missing_frontmatter",
                            severity="medium",
                            message=f"Skill missing '{field}' in frontmatter",
                            suggestion=f"Add '{field}' to the YAML frontmatter",
                        ))
            except Exception:
                issues.append(ConfigQualityIssue(
                    file_path=path_str,
                    issue_type="missing_frontmatter",
                    severity="high",
                    message="Cannot parse YAML frontmatter",
                    suggestion="Ensure the file starts with valid --- YAML --- frontmatter",
                ))

        # Global CLAUDE.md: check required sections
        elif path == CLAUDE_HOME / "CLAUDE.md":
            required = ["Routing Protocol", "Quick Reference", "Stack Profiles"]
            for section in required:
                if section not in content:
                    issues.append(ConfigQualityIssue(
                        file_path=path_str,
                        issue_type="missing_section",
                        severity="medium",
                        message=f"Missing expected section: {section}",
                        suggestion=f"Add a '## {section}' section",
                    ))

        # Project CLAUDE.md: check profile declaration
        elif path.name == "CLAUDE.md":
            if "## Profile" not in content and "**Stack:**" not in content:
                issues.append(ConfigQualityIssue(
                    file_path=path_str,
                    issue_type="missing_section",
                    severity="low",
                    message="Project CLAUDE.md missing stack profile declaration",
                    suggestion="Add a ## Profile section with **Stack:** declaration",
                ))

    return issues


# ── Complexity Metrics ─────────────────────────────────────────────

def _classify_file(path: Path) -> tuple[str, str]:
    """Return (file_type, display_name) for a config file."""
    if AGENTS_DIR in path.parents:
        return "agent", path.stem
    if SKILLS_DIR in path.parents:
        return "skill", path.parent.name
    if path == CLAUDE_HOME / "CLAUDE.md":
        return "global_claude_md", "Global CLAUDE.md"
    return "project_claude_md", str(path.parent.name) + "/CLAUDE.md"


def analyze_complexity(files: list[tuple[Path, str]]) -> list[ConfigComplexityMetrics]:
    """Compute complexity metrics for each config file."""
    results: list[ConfigComplexityMetrics] = []

    for path, content in files:
        lines = content.split("\n")
        line_lengths = [len(line) for line in lines]
        file_type, name = _classify_file(path)

        results.append(ConfigComplexityMetrics(
            file_path=str(path),
            name=name,
            file_type=file_type,
            lines=len(lines),
            avg_line_length=sum(line_lengths) / max(len(line_lengths), 1),
            max_line_length=max(line_lengths) if line_lengths else 0,
            section_count=sum(1 for line in lines if re.match(r"^#{1,3}\s", line)),
            table_count=sum(1 for line in lines if line.strip().startswith("|") and "|" in line[1:]),
            code_block_count=content.count("```") // 2,
            word_count=len(content.split()),
        ))

    return results


# ── Cross-file Consistency ─────────────────────────────────────────

def analyze_consistency(files: list[tuple[Path, str]]) -> list[ConfigQualityIssue]:
    """Check cross-file consistency using existing cross_reference logic."""
    agents = scan_agents()
    skills = scan_skills()

    # Find global CLAUDE.md content
    claude_md_content = ""
    for path, content in files:
        if path == CLAUDE_HOME / "CLAUDE.md":
            claude_md_content = content
            break

    if not claude_md_content:
        return []

    scan_issues = cross_reference(agents, skills, claude_md_content)

    return [
        ConfigQualityIssue(
            file_path=issue.file,
            issue_type="broken_reference" if issue.category == "missing" else "stale_entry",
            severity=issue.severity,
            message=issue.message,
            suggestion=issue.suggestion,
        )
        for issue in scan_issues
    ]


# ── LLM Review ─────────────────────────────────────────────────────

def analyze_with_llm(file_path: Path, content: str) -> ConfigLLMReview:
    """Run LLM review on a single config file using claude CLI."""
    import shutil

    # Check if claude CLI is available
    if not shutil.which("claude"):
        return ConfigLLMReview(
            file_path=str(file_path),
            summary="LLM review skipped: 'claude' CLI not found in PATH",
        )

    prompt = (
        "Analyze this Claude Code configuration file for quality. "
        "Return ONLY valid JSON with these fields:\n"
        '- "clarity_score": number 0-100 (how clear and well-organized)\n'
        '- "redundancy_issues": list of strings (redundant or duplicated content)\n'
        '- "improvement_suggestions": list of strings (specific improvements)\n'
        '- "summary": string (1-2 sentence overall assessment)\n\n'
        f"File: {file_path.name}\n\n"
        f"Content:\n{content[:8000]}"  # Limit content to avoid token issues
    )

    try:
        # Strip CLAUDE* env vars to prevent nested-session detection
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        # claude CLI reads prompt from stdin when piped
        result = subprocess.run(
            ["claude", "--print", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=90,
            env=clean_env,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:200] if result.stderr else "unknown error"
            return ConfigLLMReview(
                file_path=str(file_path),
                summary=f"LLM review failed (exit {result.returncode}): {stderr}",
            )

        response = result.stdout.strip()

        # Try to extract JSON from the response
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            data = json.loads(json_match.group())
            return ConfigLLMReview(
                file_path=str(file_path),
                clarity_score=float(data.get("clarity_score", 0)),
                redundancy_issues=data.get("redundancy_issues", []),
                improvement_suggestions=data.get("improvement_suggestions", []),
                summary=data.get("summary", ""),
            )

        # Fallback: use raw response as summary
        return ConfigLLMReview(
            file_path=str(file_path),
            summary=response[:500] if response else "LLM review returned no output",
        )
    except subprocess.TimeoutExpired:
        return ConfigLLMReview(
            file_path=str(file_path),
            summary="LLM review timed out after 90s",
        )
    except Exception as e:
        return ConfigLLMReview(
            file_path=str(file_path),
            summary=f"LLM review failed: {type(e).__name__}: {str(e)[:100]}",
        )


# ── Full Analysis ──────────────────────────────────────────────────

def _collect_all_config_files() -> list[tuple[Path, str]]:
    """Collect all config files with their content."""
    files: list[tuple[Path, str]] = []

    # CLAUDE.md files
    for path in find_claude_md_files():
        try:
            files.append((path, path.read_text()))
        except Exception:
            pass

    # Agent files
    if AGENTS_DIR.exists():
        for filepath in sorted(AGENTS_DIR.glob("*.md")):
            try:
                files.append((filepath, filepath.read_text()))
            except Exception:
                pass

    # Skill files (subdirectories with SKILL.md + standalone .md files)
    if SKILLS_DIR.exists():
        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    try:
                        files.append((skill_file, skill_file.read_text()))
                    except Exception:
                        pass
            elif skill_dir.suffix == ".md" and skill_dir.is_file():
                try:
                    files.append((skill_dir, skill_dir.read_text()))
                except Exception:
                    pass

    return files


def run_full_analysis(progress_callback=None) -> ConfigAnalysisResult:
    """Run all analysis checks and return combined results."""
    start = time.time()
    files = _collect_all_config_files()

    quality_issues = analyze_quality(files)
    complexity_metrics = analyze_complexity(files)
    consistency_issues = analyze_consistency(files)

    # LLM reviews (only for files > 20 lines)
    llm_reviews: dict[str, ConfigLLMReview] = {}
    reviewable = [(p, c) for p, c in files if c.count("\n") > 20]
    for i, (path, content) in enumerate(reviewable):
        if progress_callback:
            progress_callback((i + 1) / len(reviewable), f"Reviewing {path.name}...")
        review = analyze_with_llm(path, content)
        llm_reviews[str(path)] = review

    result = ConfigAnalysisResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        quality_issues=quality_issues,
        complexity_metrics=complexity_metrics,
        llm_reviews=llm_reviews,
        consistency_issues=consistency_issues,
        analysis_duration_seconds=round(time.time() - start, 1),
    )

    # Cache result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSIS_CACHE.write_text(result.model_dump_json(indent=2))

    return result


def load_cached_analysis() -> ConfigAnalysisResult | None:
    """Load cached analysis result, or None if not available."""
    if not ANALYSIS_CACHE.exists():
        return None
    try:
        data = json.loads(ANALYSIS_CACHE.read_text())
        return ConfigAnalysisResult.model_validate(data)
    except Exception:
        return None
