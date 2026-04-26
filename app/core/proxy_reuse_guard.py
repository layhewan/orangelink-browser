from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ProxyReuseDecision:
    allowed: bool
    reason: str


class ProxyReuseGuard:
    def can_use_proxy(
        self,
        *,
        proxy_key: str,
        active_proxy_keys: Iterable[str],
        allow_proxy_reuse: bool = False,
    ) -> bool:
        return self.decide(
            proxy_key=proxy_key,
            active_proxy_keys=active_proxy_keys,
            allow_proxy_reuse=allow_proxy_reuse,
        ).allowed

    def decide(
        self,
        *,
        proxy_key: str,
        active_proxy_keys: Iterable[str],
        allow_proxy_reuse: bool = False,
    ) -> ProxyReuseDecision:
        if allow_proxy_reuse:
            return ProxyReuseDecision(
                allowed=True,
                reason="profile_opted_in_allow_proxy_reuse",
            )

        if proxy_key in set(active_proxy_keys):
            return ProxyReuseDecision(
                allowed=False,
                reason="active_proxy_reuse_disallowed_by_default",
            )

        return ProxyReuseDecision(
            allowed=True,
            reason="proxy_not_active",
        )
