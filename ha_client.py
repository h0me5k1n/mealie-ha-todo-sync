"""Thin Home Assistant REST API wrapper with OpenTelemetry instrumentation."""

import requests
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("mealie-ha-todo-sync")


def _extract_items(data: object) -> list:
    """Extract a flat item list from any HA service response shape."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # HA wraps service responses: {"service_response": {entity_id: {"items": [...]}}}
    if "service_response" in data:
        items: list = []
        for entity_data in data["service_response"].values():
            if isinstance(entity_data, list):
                items.extend(entity_data)
            elif isinstance(entity_data, dict):
                items.extend(entity_data.get("items", []))
        return items
    if "items" in data:
        return data["items"]
    # Flat {entity_id: [...]} or {entity_id: {"items": [...]}}
    items = []
    for entity_data in data.values():
        if isinstance(entity_data, list):
            items.extend(entity_data)
        elif isinstance(entity_data, dict):
            items.extend(entity_data.get("items", []))
    return items


class HAClient:
    def __init__(self, ha_url: str, ha_token: str):
        self._base = ha_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }
        )

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}{path}"
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def ping(self, parent_span: trace.Span) -> None:
        with tracer.start_as_current_span(
            "ha.ping", context=trace.set_span_in_context(parent_span)
        ) as span:
            try:
                url = f"{self._base}/api/"
                resp = self._session.get(url)
                resp.raise_for_status()
                span.set_attribute("http.status_code", 200)
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def get_shopping_list_items(self, list_entity: str, list_name: str, parent_span: trace.Span) -> list:
        with tracer.start_as_current_span(
            "ha.get_shopping_list_items",
            context=trace.set_span_in_context(parent_span),
        ) as span:
            span.set_attribute("list.name", list_name)
            try:
                data = self._post(
                    "/api/services/mealie/get_shopping_list_items?return_response",
                    {"entity_id": list_entity},
                )
                items = _extract_items(data)
                span.set_attribute("http.status_code", 200)
                span.set_attribute("items.count", len(items))
                return items
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def get_destination_items(self, entity_id: str, parent_span: trace.Span) -> list:
        with tracer.start_as_current_span(
            "ha.get_destination_items",
            context=trace.set_span_in_context(parent_span),
        ) as span:
            try:
                data = self._post(
                    "/api/services/todo/get_items?return_response",
                    {"entity_id": entity_id},
                )
                items = _extract_items(data)
                span.set_attribute("http.status_code", 200)
                span.set_attribute("items.count", len(items))
                return items
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def remove_item(self, entity_id: str, item_summary: str, parent_span: trace.Span) -> None:
        with tracer.start_as_current_span(
            "ha.remove_item",
            context=trace.set_span_in_context(parent_span),
        ) as span:
            span.set_attribute("item.name", item_summary)
            try:
                self._post(
                    "/api/services/todo/remove_item",
                    {"entity_id": entity_id, "item": item_summary},
                )
                span.set_attribute("http.status_code", 200)
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def refresh_entity(self, entity_id: str, parent_span: trace.Span) -> None:
        """Force HA to re-poll the entity from its integration source.

        Called before todo.get_items on the Mealie entity so we always read the
        exact summaries HA currently holds rather than a potentially stale cache.
        """
        with tracer.start_as_current_span(
            "ha.refresh_entity", context=trace.set_span_in_context(parent_span)
        ) as span:
            span.set_attribute("entity_id", entity_id)
            try:
                self._post(
                    "/api/services/homeassistant/update_entity",
                    {"entity_id": entity_id},
                )
                span.set_attribute("http.status_code", 200)
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def mark_item_complete(self, entity_id: str, item_display: str, parent_span: trace.Span) -> None:
        with tracer.start_as_current_span(
            "ha.mark_item_complete", context=trace.set_span_in_context(parent_span)
        ) as span:
            span.set_attribute("item.name", item_display)
            try:
                self._post(
                    "/api/services/todo/update_item",
                    {"entity_id": entity_id, "item": item_display, "status": "completed"},
                )
                span.set_attribute("http.status_code", 200)
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise

    def add_item(self, entity_id: str, item_summary: str, parent_span: trace.Span) -> None:
        with tracer.start_as_current_span(
            "ha.add_item",
            context=trace.set_span_in_context(parent_span),
        ) as span:
            span.set_attribute("item.name", item_summary)
            try:
                self._post(
                    "/api/services/todo/add_item",
                    {"entity_id": entity_id, "item": item_summary},
                )
                span.set_attribute("http.status_code", 200)
            except requests.HTTPError as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                span.set_attribute("http.status_code", exc.response.status_code)
                raise
