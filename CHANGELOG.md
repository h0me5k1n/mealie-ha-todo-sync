# Changelog

## Unreleased

- certifi bumped to 2026.10.23: the previous version trusted emSign root CAs whose intermediate CA keys were compromised (GHSA-6q48-6c7w-9gw2)
- Docker builds no longer copy `.env`, `.venv`, `.git` or test files into the image; a locally built image previously contained the `.env` secrets

- Home Assistant requests now time out (5s connect, 30s read) instead of waiting forever; a stalled connection previously hung the run indefinitely and blocked every later timer-triggered sync

- Dependencies are now pinned: `requirements.in` holds the direct dependencies and `requirements.txt` is a pip-compile lockfile with exact versions, so CI and deployments install the same set
- Dependabot opens a single weekly PR for all Python updates
- Minimum versions raised: OpenTelemetry 1.45 / 0.66b0, python-dotenv 1.2.4

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
