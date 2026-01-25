from __future__ import annotations


class ExecutorError(RuntimeError):
    pass


class ExecutorTimeout(ExecutorError):
    pass


class ExecutorToolCallAttempt(ExecutorError):
    pass


class ExecutorOutputError(ExecutorError):
    pass
