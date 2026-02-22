"""Scan and parse skill definition files."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from claudealytics.models.schemas import SkillInfo

SKILLS_DIR = Path.home() / ".claude" / "skills"


def _default_name(filepath: Path) -> str:
    """Derive a default skill name from the file path.

    For SKILL.md inside a directory, use the directory name.
    For standalone .md files, use the file stem.
    """
    if filepath.name == "SKILL.md":
        return filepath.parent.name
    return filepath.stem


def parse_skill_file(filepath: Path) -> SkillInfo | None:
    """Parse a SKILL.md or standalone .md skill file with YAML frontmatter."""
    default = _default_name(filepath)
    try:
        post = frontmatter.load(str(filepath))
        meta = post.metadata

        return SkillInfo(
            name=meta.get("name", default),
            file_path=str(filepath),
            description=meta.get("description", ""),
            user_invocable=meta.get("user_invocable", False),
        )
    except Exception:
        return SkillInfo(
            name=default,
            file_path=str(filepath),
        )


def scan_skills(skills_dir: Path = SKILLS_DIR) -> list[SkillInfo]:
    """Scan all skill directories and standalone .md files."""
    if not skills_dir.exists():
        return []

    skills = []
    seen_names: set[str] = set()

    # Scan subdirectories with SKILL.md
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            info = parse_skill_file(skill_file)
            if info:
                skills.append(info)
                seen_names.add(info.name)

    # Scan standalone .md files directly in the skills dir
    for md_file in sorted(skills_dir.glob("*.md")):
        if not md_file.is_file():
            continue
        stem = md_file.stem
        if stem in seen_names:
            continue
        info = parse_skill_file(md_file)
        if info:
            skills.append(info)
            seen_names.add(info.name)

    return skills
