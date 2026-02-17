"""Scan and parse skill definition files."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from claude_insights.models.schemas import SkillInfo

SKILLS_DIR = Path.home() / ".claude" / "skills"


def parse_skill_file(filepath: Path) -> SkillInfo | None:
    """Parse a SKILL.md file with YAML frontmatter."""
    try:
        post = frontmatter.load(str(filepath))
        meta = post.metadata

        return SkillInfo(
            name=meta.get("name", filepath.parent.name),
            file_path=str(filepath),
            description=meta.get("description", ""),
            user_invocable=meta.get("user_invocable", False),
        )
    except Exception:
        return SkillInfo(
            name=filepath.parent.name,
            file_path=str(filepath),
        )


def scan_skills(skills_dir: Path = SKILLS_DIR) -> list[SkillInfo]:
    """Scan all skill directories and return parsed info."""
    if not skills_dir.exists():
        return []

    skills = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            info = parse_skill_file(skill_file)
            if info:
                skills.append(info)

    return skills
