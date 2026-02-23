"""Testing discipline analysis from bash test commands."""

from __future__ import annotations

import re

import pandas as pd


_FRAMEWORK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("pytest", re.compile(r"\bpytest\b|\bpython3?\s+-m\s+pytest\b", re.I)),
    ("unittest", re.compile(r"\bpython3?\s+-m\s+unittest\b", re.I)),
    ("jest", re.compile(r"\bjest\b", re.I)),
    ("vitest", re.compile(r"\bvitest\b", re.I)),
    ("mocha", re.compile(r"\bmocha\b", re.I)),
    ("cargo test", re.compile(r"\bcargo\s+test\b", re.I)),
    ("go test", re.compile(r"\bgo\s+test\b", re.I)),
    ("npm test", re.compile(r"\bnpm\s+(?:run\s+)?test\b", re.I)),
    ("yarn test", re.compile(r"\byarn\s+test\b", re.I)),
    ("pnpm test", re.compile(r"\bpnpm\s+test\b", re.I)),
]


def compute_test_frequency(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Daily test command counts.

    Returns DF: date, test_count
    """
    if tool_calls.empty or "is_test_command" not in tool_calls.columns:
        return pd.DataFrame(columns=["date", "test_count"])

    df = tool_calls[tool_calls["is_test_command"] == True].copy()  # noqa: E712
    if df.empty:
        return pd.DataFrame(columns=["date", "test_count"])

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    result = df.groupby("date").size().reset_index(name="test_count")
    return result.sort_values("date").reset_index(drop=True)


def compute_test_frameworks(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Detect which test frameworks are used.

    Returns DF: framework, count
    """
    if tool_calls.empty or "bash_command" not in tool_calls.columns:
        return pd.DataFrame(columns=["framework", "count"])

    df = tool_calls[tool_calls["is_test_command"] == True].copy()  # noqa: E712
    if df.empty:
        return pd.DataFrame(columns=["framework", "count"])

    bash_cmds = df[df["bash_command"].notna()]["bash_command"]
    rows = []
    for fw, pattern in _FRAMEWORK_PATTERNS:
        count = int(bash_cmds.str.contains(pattern, na=False).sum())
        if count > 0:
            rows.append({"framework": fw, "count": count})

    if not rows:
        return pd.DataFrame(columns=["framework", "count"])

    return pd.DataFrame(rows).sort_values("count", ascending=False).reset_index(drop=True)


def compute_test_position(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Whether tests are run before or after Write/Edit within each session.

    Returns DF: position, count
    """
    if tool_calls.empty or "is_test_command" not in tool_calls.columns:
        return pd.DataFrame(columns=["position", "count"])

    before = 0
    after = 0

    for _, grp in tool_calls.sort_values("timestamp").groupby("session_id"):
        saw_write = False
        for _, row in grp.iterrows():
            if row["tool_name"] in ("Write", "Edit"):
                saw_write = True
            if row.get("is_test_command", False):
                if saw_write:
                    after += 1
                else:
                    before += 1

    if before == 0 and after == 0:
        return pd.DataFrame(columns=["position", "count"])

    rows = []
    if before > 0:
        rows.append({"position": "Before code changes", "count": before})
    if after > 0:
        rows.append({"position": "After code changes", "count": after})
    return pd.DataFrame(rows)


def compute_test_by_project(
    tool_calls: pd.DataFrame, session_stats: pd.DataFrame
) -> pd.DataFrame:
    """Test counts per project.

    Returns DF: project, test_count, sessions
    """
    if tool_calls.empty or "is_test_command" not in tool_calls.columns:
        return pd.DataFrame(columns=["project", "test_count", "sessions"])

    df = tool_calls[tool_calls["is_test_command"] == True].copy()  # noqa: E712
    if df.empty:
        return pd.DataFrame(columns=["project", "test_count", "sessions"])

    if not session_stats.empty and "project" in session_stats.columns:
        proj_map = session_stats.set_index("session_id")["project"].to_dict()
        df["project"] = df["session_id"].map(proj_map).fillna("unknown")
    else:
        df["project"] = "unknown"

    result = df.groupby("project").agg(
        test_count=("session_id", "size"),
        sessions=("session_id", "nunique"),
    ).reset_index()

    return result.sort_values("test_count", ascending=False).reset_index(drop=True)
