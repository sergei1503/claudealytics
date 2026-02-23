"""Scan external CLI tool versions and check for updates."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from enum import Enum

from claudealytics.models.schemas import ToolVersionResult


class LatestSource(Enum):
    NPM = "npm"
    PYPI = "pypi"
    GITHUB = "github"


@dataclass
class ToolSpec:
    name: str
    version_cmd: str
    latest_source: LatestSource
    package_name: str


TOOL_REGISTRY: list[ToolSpec] = [
    ToolSpec(
        name="agent-browser",
        version_cmd="agent-browser --version",
        latest_source=LatestSource.NPM,
        package_name="agent-browser",
    ),
    ToolSpec(
        name="claude",
        version_cmd="claude --version",
        latest_source=LatestSource.NPM,
        package_name="@anthropic-ai/claude-code",
    ),
    ToolSpec(
        name="portless",
        version_cmd="portless --version",
        latest_source=LatestSource.NPM,
        package_name="portless",
    ),
    ToolSpec(
        name="pm2",
        version_cmd="pm2 --version",
        latest_source=LatestSource.NPM,
        package_name="pm2",
    ),
    ToolSpec(
        name="uv",
        version_cmd="uv --version",
        latest_source=LatestSource.PYPI,
        package_name="uv",
    ),
    ToolSpec(
        name="gh",
        version_cmd="gh --version",
        latest_source=LatestSource.GITHUB,
        package_name="cli/cli",
    ),
    ToolSpec(
        name="git",
        version_cmd="git --version",
        latest_source=LatestSource.GITHUB,
        package_name="git/git",
    ),
    ToolSpec(
        name="npm",
        version_cmd="npm --version",
        latest_source=LatestSource.NPM,
        package_name="npm",
    ),
    ToolSpec(
        name="node",
        version_cmd="node --version",
        latest_source=LatestSource.GITHUB,
        package_name="nodejs/node",
    ),
]

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:[a-zA-Z0-9._-]*))")


def _extract_version(text: str) -> str | None:
    """Extract a semver-like version string from text."""
    m = _VERSION_RE.search(text)
    return m.group(1) if m else None


def get_installed_version(spec: ToolSpec) -> str | None:
    """Run the local version command and parse the version string."""
    try:
        result = subprocess.run(
            spec.version_cmd.split(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return _extract_version(output)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def get_latest_version(spec: ToolSpec) -> str | None:
    """Query the appropriate registry for the latest version."""
    try:
        if spec.latest_source == LatestSource.NPM:
            result = subprocess.run(
                ["npm", "view", spec.package_name, "version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return _extract_version(result.stdout.strip())

        elif spec.latest_source == LatestSource.PYPI:
            url = f"https://pypi.org/pypi/{spec.package_name}/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("info", {}).get("version")

        elif spec.latest_source == LatestSource.GITHUB:
            url = f"https://api.github.com/repos/{spec.package_name}/releases/latest"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                tag = data.get("tag_name", "")
                return _extract_version(tag)

    except Exception:
        return None

    return None


def _compare_versions(installed: str, latest: str) -> bool:
    """Return True if installed >= latest. Uses packaging if available, else string compare."""
    try:
        from packaging.version import Version
        return Version(installed) >= Version(latest)
    except Exception:
        return installed == latest


def scan_tool_versions() -> list[ToolVersionResult]:
    """Run all tool version checks and return results."""
    results: list[ToolVersionResult] = []

    for spec in TOOL_REGISTRY:
        installed = get_installed_version(spec)
        latest = get_latest_version(spec)

        if installed is None:
            status = "not_installed"
        elif latest is None:
            status = "unknown"
        elif _compare_versions(installed, latest):
            status = "up_to_date"
        else:
            status = "update_available"

        results.append(
            ToolVersionResult(
                name=spec.name,
                installed_version=installed,
                latest_version=latest,
                status=status,
            )
        )

    return results
