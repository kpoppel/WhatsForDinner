# WhatsForDinner

FastAPI backend for a mobile app that proxies recipe and shopping list data from Tandoor Recipes.

## Features

- REST endpoints for mobile clients
- Tandoor integration via configurable base URL and token
- Browser inspection UI at `/inspect` to quickly test endpoints
- OpenAPI docs at `/docs`

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
Visit your instance of Tandoor: https://<tandoor_url>/settings/api and create a new API token here. It needs to read/write to e able to update meal plans and shopping lists.

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
   docker compose -f docker/docker-compose.traefik.yml up -d --build
   ```

4. Stop:

   ```bash
   docker compose -f docker/docker-compose.traefik.yml down
   ```

## API endpoints

- `GET /api/v1/health`
- `GET /api/v1/recipes?search=<term>&limit=<n>`
- `GET /api/v1/shopping-list`

## Browser inspection

- Open `http://127.0.0.1:8000/inspect` for a lightweight UI to call the API.
- Open `http://127.0.0.1:8000/docs` for interactive Swagger docs.
