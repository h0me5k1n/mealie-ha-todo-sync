from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import NoOpTracerProvider

import sync


def test_setup_tracing_disabled_installs_noop_provider(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "false")
    captured = {}
    monkeypatch.setattr(sync.trace, "set_tracer_provider", lambda p: captured.setdefault("tp", p))
    monkeypatch.setattr(sync, "_tracer_provider", object())  # ensure it gets cleared

    sync._setup_tracing()

    assert isinstance(captured["tp"], NoOpTracerProvider)
    # Nothing to flush when tracing is disabled.
    assert sync._tracer_provider is None


def test_setup_tracing_enabled_builds_real_provider(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    captured = {}
    monkeypatch.setattr(sync.trace, "set_tracer_provider", lambda p: captured.setdefault("tp", p))

    sync._setup_tracing()

    try:
        assert isinstance(captured["tp"], TracerProvider)
        # Recorded so main() can flush it on the way out.
        assert sync._tracer_provider is captured["tp"]
    finally:
        captured["tp"].shutdown()
        monkeypatch.setattr(sync, "_tracer_provider", None, raising=False)
