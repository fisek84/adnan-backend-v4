from __future__ import annotations

import logging
import os
import sys

from jobs.outcome_feedback_loop_job import _configure_logging, run_once

logger = logging.getLogger("jobs.ofl_scheduler")


def main() -> int:
    # Keep behavior identical: reuse existing OFL job (advisory lock + evaluation).
    return run_once()


if __name__ == "__main__":
    _configure_logging()
    raise SystemExit(main())
