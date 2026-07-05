from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import NoOpTracerProvider

import sync


def test_setup_tracing_disabled_installs_noop_provider(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "false")
    captured = {}
    monkeypatch.setattr(sync.trace, "set_tracer_provider", lambda p: captured.setdefault("tp", p))

    sync._setup_tracing()

    assert isinstance(captured["tp"], NoOpTracerProvider)


def test_setup_tracing_enabled_builds_real_provider(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    captured = {}
    monkeypatch.setattr(sync.trace, "set_tracer_provider", lambda p: captured.setdefault("tp", p))

    sync._setup_tracing()

    try:
        assert isinstance(captured["tp"], TracerProvider)
    finally:
        captured["tp"].shutdown()
