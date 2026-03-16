"""HTTP boundary layer: query params, error mapping, and responses."""

import binascii
import os
import tomllib

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from runtime_config import get_runtime_config
from transaction_service import fetch_transaction_status

router = APIRouter()
# Read once at import; override per request via query arg.
QUERY_TIMEOUT_DEFAULT = int(os.getenv("QUERY_TIMEOUT", "30"))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/transaction-status")
async def transaction_status(
    request: Request,
    tx_hash: str = Query(..., description="Transaction hash (64 hex chars)."),
    client_toml: str | None = Query(
        default=None,
        description="Optional path to iroha client.toml (cached after first load).",
    ),
    timeout: int = Query(
        default=QUERY_TIMEOUT_DEFAULT,
        ge=1,
        le=300,
        description="HTTP timeout in seconds",
    ),
) -> dict[str, str]:
    try:
        # Uses startup-cached config unless a custom file path is provided.
        runtime_config = get_runtime_config(request, client_toml)
        return await fetch_transaction_status(
            tx_hash=tx_hash,
            runtime_config=runtime_config,
            http_client=request.app.state.http_client,
            timeout=timeout,
        )
    except ValueError as exc:
        # Bad hash/key formatting and other client input issues.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (KeyError, FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        # Misconfigured client.toml should be treated as server configuration errors.
        raise HTTPException(status_code=500, detail=f"Invalid client.toml: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        # Preserve upstream Torii status/details whenever possible.
        response = exc.response
        code = response.status_code if response is not None else 502
        detail = response.text if response is not None else str(exc)
        raise HTTPException(status_code=code, detail=detail) from exc
    except (httpx.RequestError, RuntimeError, binascii.Error) as exc:
        # Transport/protocol failures are exposed as Bad Gateway.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
