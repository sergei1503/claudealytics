"""Shared fixtures: mock Streamlit API so layout functions can run headless."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeColumn:
    """Mimics st.columns() context manager and .metric() calls."""
    def metric(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeExpander:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture(autouse=True)
def mock_streamlit(monkeypatch):
    """Patch streamlit so render functions don't need a running server."""
    import streamlit as st

    monkeypatch.setattr(st, "columns", lambda n, **kw: [_FakeColumn() for _ in range(n)])
    monkeypatch.setattr(st, "tabs", lambda labels: [MagicMock() for _ in labels])
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
    monkeypatch.setattr(st, "divider", lambda: None)
    monkeypatch.setattr(st, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(st, "plotly_chart", lambda *a, **kw: None)
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)
    monkeypatch.setattr(st, "metric", lambda *a, **kw: None)
    monkeypatch.setattr(st, "slider", lambda *a, **kw: kw.get("value", 1))
    monkeypatch.setattr(st, "expander", lambda *a, **kw: _FakeExpander())
    monkeypatch.setattr(st, "date_input", lambda *a, **kw: kw.get("value"))
