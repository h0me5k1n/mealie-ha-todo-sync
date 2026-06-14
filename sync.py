"""
mealie-ha-todo-sync — main entrypoint.

Syncs ingredients from the Mealie shopping list (via HA service calls) into
any Home Assistant todo entity, with full OpenTelemetry distributed tracing.
"""

import contextvars
import os
import sys
import logging
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
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
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
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
            # Phase 1: Confirm HA is reachable and fetch Mealie shopping list
            list_name = mealie_todo_entity.replace("todo.", "").replace("_", " ").title()
            with tracer.start_as_current_span("sync.fetch_mealie_list") as phase1:
                log.info("Pinging HA…")
                client.ping()
                log.info("HA reachable")
                log.info("Fetching shopping list items for %s…", mealie_todo_entity)
                raw_items = client.get_shopping_list_items(mealie_todo_entity, list_name)
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
                phase1.set_attribute("mealie.items.total", len(raw_items))
                phase1.set_attribute("mealie.items.unchecked", len(unchecked_raw))
                phase1.set_attribute("mealie.items", [i.food for i in ingredients])
            root.set_attribute("ingredients.count", len(ingredients))

            # Phase 2: Fetch current destination items
            with tracer.start_as_current_span("sync.fetch_destination_list") as phase2:
                log.info("Fetching current items from destination: %s…", destination_entity)
                dest_items = client.get_destination_items(destination_entity)
                active_dest = [
                    i for i in dest_items
                    if i.get("status") not in ("completed", "complete")
                ]
                phase2.set_attribute("destination.items.total", len(dest_items))
                phase2.set_attribute("destination.items.active", len(active_dest))
                phase2.set_attribute("destination.items", [i.get("summary", "") for i in active_dest])

            # Phase 3: Remove old tagged items (cleanup / backward compat with previous deploys)
            with tracer.start_as_current_span("sync.cleanup_tagged_items") as phase3:
                to_remove = filter_tagged(dest_items, item_tag)
                log.info("Removing %d previously tagged item(s)…", len(to_remove))
                phase3.set_attribute("items.removed", len(to_remove))
                phase3.set_attribute("cleanup.items", [i.get("summary", "") for i in to_remove])
                for item in to_remove:
                    log.info("  - removing: %s", item.get("summary", ""))
                    client.remove_item(destination_entity, item.get("summary", ""), reason="tag_cleanup")

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

            # Phase 4: Add Mealie items, merging quantities where a match already exists.
            # Pre-compute all operations first (no API calls), then run removes and adds
            # concurrently — items are independent so there is no ordering constraint
            # across them. contextvars.copy_context() propagates the OTel span context
            # into each worker thread so child spans are correctly parented.
            with tracer.start_as_current_span("sync.match_and_merge") as phase4:
                log.info("Adding %d item(s) to %s…", len(ingredients), destination_entity)
                to_remove: list[str] = []
                to_add: list[str] = []
                merged_items: list[str] = []
                added_items: list[str] = []

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
                        to_remove.append(matched.get("summary", ""))
                        summary = merged.format_summary(item_tag, tag_position)
                        merged_items.append(
                            f"{ingredient.food}: {dest_qty:.4g} + {mealie_qty:.4g} = {combined_qty:.4g}"
                        )
                    else:
                        summary = ingredient.format_summary(item_tag, tag_position)
                        log.info("  + adding: %s", summary)
                        added_items.append(summary)
                    to_add.append(summary)

                otel_ctx = contextvars.copy_context()
                with ThreadPoolExecutor() as executor:
                    futs = [
                        executor.submit(otel_ctx.run, client.remove_item, destination_entity, s, "merge")
                        for s in to_remove
                    ]
                    for f in futs:
                        f.result()

                with ThreadPoolExecutor() as executor:
                    futs = [
                        executor.submit(otel_ctx.run, client.add_item, destination_entity, s)
                        for s in to_add
                    ]
                    for f in futs:
                        f.result()

                phase4.set_attribute("items.added", len(ingredients))
                phase4.set_attribute("items.merged", len(merged_items))
                phase4.set_attribute("match.added.items", added_items)
                phase4.set_attribute("match.merged.items", merged_items)

            # Phase 5: Mark all Mealie items complete so they don't reappear next cycle.
            # Force HA to re-poll Mealie before reading the entity's items — the entity
            # is polled on a schedule and todo.get_items can return stale cached data
            # (0 items, or capitalized food names differing from the raw display field).
            with tracer.start_as_current_span("sync.complete_mealie_items") as phase5:
                log.info("Refreshing Mealie entity cache…")
                try:
                    client.refresh_entity(mealie_todo_entity)
                except Exception as exc:
                    log.warning("Entity refresh failed (%s); todo.get_items may be stale", exc)
                mealie_ha_items = client.get_destination_items(mealie_todo_entity)
                to_complete = [
                    i for i in mealie_ha_items
                    if i.get("status") not in ("completed", "complete")
                ]
                if not to_complete and mealie_displays:
                    log.info(
                        "HA entity shows 0 unchecked items after refresh; "
                        "using Mealie display values as fallback"
                    )
                    to_complete = [{"summary": d} for d in mealie_displays]
                log.info("Removing %d item(s) from %s…", len(to_complete), mealie_todo_entity)
                phase5.set_attribute("items.completed", len(to_complete))
                phase5.set_attribute("complete.items", [i.get("summary", "") for i in to_complete])
                mark_failed = 0
                for item in to_complete:
                    summary = item.get("summary", "")
                    log.info("  ✓ removing: %s", summary)
                    try:
                        client.remove_item(mealie_todo_entity, summary, reason="mealie_sync")
                    except Exception as exc:
                        log.warning("  ! failed to remove: %s — %s", summary, exc)
                        mark_failed += 1
                if mark_failed:
                    log.warning(
                        "%d item(s) could not be removed — they may reappear next sync",
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
