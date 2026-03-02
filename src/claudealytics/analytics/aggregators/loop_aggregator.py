"""Agentic loop analysis: tool sequences, error recovery, discipline."""

from __future__ import annotations

from collections import Counter

import pandas as pd

_READ_TOOLS = frozenset({"Read", "Grep", "Glob", "WebFetch", "WebSearch"})
_EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


def _classify_chain(tool_list: list[str]) -> str:
    """Classify a multi-tool sequence by its dominant usage pattern."""
    reads = sum(1 for t in tool_list if t in _READ_TOOLS)
    edits = sum(1 for t in tool_list if t in _EDIT_TOOLS)

    if reads == 0 and edits == 0:
        return "other"

    first_edit_idx = next((i for i, t in enumerate(tool_list) if t in _EDIT_TOOLS), None)
    first_read_idx = next((i for i, t in enumerate(tool_list) if t in _READ_TOOLS), None)

    if edits >= 2 and reads == 0:
        return "blind-editing"
    if first_read_idx is not None and (first_edit_idx is None or first_read_idx < first_edit_idx):
        return "investigation-first"
    if first_edit_idx is not None and (first_read_idx is None or first_edit_idx < first_read_idx):
        return "edit-first"
    return "mixed"


def compute_tool_sequences(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Top N most frequent consecutive tool-call pairs per assistant turn.

    Single-tool turns are excluded — only turns with 2+ tools produce pairs.
    Includes a chain_type column classifying each turn's overall pattern.
    """
    if tool_calls.empty or "message_uuid" not in tool_calls.columns:
        return pd.DataFrame(columns=["pattern", "count", "chain_type"])

    pair_counts: Counter = Counter()
    pair_chain_type: dict[str, str] = {}

    for _, turn_tools in tool_calls.groupby("message_uuid")["tool_name"]:
        tool_list = list(turn_tools)
        if len(tool_list) < 2:
            continue
        chain_type = _classify_chain(tool_list)
        for i in range(len(tool_list) - 1):
            pair = f"{tool_list[i]} → {tool_list[i + 1]}"
            pair_counts[pair] += 1
            # First chain type wins for each pattern key
            pair_chain_type.setdefault(pair, chain_type)

    top = pair_counts.most_common(30)
    rows = [{"pattern": p, "count": c, "chain_type": pair_chain_type.get(p, "other")} for p, c in top]
    return pd.DataFrame(rows, columns=["pattern", "count", "chain_type"])


def compute_error_recovery(tool_calls: pd.DataFrame, error_results: pd.DataFrame) -> pd.DataFrame:
    """Per error: what tool follows the failed tool.

    If tool_calls has a tool_use_id column, matches errors directly.
    Otherwise falls back to session-level heuristic: any tool called immediately
    after a known-errored tool name within the same session.
    """
    if error_results.empty or tool_calls.empty:
        return pd.DataFrame(columns=["failed_tool", "recovery_action", "count"])

    recovery_counts: Counter = Counter()

    has_tool_use_id = "tool_use_id" in tool_calls.columns and "tool_use_id" in error_results.columns

    if has_tool_use_id:
        # Build a lookup: tool_use_id → next tool_name in the same session
        required_cols = {"tool_use_id", "session_id", "timestamp", "tool_name"}
        if required_cols.issubset(tool_calls.columns):
            for _, session_df in tool_calls.groupby("session_id"):
                session_df = session_df.sort_values("timestamp").reset_index(drop=True)
                for i in range(len(session_df) - 1):
                    current_id = session_df.at[i, "tool_use_id"]
                    if current_id in set(error_results["tool_use_id"].dropna()):
                        failed_tool = session_df.at[i, "tool_name"]
                        recovery_tool = session_df.at[i + 1, "tool_name"]
                        recovery_counts[(failed_tool, recovery_tool)] += 1
    else:
        # Heuristic fallback: use error_results tool names; look for them in session sequences
        error_tool_names: set[str] = set()
        if "tool_name" in error_results.columns:
            error_tool_names = set(error_results["tool_name"].dropna())

        if not error_tool_names or "session_id" not in tool_calls.columns:
            return pd.DataFrame(columns=["failed_tool", "recovery_action", "count"])

        for _, session_df in tool_calls.groupby("session_id"):
            sort_col = "timestamp" if "timestamp" in session_df.columns else session_df.columns[0]
            session_df = session_df.sort_values(sort_col).reset_index(drop=True)
            tool_list = session_df["tool_name"].tolist()
            for i in range(len(tool_list) - 1):
                if tool_list[i] in error_tool_names:
                    recovery_counts[(tool_list[i], tool_list[i + 1])] += 1

    if not recovery_counts:
        return pd.DataFrame(columns=["failed_tool", "recovery_action", "count"])

    rows = [
        {"failed_tool": k[0], "recovery_action": k[1], "count": v}
        for k, v in recovery_counts.most_common()
    ]
    return pd.DataFrame(rows, columns=["failed_tool", "recovery_action", "count"])


def compute_discipline(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: read-before-write discipline percentage."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[["session_id", "date", "project", "writes_with_prior_read_count", "writes_total_count"]].copy()
    df["read_before_write_pct"] = (
        (df["writes_with_prior_read_count"] / df["writes_total_count"] * 100)
        .where(df["writes_total_count"] > 0, 0)
        .round(1)
    )
    return df


def compute_daily_discipline(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per day: aggregate read-before-write discipline."""
    if session_stats.empty:
        return pd.DataFrame()

    df = session_stats[["date", "writes_with_prior_read_count", "writes_total_count"]].copy()
    daily = df.groupby("date").sum().reset_index()
    daily["read_before_write_pct"] = (
        (daily["writes_with_prior_read_count"] / daily["writes_total_count"] * 100)
        .where(daily["writes_total_count"] > 0, 0)
        .round(1)
    )
    return daily


def _normalize_tool_name(name: str) -> str:
    """Consolidate MCP tool names into a readable label."""
    if name.startswith("mcp_"):
        parts = name.split("_")
        if len(parts) >= 3:
            return f"{parts[1].title()} (MCP)"
    return name


def compute_tool_type_daily(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Per day x tool type: call count for stacked area chart."""
    if tool_calls.empty or "timestamp" not in tool_calls.columns:
        return pd.DataFrame()

    df = tool_calls.copy()
    df["date"] = df["timestamp"].dt.date
    df["tool_name"] = df["tool_name"].apply(_normalize_tool_name)
    pivot = df.groupby(["date", "tool_name"]).size().reset_index(name="count")
    return pivot
