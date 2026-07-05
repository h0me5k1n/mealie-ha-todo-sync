from __future__ import annotations

import pytest
from opentelemetry.trace import StatusCode

import ha_client
import sync
from tests.conftest import make_response

HA_URL = "http://ha.local:8123"
HA_TOKEN = "faketoken"
MEALIE_ENTITY = "todo.mealie_weekly_shopping"
DEST_ENTITY = "todo.shopping_list"


class _FakeSession:
    """Stubs only the network layer — ha_client.py's real span-creation code
    runs for real, including inside ThreadPoolExecutor workers, which is
    required for the parent-span assertions below to mean anything."""

    def __init__(self, mealie_raw_items, dest_items, mealie_ha_items):
        self.headers = {}
        self.calls = []
        self._mealie_raw_items = mealie_raw_items
        self._dest_items = dest_items
        self._mealie_ha_items = mealie_ha_items

    def get(self, url):
        self.calls.append(("GET", url, None))
        return make_response(200)

    def post(self, url, json=None):
        payload = json or {}
        self.calls.append(("POST", url, payload))
        entity_id = payload.get("entity_id")

        if url.endswith("/services/mealie/get_shopping_list_items?return_response"):
            return make_response(200, {"items": self._mealie_raw_items})

        if url.endswith("/services/todo/get_items?return_response"):
            if entity_id == DEST_ENTITY:
                return make_response(200, {"items": self._dest_items})
            if entity_id == MEALIE_ENTITY:
                return make_response(200, {"items": self._mealie_ha_items})
            return make_response(200, {"items": []})

        # remove_item, add_item, homeassistant.update_entity (refresh) — fire and forget
        return make_response(200, {})


class _AlwaysFailingSession:
    def __init__(self):
        self.headers = {}

    def get(self, url):
        return make_response(500)

    def post(self, url, json=None):
        return make_response(200, {})


def _set_required_env(monkeypatch):
    monkeypatch.setenv("HA_URL", HA_URL)
    monkeypatch.setenv("HA_TOKEN", HA_TOKEN)
    monkeypatch.setenv("MEALIE_TODO_ENTITY", MEALIE_ENTITY)
    monkeypatch.setenv("DESTINATION_TODO_ENTITY", DEST_ENTITY)
    monkeypatch.setenv("OTEL_ENABLED", "false")  # exercise NoOp branch; spans still captured via otel_state


def _spans_named(otel_state, name):
    return [s for s in otel_state.span_exporter.get_finished_spans() if s.name == name]


def _one_span_named(otel_state, name):
    spans = _spans_named(otel_state, name)
    assert len(spans) == 1, f"expected exactly one {name!r} span, got {len(spans)}"
    return spans[0]


@pytest.fixture
def scripted_session(monkeypatch):
    mealie_raw_items = [
        {"food": {"name": "Chicken Breast"}, "quantity": 2, "unit": None, "checked": False, "display": "Chicken Breast"},
        {"food": {"name": "Flour"}, "quantity": 500, "unit": {"name": "g"}, "checked": False, "display": "Flour g (500)"},
        {"food": {"name": "Milk"}, "quantity": 1, "unit": {"name": "l"}, "checked": True, "display": "Milk l (1)"},
    ]
    dest_items = [
        {"summary": "Ketchup [Mealie]", "status": "needs_action"},
        {"summary": "Chicken Breast (3)", "status": "needs_action"},
        {"summary": "Toilet Paper", "status": "needs_action"},
    ]
    mealie_ha_items = [
        {"summary": "Chicken Breast (2)", "status": "needs_action"},
        {"summary": "Flour g (500)", "status": "needs_action"},
    ]
    fake_session = _FakeSession(mealie_raw_items, dest_items, mealie_ha_items)
    monkeypatch.setattr(ha_client.requests, "Session", lambda: fake_session)
    return fake_session


