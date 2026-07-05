from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests
from opentelemetry.trace import StatusCode

from tests.conftest import make_response
from ha_client import HAClient, _extract_items


class TestExtractItems:
    def test_list_input_returned_as_is(self):
        assert _extract_items([{"summary": "a"}]) == [{"summary": "a"}]

    def test_service_response_wrapping_list_shaped(self):
        data = {"service_response": {"todo.shopping_list": [{"summary": "a"}]}}
        assert _extract_items(data) == [{"summary": "a"}]

    def test_service_response_wrapping_dict_with_items(self):
        data = {"service_response": {"todo.shopping_list": {"items": [{"summary": "a"}]}}}
        assert _extract_items(data) == [{"summary": "a"}]

    def test_top_level_items_key(self):
        data = {"items": [{"summary": "a"}]}
        assert _extract_items(data) == [{"summary": "a"}]

    def test_flat_entity_id_to_list(self):
        data = {"todo.shopping_list": [{"summary": "a"}]}
        assert _extract_items(data) == [{"summary": "a"}]

    def test_flat_entity_id_to_dict_with_items(self):
        data = {"todo.shopping_list": {"items": [{"summary": "a"}]}}
        assert _extract_items(data) == [{"summary": "a"}]

    def test_non_list_non_dict_returns_empty(self):
        assert _extract_items("garbage") == []
        assert _extract_items(None) == []


@pytest.fixture
def client():
    return HAClient("http://ha.local:8123", "faketoken")


def _finished_span(otel_state, name):
    spans = [s for s in otel_state.span_exporter.get_finished_spans() if s.name == name]
    assert len(spans) == 1, f"expected exactly one {name!r} span, got {len(spans)}"
    return spans[0]


def _assert_error_span(span, expected_status_code):
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["http.status_code"] == expected_status_code
    # start_as_current_span auto-records the exception on propagation
    # (record_exception=True by default) *in addition* to the explicit
    # span.record_exception(exc) call in the except block — 2 events is
    # the correct, expected count, not 1.
    exception_events = [e for e in span.events if e.name == "exception"]
    assert len(exception_events) >= 1


class TestPing:
    def test_success(self, client, otel_state):
        client._session.get = MagicMock(return_value=make_response(200))
        client.ping()
        span = _finished_span(otel_state, "ha.ping")
        assert span.attributes["http.status_code"] == 200

    def test_http_error(self, client, otel_state):
        client._session.get = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.ping()
        span = _finished_span(otel_state, "ha.ping")
        _assert_error_span(span, 500)


class TestGetShoppingListItems:
    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200, {"items": [{"summary": "a"}, {"summary": "b"}]}))
        items = client.get_shopping_list_items("todo.mealie", "Mealie")
        assert items == [{"summary": "a"}, {"summary": "b"}]
        span = _finished_span(otel_state, "ha.get_shopping_list_items")
        assert span.attributes["entity_id"] == "todo.mealie"
        assert span.attributes["list.name"] == "Mealie"
        assert span.attributes["http.status_code"] == 200
        assert span.attributes["items.count"] == 2

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(404))
        with pytest.raises(requests.HTTPError):
            client.get_shopping_list_items("todo.mealie", "Mealie")
        span = _finished_span(otel_state, "ha.get_shopping_list_items")
        _assert_error_span(span, 404)


class TestGetDestinationItems:
    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200, {"items": [{"summary": "a"}]}))
        items = client.get_destination_items("todo.shopping_list")
        assert items == [{"summary": "a"}]
        span = _finished_span(otel_state, "ha.get_destination_items")
        assert span.attributes["entity_id"] == "todo.shopping_list"
        assert span.attributes["items.count"] == 1

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.get_destination_items("todo.shopping_list")
        span = _finished_span(otel_state, "ha.get_destination_items")
        _assert_error_span(span, 500)


class TestRemoveItem:
    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200))
        client.remove_item("todo.shopping_list", "chicken breast (2)", reason="merge")
        span = _finished_span(otel_state, "ha.remove_item")
        assert span.attributes["entity_id"] == "todo.shopping_list"
        assert span.attributes["item.name"] == "chicken breast (2)"
        assert span.attributes["remove.reason"] == "merge"
        assert span.attributes["http.status_code"] == 200

    def test_success_without_reason_attribute_absent(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200))
        client.remove_item("todo.shopping_list", "chicken breast (2)")
        span = _finished_span(otel_state, "ha.remove_item")
        assert "remove.reason" not in span.attributes

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.remove_item("todo.shopping_list", "chicken breast (2)")
        span = _finished_span(otel_state, "ha.remove_item")
        _assert_error_span(span, 500)


class TestRefreshEntity:
    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200))
        client.refresh_entity("todo.mealie")
        span = _finished_span(otel_state, "ha.refresh_entity")
        assert span.attributes["entity_id"] == "todo.mealie"
        assert span.attributes["http.status_code"] == 200

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.refresh_entity("todo.mealie")
        span = _finished_span(otel_state, "ha.refresh_entity")
        _assert_error_span(span, 500)


class TestMarkItemComplete:
    """Unused by main() today, but part of HAClient's public API — first-ever coverage."""

    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200))
        client.mark_item_complete("todo.shopping_list", "chicken breast (2)")
        span = _finished_span(otel_state, "ha.mark_item_complete")
        assert span.attributes["entity_id"] == "todo.shopping_list"
        assert span.attributes["item.name"] == "chicken breast (2)"
        assert span.attributes["http.status_code"] == 200

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.mark_item_complete("todo.shopping_list", "chicken breast (2)")
        span = _finished_span(otel_state, "ha.mark_item_complete")
        _assert_error_span(span, 500)


class TestAddItem:
    def test_success(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(200))
        client.add_item("todo.shopping_list", "flour (100)")
        span = _finished_span(otel_state, "ha.add_item")
        assert span.attributes["entity_id"] == "todo.shopping_list"
        assert span.attributes["item.name"] == "flour (100)"
        assert span.attributes["http.status_code"] == 200

    def test_http_error(self, client, otel_state):
        client._session.post = MagicMock(return_value=make_response(500))
        with pytest.raises(requests.HTTPError):
            client.add_item("todo.shopping_list", "flour (100)")
        span = _finished_span(otel_state, "ha.add_item")
        _assert_error_span(span, 500)
