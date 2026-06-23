"""Shared retry/backoff helpers for provider adapters."""


def is_retryable_exception(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate limit" in msg or "429" in msg:
        return True
    if "timeout" in name or "timed out" in msg:
        return True
    if "apiconnection" in name or "connection" in msg:
        return True
    if "server error" in msg or any(s in msg for s in ("500", "502", "503", "504")):
        return True
    return False


def sleep_backoff_s(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))