def test_main_happy_path_traces_and_orchestrates_correctly(monkeypatch, otel_state, scripted_session):
    _set_required_env(monkeypatch)

    sync.main()

    root = _one_span_named(otel_state, "meal_plan_sync")
    assert root.status.status_code == StatusCode.OK
    assert root.attributes["ingredients.count"] == 2

    phase1 = _one_span_named(otel_state, "sync.fetch_mealie_list")
    assert phase1.attributes["mealie.items.total"] == 3
    assert phase1.attributes["mealie.items.unchecked"] == 2
    assert list(phase1.attributes["mealie.items"]) == ["Chicken Breast", "Flour"]

    phase2 = _one_span_named(otel_state, "sync.fetch_destination_list")
    assert phase2.attributes["destination.items.total"] == 3
    assert phase2.attributes["destination.items.active"] == 3

    phase3 = _one_span_named(otel_state, "sync.cleanup_tagged_items")
    assert phase3.attributes["items.removed"] == 1
    assert list(phase3.attributes["cleanup.items"]) == ["Ketchup [Mealie]"]

    phase4 = _one_span_named(otel_state, "sync.match_and_merge")
    assert phase4.attributes["items.added"] == 2
    assert phase4.attributes["items.merged"] == 1
    assert list(phase4.attributes["match.added.items"]) == ["Flour g (500) [Mealie]"]
    assert list(phase4.attributes["match.merged.items"]) == ["Chicken Breast: 3 + 2 = 5"]

    phase5 = _one_span_named(otel_state, "sync.complete_mealie_items")
    assert phase5.attributes["items.completed"] == 2

    # Central assertion: every ha.remove_item/ha.add_item span parents to the
    # correct phase span — including phase 4's threaded calls, where this only
    # holds because of sync.py's contextvars.copy_context().run(...) wrapper.
    remove_spans = _spans_named(otel_state, "ha.remove_item")
    add_spans = _spans_named(otel_state, "ha.add_item")
    assert len(remove_spans) == 4  # phase3: 1, phase4: 1, phase5: 2
    assert len(add_spans) == 2  # phase4: 2

    def parent_span_id(span):
        assert span.parent is not None, f"{span.name} ({span.attributes.get('item.name')}) is unexpectedly parentless"
        return span.parent.span_id

    phase3_removes = [s for s in remove_spans if s.attributes.get("item.name") == "Ketchup [Mealie]"]
    assert len(phase3_removes) == 1
    assert parent_span_id(phase3_removes[0]) == phase3.context.span_id

    phase4_removes = [s for s in remove_spans if s.attributes.get("item.name") == "Chicken Breast (3)"]
    assert len(phase4_removes) == 1
    assert parent_span_id(phase4_removes[0]) == phase4.context.span_id

    for add_span in add_spans:
        assert parent_span_id(add_span) == phase4.context.span_id

    phase5_removes = [
        s for s in remove_spans
        if s.attributes.get("item.name") in ("Chicken Breast (2)", "Flour g (500)")
    ]
    assert len(phase5_removes) == 2
    for span in phase5_removes:
        assert parent_span_id(span) == phase5.context.span_id


def test_main_ping_failure_sets_root_error_and_exits(monkeypatch, otel_state):
    _set_required_env(monkeypatch)
    monkeypatch.setattr(ha_client.requests, "Session", lambda: _AlwaysFailingSession())

    with pytest.raises(SystemExit) as exc_info:
        sync.main()
    assert exc_info.value.code == 1

    root = _one_span_named(otel_state, "meal_plan_sync")
    assert root.status.status_code == StatusCode.ERROR
    assert any(e.name == "exception" for e in root.events)

    ping_span = _one_span_named(otel_state, "ha.ping")
    assert ping_span.status.status_code == StatusCode.ERROR
    assert any(e.name == "exception" for e in ping_span.events)


def test_main_missing_required_env_var_exits(monkeypatch, otel_state):
    monkeypatch.setenv("HA_TOKEN", HA_TOKEN)
    monkeypatch.setenv("MEALIE_TODO_ENTITY", MEALIE_ENTITY)
    monkeypatch.setenv("DESTINATION_TODO_ENTITY", DEST_ENTITY)
    # HA_URL deliberately left unset

    with pytest.raises(SystemExit) as exc_info:
        sync.main()
    assert exc_info.value.code == 1
    assert _spans_named(otel_state, "meal_plan_sync") == []


def test_main_invalid_item_tag_position_exits(monkeypatch, otel_state, scripted_session):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ITEM_TAG_POSITION", "middle")

    with pytest.raises(SystemExit) as exc_info:
        sync.main()
    assert exc_info.value.code == 1
    assert _spans_named(otel_state, "meal_plan_sync") == []
