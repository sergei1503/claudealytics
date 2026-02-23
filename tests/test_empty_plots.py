"""Verify that aggregators and render functions handle empty DataFrames without crashing."""

from __future__ import annotations

import pandas as pd

from claudealytics.analytics.aggregators.intervention_aggregator import compute_autonomy
from claudealytics.analytics.aggregators.loop_aggregator import compute_tool_sequences
from claudealytics.analytics.aggregators.file_activity_aggregator import (
    compute_files_per_session,
    compute_hot_files,
    compute_cooccurrence,
    compute_change_volume,
)


# ── Aggregator tests ──────────────────────────────────────────────


def test_compute_autonomy_empty():
    result = compute_autonomy(pd.DataFrame())
    assert result.empty


def test_compute_tool_sequences_empty():
    result = compute_tool_sequences(pd.DataFrame())
    assert list(result.columns) == ["pattern", "count"]
    assert result.empty


def test_compute_tool_sequences_single_tool_turns():
    """Turns with only one tool call should produce no pairs."""
    df = pd.DataFrame(
        {
            "message_uuid": ["a", "b", "c"],
            "tool_name": ["Read", "Edit", "Bash"],
        }
    )
    result = compute_tool_sequences(df)
    assert result.empty


def test_compute_tool_sequences_pairs():
    """Multi-tool turns should produce correct pairs."""
    df = pd.DataFrame(
        {
            "message_uuid": ["a", "a", "a", "b", "b"],
            "tool_name": ["Read", "Edit", "Write", "Bash", "Bash"],
        }
    )
    result = compute_tool_sequences(df)
    assert not result.empty
    patterns = set(result["pattern"])
    assert "Read → Edit" in patterns
    assert "Edit → Write" in patterns
    assert "Bash → Bash" in patterns


def test_compute_files_per_session_empty():
    result = compute_files_per_session(pd.DataFrame())
    assert result.empty


def test_compute_hot_files_empty():
    result = compute_hot_files(pd.DataFrame())
    assert list(result.columns) == ["file_path", "total", "reads", "writes", "edits"]
    assert result.empty


def test_compute_cooccurrence_empty():
    result = compute_cooccurrence(pd.DataFrame())
    assert result.empty


def test_compute_change_volume_empty():
    result = compute_change_volume(pd.DataFrame())
    assert result.empty


# ── Render function tests (empty inputs, no crash) ────────────────


def test_render_interventions_empty():
    from claudealytics.dashboard.layouts.conversation_analysis import _render_interventions

    _render_interventions(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())


def test_render_loops_empty():
    from claudealytics.dashboard.layouts.conversation_analysis import _render_loops

    _render_loops(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())


def test_render_files_empty():
    from claudealytics.dashboard.layouts.conversation_analysis import _render_files

    _render_files(pd.DataFrame(), pd.DataFrame())
