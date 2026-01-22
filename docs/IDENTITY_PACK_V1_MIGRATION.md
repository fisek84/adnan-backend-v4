# IDENTITY_PACK_V1_MIGRATION

This repo exposes a best-effort CEO identity payload via `load_ceo_identity_pack()`.

As of `identity_pack.v1`, the payload is still **backward-compatible** (keeps legacy keys like `identity`, `kernel`, etc.) but also emits a canonical shape used by the CEO grounding system.

## What changed

`load_ceo_identity_pack()` now returns an additive CANON structure:

- `schema_version: "identity_pack.v1"`
- `status: "ok" | "missing"`
- `meta`: deterministic hash + file mtimes + generated_at
- `diagnostics`: `missing_keys` + `recommended_action`
- Canonical fields (best-effort mapping):
  - `immutable_laws.kernel`
  - `trajectory_targets`
  - `reasoning_filters`
  - `tone`
  - `authority_order`

## Required SSOT keys

### authority_order

Add `authority_order` to `identity/kernel.json` (preferred SSOT location):

- Type: `list[str]`
- Meaning: conflict-resolution priority; earlier entries override later entries.

Recommended default (already added in this repo):

- `identity_pack`
- `kb_snapshot`
- `notion_snapshot`
- `memory_snapshot`
- `user_input`

## Backward compatibility

- Existing consumers can keep using legacy keys (`identity`, `kernel`, ...).
- New consumers should use CANON keys and treat missing keys as normal (fail-soft).
- `meta.hash` is deterministic and excludes `meta.hash` itself to avoid recursion.

## Operational guidance

- Update identity JSON files under `identity/` and re-run:
  - `pre-commit run -a`
  - `pytest -q`

If `diagnostics.missing_keys` includes `authority_order`, confirm it exists in `identity/kernel.json` and is a non-empty `list[str]`.
