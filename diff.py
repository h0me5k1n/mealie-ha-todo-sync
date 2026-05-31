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
        """Build the todo item summary string.

        Unit (if any) follows the food name; quantity in parentheses at the end:
            chicken breast (2)
            flour g (500)
        """
        base = f"{self.food} {self.unit}" if self.unit else self.food
        if self.quantity is not None and self.quantity != 0:
            qty_str = (
                str(int(self.quantity))
                if self.quantity == int(self.quantity)
                else f"{self.quantity:g}"
            )
            text = f"{base} ({qty_str})"
        else:
            text = base

        if not tag:
            return text
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
    if not tag:
        return []
    return [item for item in items if has_tag(item.get("summary", ""), tag)]


# Common cooking unit abbreviations used to detect the unit token in synced items.
# "flour g (500)" → unit token "g" is stripped so the food name "flour" is isolated.
_COOKING_UNITS: frozenset[str] = frozenset({
    "g", "kg", "mg",
    "ml", "l", "dl", "cl",
    "tsp", "tbsp", "cup", "cups",
    "oz", "lb", "lbs",
    "piece", "pieces", "pcs", "pc",
    "slice", "slices",
    "can", "cans",
    "bunch", "bunches",
    "clove", "cloves",
    "sprig", "sprigs",
    "head", "heads",
    "stalk", "stalks",
    "sheet", "sheets",
    "pinch",
})


def normalise_dest_name(summary: str, tag: str) -> str:
    """Strip tag, unit, and quantity from a destination item summary for matching.

    Handles:
    - manually-added items: "2 chicken breasts" → "chicken breast"
    - synced unitless items: "chicken breast (2)" → "chicken breast"
    - synced items with unit: "flour g (500)" → "flour"
    """
    text = summary.strip()
    if tag:
        escaped = re.escape(tag)
        text = re.sub(rf"^{escaped}\s+", "", text)
        text = re.sub(rf"\s+{escaped}$", "", text).strip()
    # Strip leading number (manually-added format: "2 chicken breasts")
    text = re.sub(r"^\d+(?:\.\d+)?\s+", "", text)
    # Strip "unit (qty)" suffix when the word before the parens is a known unit
    m = re.match(r"^(.*?)\s+(\S+)\s+\(\d[^)]*\)\s*$", text)
    if m and m.group(2).lower() in _COOKING_UNITS:
        text = m.group(1)
    else:
        # Strip plain "(qty)" suffix (unitless synced format: "chicken breast (2)")
        text = re.sub(r"\s+\(\d[^)]*\)\s*$", "", text)
    text = text.lower().strip()
    if len(text) > 3 and text.endswith("s") and not text.endswith("ss"):
        text = text[:-1]
    return text


def parse_dest_quantity(summary: str) -> float:
    """Return the numeric quantity from a summary string, or 1.0.

    Handles:
    - synced items: "chicken breast (2)" or "flour g (500)" → number from parens
    - manually-added items: "2 chicken breasts" → leading number
    """
    text = summary.strip()
    # Try parenthesised suffix first (synced format)
    match = re.search(r"\((\d+(?:\.\d+)?)\)", text)
    if match:
        return float(match.group(1))
    # Fall back to leading number (manually-added format: "2 chicken breasts")
    match = re.match(r"^(\d+(?:\.\d+)?)\s+", text)
    return float(match.group(1)) if match else 1.0


def parse_mealie_item(raw: dict) -> IngredientItem:
    """Convert a raw Mealie shopping list item dict into an IngredientItem."""
    food = (raw.get("food") or {}).get("name") or raw.get("note") or ""
    quantity = raw.get("quantity")
    unit_obj = raw.get("unit") or {}
    unit = unit_obj.get("name") if isinstance(unit_obj, dict) else None
    return IngredientItem(food=food, quantity=quantity, unit=unit)
