"""
mealie-ha-todo-sync — main entrypoint.

Syncs ingredients from the Mealie shopping list (via HA service calls) into
any Home Assistant todo entity, with full OpenTelemetry distributed tracing.
"""

import os
import sys
import logging

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace import NoOpTracerProvider

from ha_client import HAClient
from diff import (
    IngredientItem,
    filter_tagged,
    normalise_dest_name,
    parse_dest_quantity,
    parse_mealie_item,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        log.error("Required environment variable %s is not set", name)
        sys.exit(1)
    return value


def _setup_tracing() -> None:
    if os.getenv("OTEL_ENABLED", "true").lower() in ("false", "0", "no"):
        trace.set_tracer_provider(NoOpTracerProvider())
        log.info("OTEL_ENABLED=false — tracing disabled")
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    # Normalise: the gRPC exporter wants host:port without a scheme.
    endpoint = endpoint.removeprefix("http://").removeprefix("https://")

    resource = Resource.create({"service.name": "mealie-ha-todo-sync"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    RequestsInstrumentor().instrument()
    log.info("Tracing enabled → %s", endpoint)


def main() -> None:
    _setup_tracing()

    ha_url = _require_env("HA_URL")
    ha_token = _require_env("HA_TOKEN")
    mealie_todo_entity = _require_env("MEALIE_TODO_ENTITY")
    destination_entity = _require_env("DESTINATION_TODO_ENTITY")
    item_tag = os.getenv("ITEM_TAG", "[Mealie]")
    tag_position = os.getenv("ITEM_TAG_POSITION", "suffix").lower()

    if tag_position not in ("suffix", "prefix"):
        log.error("ITEM_TAG_POSITION must be 'suffix' or 'prefix', got: %s", tag_position)
        sys.exit(1)

    client = HAClient(ha_url, ha_token)
    tracer = trace.get_tracer("mealie-ha-todo-sync")

    with tracer.start_as_current_span("meal_plan_sync") as root:
        try:
            # 1. Confirm HA is reachable
            log.info("Pinging HA…")
            client.ping(root)
            log.info("HA reachable")

            # 2. Fetch unchecked shopping list items from Mealie via HA
            list_name = mealie_todo_entity.replace("todo.", "").replace("_", " ").title()
            log.info("Fetching shopping list items for %s…", mealie_todo_entity)
            raw_items = client.get_shopping_list_items(mealie_todo_entity, list_name, root)
            unchecked_raw = [r for r in raw_items if r.get("checked") is not True]
            ingredients = [parse_mealie_item(r) for r in unchecked_raw]
            # Keep display values as fallback for mark-complete: todo.get_items on the
            # Mealie entity can return stale cached data (0 items) immediately after
            # calling mealie.get_shopping_list_items, so we may need these as a fallback.
            mealie_displays = [
                d for r in unchecked_raw
                if (d := r.get("display") or r.get("note") or "")
            ]
            log.info("Fetched %d unchecked ingredient(s)", len(ingredients))
            root.set_attribute("ingredients.count", len(ingredients))

            # 3. Fetch current destination items
            log.info("Fetching current items from destination: %s…", destination_entity)
            dest_items = client.get_destination_items(destination_entity, root)

            # 4. Remove old tagged items (cleanup / backward compat with previous deploys)
            to_remove = filter_tagged(dest_items, item_tag)
            log.info("Removing %d previously tagged item(s)…", len(to_remove))
            root.set_attribute("items.removed", len(to_remove))
            for item in to_remove:
                log.info("  - removing: %s", item.get("summary", ""))
                client.remove_item(destination_entity, item.get("summary", ""), root)

            # Build a lookup of active (untagged, unchecked) dest items by normalised name.
            # Completed items are deliberately excluded — merging quantities into a
            # checked-off item would remove it from the completed state and reinstate it.
            remaining = [
                i for i in dest_items
                if i not in to_remove
                and i.get("status") not in ("completed", "complete")
            ]
            dest_by_norm = {
                normalise_dest_name(i.get("summary", ""), item_tag): i
                for i in remaining
            }

            # 5. Add Mealie items, merging quantities where a match already exists
            log.info("Adding %d item(s) to %s…", len(ingredients), destination_entity)
            root.set_attribute("items.added", len(ingredients))
            for ingredient in ingredients:
                matched = dest_by_norm.get(ingredient.normalised_food)
                if matched:
                    dest_qty = parse_dest_quantity(matched.get("summary", ""))
                    mealie_qty = ingredient.quantity if ingredient.quantity else 1.0
                    combined_qty = dest_qty + mealie_qty
                    merged = IngredientItem(
                        food=ingredient.food,
                        quantity=combined_qty,
                        unit=ingredient.unit,
                    )
                    log.info(
                        "  ~ merging: %s (%.4g + %.4g = %.4g)",
                        ingredient.food, dest_qty, mealie_qty, combined_qty,
                    )
                    client.remove_item(destination_entity, matched.get("summary", ""), root)
                    summary = merged.format_summary(item_tag, tag_position)
                else:
                    summary = ingredient.format_summary(item_tag, tag_position)
                    log.info("  + adding: %s", summary)
                client.add_item(destination_entity, summary, root)

            # 6. Mark all Mealie items complete so they don't reappear next cycle.
            # Preferred: fetch the entity's actual items via todo.get_items so we use
            # the exact summaries HA knows about. The Mealie entity is polled on a
            # schedule so todo.get_items can return stale cached data (0 items)
            # immediately after calling mealie.get_shopping_list_items; fall back to
            # the display values captured from the service response when that happens.
            mealie_ha_items = client.get_destination_items(mealie_todo_entity, root)
            to_complete = [
                i for i in mealie_ha_items
                if i.get("status") not in ("completed", "complete")
            ]
            if not to_complete and mealie_displays:
                log.info(
                    "HA entity shows 0 unchecked items (stale cache); "
                    "using Mealie display values as fallback"
                )
                to_complete = [{"summary": d} for d in mealie_displays]
            log.info("Marking %d item(s) as complete in %s…", len(to_complete), mealie_todo_entity)
            root.set_attribute("items.completed", len(to_complete))
            mark_failed = 0
            for item in to_complete:
                summary = item.get("summary", "")
                log.info("  ✓ complete: %s", summary)
                try:
                    client.mark_item_complete(mealie_todo_entity, summary, root)
                except Exception as exc:
                    log.warning("  ! failed to mark complete: %s — %s", summary, exc)
                    mark_failed += 1
            if mark_failed:
                log.warning(
                    "%d item(s) could not be marked complete — they may reappear next sync",
                    mark_failed,
                )

            root.set_status(Status(StatusCode.OK))
            log.info("Sync complete.")

        except Exception as exc:
            root.set_status(Status(StatusCode.ERROR, str(exc)))
            root.record_exception(exc)
            log.error("Sync failed: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
