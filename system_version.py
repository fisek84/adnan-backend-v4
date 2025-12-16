"""
SYSTEM VERSION — CANONICAL SOURCE OF TRUTH

This file is the SINGLE authoritative version marker
for Adnan.AI / Evolia OS.

RULES (ENFORCED BY CONVENTION):
- If ARCH_LOCK = True → architecture is frozen
- Any structural or architectural change REQUIRES version bump
- Loaded at gateway boot time
- Used by audit, telemetry, and ops
"""

SYSTEM_NAME = "Adnan.AI / Evolia OS"

# Semantic Versioning (MAJOR.MINOR.PATCH)
# MAJOR — architectural change (VERY RARE)
# MINOR — feature addition without breaking canon
# PATCH — bugfix / internal hardening
VERSION = "1.0.0"

# When True:
# - architecture is frozen
# - canon cannot be altered
# - only PATCH-level changes are allowed
ARCH_LOCK = True

# Release channel indicates operational stability,
# not feature completeness
RELEASE_CHANNEL = "stable"

# Informational only — no logic may depend on this
BUILD_DATE = "2025-01-XX"
