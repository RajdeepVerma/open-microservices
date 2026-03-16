"""App wiring: lifecycle resources + route registration."""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from api_routes import router
from env_loader import load_env_file
from runtime_config import load_client_config


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

    try:
        yield
    finally:
        await app.state.http_client.aclose()


def create_app() -> FastAPI:
    # Load .env before reading runtime defaults from os.environ.
    load_env_file()

    app = FastAPI(
        title="Iroha Transaction Status API",
        version="1.0.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    # Keep API endpoints isolated in a dedicated router module.
    app.include_router(router)
    return app
