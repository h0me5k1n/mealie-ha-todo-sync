import pytest
from diff import IngredientItem, has_tag, filter_tagged, parse_mealie_item


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


class TestFormatSummary:
    def test_suffix_with_quantity_and_unit(self):
        item = IngredientItem(food="flour", quantity=500, unit="g")
        assert item.format_summary("[Mealie]", "suffix") == "500 g flour [Mealie]"

    def test_prefix_with_quantity_and_unit(self):
        item = IngredientItem(food="flour", quantity=500, unit="g")
        assert item.format_summary("[Mealie]", "prefix") == "[Mealie] 500 g flour"

    def test_no_unit(self):
        item = IngredientItem(food="chicken breast", quantity=2, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "2 chicken breast [Mealie]"

    def test_no_quantity(self):
        item = IngredientItem(food="salt", quantity=None, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "salt [Mealie]"

    def test_zero_quantity_omitted(self):
        item = IngredientItem(food="pepper", quantity=0, unit="tsp")
        assert item.format_summary("[Mealie]", "suffix") == "tsp pepper [Mealie]"

    def test_float_quantity_trimmed(self):
        item = IngredientItem(food="butter", quantity=1.5, unit="tbsp")
        assert item.format_summary("[Mealie]", "suffix") == "1.5 tbsp butter [Mealie]"

    def test_whole_float_shows_as_int(self):
        item = IngredientItem(food="eggs", quantity=3.0, unit=None)
        assert item.format_summary("[Mealie]", "suffix") == "3 eggs [Mealie]"


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
