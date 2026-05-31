import pytest
from diff import IngredientItem, has_tag, filter_tagged, normalise_dest_name, parse_dest_quantity, parse_mealie_item


class TestHasTag:
    def test_suffix_match(self):
        assert has_tag("2 chicken breasts [Mealie]", "[Mealie]")

    def test_prefix_match(self):
        assert has_tag("[Mealie] 2 chicken breasts", "[Mealie]")

    def test_no_match(self):
        assert not has_tag("2 chicken breasts", "[Mealie]")

    def test_partial_match_not_accepted(self):
        # Tag embedded in the middle of text should not match
        assert not has_tag("2 chicken [Mealie] breasts", "[Mealie]")

    def test_custom_tag_suffix(self):
        assert has_tag("500 g flour [sync]", "[sync]")

    def test_custom_tag_prefix(self):
        assert has_tag("[sync] 500 g flour", "[sync]")

    def test_different_tag_not_matched(self):
        assert not has_tag("2 eggs [Mealie]", "[OtherTag]")


class TestFilterTagged:
    def test_returns_only_tagged(self):
        items = [
            {"summary": "2 eggs [Mealie]"},
            {"summary": "bread"},
            {"summary": "[Mealie] milk"},
        ]
        result = filter_tagged(items, "[Mealie]")
        assert len(result) == 2
        assert result[0]["summary"] == "2 eggs [Mealie]"
        assert result[1]["summary"] == "[Mealie] milk"

    def test_empty_list(self):
        assert filter_tagged([], "[Mealie]") == []

    def test_no_tagged_items(self):
        items = [{"summary": "bread"}, {"summary": "butter"}]
        assert filter_tagged(items, "[Mealie]") == []

    def test_empty_tag_returns_nothing(self):
        items = [{"summary": "bread"}, {"summary": "butter"}]
        assert filter_tagged(items, "") == []


class TestFormatSummary:
    def test_suffix_with_quantity_and_unit(self):
        item = IngredientItem(food="flour", quantity=500, unit="g")
        assert item.format_summary("[Mealie]", "suffix") == "flour g (500) [Mealie]"

    def test_prefix_with_quantity_and_unit(self):
        item = IngredientItem(food="flour", quantity=500, unit="g")
        assert item.format_summary("[Mealie]", "prefix") == "[Mealie] flour g (500)"

    def test_no_unit(self):
        item = IngredientItem(food="chicken breast", quantity=2, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "chicken breast (2) [Mealie]"

    def test_no_quantity(self):
        item = IngredientItem(food="salt", quantity=None, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "salt [Mealie]"

    def test_zero_quantity_unit_shown_without_parens(self):
        item = IngredientItem(food="pepper", quantity=0, unit="tsp")
        assert item.format_summary("[Mealie]", "suffix") == "pepper tsp [Mealie]"

    def test_float_quantity_trimmed(self):
        item = IngredientItem(food="butter", quantity=1.5, unit="tbsp")
        assert item.format_summary("[Mealie]", "suffix") == "butter tbsp (1.5) [Mealie]"

    def test_whole_float_shows_as_int(self):
        item = IngredientItem(food="eggs", quantity=3.0, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "eggs (3) [Mealie]"

    def test_empty_tag_returns_plain_text(self):
        item = IngredientItem(food="bread", quantity=None, unit=None)
        assert item.format_summary("", "suffix") == "bread"

    def test_empty_tag_with_quantity(self):
        item = IngredientItem(food="chicken breast", quantity=5.0, unit=None)
        assert item.format_summary("", "suffix") == "chicken breast (5)"


class TestNormalisedFood:
    def test_lowercase(self):
        assert IngredientItem(food="Chicken", quantity=None, unit=None).normalised_food == "chicken"

    def test_strips_trailing_s(self):
        assert IngredientItem(food="carrots", quantity=None, unit=None).normalised_food == "carrot"

    def test_preserves_short_words(self):
        # "peas" is 4 chars — trailing s should still be stripped
        assert IngredientItem(food="peas", quantity=None, unit=None).normalised_food == "pea"

    def test_preserves_double_s(self):
        assert IngredientItem(food="lass", quantity=None, unit=None).normalised_food == "lass"


class TestNormaliseDestName:
    def test_manually_added_leading_number(self):
        # "2 chicken breasts" as manually entered by user
        assert normalise_dest_name("2 chicken breasts", "") == "chicken breast"

    def test_synced_unitless(self):
        # "chicken breast (2)" from a previous sync cycle (no unit)
        assert normalise_dest_name("chicken breast (2)", "") == "chicken breast"

    def test_synced_with_unit_abbrev(self):
        # "flour g (500)" — unit abbreviation before parens
        assert normalise_dest_name("flour g (500)", "") == "flour"

    def test_synced_with_unit_full_name(self):
        # "flour gram (500)" — Mealie stores full unit names (e.g. unit.name = "gram")
        assert normalise_dest_name("flour gram (500)", "") == "flour"

    def test_synced_with_unit_and_tag(self):
        assert normalise_dest_name("flour g (500) [Mealie]", "[Mealie]") == "flour"

    def test_synced_with_tag_prefix(self):
        assert normalise_dest_name("[Mealie] chicken breast (2)", "[Mealie]") == "chicken breast"

    def test_no_quantity(self):
        assert normalise_dest_name("chicken breast", "") == "chicken breast"

    def test_multiword_food_not_mangled(self):
        # "breast" must NOT be stripped as a unit — it's part of the food name
        assert normalise_dest_name("chicken breast (2)", "") == "chicken breast"


class TestParseDestQuantity:
    def test_synced_unitless(self):
        assert parse_dest_quantity("chicken breast (2)") == 2.0

    def test_synced_with_unit(self):
        assert parse_dest_quantity("flour g (500)") == 500.0

    def test_synced_float(self):
        assert parse_dest_quantity("butter tbsp (1.5)") == 1.5

    def test_manually_added_leading_number(self):
        assert parse_dest_quantity("2 chicken breasts") == 2.0

    def test_manually_added_float(self):
        assert parse_dest_quantity("1.5 cups milk") == 1.5

    def test_no_quantity_defaults_to_one(self):
        assert parse_dest_quantity("chicken breast") == 1.0


class TestParseMealieItem:
    def test_full_item(self):
        raw = {
            "food": {"name": "Chicken Breast"},
            "quantity": 2.0,
            "unit": {"name": "piece"},
        }
        item = parse_mealie_item(raw)
        assert item.food == "Chicken Breast"
        assert item.quantity == 2.0
        assert item.unit == "piece"

    def test_no_unit(self):
        raw = {"food": {"name": "Salt"}, "quantity": None, "unit": None}
        item = parse_mealie_item(raw)
        assert item.unit is None

    def test_falls_back_to_note(self):
        raw = {"food": None, "quantity": 1, "unit": None, "note": "pinch of nutmeg"}
        item = parse_mealie_item(raw)
        assert item.food == "pinch of nutmeg"
