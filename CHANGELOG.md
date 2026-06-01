# Changelog

## v1.0.0 — 2026-06-01

Initial stable release. Core sync loop is proven in production.

- Fetches unchecked Mealie shopping list items and syncs them into any HA todo entity
- Quantity merging: combines duplicate items from separate recipes
- Optional item tagging with configurable prefix or suffix
- Marks Mealie items complete after each sync to prevent re-appearance
- Full OpenTelemetry instrumentation with Jaeger-compatible trace export
- Docker Compose stack with OTel Collector and Jaeger for local development
- CI: Python 3.11/3.12/3.13 matrix, pip-audit CVE scanning, Trivy container scanning, weekly Dependabot updates
- Release workflow: auto-tags on merge to main using [PATCH]/[MINOR]/[MAJOR] tokens; Dependabot merges skipped
