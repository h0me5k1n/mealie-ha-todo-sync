# mealie-ha-todo-sync

One-shot Python script that syncs a Mealie shopping list (exposed as a Home Assistant todo entity) into another HA todo entity over the HA REST API. It exits after one sync; scheduling is external (systemd timer, cron). Traces are exported over OTLP/gRPC.

- `sync.py` — entrypoint, tracing setup, sync flow
- `ha_client.py` — HA REST wrapper with OTel spans
- `diff.py` — ingredient parsing and item tagging

## Commands

```bash
pip install -r requirements.txt
pytest tests/                                   # all tests
python -m compileall sync.py ha_client.py diff.py
```

CI runs the tests on Python 3.11, 3.12 and 3.13. Deployments and the Docker image use 3.12.

## Dependencies

- `requirements.in` holds direct dependencies; `requirements.txt` is a pip-compile lockfile. Never edit `requirements.txt` by hand.
- Regenerate with Python 3.12: `pip-compile --strip-extras --output-file=requirements.txt requirements.in`
- Dependabot opens one grouped PR per week for Python updates.

## Tests

- Tests are unit tests: HA is mocked and spans go to an in-memory exporter (`tests/conftest.py`). They do not exercise real HTTP or gRPC export, so a dependency change that passes CI can still break at runtime — see "To do" in the README.
- `sync.py` calls `load_dotenv()` at import time; `conftest.py` clears the relevant env vars so a local `.env` doesn't leak into tests. Keep that in mind when adding config.

## Commits, PRs and releases

- Every merge to `main` cuts a release, except commits whose subject starts with `build(deps)`, which are batched into a weekly scheduled release. Use that prefix for dependency-only changes and keep it when squash-merging.
- Version bump is driven by commit messages (see the PR template). Default is patch.
- Update `CHANGELOG.md` for user-visible changes.
- Do not add `Co-Authored-By` trailers to commits.
- This repo is public. Never put real IP addresses, hostnames, container IDs or tokens in code, comments, commit messages, PR text or issues. `.env` is local only and must not be committed.
