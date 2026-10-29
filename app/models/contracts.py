from __future__ import annotations

import re
import datetime
from datetime import date
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIME_24H_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SetSelectedKeywordsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword_ids: list[int]


class RecipeUseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: int = Field(gt=0)


class RecipeUseDateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_date: date


class RecipeChatMessage(BaseModel):
    """One turn in a recipe-idea conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=20000)


class AIRecipeIngredient(BaseModel):
    """One ingredient with quantities suitable for local shopping entries."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0, allow_inf_nan=False)
    unit: str = Field(max_length=80)
    needs_purchase: bool


class AIRecipe(BaseModel):
    """Complete one-off recipe retained independently of the chat conversation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(strict=True, ge=1, le=20)
    prep_time: str = Field(min_length=1, max_length=100)
    cook_time: str = Field(min_length=1, max_length=100)
    ingredients: list[AIRecipeIngredient] = Field(min_length=1, max_length=100)
    steps: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_steps(self) -> "AIRecipe":
        """Reject blank method steps before storing or displaying a recipe."""
        if any(not step.strip() for step in self.steps):
            raise ValueError("Recipe steps must not be blank.")
        return self

    def render_text(self, servings: int | None = None) -> str:
        """Render a readable snapshot scaled to the scheduled meal's servings."""
        target_servings = self.servings if servings is None else servings
        factor = target_servings / self.servings
        ingredients = [
            f"{item.amount * factor:g} {item.unit} {item.name}".replace("  ", " ")
            for item in self.ingredients
        ]
        to_buy = [text for text, ingredient in zip(ingredients, self.ingredients) if ingredient.needs_purchase]
        return "\n".join([
            self.title,
            f"Serves {target_servings} | Prep: {self.prep_time} | Cook: {self.cook_time}",
            "", "Ingredients", *(f"- {item}" for item in ingredients),
            "", "Method", *(f"{index}. {step}" for index, step in enumerate(self.steps, start=1)),
            *(["", "To buy", *(f"- {item}" for item in to_buy)] if to_buy else []),
        ])


class RecipeChatRequest(BaseModel):
    """Bounded conversation ending in the user's current question."""

    model_config = ConfigDict(extra="forbid")

    messages: list[RecipeChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_turns(self) -> "RecipeChatRequest":
        if self.messages[-1].role != "user" or any(
            message.role != ("user" if index % 2 == 0 else "model")
            for index, message in enumerate(self.messages)
        ):
            raise ValueError("messages must alternate user and model turns, ending with user.")
        return self


class AIRecipeSaveRequest(BaseModel):
    """Assign a selected chat reply to exactly one existing or new meal day."""

    model_config = ConfigDict(extra="forbid")

    recipe_id: UUID
    recipe: AIRecipe
    entry_id: int | None = Field(default=None, gt=0)
    date: datetime.date | None = None

    @model_validator(mode="after")
    def validate_destination(self) -> "AIRecipeSaveRequest":
        """Require one unambiguous meal-day destination."""
        if (self.entry_id is None) == (self.date is None):
            raise ValueError("Choose an existing meal day or a new date.")
        return self


class MealPlanRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_repeat_days: int = Field(ge=0)


class UserSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_diners: int = Field(ge=1, le=20)
    default_notification_time: str

    @model_validator(mode="after")
    def validate_time(self) -> "UserSettingsRequest":
        if TIME_24H_RE.match(self.default_notification_time.strip()) is None:
            raise ValueError("default_notification_time must be HH:MM (24-hour).")
        return self


class SettingsRequest(UserSettingsRequest):
    no_repeat_days: int = Field(ge=0)
    keyword_ids: list[int]


class MealPlanConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leftover_days: list[int | str] = Field(default_factory=list)
    takeout_days: list[int | str] = Field(default_factory=list)
    empty_days: list[int | str] = Field(default_factory=list)


class GenerateMealPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    length_days: int = Field(default=7, ge=1, le=31)
    diners: int | None = Field(default=None, ge=1, le=20)
    constraints: MealPlanConstraints = Field(default_factory=MealPlanConstraints)
    keyword_ids: list[int] | None = None
    no_repeat_days: int | None = Field(default=None, ge=0)


class MealPlanPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: str | None = None
    length_days: int | None = None
    diners: int | None = None
    constraints: MealPlanConstraints | None = None
    keyword_ids: list[int] | None = None
    entries: list[dict[str, Any]] | None = None


class MealPlanEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int | None = None
    date: str | None = None
    title: str | None = None
    mode: str | None = None
    recipes: list[dict[str, Any]] | None = None
    servings: int | None = None
    reminder_enabled: bool | None = None
    reminder_text: str | None = None
    notes: str | None = None


class MealPlanEntryPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int | None = None
    date: str | None = None
    title: str | None = None
    mode: str | None = None
    recipes: list[dict[str, Any]] | None = None
    servings: int | None = None
    reminder_enabled: bool | None = None
    reminder_text: str | None = None
    notes: str | None = None
    target_day_index: int | None = None


class ShoppingEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ad_hoc: bool | None = None
    status: str | None = None
    reminder_enabled: bool | None = None
    reminder_date: str | None = None
    reminder_text: str | None = None
    name: str | None = None
    amount: int | float | None = None
    unit: str | None = None
    ingredient_type: str | None = None
    recipe_context: str | None = None
    food_id: int | None = None
    recipe: dict[str, Any] | None = None
    store_group: dict[str, Any] | str | int | None = None
    food: dict[str, Any] | None = None
    checked: bool | None = None
    delay_until: str | None = None


class ShoppingEntryPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    reminder_enabled: bool | None = None
    reminder_date: str | None = None
    reminder_text: str | None = None
    name: str | None = None
    amount: int | float | None = None
    unit: str | None = None
    ingredient_type: str | None = None
    recipe_context: str | None = None
    store_group: dict[str, Any] | str | int | None = None
    food: dict[str, Any] | None = None
    checked: bool | None = None
    delay_until: str | None = None


class SyncOperation(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class ShoppingSyncChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: SyncOperation
    entry_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    queued_at: str | None = None

    @model_validator(mode="after")
    def validate_entry_id(self) -> "ShoppingSyncChange":
        if self.operation in {SyncOperation.update, SyncOperation.delete} and self.entry_id is None:
            raise ValueError("entry_id is required for update and delete operations.")
        return self


class ShoppingSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[ShoppingSyncChange]


class ShoppingListOcrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]
