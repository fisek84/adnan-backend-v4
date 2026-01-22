import pytest


def test_no_network_guard_blocks_external_httpx():
    httpx = pytest.importorskip("httpx")
    with pytest.raises(RuntimeError, match=r"Network disabled in tests"):
        httpx.get("https://example.com", timeout=1.0)
