"""Code change semantics analysis from Edit tool classifications."""

from __future__ import annotations

from pathlib import PurePosixPath

import pandas as pd


_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".c": "C", ".cpp": "C++",
    ".cs": "C#", ".css": "CSS", ".html": "HTML", ".vue": "Vue",
    ".svelte": "Svelte", ".sql": "SQL", ".sh": "Shell",
}


def compute_edit_categories(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Distribution of edit categories.

    Returns DF: category, count, pct
    """
    if tool_calls.empty or "edit_category" not in tool_calls.columns:
        return pd.DataFrame(columns=["category", "count", "pct"])

    cats = tool_calls[tool_calls["edit_category"].notna()]["edit_category"]
    if cats.empty:
        return pd.DataFrame(columns=["category", "count", "pct"])

    counts = cats.value_counts().reset_index()
    counts.columns = ["category", "count"]
    total = counts["count"].sum()
    counts["pct"] = round(counts["count"] / total * 100, 1)
    return counts


def compute_edit_complexity(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Daily average edit delta (complexity proxy).

    Returns DF: date, avg_delta, edit_count
    """
    if tool_calls.empty or "edit_delta" not in tool_calls.columns:
        return pd.DataFrame(columns=["date", "avg_delta", "edit_count"])

    df = tool_calls[tool_calls["edit_delta"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "avg_delta", "edit_count"])

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    df["abs_delta"] = df["edit_delta"].abs()

    result = df.groupby("date").agg(
        avg_delta=("abs_delta", "mean"),
        edit_count=("abs_delta", "size"),
    ).reset_index()

    result["avg_delta"] = result["avg_delta"].round(1)
    return result.sort_values("date").reset_index(drop=True)


def compute_import_tracking(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Count of import additions by language.

    Returns DF: language, import_count
    """
    if tool_calls.empty or "edit_category" not in tool_calls.columns:
        return pd.DataFrame(columns=["language", "import_count"])

    df = tool_calls[
        (tool_calls["edit_category"] == "import_add") &
        (tool_calls["file_path"].notna())
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=["language", "import_count"])

    def _ext_to_lang(fp):
        if not fp:
            return "Other"
        name = PurePosixPath(fp).name.lower()
        if "." in name:
            ext = "." + name.rsplit(".", 1)[-1]
            return _EXTENSION_LANGUAGE.get(ext, "Other")
        return "Other"

    df["language"] = df["file_path"].apply(_ext_to_lang)
    result = df.groupby("language").size().reset_index(name="import_count")
    return result.sort_values("import_count", ascending=False).reset_index(drop=True)


def compute_change_type_timeline(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Daily breakdown by edit category.

    Returns DF: date, category, count
    """
    if tool_calls.empty or "edit_category" not in tool_calls.columns:
        return pd.DataFrame(columns=["date", "category", "count"])

    df = tool_calls[tool_calls["edit_category"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "category", "count"])

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    result = df.groupby(["date", "edit_category"]).size().reset_index(name="count")
    result.columns = ["date", "category", "count"]
    return result.sort_values("date").reset_index(drop=True)
