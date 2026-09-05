# WhatsForDinner

FastAPI backend for a mobile app that proxies recipe and shopping list data from Tandoor Recipes.

## Features

- REST endpoints for mobile clients
- Tandoor integration via configurable base URL and token
- Browser inspection UI at `/inspect` to quickly test endpoints
- Stage 2 user app at `/app` with four sections: configuration, quick 1-day meal planning, multi-day meal planning, and shopping list handling
- Offline-friendly shopping sync endpoints with cursor-based change feeds
- OpenAPI docs at `/docs` and versioned docs at `/api/v1/docs`

## Architecture guardrails

- API request contracts are strict for mutable endpoints. Unknown or invalid fields are rejected with a 4xx response.
- Contract violations are logged with request method, path, and correlation ID.
- Stage 2 local JSON state is schema-versioned (`schema_version`) and validated on load and save.
- Invalid persisted state fails fast; the server does not silently auto-heal broken state payloads.
- Local responses carry a monotonic `revision`; browser stores reject older responses before applying them.
- Meal-plan intent is accepted locally when Tandoor projection fails and is exposed as a durable pending projection with an operation ID.
- Automatic projection retries are not enabled. Users explicitly retry pending reconciliation from the app.
- No compatibility aliases or duplicate API keys are introduced to mask contract mismatches.

The browser keeps meal plans and settings read-only while offline. Shopping changes are applied optimistically, persisted locally, and submitted through the shopping sync endpoint when connectivity returns. The service worker caches the application shell for offline use and uses network-first navigation so an online launch receives the current shell.

## Developer code map

Backend ownership:

- `app/main.py` composes FastAPI, middleware, static files, and process lifecycle.
- `app/api.py` owns HTTP routes and transformations between upstream payloads and client view models.
- `app/models/contracts.py` defines strict HTTP mutation contracts; `app/models/state_schema.py` defines the persisted document.
- `app/services/stage2_state.py` is the only local JSON repository and revision allocator.
- `app/services/meal_plan_service.py` and `app/services/shopping_service.py` own domain rules and Tandoor projection workflows.
- `app/services/tandoor_client.py` is the only backend Tandoor transport.

Frontend ownership:

- Screen modules (`home_tab.js`, `meal_plans.js`, `settings_tab.js`, and `shop_editor.js`) own DOM events, rendering, and ephemeral view state.
- `app/static/js/store/commands.js` is the mutation and backend-command boundary; `selectors.js` is the model read boundary.
- `app/static/js/api.js` is the only browser HTTP transport.
- `app/static/js/sync.js` and `sync_coordinator.js` serialize shopping synchronization and reject stale work.
- `app/static/js/render.js` projects shopping state into DOM; the service worker caches only the application shell and static assets.

Screen code must not call `fetch`, mutate the exported store, or persist server-backed model data directly. Local UI preferences such as the selected grouping mode may remain screen-owned.

## Quick start

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:

   ```bash
   cp .env.example .env
   ```

   Set `TANDOOR_BASE_URL` and `TANDOOR_API_TOKEN` if your Tandoor instance requires auth.

4. Run the API:

   ```bash
   uvicorn app.main:app --reload
   ```

## Testing

Install dev/test dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the full suite from the repo root:

```bash
pytest -q
```

Equivalent command using the virtual environment interpreter:

```bash
/home/kpo/development/WhatsForDinner/.venv/bin/python -m pytest -q
```

The repository includes `pytest.ini` with `pythonpath = .` so both invocations resolve `app.*` imports consistently.

## Docker deployment

The repository includes a containerized deployment under `docker/`:

- `docker/Dockerfile` builds the FastAPI app image.
- `docker/docker-compose.caddy.yaml` is the Caddy template.
- `docker/docker-compose.traefik.yaml` is the Traefik template.

Copy the template you want to `docker-compose.yaml` before using plain `docker compose up` from inside `docker/`.

Before deploying, ensure `.env` contains your Tandoor settings:

- `TANDOOR_BASE_URL`
- `TANDOOR_API_TOKEN`

#### Getting a Tandoor Token
Visit your instance of Tandoor: https://<tandoor_url>/settings/api and create a new API token here. It needs read/write access to update meal plans and shopping lists.

#### Handwritten Shopping List OCR
To enable "scan a handwritten list" in the Shop Editor, set:

- `GOOGLE_LLM_API_KEY` — a Google AI Studio API key with access to the Gemini API.
- `GOOGLE_LLM_MODEL` — optional, defaults to `gemini-2.5-flash`.

If `GOOGLE_LLM_API_KEY` is unset, the camera button's OCR request returns a 503 error.

### Deploy with Caddy

From inside `docker/`, plain commands are:

```bash
cd docker
cp docker-compose.caddy.yaml docker-compose.yaml
docker compose --env-file ../.env up -d --build
docker compose --env-file ../.env down
```

1. Optional: set the site address (defaults to `:80`):

   ```bash
   export CADDY_SITE_ADDRESS=recipes.example.com
   ```

2. Build and start:

   ```bash
   docker compose --env-file .env -f docker/docker-compose.caddy.yaml up -d --build
   ```

