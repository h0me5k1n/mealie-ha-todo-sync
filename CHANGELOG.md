# Changelog

## v1.1.1 — 2026-06-01

### [1.1.1](https://github.com/h0me5k1n/mealie-ha-todo-sync/compare/v1.1.0...v1.1.1) (2026-06-01)


### Bug Fixes

* move CHANGELOG update to PR workflow to avoid pushing to protected main ([78fe739](https://github.com/h0me5k1n/mealie-ha-todo-sync/commit/78fe7399eb8a741b0fe4d4b0e1d729c1bc37c1ad))



## v1.0.0 — 2026-06-01

Initial stable release. Core sync loop is proven in production.

- Fetches unchecked Mealie shopping list items and syncs them into any HA todo entity
- Quantity merging: combines duplicate items from separate recipes
- Optional item tagging with configurable prefix or suffix
- Marks Mealie items complete after each sync to prevent re-appearance
- Full OpenTelemetry instrumentation with Jaeger-compatible trace export
- Docker Compose stack with OTel Collector and Jaeger for local development
- CI: Python 3.11/3.12/3.13 matrix, pip-audit CVE scanning, Trivy container scanning, weekly Dependabot updates

