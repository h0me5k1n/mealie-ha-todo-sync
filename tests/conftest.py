from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
import requests
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass
class OtelTestState:
    span_exporter: InMemorySpanExporter


@pytest.fixture(scope="session")
def otel_state():
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)  # must be the first set() in the session
    return OtelTestState(span_exporter)


@pytest.fixture(autouse=True)
def _clear_spans(otel_state):
    otel_state.span_exporter.clear()


@pytest.fixture(autouse=True)
def _clean_sync_env(monkeypatch):
    # sync.py calls load_dotenv() at import time, and this repo has a real
    # (gitignored) .env with OTEL_ENABLED=false and empty required vars.
    # load_dotenv() doesn't override already-set env vars, but it does
    # populate os.environ from the file on first import in a fresh process —
    # so every test must start from a clean slate rather than relying on
    # unset-by-default.
    for name in (
        "HA_URL",
        "HA_TOKEN",
        "MEALIE_TODO_ENTITY",
        "DESTINATION_TODO_ENTITY",
        "ITEM_TAG",
        "ITEM_TAG_POSITION",
        "OTEL_ENABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)


def make_response(status_code: int = 200, body: object = None) -> requests.Response:
    """Build a real requests.Response so .json()/.raise_for_status() behave exactly
    like the real thing (auto-populates HTTPError.response on error statuses)."""
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(body if body is not None else {}).encode()
    return resp
