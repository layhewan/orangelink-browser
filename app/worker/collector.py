from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping
from urllib import request

from app.worker.ipc import WorkerToMainType, build_worker_message


HttpPost = Callable[[str, dict[str, Any], float], dict[str, Any]]
ProbeExtractor = Callable[[Any], Mapping[str, Any] | None]
ProbeTransformer = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class SnapshotCollectionResult:
    snapshot_id: str | None
    score_summary: dict[str, Any]
    raw_response: dict[str, Any]


class WorkerCollectorClient:
    def __init__(
        self,
        *,
        detection_page_url: str,
        scoring_api_url: str,
        request_timeout_s: float = 10.0,
        http_post: HttpPost | None = None,
        probe_extractors: list[ProbeExtractor] | None = None,
        payload_transformers: list[ProbeTransformer] | None = None,
    ) -> None:
        self._detection_page_url = detection_page_url
        self._scoring_api_url = scoring_api_url
        self._request_timeout_s = request_timeout_s
        self._http_post = http_post or self._default_http_post
        self._probe_extractors = list(probe_extractors or [])
        self._payload_transformers = list(payload_transformers or [])

    def collect_snapshot(
        self,
        *,
        context: Any,
        profile_id: str,
        extra_probe_payload: Mapping[str, Any] | None = None,
    ) -> SnapshotCollectionResult:
        page = self._get_or_create_page(context)
        if page is not None and hasattr(page, "goto"):
            page.goto(self._detection_page_url, wait_until="domcontentloaded")

        probe_payload = self._collect_probe_payload(page)
        if extra_probe_payload:
            probe_payload.update(dict(extra_probe_payload))

        for transformer in self._payload_transformers:
            probe_payload = dict(transformer(probe_payload))

        response = self._http_post(
            self._scoring_api_url,
            {"profile_id": profile_id, **probe_payload},
            self._request_timeout_s,
        )

        snapshot_id = response.get("snapshot_id")
        if snapshot_id is not None:
            snapshot_id = str(snapshot_id)
        score_summary = response.get("score_summary")
        if not isinstance(score_summary, Mapping):
            score_summary = {
                "score": response.get("score"),
                "penalties": response.get("penalties", []),
            }

        return SnapshotCollectionResult(
            snapshot_id=snapshot_id,
            score_summary=dict(score_summary),
            raw_response=dict(response),
        )

    def build_snapshot_event(
        self,
        *,
        result: SnapshotCollectionResult,
        worker_pid: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "snapshot_id": result.snapshot_id,
            "score_summary": dict(result.score_summary),
        }
        return build_worker_message(
            WorkerToMainType.SNAPSHOT_COLLECTED,
            payload=payload,
            worker_pid=worker_pid,
        )

    def _get_or_create_page(self, context: Any) -> Any:
        if context is None:
            return None

        pages = getattr(context, "pages", None)
        if pages:
            return pages[0]

        if hasattr(context, "new_page"):
            return context.new_page()

        return None

    def _collect_probe_payload(self, page: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for extractor in self._probe_extractors:
            extracted = extractor(page)
            if extracted:
                payload.update(dict(extracted))
        return payload

    @staticmethod
    def _default_http_post(url: str, data: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        encoded_payload = json.dumps(data).encode("utf-8")
        http_request = request.Request(
            url=url,
            data=encoded_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("scoring API response must be a JSON object")
        return parsed
