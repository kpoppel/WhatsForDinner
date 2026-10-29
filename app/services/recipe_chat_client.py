from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.models.contracts import AIRecipe

RECIPE_INSTRUCTIONS = (
    "You are a practical home cook helping someone turn ingredients in their fridge or pantry "
    "into a meal. Every response must be one complete, self-contained recipe they can follow, "
    "including when they ask for a change to an earlier recipe. Never respond with just a list "
    "of extra ingredients, a partial update, or a clarifying question. Make reasonable assumptions "
    "when details are missing. Treat the user's ingredient list as available options, not a requirement "
    "to use everything. Prioritize a coherent, appetizing meal over using as many ingredients as possible. "
    "Choose a recognizable dish or a plausible variation with compatible flavors, textures and cooking "
    "methods. Leave out ingredients that do not suit the dish; do not force them into a garnish, sauce "
    "or side just to include them. For example, with avocado, mandarin, carrot, tuna and raisins, "
    "a tuna-avocado sandwich with carrot slaw could work; the mandarin and raisins can be left unused. "
    "Add only a small number of supporting ingredients when needed to make a proper meal, and mark "
    "anything not stated as available as needing purchase. Include a descriptive title, servings, prep and cook times, a full "
    "ingredient list with quantities, and ordered cooking steps with heat levels and approximate "
    "timings where useful. Clearly identify ingredients they still need to buy. Respect dietary "
    "needs, available ingredients and follow-up requests. Before responding, check that the result is "
    "a complete, practical recipe for the named dish: the flavors and textures work together, quantities "
    "and portions are realistic, preparation and cooking are food-safe, every listed ingredient is used "
    "in the method, and every ingredient required by the method is listed. If any check fails, revise "
    "the recipe and check it again. Return only the final recipe, not the review or discarded ideas. "
    "Never claim to have saved a recipe or "
    "added it to a meal plan."
)

RECIPE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "servings": {"type": "INTEGER"},
        "prep_time": {"type": "STRING"},
        "cook_time": {"type": "STRING"},
        "ingredients": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "amount": {"type": "NUMBER"},
                "unit": {"type": "STRING"},
                "needs_purchase": {"type": "BOOLEAN"},
            },
            "required": ["name", "amount", "unit", "needs_purchase"],
        }},
        "steps": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "servings", "prep_time", "cook_time", "ingredients", "steps"],
}


class RecipeChatError(RuntimeError):
    """Raised when the recipe chat provider fails or returns unusable text."""


class GeminiRecipeChatClient:
    """Request a recipe suggestion using the conversation supplied by the caller."""

    async def reply(self, messages: list[dict[str, str]], servings: int) -> AIRecipe:
        """Request a complete recipe scaled to the saved number of diners."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.google_llm_model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": (
                f"{RECIPE_INSTRUCTIONS} The saved serving setting is {servings}. "
                f"Make exactly {servings} servings and scale every ingredient quantity accordingly, "
                "even if an earlier recipe or the user's message mentions a different serving count."
            )}]},
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": RECIPE_SCHEMA},
            "contents": [
                {"role": "user" if message["role"] == "user" else "model", "parts": [{"text": message["content"]}]}
                for message in messages
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=settings.google_llm_timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json", "x-goog-api-key": settings.google_llm_api_key},
                )
                response.raise_for_status()
                data: Any = response.json()
        except httpx.HTTPError as exc:
            raise RecipeChatError("Unable to get a recipe idea from Gemini.") from exc

        try:
            text = "".join(part["text"] for part in data["candidates"][0]["content"]["parts"])
            recipe = AIRecipe.model_validate(json.loads(text))
            if recipe.servings != servings:
                raise ValueError("Recipe servings do not match the saved setting.")
            return recipe
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise RecipeChatError("Gemini did not return a complete recipe.") from exc