from __future__ import annotations

from jobs.outcome_feedback_loop_job import _configure_logging, run_once


def main() -> int:
    return int(run_once() or 0)


if __name__ == "__main__":
    _configure_logging()
    raise SystemExit(main())
