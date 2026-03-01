"""Integration tests: claudealytics → guilder publish flow.

Run with: uv run pytest tests/integration/ -v -m integration
Requires: guilder dev server at http://guilder.localhost:1355
"""

from __future__ import annotations

import os

import httpx
import pytest

GUILDER_URL = os.environ.get("GUILDER_URL", "http://guilder.localhost:1355")

pytestmark = pytest.mark.integration


def _sample_profile() -> dict:
    return {
        "version": 1,
        "exported_at": "2025-06-01T00:00:00Z",
        "claudealytics_version": "0.1.0",
        "sessions_analyzed": 5,
        "date_range": {"start": "2025-05-01", "end": "2025-06-01"},
        "overall_score": 7.2,
        "category_scores": {
            "communication": 7.5,
            "strategy": 6.8,
            "technical": 7.0,
            "autonomy": 6.5,
        },
        "dimensions": [
            {
                "key": "context_precision",
                "name": "Context Precision",
                "category": "communication",
                "score": 8.0,
                "sub_scores": [
                    {
                        "name": "Prompt clarity",
                        "raw_value": 0.7,
                        "normalized": 0.7,
                        "weight": 0.4,
                        "contribution": 0.28,
                    }
                ],
            },
            {
                "key": "semantic_density",
                "name": "Semantic Density",
                "category": "communication",
                "score": 7.0,
                "sub_scores": [],
            },
            {
                "key": "code_literacy",
                "name": "Code Literacy",
                "category": "technical",
                "score": 7.0,
                "sub_scores": [],
            },
        ],
    }


class TestGuilderReachable:
    def test_guilder_reachable(self):
        """GET /api/health → 200."""
        resp = httpx.get(f"{GUILDER_URL}/api/health", timeout=10)
        assert resp.status_code == 200


class TestPublishFlow:
    def test_publish_returns_claim_code(self):
        """POST profile → 201, response has claimCode/claimUrl/overallScore."""
        resp = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json=_sample_profile(),
            timeout=15,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "claimCode" in data
        assert "claimUrl" in data
        assert "overallScore" in data
        assert isinstance(data["claimCode"], str)
        assert len(data["claimCode"]) > 0

    def test_republish_preserves_claim_code(self):
        """POST with X-Claim-Code → same code returned."""
        # First publish
        resp1 = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json=_sample_profile(),
            timeout=15,
        )
        assert resp1.status_code == 201
        claim_code = resp1.json()["claimCode"]

        # Re-publish with claim code
        resp2 = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json=_sample_profile(),
            headers={"X-Claim-Code": claim_code},
            timeout=15,
        )
        assert resp2.status_code == 201
        assert resp2.json()["claimCode"] == claim_code

    def test_claim_page_loads(self):
        """GET claim URL → 200."""
        # Publish to get a claim URL
        resp = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json=_sample_profile(),
            timeout=15,
        )
        assert resp.status_code == 201
        claim_url = resp.json()["claimUrl"]

        # Load claim page (follow redirects)
        page_resp = httpx.get(claim_url, follow_redirects=True, timeout=15)
        assert page_resp.status_code == 200

    def test_sub_scores_accepted(self):
        """Profile with sub_scores accepted without error."""
        profile = _sample_profile()
        # Ensure sub_scores are present
        assert any(d["sub_scores"] for d in profile["dimensions"])

        resp = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json=profile,
            timeout=15,
        )
        assert resp.status_code == 201

    def test_invalid_payload_rejected(self):
        """Bad JSON → 422."""
        resp = httpx.post(
            f"{GUILDER_URL}/api/cli/publish",
            json={"garbage": True},
            timeout=15,
        )
        assert resp.status_code in (400, 422)
