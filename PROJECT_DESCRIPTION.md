This is a description of the project and its requirements. It is OpenSource.

# Purpose of the proejct
Figuring our what is for dinner is often hard enough in a busy day, where the familty has different schedules, some days need to produce meals for 2 days, shopping needs to be done, and so on.
Oftentimes one in the familty ends up trying to fit it all together, because it is just easier, and because if one does it, the rest need not worry.  Writing the shpping list on a piece of paper works, but it is difficult to see it if going shopping after work.

This project is an attempt at solving some core needs using software:
- Deciding what to have for dinner during a 1 week period
- Easy access to a common shopping list when on the go
- Easy management of the 'we always need this' shopping list

A great many other projects hae been created around the same topic for sure, but it is also fun to build something new.

As a user the flow of work would ideally be something like:

1. We need a meal for TODAY -> Press a button to get a meal for today -> get shopping list -> shop -> cook
2. We need a meal plan for the next week -> Setup the next week for leftovers, takeout and so on -> press a button to get a meal plan -> make last edits -> get shoppińg list -> shop -> cook
3. We need to change the meal plan -> change the meal plan
4. We need to change the shopping list -> update the shopping list -> family members sync when home -> shop

# Requirements
These are the requirements the project must ultimately fulfil:

## Techincal

TREQ1: The software must run in Docker and support deployment behind standalone Caddy or Traefik.
TREQ2: The backend must use an existing Tandoor Recipes instance as the source of truth for recipes, meal plans, and shopping lists.
TREQ3: The client must support offline shopping list usage.
TREQ4: The client must sync local shopping changes to backend when connectivity returns.
TREQ5: The backend must expose REST endpoints required by user needs listed below.
TREQ6: The backend must expose a Home Assistant friendly endpoint for today meal immersion view with recipe title, ingredients, and steps.

## User Needs
REQ1: Users can select recipe categories or tags for candidate selection. Categories and tags are Tandoor backed.
REQ2: Users can request one meal suggestion and generate its shopping list.
REQ3: Users can generate meal plans with configurable start date and length in days.
REQ4: Users can apply constraints such as leftover day, takeout day, empty day, and number of diners.
REQ5: Users can edit meal plans by adding, removing, moving, or replacing meals.
REQ6: Users can view shopping lists grouped by ingredient type or store layout.
REQ7: Users can remove shopping list items.
REQ8: Users can add shopping list items.
REQ9: Users can use shopping mode actions: mark in basket and mark skipped.
REQ10: Shopping list views include Remaining, Skipped, and Completed sections.
REQ11: Users can see today dinner with direct recipe link inside the app.
REQ12: Home Assistant shows an immersive today meal card with recipe, ingredients, and steps without opening Tandoor UI.
REQ13: Users can configure a "don't repeat" criteria so that recipes cannot reappear in meal plans within N days.

## Acceptance Criteria (Initial)
AC1: Docker compose deployment works with Caddy and with Traefik using documented environment variables.
AC2: Backend can fetch recipe and shopping data from Tandoor using bearer token auth.
AC3: Today meal endpoint returns stable JSON with title, ingredients, and steps.
AC4: Shopping list endpoints support read and write operations required by REQ6 to REQ10.
AC5: Inspection UI demonstrates all Stage 1 endpoints.

# Build plan

## Stage 1

### Backend:

- FastAPI service in Docker.
- Tandoor integration for recipe retrieval, tags, meal plan operations, and shopping list read and write.
- Transformation layer from Tandoor models to app-specific API models.
- Inspection web UI for endpoint exploration.

### Frontend:

- Minimal HTML and JavaScript demo.
- Interactions:
    - Select recipe tags.
    - Generate shopping list from recipes.
    - Add shopping list item.
    - Remove shopping list item.

## Stage 2

### Backend:

- Add dedicated API endpoints to support the Stage 2 user app sections.
- Configuration API:
    - Read available Tandoor-backed keywords/tags.
    - Save and load selected keywords used for meal retrieval and meal planning.
- Panic Button API (one operation):
    - Select one random recipe from selected keywords.
    - Retrieve full recipe details (title, ingredients, steps).
    - Create/update shopping list entries for the selected recipe.
    - Return one response payload with recipe + shopping list result metadata.
- Meal Plan API:
    - Create meal plan with configurable start date and length in days.
    - Apply constraints: leftover day, takeout day, empty day, number of diners.
    - Edit plan entries: add, remove, move, replace, and update constraints.
    - Generate shopping list from full plan and allow re-generation after edits.
