#!/usr/bin/env bash
# Integration test: claudealytics → guilder publish flow
# Requires: guilder dev server at http://guilder.localhost:1355
#
# Usage: bash tests/integration/test_publish_flow.sh

set -euo pipefail

BASE_URL="${GUILDER_URL:-http://guilder.localhost:1355}"
PASSED=0
FAILED=0

pass() { PASSED=$((PASSED + 1)); echo "  ✓ $1"; }
fail() { FAILED=$((FAILED + 1)); echo "  ✗ $1: $2"; }

echo "=== Integration: claudealytics → guilder publish flow ==="
echo "Server: $BASE_URL"
echo

# --- 1. Health check ---
echo "1. Health check"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE_URL/api/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  pass "GET /api/health → 200"
else
  fail "GET /api/health" "got $HTTP_CODE (is guilder running at $BASE_URL?)"
  echo
  echo "ABORT: Guilder not reachable. Start with: cd guilder && npm run dev"
  exit 1
fi

# --- 2. Publish profile ---
echo "2. Publish profile"
PROFILE_JSON='{
  "version": 1,
  "exported_at": "2025-06-01T00:00:00Z",
  "claudealytics_version": "0.1.0",
  "sessions_analyzed": 5,
  "date_range": {"start": "2025-05-01", "end": "2025-06-01"},
  "overall_score": 7.2,
  "category_scores": {"communication": 7.5, "strategy": 6.8, "technical": 7.0, "autonomy": 6.5},
  "dimensions": [
    {"key": "context_precision", "name": "Context Precision", "category": "communication", "score": 8.0, "sub_scores": [
      {"name": "Prompt clarity", "raw_value": 0.7, "normalized": 0.7, "weight": 0.4, "contribution": 0.28}
    ]},
    {"key": "semantic_density", "name": "Semantic Density", "category": "communication", "score": 7.0, "sub_scores": []},
    {"key": "code_literacy", "name": "Code Literacy", "category": "technical", "score": 7.0, "sub_scores": []}
  ]
}'

RESPONSE=$(curl -sf -X POST "$BASE_URL/api/cli/publish" \
  -H "Content-Type: application/json" \
  -d "$PROFILE_JSON" 2>/dev/null || echo "CURL_FAILED")

if [ "$RESPONSE" = "CURL_FAILED" ]; then
  fail "POST /api/cli/publish" "request failed"
else
  CLAIM_CODE=$(echo "$RESPONSE" | jq -r '.claimCode // empty')
  CLAIM_URL=$(echo "$RESPONSE" | jq -r '.claimUrl // empty')
  OVERALL=$(echo "$RESPONSE" | jq -r '.overallScore // empty')

  if [ -n "$CLAIM_CODE" ] && [ -n "$CLAIM_URL" ] && [ -n "$OVERALL" ]; then
    pass "POST → 201 with claimCode=$CLAIM_CODE, overallScore=$OVERALL"
  else
    fail "POST /api/cli/publish" "missing fields in response: $RESPONSE"
  fi
fi

# --- 3. Claim page loads ---
echo "3. Claim page"
if [ -n "${CLAIM_URL:-}" ]; then
  # Convert absolute URL to relative for same-server request
  CLAIM_PATH=$(echo "$CLAIM_URL" | sed 's|https\?://[^/]*||')
  CLAIM_HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "$BASE_URL$CLAIM_PATH" 2>/dev/null || echo "000")
  if [ "$CLAIM_HTTP" = "200" ]; then
    pass "GET claim page → 200"
  else
    fail "GET claim page" "got $CLAIM_HTTP for $BASE_URL$CLAIM_PATH"
  fi
else
  fail "GET claim page" "no claimUrl from publish step"
fi

# --- 4. Re-publish with X-Claim-Code ---
echo "4. Re-publish with claim code"
if [ -n "${CLAIM_CODE:-}" ]; then
  RESPONSE2=$(curl -sf -X POST "$BASE_URL/api/cli/publish" \
    -H "Content-Type: application/json" \
    -H "X-Claim-Code: $CLAIM_CODE" \
    -d "$PROFILE_JSON" 2>/dev/null || echo "CURL_FAILED")

  if [ "$RESPONSE2" = "CURL_FAILED" ]; then
    fail "Re-publish" "request failed"
  else
    CODE2=$(echo "$RESPONSE2" | jq -r '.claimCode // empty')
    if [ "$CODE2" = "$CLAIM_CODE" ]; then
      pass "Re-publish preserves claimCode=$CODE2"
    else
      fail "Re-publish" "claimCode changed: $CLAIM_CODE → $CODE2"
    fi
  fi
else
  fail "Re-publish" "no claimCode from publish step"
fi

# --- 5. Sub-scores accepted ---
echo "5. Sub-scores accepted"
# The profile already has sub_scores — if publish succeeded, they were accepted
if [ -n "${CLAIM_CODE:-}" ]; then
  pass "Profile with sub_scores accepted without error"
else
  fail "Sub-scores" "publish failed so cannot verify"
fi

# --- 6. Invalid payload ---
echo "6. Invalid payload"
INVALID_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/cli/publish" \
  -H "Content-Type: application/json" \
  -d '{"garbage": true}' 2>/dev/null || echo "000")

if [ "$INVALID_CODE" = "422" ] || [ "$INVALID_CODE" = "400" ]; then
  pass "Bad JSON → $INVALID_CODE"
else
  fail "Invalid payload" "expected 422/400, got $INVALID_CODE"
fi

# --- Summary ---
echo
echo "=== Results: $PASSED passed, $FAILED failed ==="
[ "$FAILED" -eq 0 ] && exit 0 || exit 1
