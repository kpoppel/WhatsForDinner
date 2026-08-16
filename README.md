# WhatsForDinner

FastAPI backend for a mobile app that proxies recipe and shopping list data from Tandoor Recipes.

## Features

- REST endpoints for mobile clients
- Tandoor integration via configurable base URL and token
- Browser inspection UI at `/inspect` to quickly test endpoints
- Stage 2 user app at `/app` with four sections: configuration, quick 1-day meal planning, multi-day meal planning, and shopping list handling
- Offline-friendly shopping sync endpoints with cursor-based change feeds
- OpenAPI docs at `/docs` and versioned docs at `/api/v1/docs`

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

## Docker deployment

The repository includes a containerized deployment under `docker/`:

- `docker/Dockerfile` builds the FastAPI app image.
- `docker/docker-compose.caddy.yml` runs the app behind Caddy.
- `docker/docker-compose.traefik.yml` runs the app with Traefik labels so it can be attached to an existing Traefik proxy.

Before deploying, ensure `.env` contains your Tandoor settings:

- `TANDOOR_BASE_URL`
- `TANDOOR_API_TOKEN`

#### Getting a Tandoor Token
Visit your instance of Tandoor: https://<tandoor_url>/settings/api and create a new API token here. It needs read/write access to update meal plans and shopping lists.

### Deploy with Caddy

1. Optional: set the site address (defaults to `:80`):

   ```bash
   export CADDY_SITE_ADDRESS=recipes.example.com
   ```

2. Build and start:

   ```bash
   docker compose -f docker/docker-compose.caddy.yml up -d --build
   ```

3. Stop:

   ```bash
   docker compose -f docker/docker-compose.caddy.yml down
   ```

### Deploy with Traefik

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
   docker compose --env-file .env -f docker/docker-compose.traefik.yml up -d --build
   ```

   If you run the command from inside `docker/`, use:

   ```bash
   docker compose --env-file ../.env -f docker-compose.traefik.yml up -d --build
   ```

4. Ensure the external Traefik network already exists and matches `TRAEFIK_NETWORK`:

   ```bash
   docker network ls
   ```

   If the network is named `traefik`, set `TRAEFIK_NETWORK=traefik`. If it is named `traefik_proxy`, set `TRAEFIK_NETWORK=traefik_proxy`.

5. Stop:

   ```bash
   docker compose --env-file .env -f docker/docker-compose.traefik.yml down
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

### Documentation endpoints

- `GET /docs`
- `GET /api/v1/docs`
- `GET /api/v1/redoc`
- `GET /api/v1/openapi.json`

## Stage 2 state persistence

Stage 2 stores local app state (selected keywords, meal-plan drafts, and shopping sync event cursors) in a JSON file:

- default path: `app/state/stage2_state.json`
- configurable with: `STAGE2_STATE_FILE`

This local state is app-managed metadata; recipe and shopping list data still come from Tandoor APIs.

## Browser inspection

- Open `http://127.0.0.1:8000/inspect` for a lightweight UI to call the API.
- Open `http://127.0.0.1:8000/app` for the Stage 2 user app flow (configuration, quick 1-day plan, meal planning, shopping + sync).
- Open `http://127.0.0.1:8000/docs` for interactive Swagger docs.
- Open `http://127.0.0.1:8000/api/v1/docs` for versioned Swagger docs tied to `http://127.0.0.1:8000/api/v1/openapi.json`.
- Open `http://127.0.0.1:8000/api/v1/redoc` for versioned ReDoc.