- Shopping List API:
    - Provide a dedicated endpoint/view model for shopping list retrieval in user-app friendly format.
    - Provide grouped shopping list output by ingredient type and supermarket placement (REQ6).
    - Support add and remove operations for shopping list entries (REQ7, REQ8).
    - Support status transitions for shopping mode:
        - remaining -> completed (mark in basket)
        - remaining -> skipped
        - skipped -> remaining
        - completed -> remaining (undo)
    - Return list sections required by REQ10: Remaining Items, Skipped Items, Completed Items.
    - Support sync semantics for offline-first clients (delta-friendly reads/writes and conflict-safe updates) aligned with TREQ3 and TREQ4.

### Stage 2 Endpoint Candidates

| Area | Method | Endpoint | Purpose |
|---|---|---|---|
| Configuration | GET | `/api/v1/config/keywords` | Retrieve available Tandoor-backed keywords/tags for selection UI. |
| Configuration | GET | `/api/v1/config/keywords/selected` | Read currently selected keywords used by panic button and meal planner. |
| Configuration | PUT | `/api/v1/config/keywords/selected` | Save selected keywords (replace current selection). |
| One Meal (Panic) | POST | `/api/v1/one-meal/run` | One operation: pick random recipe from selected keywords, fetch full recipe details, create/update shopping list, return combined response. |
| One Meal (Panic) | GET | `/api/v1/one-meal/last` | Retrieve last panic-button result for UI resume and quick review. |
| Meal Plan | POST | `/api/v1/meal-plans/generate` | Generate meal plan from start date, length, and constraints. |
| Meal Plan | GET | `/api/v1/meal-plans/{plan_id}` | Retrieve a full meal plan with entries and constraints. |
| Meal Plan | PATCH | `/api/v1/meal-plans/{plan_id}` | Update meal plan metadata and constraints. |
| Meal Plan | POST | `/api/v1/meal-plans/{plan_id}/entries` | Add a new meal entry. |
| Meal Plan | PATCH | `/api/v1/meal-plans/{plan_id}/entries/{entry_id}` | Move/replace/update a meal entry. |
| Meal Plan | DELETE | `/api/v1/meal-plans/{plan_id}/entries/{entry_id}` | Remove a meal entry. |
| Meal Plan | POST | `/api/v1/meal-plans/{plan_id}/shopping-list` | Generate or refresh shopping list from current meal plan state. |
| Shopping List | GET | `/api/v1/shopping-list/view` | Retrieve grouped shopping list view model (ingredient type/supermarket placement + Remaining/Skipped/Completed). |
| Shopping List | POST | `/api/v1/shopping-list/entries` | Add a shopping list entry. |
| Shopping List | PATCH | `/api/v1/shopping-list/entries/{entry_id}` | Update shopping list entry fields including shopping-mode status. |
| Shopping List | DELETE | `/api/v1/shopping-list/entries/{entry_id}` | Remove a shopping list entry. |
| Shopping List | POST | `/api/v1/shopping-list/sync` | Submit offline client changes and receive resolved state/deltas. |
| Shopping List | GET | `/api/v1/shopping-list/sync` | Fetch changes since cursor/timestamp for incremental synchronization. |

### Frontend:

- Expand the rudimentary user app into four clear sections.

- Section 1: Configuration
    - Show available Tandoor-backed keywords/tags.
    - Let user select and save keywords of interest.
    - Show active keyword selection clearly.

- Section 2: One Random Meal (Panic Button)
    - Single action button for "Get One Meal".
    - Uses active keyword selection.
    - Displays recipe title, ingredients, and steps.
    - In the same operation, creates shopping list content for the selected meal.
    - Show success/failure feedback for both recipe retrieval and shopping list creation.

- Section 3: Meal Plan
    - Define plan length and start date.
    - Configure constraints per requirements (leftover, takeout, empty, diners).
    - Generate initial meal plan.
    - Modify plan entries (remove, move, replace, add).
    - Generate shopping list from current meal plan state.
    - Present shopping list in sections required by REQ10: Remaining, Skipped, Completed.

- Section 4: Shopping List
    - Dedicated shopping list view in the user app.
    - Show list grouped by ingredient type or supermarket placement (REQ6).
    - Support add and remove actions on list items (REQ7, REQ8).
    - Support shopping mode actions: mark in basket and mark skipped (REQ9).
    - Present sections required by REQ10: Remaining Items, Skipped Items, Completed Items.
    - Keep list in sync with backend when online and support offline-first behavior per TREQ3 and TREQ4.


