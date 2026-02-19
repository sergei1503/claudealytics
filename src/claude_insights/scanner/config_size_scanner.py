"""Measure config file sizes and track history over time."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_insights.models.schemas import (
    ConfigFileMetrics,
    ConfigSizeHistory,
    ConfigSizeSnapshot,
)
from claude_insights.scanner.agent_scanner import AGENTS_DIR
from claude_insights.scanner.claude_md_scanner import CLAUDE_HOME, find_claude_md_files
from claude_insights.scanner.skill_scanner import SKILLS_DIR

CACHE_DIR = Path.home() / ".cache" / "claude-insights"
HISTORY_FILE = CACHE_DIR / "config-sizes.json"


def _classify_claude_md(path: Path) -> tuple[str, str]:
    """Return (file_type, display_name) for a CLAUDE.md file."""
    if path == CLAUDE_HOME / "CLAUDE.md":
        return "global_claude_md", "Global CLAUDE.md"
    return "project_claude_md", str(path.parent.name) + "/CLAUDE.md"


def _measure_file(path: Path, file_type: str, name: str) -> ConfigFileMetrics | None:
    """Measure a single file's size metrics."""
    try:
        content = path.read_text()
        return ConfigFileMetrics(
            path=str(path),
            file_type=file_type,
            name=name,
            lines=content.count("\n") + (1 if content and not content.endswith("\n") else 0),
            bytes=path.stat().st_size,
        )
    except Exception:
        return None


def measure_all_config_files() -> list[ConfigFileMetrics]:
    """Measure all config files (agents, skills, CLAUDE.md files)."""
    metrics: list[ConfigFileMetrics] = []

    # CLAUDE.md files
    for path in find_claude_md_files():
        file_type, name = _classify_claude_md(path)
        m = _measure_file(path, file_type, name)
        if m:
            metrics.append(m)

    # Agent files
    if AGENTS_DIR.exists():
        for filepath in sorted(AGENTS_DIR.glob("*.md")):
            m = _measure_file(filepath, "agent", filepath.stem)
            if m:
                metrics.append(m)

    # Skill files (subdirectories with SKILL.md + standalone .md files)
    if SKILLS_DIR.exists():
        for entry in sorted(SKILLS_DIR.iterdir()):
            if entry.is_dir():
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    m = _measure_file(skill_file, "skill", entry.name)
                    if m:
                        metrics.append(m)
            elif entry.suffix == ".md" and entry.is_file():
                m = _measure_file(entry, "skill", entry.stem)
                if m:
                    metrics.append(m)

    return metrics


def create_snapshot() -> ConfigSizeSnapshot:
    """Create a snapshot of current config file sizes."""
    files = measure_all_config_files()
    return ConfigSizeSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        files=files,
        total_lines=sum(f.lines for f in files),
        total_bytes=sum(f.bytes for f in files),
    )


def load_history() -> ConfigSizeHistory:
    """Load snapshot history from cache."""
    if not HISTORY_FILE.exists():
        return ConfigSizeHistory()
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return ConfigSizeHistory.model_validate(data)
    except Exception:
        return ConfigSizeHistory()


def save_history(history: ConfigSizeHistory) -> None:
    """Save snapshot history to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(history.model_dump_json(indent=2))


def record_snapshot() -> ConfigSizeSnapshot:
    """Create and save a new snapshot, with 1-hour dedup."""
    history = load_history()

    # Dedup: skip if last snapshot is less than 1 hour old
    if history.snapshots:
        last_ts = history.snapshots[-1].timestamp
        try:
            last_dt = datetime.fromisoformat(last_ts)
            now = datetime.now(timezone.utc)
            if (now - last_dt).total_seconds() < 3600:
                return history.snapshots[-1]
        except (ValueError, TypeError):
            pass

    snapshot = create_snapshot()
    history.snapshots.append(snapshot)
    save_history(history)
    return snapshot
