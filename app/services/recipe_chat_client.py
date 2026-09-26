from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings

RECIPE_INSTRUCTIONS = (
    "You are a practical home cook helping someone turn ingredients in their fridge or pantry "
    "into a meal. Every response must be one complete, self-contained recipe they can follow, "
    "including when they ask for a change to an earlier recipe. Never respond with just a list "
    "of extra ingredients, a partial update, or a clarifying question. Make reasonable assumptions "
    "when details are missing. Include a descriptive title, servings, prep and cook times, a full "
    "ingredient list with quantities, and ordered cooking steps with heat levels and approximate "
    "timings where useful. Clearly identify ingredients they still need to buy. Respect dietary "
    "needs, available ingredients and follow-up requests. Never claim to have saved a recipe or "
    "added it to a meal plan."
)

RECIPE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "servings": {"type": "INTEGER"},
        "prep_time": {"type": "STRING"},
        "cook_time": {"type": "STRING"},
        "ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
        "steps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "to_buy": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "servings", "prep_time", "cook_time", "ingredients", "steps", "to_buy"],
}


class RecipeChatError(RuntimeError):
    """Raised when the recipe chat provider fails or returns unusable text."""


class GeminiRecipeChatClient:
    """Request a recipe suggestion using the conversation supplied by the caller."""

    async def reply(self, messages: list[dict[str, str]], servings: int) -> str:
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
            recipe = json.loads(text)
            title = recipe["title"].strip()
            recipe_servings = recipe["servings"]
            prep_time = recipe["prep_time"].strip()
            cook_time = recipe["cook_time"].strip()
            ingredients = recipe["ingredients"]
            steps = recipe["steps"]
            to_buy = recipe["to_buy"]
            if (
                not title or type(recipe_servings) is not int or recipe_servings != servings
                or not prep_time or not cook_time
                or not isinstance(ingredients, list) or not ingredients
                or not isinstance(steps, list) or not steps
                or not isinstance(to_buy, list)
                or not all(isinstance(item, str) and item.strip() for item in ingredients + steps + to_buy)
            ):
                raise ValueError("Incomplete recipe")
            return "\n".join([
                title,
                f"Serves {recipe_servings} | Prep: {prep_time} | Cook: {cook_time}",
                "",
                "Ingredients",
                *(f"- {item}" for item in ingredients),
                "",
                "Method",
                *(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
                *(["", "To buy", *(f"- {item}" for item in to_buy)] if to_buy else []),
            ])
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise RecipeChatError("Gemini did not return a complete recipe.") from exc