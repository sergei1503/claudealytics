"""In-depth config analysis: quality, complexity, consistency, and LLM review."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import frontmatter
import yaml

from claudealytics.models.schemas import (
    ConfigAnalysisResult,
    ConfigComplexityMetrics,
    ConfigLLMReview,
    ConfigQualityIssue,
)
from claudealytics.scanner.agent_scanner import AGENTS_DIR, scan_agents
from claudealytics.scanner.claude_md_scanner import CLAUDE_HOME, find_claude_md_files
from claudealytics.scanner.cross_reference import cross_reference
from claudealytics.scanner.skill_scanner import SKILLS_DIR, scan_skills

CACHE_DIR = Path.home() / ".cache" / "claudealytics"
ANALYSIS_CACHE = CACHE_DIR / "config-analysis.json"
LOG_FILE = CACHE_DIR / "llm-review.log"
DEBUG_DIR = CACHE_DIR / "llm-debug"
BATCH_SIZE = 8
DEFAULT_MODEL = "claude-sonnet-4-6"

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    """Lazy-init a rotating file logger for LLM review diagnostics."""
    global _logger
    if _logger is not None:
        return _logger

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("claudealytics.llm_review")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = RotatingFileHandler(
            str(LOG_FILE), maxBytes=1_000_000, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    _logger = logger
    return _logger


def _clean_debug_dir() -> None:
    """Remove old debug files before a new run."""
    if DEBUG_DIR.exists():
        for f in DEBUG_DIR.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def _save_debug_response(batch_index: int, stdout: str, stderr: str) -> None:
    """Persist raw LLM output for a batch (capped at 50K chars)."""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = DEBUG_DIR / f"batch_{batch_index}_{ts}.json"
        payload = json.dumps({
            "batch_index": batch_index,
            "timestamp": ts,
            "stdout": stdout[:50_000],
            "stderr": stderr[:50_000] if stderr else "",
        }, indent=2)
        path.write_text(payload)
    except Exception:
        pass


# ── Quality Checks ─────────────────────────────────────────────────

def _parse_frontmatter_robust(content: str) -> dict | None:
    """Parse YAML frontmatter with fallback for complex content.

    Returns:
        dict with metadata (may be empty if no frontmatter), or
        None on genuine parse failure.
    """
    # Try python-frontmatter first
    try:
        post = frontmatter.loads(content)
        return post.metadata
    except Exception:
        pass

    # Fallback: regex-extract the --- block and parse with yaml.safe_load
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if match:
        try:
            meta = yaml.safe_load(match.group(1))
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return None

    # No frontmatter at all
    return {}


def analyze_quality(files: list[tuple[Path, str]]) -> list[ConfigQualityIssue]:
    """Run quality checks on config files."""
    issues: list[ConfigQualityIssue] = []

    for path, content in files:
        path_str = str(path)

        # Agent files: check frontmatter
        if AGENTS_DIR in path.parents:
            meta = _parse_frontmatter_robust(content)
            if meta is None:
                issues.append(ConfigQualityIssue(
                    file_path=path_str,
                    issue_type="missing_frontmatter",
                    severity="high",
                    message="Cannot parse YAML frontmatter",
                    suggestion="Ensure the file starts with valid --- YAML --- frontmatter",
                ))
            else:
                for field in ("name", "description"):
                    if not meta.get(field):
                        issues.append(ConfigQualityIssue(
                            file_path=path_str,
                            issue_type="missing_frontmatter",
                            severity="medium",
                            message=f"Agent missing '{field}' in frontmatter",
                            suggestion=f"Add '{field}' to the YAML frontmatter",
                        ))

        # Skill files: check frontmatter (optional — no issue if absent)
        elif SKILLS_DIR in path.parents:
            meta = _parse_frontmatter_robust(content)
            if meta is None:
                issues.append(ConfigQualityIssue(
                    file_path=path_str,
                    issue_type="missing_frontmatter",
                    severity="high",
                    message="Cannot parse YAML frontmatter",
                    suggestion="Ensure the file starts with valid --- YAML --- frontmatter",
                ))
            elif meta:
                # Frontmatter exists but may be missing optional fields
                for field in ("name", "description"):
                    if not meta.get(field):
                        issues.append(ConfigQualityIssue(
                            file_path=path_str,
                            issue_type="missing_frontmatter",
                            severity="low",
                            message=f"Skill missing '{field}' in frontmatter (optional)",
                            suggestion=f"Consider adding '{field}' to the YAML frontmatter",
                        ))
            # meta == {} means no frontmatter at all — skip (by design for skills)

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
        if issue.category != "orphan"
    ]


# ── LLM Review ─────────────────────────────────────────────────────

def _review_batch(
    batch_files: list[tuple[Path, str]],
    batch_index: int,
    include_cross_file: bool,
    model: str,
    logger: logging.Logger,
) -> tuple[dict[str, ConfigLLMReview], list[str]]:
    """Review a single batch of files via the claude CLI.

    Returns: (reviews dict for this batch, cross_file_observations list)
    """
    file_blocks = "\n\n".join(
        f'<file name="{p.name}" path="{p}">\n{content}\n</file>'
        for p, content in batch_files
    )

    cross_file_section = ""
    if include_cross_file:
        cross_file_section = '  "cross_file_observations": ["observation 1", "observation 2"]\n'
    else:
        cross_file_section = '  "cross_file_observations": []\n'

    prompt = (
        "You are reviewing Claude Code configuration files to identify quality issues.\n"
        f"This is batch {batch_index + 1}. Analyze ALL the following files. Look for:\n"
        "- Per-file quality (clarity, redundancy, improvement opportunities)\n"
        + ("- Cross-file patterns: overlap, contradictions, consolidation opportunities\n" if include_cross_file else "")
        + "\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "files": {\n'
        '    "<exact file path as shown>": {\n'
        '      "clarity_score": <number 0-100>,\n'
        '      "redundancy_issues": ["..."],\n'
        '      "improvement_suggestions": ["..."],\n'
        '      "summary": "1-2 sentence assessment"\n'
        "    }\n"
        "  },\n"
        + cross_file_section
        + "}\n\n"
        "Files to analyze:\n\n"
        f"{file_blocks}"
    )

    prompt_size = len(prompt)
    file_names = [p.name for p, _ in batch_files]
    logger.info(
        "Batch %d: %d files, prompt_size=%d chars, files=%s",
        batch_index, len(batch_files), prompt_size, file_names,
    )

    t0 = time.time()

    try:
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        cmd = ["claude", "--print", "--allowedTools", "", "--model", model]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            env=clean_env,
        )

        elapsed = round(time.time() - t0, 1)
        response = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""

        _save_debug_response(batch_index, response, stderr)

        logger.info(
            "Batch %d: elapsed=%.1fs, response_size=%d chars, returncode=%d",
            batch_index, elapsed, len(response), result.returncode,
        )

        if result.returncode != 0:
            detail = (stderr or response or "unknown error")[:300]
            logger.error("Batch %d failed (exit %d): %s", batch_index, result.returncode, detail)
            error_reviews = {
                str(p): ConfigLLMReview(
                    file_path=str(p),
                    summary=f"LLM review failed (batch {batch_index}, exit {result.returncode}): {detail}",
                )
                for p, _ in batch_files
            }
            return error_reviews, []

        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            logger.warning(
                "Batch %d: no JSON found in response (first 200 chars: %s)",
                batch_index, response[:200],
            )
            fallback = {
                str(p): ConfigLLMReview(
                    file_path=str(p),
                    summary=response[:300] if response else "LLM review returned no JSON",
                )
                for p, _ in batch_files
            }
            return fallback, []

        data = json.loads(json_match.group())
        file_data: dict = data.get("files", {})
        cross_obs: list[str] = data.get("cross_file_observations", []) if include_cross_file else []

        logger.info(
            "Batch %d: LLM returned keys=%s", batch_index, list(file_data.keys()),
        )

        reviews: dict[str, ConfigLLMReview] = {}
        matched = 0
        unmatched = 0
        for path, _ in batch_files:
            entry = file_data.get(str(path)) or file_data.get(path.name) or {}
            if entry:
                matched += 1
            else:
                unmatched += 1
            reviews[str(path)] = ConfigLLMReview(
                file_path=str(path),
                clarity_score=float(entry.get("clarity_score", 0)),
                redundancy_issues=entry.get("redundancy_issues", []),
                improvement_suggestions=entry.get("improvement_suggestions", []),
                summary=entry.get("summary", "No summary returned"),
            )

        logger.info(
            "Batch %d: matched=%d, unmatched=%d", batch_index, matched, unmatched,
        )

        return reviews, cross_obs

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - t0, 1)
        logger.error("Batch %d: timed out after %.1fs", batch_index, elapsed)
        timeout_reviews = {
            str(p): ConfigLLMReview(
                file_path=str(p),
                summary=f"LLM review timed out (batch {batch_index}) after 180s",
            )
            for p, _ in batch_files
        }
        return timeout_reviews, []
    except Exception as e:
        logger.error("Batch %d: exception %s: %s", batch_index, type(e).__name__, str(e)[:200])
        err_reviews = {
            str(p): ConfigLLMReview(
                file_path=str(p),
                summary=f"LLM review failed (batch {batch_index}): {type(e).__name__}: {str(e)[:100]}",
            )
            for p, _ in batch_files
        }
        return err_reviews, []


def analyze_all_with_llm(
    files: list[tuple[Path, str]],
    progress_callback=None,
) -> tuple[dict[str, ConfigLLMReview], list[str]]:
    """Batched LLM review of all config files using claude CLI.

    Files are split into batches of BATCH_SIZE and reviewed sequentially.
    Full file content is sent (no truncation).

    Returns: (llm_reviews dict, cross_file_observations list)
    """
    import shutil

    logger = _get_logger()

    if not shutil.which("claude"):
        skip_msg = "LLM review skipped: 'claude' CLI not found in PATH"
        logger.warning(skip_msg)
        return {str(p): ConfigLLMReview(file_path=str(p), summary=skip_msg) for p, _ in files}, []

    if not files:
        return {}, []

    model = os.environ.get("CLAUDE_INSIGHTS_MODEL", DEFAULT_MODEL)
    num_batches = (len(files) + BATCH_SIZE - 1) // BATCH_SIZE

    logger.info(
        "=== LLM Review started: %d files, batch_size=%d, batches=%d, model=%s ===",
        len(files), BATCH_SIZE, num_batches, model,
    )

    _clean_debug_dir()

    all_reviews: dict[str, ConfigLLMReview] = {}
    all_cross_obs: list[str] = []
    t_start = time.time()

    for i in range(num_batches):
        batch_start = i * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(files))
        batch_files = files[batch_start:batch_end]

        if progress_callback:
            progress_callback(
                i / num_batches,
                f"Batch {i + 1}/{num_batches}: reviewing {len(batch_files)} files...",
            )

        reviews, cross_obs = _review_batch(
            batch_files=batch_files,
            batch_index=i,
            include_cross_file=(i == 0),
            model=model,
            logger=logger,
        )

        all_reviews.update(reviews)
        all_cross_obs.extend(cross_obs)

    total_elapsed = round(time.time() - t_start, 1)
    success_count = sum(1 for v in all_reviews.values() if v.clarity_score > 0)
    logger.info(
        "=== LLM Review complete: %d/%d files scored, %.1fs total ===",
        success_count, len(files), total_elapsed,
    )

    if progress_callback:
        progress_callback(1.0, "LLM review complete")

    return all_reviews, all_cross_obs


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

    # LLM reviews (only for files > 20 lines) — batched calls
    reviewable = [(p, c) for p, c in files if c.count("\n") > 20]
    if progress_callback:
        progress_callback(0.05, f"Running LLM review on {len(reviewable)} files...")

    llm_reviews, cross_file_observations = analyze_all_with_llm(
        reviewable, progress_callback=progress_callback,
    )

    result = ConfigAnalysisResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        quality_issues=quality_issues,
        complexity_metrics=complexity_metrics,
        llm_reviews=llm_reviews,
        consistency_issues=consistency_issues,
        cross_file_observations=cross_file_observations,
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
