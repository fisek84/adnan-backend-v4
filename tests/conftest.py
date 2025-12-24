# tests/conftest.py
import pytest


@pytest.fixture
def anyio_backend():
    # Force AnyIO tests to run on asyncio only.
    # This avoids requiring optional dependency "trio".
    return "asyncio"
