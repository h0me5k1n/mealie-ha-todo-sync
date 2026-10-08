# mealie-ha-todo-sync

Syncs ingredients from a Mealie meal plan into any Home Assistant todo list entity — OurGroceries, Bring!, Todoist, the native HA shopping list, or any other todo integration you have configured.

Every HA API call is instrumented with OpenTelemetry, producing a full distributed trace per sync run that you can export to any OTLP-compatible collector.

---

## How it works

1. Fetches unchecked shopping list items from Mealie via `mealie.get_shopping_list_items`
2. Fetches current items from the destination todo entity via `todo.get_items`
3. Removes any destination items carrying the configured tag (backward-compat cleanup — see [Item tagging](#item-tagging))
4. For each Mealie item, checks whether a matching item already exists in the destination:
   - **Match found:** removes the existing item, combines the quantities, adds the merged item
   - **No match:** adds the item as-is
5. Removes all synced items from the Mealie shopping list so they don't reappear on the next cycle

Items are formatted as `food [unit] (qty)` — for example `chicken breast (5)` or `flour gram (100)`.

All HA traffic goes through the standard REST API (`/api/services/…`). No HA-specific Python libraries are used, so OpenTelemetry auto-instrumentation wraps real HTTP calls and produces genuine latency and error data in traces.

### Ingredient requirement: parsed ingredients in Mealie

Quantity consolidation across recipes is handled by Mealie's shopping list engine — **not by this script**. This only works correctly when ingredients are stored as parsed structured data (food + quantity + unit) rather than free-text notes. If a recipe's ingredients were entered or imported as free text, Mealie cannot consolidate them and they will appear as separate line items.

---

## Known limitations

### Quantity embedded in the food name

Some items in Mealie have the quantity baked into the food name rather than stored in the structured `quantity`/`unit` fields — for example `50g Parmesan` or `2 tins chopped tomatoes`. This happens when:

- The recipe was imported and Mealie could not parse the ingredient into structured data
- The ingredient was entered as a free-text note

The script cannot distinguish these from plain food names, so they appear verbatim in the destination list (e.g. `50g Parmesan`) with no quantity merging. The only fix is to edit those ingredients in Mealie so they have properly structured food + quantity + unit fields.

### Duplicate lines from the same sync batch

If two recipes both include "chicken breast" and Mealie keeps them as separate shopping list entries, the script adds both to the destination in the same run — resulting in two lines (`chicken breast (2)` and `chicken breast (3)`) rather than one merged line (`chicken breast (5)`). The merge logic only combines a new Mealie item with an item that was already present in the destination from a *previous* sync. On the following sync the two lines will be merged if they are still there.

The correct fix is to ensure Mealie consolidates quantities in its own shopping list before the sync runs — this is the shopping list engine's responsibility and works reliably when ingredients are stored as structured data.

---

## Item tagging

Item tagging is optional (default is no tag). When set, every item written to the destination entity carries the tag, which allows the script to identify and clean up its own items from previous deploys. The default format is a suffix:

```
chicken breast (5) [Mealie]
flour gram (100) [Mealie]
```

You can switch to a prefix by setting `ITEM_TAG_POSITION=prefix`:

```
[Mealie] chicken breast (5)
[Mealie] flour gram (100)
```

On each sync run the script removes all destination items carrying the tag in **either** position. This means changing `ITEM_TAG_POSITION` after an initial sync will not leave orphaned items. Manually added items (no tag) are never touched.

Since the script now removes synced items from the Mealie shopping list after each run (step 5 above), tagging is no longer required for correctness — items won't reappear regardless. Set `ITEM_TAG` only if you want to be able to visually distinguish script-managed items in your destination list.

---

## Finding your entity IDs

1. Open Home Assistant
2. Go to **Developer Tools → States**
3. Filter by `todo.` in the Entity ID column
4. Mealie shopping lists appear as `todo.mealie_<list_name>` (requires the official [Mealie integration](https://www.home-assistant.io/integrations/mealie/))
5. Your destination list could be `todo.shopping_list`, `todo.ourgroceries_<list>`, `todo.bring`, etc.

---

## Creating a HA long-lived access token

1. Open Home Assistant
2. Go to your **Profile** (bottom-left avatar)
3. Scroll to **Security → Long-Lived Access Tokens**
4. Click **Create Token**, give it a name (e.g. `mealie-sync`), and copy the value
5. Store it in your `.env` file as `HA_TOKEN`

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

| Variable | Required | Default | Description |
|---|---|---|---|
| `HA_URL` | yes | — | HA base URL, e.g. `http://homeassistant.local:8123` |
| `HA_TOKEN` | yes | — | HA long-lived access token |
| `MEALIE_TODO_ENTITY` | yes | — | Mealie shopping list entity, e.g. `todo.mealie_weekly_shopping` |
| `DESTINATION_TODO_ENTITY` | yes | — | Destination todo entity, e.g. `todo.shopping_list` |
| `ITEM_TAG` | no | `` (empty) | Tag string appended/prepended to each synced item; leave empty for no tag |
| `ITEM_TAG_POSITION` | no | `suffix` | `suffix` or `prefix` |
| `OTEL_ENABLED` | no | `false` | Set to `true` to enable tracing — requires an OTLP collector reachable at `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | `localhost:4317` | OTel Collector gRPC endpoint (host:port, no scheme) — ignored when `OTEL_ENABLED=false` |

---

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your values

python sync.py
```

The script exits after a single sync. Schedule it with `cron` or a systemd timer if you want recurring syncs:

```
# crontab entry — sync every 15 minutes
*/15 * * * * /path/to/.venv/bin/python /path/to/sync.py >> /var/log/mealie-sync.log 2>&1
```

Without an OTel Collector running, the exporter will log an error but the sync will still complete.

---

## Running with Docker

```bash
cp .env.example .env
# edit .env with your values

docker compose up --build
```

This starts a single **sync** container that runs the sync script once. There's
no bundled tracing backend — set `OTEL_ENABLED=true` and
`OTEL_EXPORTER_OTLP_ENDPOINT` in `.env` to export traces to a collector of
your own (each span records HTTP status code, item counts, and errors as
span events).

### Scheduling recurring syncs in Docker

The `sync` service runs once and exits. To run on a schedule inside Docker, edit `docker-compose.yml` and uncomment the `command` override:

```yaml
command: ["sh", "-c", "while true; do python sync.py; sleep 300; done"]
```

Or run the `sync` container on-demand from the host:

```bash
docker compose run --rm sync
```

---

## Project structure

```
sync.py                    # Main entrypoint
ha_client.py               # HA REST API wrapper with OTel instrumentation
diff.py                    # Ingredient parsing and tag logic
tests/
  conftest.py              # Shared OTel in-memory span exporter + env-cleanup fixtures
  test_diff.py             # Unit tests for diff.py
  test_ha_client.py        # HAClient span/attribute/error-path coverage
  test_sync_tracing.py     # _setup_tracing() branch coverage (NoOp vs real provider)
  test_sync_main.py        # End-to-end main() flow, including span-parenting across threads
requirements.in            # Direct dependencies (edit this one)
requirements.txt           # Pinned lockfile generated from requirements.in by pip-compile
.env.example
Dockerfile
docker-compose.yml
```

---

## Running tests

```bash
pip install -r requirements.txt
pytest tests/
```

---

## Dependencies

`requirements.in` lists the direct dependencies. `requirements.txt` is a lockfile generated from it by [pip-compile](https://pip-tools.readthedocs.io/), with every package — including transitive ones such as `grpcio` and `protobuf` — pinned to an exact version. CI, the Docker image and any deployment that runs `pip install -r requirements.txt` therefore all install the same set, and a version only changes through a PR that CI has tested.

Don't edit `requirements.txt` by hand. To add or change a dependency, edit `requirements.in` and regenerate the lockfile with Python 3.12:

```bash
pip install pip-tools
pip-compile --strip-extras --output-file=requirements.txt requirements.in
```

Add `--upgrade` to move everything to the latest versions that `requirements.in` allows. Dependabot does this weekly and opens a single PR with all Python updates (see `.github/dependabot.yml`).

---

## Versioning & Releases

Merging a normal PR to `main` automatically creates a new [GitHub Release](https://github.com/h0me5k1n/mealie-ha-todo-sync/releases) and git tag using [semantic versioning](https://semver.org/).

Dependabot PRs are the exception: merging one doesn't trigger an immediate release. Dependency updates arrive grouped (all Python updates in one PR, github-actions bumps in another — see `.github/dependabot.yml`), and are batched into a single release cut by a scheduled job each Wednesday — or no release at all if nothing merged that week.

### Controlling the version bump

The bump is worked out from the commit messages merged since the last tag, using the [Conventional Commits](https://www.conventionalcommits.org/) format (the release workflow uses [`mathieudutour/github-tag-action`](https://github.com/mathieudutour/github-tag-action)). The highest match wins:

| Commit message | Bump |
|---|---|
| `feat!: ...`, `fix!: ...`, or a `BREAKING CHANGE:` footer | major — breaking changes |
| `feat: ...` | minor — new backwards-compatible features |
| `fix: ...` | patch — bug fixes |
| *(anything else)* | patch (default) |

A scope is allowed, e.g. `fix(otel): ...`. When a PR is squash-merged the PR title becomes the commit message, so the title is what decides the bump.

The PR template includes this guidance when you open a PR.

### Pinning a specific version

To run a specific release rather than the latest code, check out the tag after cloning:

```bash
git clone https://github.com/h0me5k1n/mealie-ha-todo-sync.git
cd mealie-ha-todo-sync
git checkout v1.0.0
```

If you deploy via an automation tool that clones this repo (e.g. Ansible's `git` module), pass the tag or branch name as the `version` parameter — both are accepted without any special handling.

---

## To do

### Auto-merge the weekly dependency PR

The weekly Dependabot PR is still merged by hand. It can be auto-merged once CI is able to catch the failures the current tests can't:

- [ ] **Add a smoke test to CI.** The existing tests are unit tests with HA and the OTLP exporter mocked, so they would not catch a dependency update that breaks the real HTTP calls or the gRPC trace export. The smoke test should run `sync.py` end to end against:
  - a **stubbed Home Assistant** — a small HTTP server that answers the REST endpoints `ha_client.py` calls (`/api/` ping, the Mealie `get_shopping_list_items` service, and the `todo` `get_items` / `add_item` / `remove_item` / `update_item` services) and records what it received, so the test can assert that the expected items were written;
  - a **stubbed OTel endpoint** — an OpenTelemetry Collector container (or a minimal OTLP/gRPC receiver) that the sync exports to, so the test can assert that a `meal_plan_sync` trace actually arrived.
- [ ] **Make the security checks required.** Add `pip-audit (dependency CVEs)` and `Trivy (container image scan)` to the required status checks on `main`, alongside the three test jobs and the new smoke test.
- [ ] **Enable auto-merge for the Dependabot PR.** Turn on "Allow auto-merge" in the repo settings and add a workflow that enables auto-merge (squash) on PRs opened by Dependabot, so the weekly PR merges itself when every required check passes. Consider leaving major-version bumps for manual review.
