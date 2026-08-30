"""INTEGRATION tests — hit the real Thai 2D API. NOT part of `pytest -q`.

Run explicitly:  pytest -m integration -q
These require internet access and may fail when the upstream service is
down — that failure is INFORMATION, never a substitute for cached data.
"""
import os

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE_URL = os.environ.get("THAI2D_API_BASE_URL", "https://api.thaistock2d.com")
TIMEOUT = 10.0


def test_live_endpoint_reachable_and_json():
    """The live endpoint must respond with valid JSON within 10s.

    Accepts: 200 with any JSON body (schema is parsed defensively elsewhere).
    Accepts: documented HTTP error statuses.
    Fails:   timeouts, connection errors, malformed JSON — surfacing real
             upstream problems instead of hiding them.
    """
    try:
        r = httpx.get(f"{BASE_URL}/live", timeout=TIMEOUT, follow_redirects=True)
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        pytest.fail(f"Thai 2D API unreachable at {BASE_URL}: {exc!r}")
    assert r.status_code < 500, f"Upstream server error: HTTP {r.status_code}"
    try:
        body = r.json()
    except ValueError as exc:
        pytest.fail(f"Malformed JSON from {BASE_URL}/live: {exc}")
    assert isinstance(body, (dict, list))


def test_history_endpoint_reachable():
    try:
        r = httpx.get(f"{BASE_URL}/2d_history", params={"date": "2026-08-20"},
                      timeout=TIMEOUT, follow_redirects=True)
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        pytest.fail(f"Thai 2D history API unreachable: {exc!r}")
    assert r.status_code < 500
