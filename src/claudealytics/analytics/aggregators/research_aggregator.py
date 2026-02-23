"""Research & learning analysis from WebSearch, WebFetch, and Grep tools."""

from __future__ import annotations

from urllib.parse import urlparse

import pandas as pd


def compute_research_volume(tool_calls: pd.DataFrame) -> pd.DataFrame:
    """Daily counts of research-oriented tool calls.

    Returns DF: date, searches, fetches, greps
    """
    if tool_calls.empty:
        return pd.DataFrame(columns=["date", "searches", "fetches", "greps"])

    research_tools = {"WebSearch", "WebFetch", "Grep"}
    df = tool_calls[tool_calls["tool_name"].isin(research_tools)].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "searches", "fetches", "greps"])

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    pivot = df.groupby(["date", "tool_name"]).size().unstack(fill_value=0).reset_index()
    result = pd.DataFrame({"date": pivot["date"]})
    result["searches"] = pivot.get("WebSearch", 0)
    result["fetches"] = pivot.get("WebFetch", 0)
    result["greps"] = pivot.get("Grep", 0)

    return result.sort_values("date").reset_index(drop=True)


def compute_search_topics(tool_calls: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Most frequent WebSearch queries.

    Returns DF: query, count
    """
    if tool_calls.empty or "search_query" not in tool_calls.columns:
        return pd.DataFrame(columns=["query", "count"])

    queries = tool_calls[tool_calls["search_query"].notna()]["search_query"]
    if queries.empty:
        return pd.DataFrame(columns=["query", "count"])

    counts = queries.value_counts().head(top_n).reset_index()
    counts.columns = ["query", "count"]
    return counts


def compute_documentation_sources(tool_calls: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Most-fetched domains from WebFetch.

    Returns DF: domain, count
    """
    if tool_calls.empty or "fetch_url" not in tool_calls.columns:
        return pd.DataFrame(columns=["domain", "count"])

    urls = tool_calls[tool_calls["fetch_url"].notna()]["fetch_url"]
    if urls.empty:
        return pd.DataFrame(columns=["domain", "count"])

    domains = urls.apply(lambda u: urlparse(u).netloc if u else "").replace("", pd.NA).dropna()
    if domains.empty:
        return pd.DataFrame(columns=["domain", "count"])

    counts = domains.value_counts().head(top_n).reset_index()
    counts.columns = ["domain", "count"]
    return counts


def compute_grep_patterns(tool_calls: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Most frequent Grep search patterns.

    Returns DF: pattern, count
    """
    if tool_calls.empty or "grep_pattern" not in tool_calls.columns:
        return pd.DataFrame(columns=["pattern", "count"])

    patterns = tool_calls[tool_calls["grep_pattern"].notna()]["grep_pattern"]
    if patterns.empty:
        return pd.DataFrame(columns=["pattern", "count"])

    counts = patterns.value_counts().head(top_n).reset_index()
    counts.columns = ["pattern", "count"]
    return counts
