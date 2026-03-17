"""HTTP boundary layer: query params, error mapping, and responses."""

import binascii
import logging
import os
import tomllib

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from runtime_config import get_runtime_config
from transaction_service import fetch_transaction_status

router = APIRouter()
# Read once at import; override per request via query arg.
QUERY_TIMEOUT_DEFAULT = int(os.getenv("QUERY_TIMEOUT", "30"))
logger = logging.getLogger(__name__)


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
    runtime_config = None
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
        logger.warning(
            "Rejected invalid request input",
            extra={"scenario": "invalid_request_input", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (KeyError, FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        # Misconfigured client.toml should be treated as server configuration errors.
        logger.error(
            "Invalid client.toml configuration",
            extra={"scenario": "invalid_client_toml", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail=f"Invalid client.toml: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        # Preserve upstream Torii status/details whenever possible.
        response = exc.response
        code = response.status_code if response is not None else 502
        detail = response.text if response is not None else str(exc)
        logger.warning(
            "Upstream Torii HTTP error",
            extra={"scenario": "upstream_http_error", "status_code": code},
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    except httpx.ConnectError as exc:
        logger.warning(
            "Returning 502 for Torii connect error",
            extra={"scenario": "http_response_mapping_connect_error", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail="Cannot connect to Iroha Torii.") from exc
    except httpx.ReadTimeout as exc:
        logger.warning(
            "Returning 504 for Torii read timeout",
            extra={"scenario": "http_response_mapping_read_timeout", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=504, detail="Iroha Torii timed out.") from exc
    except httpx.TimeoutException as exc:
        logger.warning(
            "Returning 504 for Torii timeout",
            extra={"scenario": "http_response_mapping_timeout", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=504, detail="Iroha Torii timed out.") from exc
    except httpx.RequestError as exc:
        logger.warning(
            "Returning 502 for Torii transport error",
            extra={"scenario": "http_response_mapping_transport_error", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail="Iroha Torii request failed.") from exc
    except (RuntimeError, binascii.Error) as exc:
        # Transport/protocol failures are exposed as Bad Gateway.
        logger.error(
            "Failed while decoding/querying Torii response",
            extra={"scenario": "torii_response_error", "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