3. Stop:

   ```bash
   docker compose --env-file .env -f docker/docker-compose.caddy.yaml down
   ```

### Deploy with Traefik

From inside `docker/`, plain commands are:

```bash
cd docker
cp docker-compose.traefik.yaml docker-compose.yaml
docker compose --env-file ../.env up -d --build
docker compose --env-file ../.env down
```

This compose file assumes you already run Traefik and have an external Docker network for proxied services.

Important: `env_file` in the compose service only populates container environment variables. It does not provide values for Compose interpolation in `labels:` or top-level `networks:`. For the Traefik compose file, pass the repo `.env` file to Docker Compose explicitly.

1. Set the host name Traefik should route:

   ```bash
   export TRAEFIK_HOST=recipes.example.com
   ```

2. Optional overrides:

- `TRAEFIK_ENTRYPOINTS` (default: `websecure`)
- `TRAEFIK_CERTRESOLVER` (default: `letsencrypt`)
- `TRAEFIK_NETWORK` (default: `traefik_proxy`)

3. Build and start:

   ```bash
   docker compose --env-file .env -f docker/docker-compose.traefik.yaml up -d --build
   ```

   If you run the command from inside `docker/`, use:

   ```bash
   docker compose --env-file ../.env -f docker-compose.traefik.yaml up -d --build
   ```

4. Ensure the external Traefik network already exists and matches `TRAEFIK_NETWORK`:

   ```bash
   docker network ls
   ```

   If the network is named `traefik`, set `TRAEFIK_NETWORK=traefik`. If it is named `traefik_proxy`, set `TRAEFIK_NETWORK=traefik_proxy`.

5. Stop:

   ```bash
   docker compose --env-file .env -f docker/docker-compose.traefik.yaml down
   ```

### Build from docker folder

If you are already in `docker/`, build using the parent directory as context:

```bash
cd docker
docker build -t whatsfordinner:latest -f Dockerfile ..
```

## API endpoints

### Core endpoints

- `GET /api/v1/health`
- `GET /api/v1/recipes?search=<term>&limit=<n>&keyword_ids=<id>`
- `GET /api/v1/recipe-tags`
- `GET /api/v1/today-meal`

### Stage 2 configuration

- `GET /api/v1/config/keywords`
- `GET /api/v1/config/keywords/selected`
- `PUT /api/v1/config/keywords/selected`
- `GET /api/v1/config/meal-plan-rules`
- `PUT /api/v1/config/meal-plan-rules`

### Stage 2 meal plan flow

- `POST /api/v1/meal-plans/generate`
- `GET /api/v1/meal-plans/stored`
- `GET /api/v1/meal-plans/{plan_id}`
- `DELETE /api/v1/meal-plans/stored/{plan_id}`
- `PATCH /api/v1/meal-plans/{plan_id}`
- `POST /api/v1/meal-plans/{plan_id}/entries`
- `PATCH /api/v1/meal-plans/{plan_id}/entries/{entry_id}`
- `DELETE /api/v1/meal-plans/{plan_id}/entries/{entry_id}`
- `POST /api/v1/meal-plans/{plan_id}/shopping-list`

### Stage 2 shopping list + sync flow

- `GET /api/v1/shopping-list/view`
- `POST /api/v1/shopping-list/entries`
- `PATCH /api/v1/shopping-list/entries/{entry_id}`
- `DELETE /api/v1/shopping-list/entries/{entry_id}`
- `GET /api/v1/shopping-list/sync?since=<cursor>`
- `POST /api/v1/shopping-list/sync`
- `GET /api/v1/sync/pending`
- `POST /api/v1/sync/pending/{operation_id}/retry`

### Documentation endpoints

- `GET /docs`
- `GET /api/v1/docs`
- `GET /api/v1/redoc`
- `GET /api/v1/openapi.json`

## Stage 2 state persistence

Stage 2 stores selected keywords, derived multi-day meal plans, recipe-use history, shopping overlays, sync cursors, revisions, and pending Tandoor projections in a JSON file:

- file name: `state.json`
- default data directory: `./data`
- configurable with: `DATA_DIR`

Writes validate the complete document and atomically replace the state file. Before replacement, the previous valid state is written to `state.json.bak`. `Stage2State.restore_backup()` restores that backup for an operator-controlled recovery.

The file lock is process-local, so deployments must run a single application process against a given `DATA_DIR`. Do not point multiple containers or Uvicorn workers at the same state file.

Tandoor remains authoritative for recipes and its projected meal-plan and shopping rows. This service is authoritative for the derived plan objects, no-repeat history, shopping overlays, and pending projection records that implement the application workflows.

## Browser inspection

- Open `http://127.0.0.1:8000/inspect` for a lightweight UI to call the API.
- Open `http://127.0.0.1:8000/app` for the Stage 2 user app flow (configuration, quick 1-day plan, meal planning, shopping + sync).
- Open `http://127.0.0.1:8000/docs` for interactive Swagger docs.
- Open `http://127.0.0.1:8000/api/v1/docs` for versioned Swagger docs tied to `http://127.0.0.1:8000/api/v1/openapi.json`.
- Open `http://127.0.0.1:8000/api/v1/redoc` for versioned ReDoc.
