from __future__ import annotations

DEFAULT_MAX_CONCURRENCY = 5


class ResourceGovernor:
    def __init__(self, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency

    def can_dispatch(self, *, current_running: int) -> bool:
        return current_running < self.max_concurrency

    def next_dispatch_count(self, *, current_running: int, pending_count: int) -> int:
        if pending_count <= 0:
            return 0

        available = max(self.max_concurrency - max(current_running, 0), 0)
        return min(available, pending_count)
