# mealie-ha-todo-sync

Syncs ingredients from a Mealie meal plan into any Home Assistant todo list entity — OurGroceries, Bring!, Todoist, the native HA shopping list, or any other todo integration you have configured.

Every HA API call is instrumented with OpenTelemetry, producing a full distributed trace per sync run that you can explore in Jaeger.

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
| `OTEL_ENABLED` | no | `true` | Set to `false` to disable tracing entirely (no collector required) |
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

## Running with Docker (includes Jaeger tracing UI)

```bash
cp .env.example .env
# edit .env with your values

docker compose up --build
```

This starts three containers:
- **sync** — runs the sync script once
- **otel-collector** — receives traces over gRPC and forwards them to Jaeger
- **jaeger** — all-in-one Jaeger instance for trace storage and UI

### Viewing traces in Jaeger

Open [http://localhost:16686](http://localhost:16686) in your browser.

1. Select `mealie-ha-todo-sync` from the **Service** dropdown
2. Click **Find Traces**
3. Click a trace to see the full span breakdown: root `meal_plan_sync` span with child spans for each HA API call

Each span records:
- HTTP status code
- Item counts (ingredients fetched, items removed/added)
- Errors as span events if any call fails

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
  test_diff.py             # Unit tests for diff.py
requirements.txt
.env.example
Dockerfile
docker-compose.yml
otel-collector-config.yaml
```

---

## Running tests

```bash
pip install -r requirements.txt
pytest tests/
```
