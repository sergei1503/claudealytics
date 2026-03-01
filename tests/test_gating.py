"""Tests verifying claudealytics gating — dimension details replaced with guilder.dev CTA."""

from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest

from claudealytics.models.schemas import (
    DimensionScore,
    ExportedDimension,
    ExportedProfile,
    SubScore,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_dimension(key="ctx", name="Context Precision", category="communication", score=7.5):
    return DimensionScore(
        key=key,
        name=name,
        category=category,
        score=score,
        explanation="test explanation",
        improvement_hint="try harder",
        sub_scores=[
            SubScore(name="Prompt clarity", raw_value=0.6, normalized=0.6, weight=0.5, contribution=0.3),
            SubScore(name="Context relevance", raw_value=0.8, normalized=0.8, weight=0.5, contribution=0.4),
        ],
    )


def _make_profile(dims=None, overall_score=7.0, category_scores=None):
    """Create a minimal profile-like object for render functions."""
    if dims is None:
        dims = [
            _make_dimension("ctx", "Context Precision", "communication", 8.0),
            _make_dimension("sem", "Semantic Density", "communication", 7.0),
            _make_dimension("val", "Validation Rigor", "strategy", 5.0),
            _make_dimension("err", "Error Resilience", "strategy", 4.0),
            _make_dimension("cod", "Code Literacy", "technical", 6.0),
            _make_dimension("dbg", "Debugging", "technical", 3.0),
        ]
    if category_scores is None:
        category_scores = {
            "communication": 7.5,
            "strategy": 4.5,
            "technical": 4.5,
            "autonomy": 5.0,
        }
    return types.SimpleNamespace(
        overall_score=overall_score,
        category_scores=category_scores,
        dimensions=dims,
    )


# ── A.2: Gating Tests ───────────────────────────────────────────────


class TestDimensionDetailsGating:
    """Verify _render_dimension_details shows CTA, not expander."""

    def test_dimension_details_shows_cta(self):
        """_render_dimension_details calls st.info with guilder.dev, NOT st.expander."""
        import streamlit as st

        from claudealytics.dashboard.layouts.conversation_profile import _render_dimension_details

        profile = _make_profile()
        _render_dimension_details(profile)

        # st.info was called with the guilder CTA
        st.info.assert_called_once()
        call_text = st.info.call_args[0][0]
        assert "guilder.dev" in call_text

        # st.expander should NOT have been called
        assert not hasattr(st.expander, "call_count") or st.expander.call_count == 0

    def test_dimension_details_has_subheader(self):
        """st.subheader("Dimension Details") is called."""
        import streamlit as st

        from claudealytics.dashboard.layouts.conversation_profile import _render_dimension_details

        profile = _make_profile()
        # Replace subheader with a MagicMock to track calls
        original = st.subheader
        st.subheader = MagicMock()
        try:
            _render_dimension_details(profile)
            st.subheader.assert_called_once_with("Dimension Details")
        finally:
            st.subheader = original


class TestSummaryGapsNoHints:
    """Verify _render_summary bottom-3 gaps don't include improvement_hint text."""

    def test_summary_gaps_no_hints(self):
        """Bottom-3 gaps should not contain improvement_hint from DimensionScore."""
        import streamlit as st

        from claudealytics.dashboard.layouts.conversation_profile import _render_summary

        profile = _make_profile()
        _render_summary(profile, session_count=3)

        # Collect all markdown call text
        all_markdown_text = " ".join(str(call[0][0]) for call in st.markdown.call_args_list if call[0])

        # The improvement_hint "try harder" should NOT appear in the summary
        assert "try harder" not in all_markdown_text


# ── Export Tests ─────────────────────────────────────────────────────


class TestExportProfile:
    """Verify build_exported_profile outputs sub_scores on every dimension."""

    @patch("claudealytics.analytics.profile_exporter.get_all_cached_scores", return_value={})
    @patch("claudealytics.analytics.profile_exporter.aggregate_profiles")
    @patch("claudealytics.analytics.profile_exporter.compute_all_profiles")
    @patch("claudealytics.analytics.profile_exporter.mine_content")
    def test_export_includes_sub_scores(self, mock_mine, mock_compute, mock_agg, mock_llm):
        """Every dimension in the exported profile should have sub_scores."""
        import pandas as pd

        from claudealytics.analytics.profile_exporter import build_exported_profile

        # Setup mocks
        mock_mine.return_value = {
            "session_stats": pd.DataFrame({"session_id": ["s1"]}),
            "tool_calls": pd.DataFrame(),
            "human_message_lengths": pd.DataFrame(),
        }

        dim1 = _make_dimension("ctx", "Context Precision", "communication", 8.0)
        dim2 = _make_dimension("sem", "Semantic Density", "communication", 6.5)

        fake_profile = types.SimpleNamespace(
            date="2025-01-01",
            overall_score=7.0,
            category_scores={"communication": 7.5},
            dimensions=[dim1, dim2],
        )
        mock_compute.return_value = [fake_profile]
        mock_agg.return_value = fake_profile

        result = build_exported_profile()

        assert result.sessions_analyzed == 1
        assert len(result.dimensions) == 2
        for dim in result.dimensions:
            assert hasattr(dim, "sub_scores"), f"Dimension {dim.key} missing sub_scores"
            assert len(dim.sub_scores) > 0, f"Dimension {dim.key} has empty sub_scores"


# ── Publish Flow Tests ───────────────────────────────────────────────


class TestPublishPayload:
    """Verify publish command formats payload correctly."""

    @patch("claudealytics.analytics.profile_exporter.get_all_cached_scores", return_value={})
    @patch("claudealytics.analytics.profile_exporter.aggregate_profiles")
    @patch("claudealytics.analytics.profile_exporter.compute_all_profiles")
    @patch("claudealytics.analytics.profile_exporter.mine_content")
    @patch("httpx.post")
    @patch("webbrowser.open")
    def test_publish_payload_date_range_object(
        self, mock_browser, mock_post, mock_mine, mock_compute, mock_agg, mock_llm
    ):
        """Publish converts tuple date_range to {start, end} object."""
        import pandas as pd
        from typer.testing import CliRunner

        from claudealytics.cli import app

        # Setup profile mocks
        mock_mine.return_value = {
            "session_stats": pd.DataFrame({"session_id": ["s1"]}),
            "tool_calls": pd.DataFrame(),
            "human_message_lengths": pd.DataFrame(),
        }

        dim = _make_dimension()
        fake_profile = types.SimpleNamespace(
            date="2025-01-01",
            overall_score=7.0,
            category_scores={"communication": 7.5},
            dimensions=[dim],
        )
        mock_compute.return_value = [fake_profile]
        mock_agg.return_value = fake_profile

        # Mock successful publish response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "claimCode": "test-123",
            "claimUrl": "https://guilder.dev/claim/test-123",
            "overallScore": 7.0,
        }
        mock_post.return_value = mock_response

        runner = CliRunner()
        result = runner.invoke(app, ["publish", "--server", "https://guilder.dev"])

        # Verify httpx.post was called
        assert mock_post.called
        posted_data = mock_post.call_args[1]["json"]

        # date_range should be an object, not a tuple/list
        dr = posted_data.get("date_range")
        assert isinstance(dr, dict), f"date_range should be dict, got {type(dr)}"
        assert "start" in dr
        assert "end" in dr

    @patch("claudealytics.analytics.profile_exporter.get_all_cached_scores", return_value={})
    @patch("claudealytics.analytics.profile_exporter.aggregate_profiles")
    @patch("claudealytics.analytics.profile_exporter.compute_all_profiles")
    @patch("claudealytics.analytics.profile_exporter.mine_content")
    @patch("httpx.post")
    @patch("webbrowser.open")
    def test_publish_sends_claim_code_header(
        self, mock_browser, mock_post, mock_mine, mock_compute, mock_agg, mock_llm, tmp_path
    ):
        """Saved claim code is sent as X-Claim-Code header."""
        import pandas as pd
        from typer.testing import CliRunner

        from claudealytics.cli import app

        # Setup profile mocks
        mock_mine.return_value = {
            "session_stats": pd.DataFrame({"session_id": ["s1"]}),
            "tool_calls": pd.DataFrame(),
            "human_message_lengths": pd.DataFrame(),
        }

        dim = _make_dimension()
        fake_profile = types.SimpleNamespace(
            date="2025-01-01",
            overall_score=7.0,
            category_scores={"communication": 7.5},
            dimensions=[dim],
        )
        mock_compute.return_value = [fake_profile]
        mock_agg.return_value = fake_profile

        # Pre-create config with saved claim code
        config_dir = tmp_path / ".cache" / "claudealytics"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "guilder.json"
        config_file.write_text(json.dumps({"claimCode": "saved-code-xyz"}))

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "claimCode": "saved-code-xyz",
            "claimUrl": "https://guilder.dev/claim/saved-code-xyz",
            "overallScore": 7.0,
        }
        mock_post.return_value = mock_response

        # Patch Path.home() to use tmp_path
        with patch("claudealytics.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(app, ["publish", "--server", "https://guilder.dev"])

        # Verify X-Claim-Code header was sent
        assert mock_post.called
        headers = mock_post.call_args[1]["headers"]
        assert headers.get("X-Claim-Code") == "saved-code-xyz"
