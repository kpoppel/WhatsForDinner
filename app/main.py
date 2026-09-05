"""FastAPI application composition, lifecycle, middleware, and HTML routes."""

import logging
from time import perf_counter
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import client as tandoor_client
from app.api import router as api_router
from app.config import settings
from app.inspect_ui import render_inspector
from app.logging_config import configure_logging
from app.user_app import render_user_app

configure_logging()
logger = logging.getLogger("wfd.api")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await tandoor_client.close()


app = FastAPI(
    title=settings.app_name,
    description="FastAPI backend for mobile clients using Tandoor recipe and shopping data.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
    request.state.correlation_id = correlation_id
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if settings.performance_metrics_enabled:
            logger.info(
                "event=request_timing method=%s path=%s correlation_id=%s "
                "duration_ms=%.3f status=exception",
                request.method,
                request.url.path,
                correlation_id,
                (perf_counter() - started_at) * 1000,
            )
        raise
    duration_ms = (perf_counter() - started_at) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-Duration-Ms"] = f"{duration_ms:.3f}"
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.3f}"
    if settings.performance_metrics_enabled:
        logger.info(
            "event=request_timing method=%s path=%s correlation_id=%s "
            "duration_ms=%.3f status=%s",
            request.method,
            request.url.path,
            correlation_id,
            duration_ms,
            response.status_code,
        )
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.warning(
        "event=request_validation_failed method=%s path=%s correlation_id=%s errors=%s",
        request.method,
        request.url.path,
        correlation_id,
        exc.errors(),
    )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.get(f"{settings.api_v1_prefix}/openapi.json", include_in_schema=False)
async def versioned_openapi_schema() -> dict:
    return app.openapi()


@app.get(f"{settings.api_v1_prefix}/docs", include_in_schema=False)
async def versioned_swagger_docs() -> object:
    return get_swagger_ui_html(
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        title=f"{settings.app_name} API - Swagger UI",
    )


@app.get(f"{settings.api_v1_prefix}/redoc", include_in_schema=False)
async def versioned_redoc_docs() -> object:
    return get_redoc_html(
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        title=f"{settings.app_name} API - ReDoc",
    )


@app.get("/app", include_in_schema=False)
async def user_app() -> object:
    return render_user_app(
        settings.api_v1_prefix,
        settings.tandoor_base_url,
        settings.performance_metrics_enabled,
    )


@app.get("/inspect", include_in_schema=False)
async def inspect() -> object:
    return render_inspector(settings.api_v1_prefix)


@app.get("/shopping-sw.js", include_in_schema=False)
async def shopping_service_worker() -> FileResponse:
    return FileResponse(
        "app/static/shopping-sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/shopping.webmanifest", include_in_schema=False)
async def shopping_webmanifest() -> FileResponse:
    return FileResponse(
        "app/static/shopping.webmanifest",
        media_type="application/manifest+json",
    )
