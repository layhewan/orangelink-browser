from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping, MutableMapping


@dataclass(frozen=True)
class ResolvedRuntimeConfig:
    final_runtime_config: dict[str, Any]
    field_sources: dict[str, str]


class TemplateResolver:
    DEFAULTS_SOURCE = "defaults"
    TEMPLATE_SOURCE = "template"
    PROFILE_OVERRIDES_SOURCE = "profile_overrides"

    def resolve(
        self,
        *,
        defaults: Mapping[str, Any] | None,
        template: Mapping[str, Any] | None = None,
        profile_overrides: Mapping[str, Any] | None = None,
    ) -> ResolvedRuntimeConfig:
        merged: dict[str, Any] = deepcopy(dict(defaults or {}))
        field_sources: dict[str, str] = {}

        self._register_value_sources(
            value=merged,
            prefix="",
            source=self.DEFAULTS_SOURCE,
            field_sources=field_sources,
        )

        self._merge_layer(
            target=merged,
            updates=template or {},
            prefix="",
            source=self.TEMPLATE_SOURCE,
            field_sources=field_sources,
        )
        self._merge_layer(
            target=merged,
            updates=profile_overrides or {},
            prefix="",
            source=self.PROFILE_OVERRIDES_SOURCE,
            field_sources=field_sources,
        )

        return ResolvedRuntimeConfig(
            final_runtime_config=merged,
            field_sources=field_sources,
        )

    def _merge_layer(
        self,
        *,
        target: MutableMapping[str, Any],
        updates: Mapping[str, Any],
        prefix: str,
        source: str,
        field_sources: dict[str, str],
    ) -> None:
        for key, value in updates.items():
            key_path = f"{prefix}.{key}" if prefix else key
            existing = target.get(key)

            if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
                self._merge_layer(
                    target=existing,
                    updates=value,
                    prefix=key_path,
                    source=source,
                    field_sources=field_sources,
                )
                continue

            target[key] = deepcopy(value)
            self._clear_path_sources(field_sources=field_sources, path=key_path)
            self._register_value_sources(
                value=value,
                prefix=key_path,
                source=source,
                field_sources=field_sources,
            )

    def _clear_path_sources(self, *, field_sources: dict[str, str], path: str) -> None:
        field_sources.pop(path, None)
        prefix = f"{path}."
        keys_to_remove = [key for key in field_sources if key.startswith(prefix)]
        for key in keys_to_remove:
            field_sources.pop(key, None)

    def _register_value_sources(
        self,
        *,
        value: Any,
        prefix: str,
        source: str,
        field_sources: dict[str, str],
    ) -> None:
        if isinstance(value, Mapping):
            if not value and prefix:
                field_sources[prefix] = source
                return
            for child_key, child_value in value.items():
                child_prefix = f"{prefix}.{child_key}" if prefix else child_key
                self._register_value_sources(
                    value=child_value,
                    prefix=child_prefix,
                    source=source,
                    field_sources=field_sources,
                )
            return

        if prefix:
            field_sources[prefix] = source
