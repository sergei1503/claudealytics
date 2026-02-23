"""File activity analysis: hot files, co-access patterns, change volume."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import pandas as pd


def compute_files_per_session(session_stats: pd.DataFrame) -> pd.DataFrame:
    """Per session: files read/written/edited, total unique files."""
    if session_stats.empty:
        return pd.DataFrame()

    return session_stats[
        ["session_id", "date", "project", "total_reads", "total_writes", "total_edits", "unique_files_touched"]
    ].copy()


def compute_hot_files(tool_calls: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """Top N most-accessed files with read/write/edit breakdowns."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["file_path", "total", "reads", "writes", "edits"])

    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["file_path", "total", "reads", "writes", "edits"])

    reads = df[df["tool_name"].isin(["Read", "Glob", "Grep"])].groupby("file_path").size()
    writes = df[df["tool_name"] == "Write"].groupby("file_path").size()
    edits = df[df["tool_name"] == "Edit"].groupby("file_path").size()

    all_files = set(reads.index) | set(writes.index) | set(edits.index)
    rows = []
    for fp in all_files:
        r = int(reads.get(fp, 0))
        w = int(writes.get(fp, 0))
        e = int(edits.get(fp, 0))
        rows.append({"file_path": fp, "total": r + w + e, "reads": r, "writes": w, "edits": e})

    result = pd.DataFrame(rows).sort_values("total", ascending=False).head(top_n)
    return result.reset_index(drop=True)


def compute_cooccurrence(tool_calls: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """Top N file pairs frequently co-accessed in the same session."""
    if tool_calls.empty or "file_path" not in tool_calls.columns:
        return pd.DataFrame(columns=["file_a", "file_b", "sessions"])

    df = tool_calls[tool_calls["file_path"].notna() & (tool_calls["file_path"] != "")].copy()
    if df.empty:
        return pd.DataFrame(columns=["file_a", "file_b", "sessions"])

    # Group files by session
    session_files = df.groupby("session_id")["file_path"].apply(set)

    pair_counts: Counter = Counter()
    for files in session_files:
        if len(files) < 2:
            continue
        # Only take top 20 files per session to avoid combinatorial explosion
        file_list = sorted(files)[:20]
        for pair in combinations(file_list, 2):
            pair_counts[pair] += 1

    top_pairs = pair_counts.most_common(top_n)
    rows = [{"file_a": a, "file_b": b, "sessions": c} for (a, b), c in top_pairs]
    return pd.DataFrame(rows)


def compute_change_volume(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Per day: total edit delta, bytes written, edit/write counts."""
    if tool_calls.empty or "timestamp" not in tool_calls.columns:
        return pd.DataFrame()

    df = tool_calls.copy()
    df["date"] = df["timestamp"].dt.date

    writes = (
        df[df["tool_name"] == "Write"]
        .groupby("date")
        .agg(
            write_count=("tool_name", "size"),
            bytes_written=("bytes_written", lambda x: x.fillna(0).sum()),
        )
    )

    edits = (
        df[df["tool_name"] == "Edit"]
        .groupby("date")
        .agg(
            edit_count=("tool_name", "size"),
            edit_delta=("edit_delta", lambda x: x.fillna(0).sum()),
        )
    )

    result = writes.join(edits, how="outer").fillna(0).reset_index()
    result.columns = ["date", "write_count", "bytes_written", "edit_count", "edit_delta"]
    for col in ["write_count", "edit_count"]:
        result[col] = result[col].astype(int)
    return result.sort_values("date")
