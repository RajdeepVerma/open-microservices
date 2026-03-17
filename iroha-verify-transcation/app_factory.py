"""App wiring: lifecycle resources + route registration."""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

from api_routes import router
from env_loader import load_env_file
from logging_config import clear_request_id, configure_logging, set_request_id
from runtime_config import load_client_config

logger = logging.getLogger(__name__)
request_logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize heavyweight resources once:
    - parsed client.toml + signing key
    - shared async HTTP client with keep-alive pool
    """
    client_toml_path = os.getenv("CLIENT_TOML_PATH", "client.toml")
    default_runtime_config = load_client_config(client_toml_path)
    app.state.runtime_config = default_runtime_config
    app.state.config_cache = {client_toml_path: default_runtime_config}

    max_connections = int(os.getenv("MAX_HTTP_CONNECTIONS", "500"))
    max_keepalive_connections = int(os.getenv("MAX_HTTP_KEEPALIVE_CONNECTIONS", "100"))
    # One shared pooled client per worker process for connection reuse.
    app.state.http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
    )
    logger.info(
        "Application startup complete",
        extra={
            "scenario": "app_startup_complete",
            "torii_url": default_runtime_config.torii_url,
            "max_connections": max_connections,
            "max_keepalive_connections": max_keepalive_connections,
        },
    )

    try:
        yield
    finally:
        logger.info("Application shutdown started", extra={"scenario": "app_shutdown_started"})
        await app.state.http_client.aclose()
        logger.info("Application shutdown complete", extra={"scenario": "app_shutdown_complete"})


def create_app() -> FastAPI:
    # Load .env before reading runtime defaults from os.environ.
    load_env_file()
    configure_logging()

    app = FastAPI(
        title="Iroha Transaction Status API",
        version="1.0.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "").strip() or uuid.uuid4().hex
        set_request_id(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            request_logger.exception(
                "Request failed",
                extra={
                    "scenario": "request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 3),
                    "client_ip": request.client.host if request.client else None,
                },
            )
            clear_request_id()
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        request_logger.info(
            "Request completed",
            extra={
                "scenario": "request_completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "status_family": f"{response.status_code // 100}xx",
                "duration_ms": round(duration_ms, 3),
                "client_ip": request.client.host if request.client else None,
            },
        )
        clear_request_id()
        return response

    # Keep API endpoints isolated in a dedicated router module.
    app.include_router(router)
    return app
