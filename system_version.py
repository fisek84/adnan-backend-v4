"""
SYSTEM VERSION — STABLE OPERATOR OS

This file is the canonical version and architecture lock marker.

RULES:
- If ARCH_LOCK = True → architecture is frozen
- Any structural change REQUIRES version bump
- Loaded at gateway boot time
"""

SYSTEM_NAME = "Adnan.AI / Evolia OS"

VERSION = "1.0.0"

ARCH_LOCK = True

RELEASE_CHANNEL = "stable"

BUILD_DATE = "2025-01-XX"  # optional, informational only
