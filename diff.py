"""
Ingredient comparison and item tag logic.

Tag detection intentionally checks both suffix and prefix positions regardless
of the current ITEM_TAG_POSITION setting, so that items written under a previous
configuration are cleaned up correctly even after the position is changed.
"""

import re
from dataclasses import dataclass


@dataclass
class IngredientItem:
    food: str           # raw food name from Mealie
    quantity: float | None
    unit: str | None    # e.g. "g", "kg", "tsp", "tbsp", "" for unitless

    @property
    def normalised_food(self) -> str:
        """Lowercase, singular food name for deduplication comparisons."""
        name = self.food.lower().strip()
        # Strip a trailing 's' only when the word is longer than 3 chars to
        # avoid mangling words like "peas" → "pea" or "oats" → "oat".
        # This is intentionally simple; Mealie's own consolidation is the
        # authoritative deduplication step.
        if len(name) > 3 and name.endswith("s") and not name.endswith("ss"):
            name = name[:-1]
        return name

    def format_summary(self, tag: str, tag_position: str) -> str:
        """Build the todo item summary string with quantity, unit, and tag."""
        parts = []
        if self.quantity is not None and self.quantity != 0:
            qty_str = (
                str(int(self.quantity))
                if self.quantity == int(self.quantity)
                else f"{self.quantity:g}"
            )
            parts.append(qty_str)
        if self.unit:
            parts.append(self.unit)
        parts.append(self.food)

        text = " ".join(parts)
        if tag_position == "prefix":
            return f"{tag} {text}"
        return f"{text} {tag}"


def has_tag(summary: str, tag: str) -> bool:
    """Return True if the summary carries the tag in either position."""
    escaped = re.escape(tag)
    return bool(
        re.search(rf"^{escaped}\s", summary)
        or re.search(rf"\s{escaped}$", summary)
    )


def filter_tagged(items: list[dict], tag: str) -> list[dict]:
    """Return only the todo items that carry the tag (in either position)."""
    return [item for item in items if has_tag(item.get("summary", ""), tag)]


def parse_mealie_item(raw: dict) -> IngredientItem:
    """Convert a raw Mealie shopping list item dict into an IngredientItem."""
    food = (raw.get("food") or {}).get("name") or raw.get("note") or ""
    quantity = raw.get("quantity")
    unit_obj = raw.get("unit") or {}
    unit = unit_obj.get("name") if isinstance(unit_obj, dict) else None
    return IngredientItem(food=food, quantity=quantity, unit=unit)
