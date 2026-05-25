"""Task-layer compatibility import for retry classification."""

from app.core.retry_policy import is_retryable_exception

__all__ = ["is_retryable_exception"]
