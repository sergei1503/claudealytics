"""Library & dependency analysis from install commands."""

from __future__ import annotations

import pandas as pd


def compute_library_installs(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Parse install_packages field into per-package counts.

    Returns DF: pkg_manager, package, count
    """
    if tool_calls.empty or "install_packages" not in tool_calls.columns:
        return pd.DataFrame(columns=["pkg_manager", "package", "count"])

    df = tool_calls[tool_calls["install_packages"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["pkg_manager", "package", "count"])

    rows = []
    for pkgs in df["install_packages"]:
        for entry in str(pkgs).split(","):
            entry = entry.strip()
            if ":" in entry:
                mgr, pkg = entry.split(":", 1)
                rows.append({"pkg_manager": mgr, "package": pkg})

    if not rows:
        return pd.DataFrame(columns=["pkg_manager", "package", "count"])

    result = pd.DataFrame(rows)
    result = result.groupby(["pkg_manager", "package"]).size().reset_index(name="count")
    return result.sort_values("count", ascending=False).reset_index(drop=True)


def compute_library_timeline(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Daily install counts by package manager.

    Returns DF: date, pkg_manager, count
    """
    if tool_calls.empty or "install_packages" not in tool_calls.columns:
        return pd.DataFrame(columns=["date", "pkg_manager", "count"])

    df = tool_calls[tool_calls["install_packages"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "pkg_manager", "count"])

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    rows = []
    for _, row in df.iterrows():
        for entry in str(row["install_packages"]).split(","):
            entry = entry.strip()
            if ":" in entry:
                mgr = entry.split(":", 1)[0]
                rows.append({"date": row["date"], "pkg_manager": mgr})

    if not rows:
        return pd.DataFrame(columns=["date", "pkg_manager", "count"])

    result = pd.DataFrame(rows)
    result = result.groupby(["date", "pkg_manager"]).size().reset_index(name="count")
    return result.sort_values("date").reset_index(drop=True)


def compute_library_by_project(tool_calls: pd.DataFrame, session_stats: pd.DataFrame) -> pd.DataFrame:
    """Unique packages installed per project.

    Returns DF: project, packages (comma-separated), install_count
    """
    if tool_calls.empty or "install_packages" not in tool_calls.columns:
        return pd.DataFrame(columns=["project", "packages", "install_count"])

    df = tool_calls[tool_calls["install_packages"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["project", "packages", "install_count"])

    # Map session_id -> project
    if not session_stats.empty and "project" in session_stats.columns:
        proj_map = session_stats.set_index("session_id")["project"].to_dict()
        df["project"] = df["session_id"].map(proj_map).fillna("unknown")
    else:
        df["project"] = "unknown"

    rows = []
    for _, row in df.iterrows():
        for entry in str(row["install_packages"]).split(","):
            entry = entry.strip()
            if ":" in entry:
                pkg = entry.split(":", 1)[1]
                rows.append({"project": row["project"], "package": pkg})

    if not rows:
        return pd.DataFrame(columns=["project", "packages", "install_count"])

    pkg_df = pd.DataFrame(rows)
    result = (
        pkg_df.groupby("project")
        .agg(
            packages=("package", lambda x: ", ".join(sorted(set(x)))),
            install_count=("package", "size"),
        )
        .reset_index()
    )

    return result.sort_values("install_count", ascending=False).reset_index(drop=True)
