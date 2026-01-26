from __future__ import annotations

from services.memory_read_only import ReadOnlyMemoryService


class _BoomMemory:
    @property
    def memory(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("storage not ready")


class _WeirdMemory:
    memory = "not a dict"


def test_export_public_snapshot_fail_soft_on_provider_error() -> None:
    ro = ReadOnlyMemoryService(memory_service=_BoomMemory())  # type: ignore[arg-type]
    snap = ro.export_public_snapshot()
    assert snap == {}


def test_export_public_snapshot_fail_soft_on_corrupted_shape() -> None:
    ro = ReadOnlyMemoryService(memory_service=_WeirdMemory())  # type: ignore[arg-type]
    snap = ro.export_public_snapshot()
    assert snap == {}
