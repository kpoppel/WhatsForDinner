"""Tandoor recipe normalization contract tests."""

from app.services.tandoor_client import TandoorClient


def test_normalize_recipe_uses_step_ingredients_when_present() -> None:
    """Verify nested step ingredients take precedence over top-level duplicates."""
    recipe = {
        "id": 53,
        "name": "Cremet citronsauce til pasta",
        "steps": [
            {
                "instruction": "Sauce",
                "ingredients": [
                    {
                        "amount": 400.0,
                        "unit": {"name": "g"},
                        "food": {"name": "hakket svinekod"},
                    }
                ],
            }
        ],
    }

    normalized = TandoorClient.normalize_recipe(recipe)
    assert normalized["title"] == "Cremet citronsauce til pasta"
    assert normalized["ingredients"][0]["name"] == "hakket svinekod"
    assert normalized["ingredients"][0]["unit"] == "g"
    assert normalized["steps"][0]["instruction"] == "Sauce"
