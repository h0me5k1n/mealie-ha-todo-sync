"""Thin Home Assistant REST API wrapper with OpenTelemetry instrumentation."""

import requests
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("mealie-ha-todo-sync")


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
                items = data if isinstance(data, list) else data.get("items", [])
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
                # Response shape: {entity_id: {"items": [...]}}
                items = []
                if isinstance(data, dict):
                    for entity_data in data.values():
                        items.extend(entity_data.get("items", []))
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
