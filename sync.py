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
from diff import filter_tagged, parse_mealie_item

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
            # 1. Fetch the meal plan (informational — confirms Mealie is alive)
            log.info("Fetching meal plan from HA…")
            meal_plan = client.get_meal_plan(root)
            log.info("Meal plan fetched (%s entries)", len(meal_plan) if isinstance(meal_plan, list) else "?")

            # 2. Fetch structured shopping list items from Mealie via HA
            list_name = mealie_todo_entity.replace("todo.", "").replace("_", " ").title()
            log.info("Fetching shopping list items for %s…", mealie_todo_entity)
            raw_items = client.get_shopping_list_items(mealie_todo_entity, list_name, root)
            ingredients = [parse_mealie_item(r) for r in raw_items if r.get("checked") is not True]
            log.info("Fetched %d unchecked ingredient(s)", len(ingredients))
            root.set_attribute("ingredients.count", len(ingredients))

            # 3. Fetch current destination items
            log.info("Fetching current items from destination: %s…", destination_entity)
            dest_items = client.get_destination_items(destination_entity, root)

            # 4. Remove all previously synced items (tagged in either position)
            to_remove = filter_tagged(dest_items, item_tag)
            log.info("Removing %d previously synced item(s)…", len(to_remove))
            root.set_attribute("items.removed", len(to_remove))
            for item in to_remove:
                summary = item.get("summary", "")
                log.info("  - removing: %s", summary)
                client.remove_item(destination_entity, summary, root)

            # 5. Add current Mealie items to destination
            log.info("Adding %d item(s) to %s…", len(ingredients), destination_entity)
            root.set_attribute("items.added", len(ingredients))
            for ingredient in ingredients:
                summary = ingredient.format_summary(item_tag, tag_position)
                log.info("  + adding: %s", summary)
                client.add_item(destination_entity, summary, root)

            root.set_status(Status(StatusCode.OK))
            log.info("Sync complete.")

        except Exception as exc:
            root.set_status(Status(StatusCode.ERROR, str(exc)))
            root.record_exception(exc)
            log.error("Sync failed: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
