"""Display version derived from git state.

Format:
  - dev branch:  dev-2026.03.02-12:59-364af98b
  - other:       2026.03.02-12:59-364af98b
  - fallback:    dev (no git available)
"""

from __future__ import annotations

import subprocess


def get_display_version() -> str:
    """Build display version from git timestamp + short hash."""
    try:
        # Get commit timestamp in UTC
        ts = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=format-local:%Y.%m.%d-%H:%M"],
            capture_output=True,
            text=True,
            timeout=5,
            env={"TZ": "UTC", "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"},
        )
        short_hash = subprocess.run(
            ["git", "log", "-1", "--format=%h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "dev"

    if ts.returncode != 0 or short_hash.returncode != 0:
        return "dev"

    version = f"{ts.stdout.strip()}-{short_hash.stdout.strip()}"
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""

    if branch_name == "dev":
        return f"dev-{version}"
    return version
