"""Service layer for transaction status lookup against Torii."""

import logging
import os
import time

import httpx

from iroha_protocol import (
    build_query_request_with_authority,
    build_signed_query,
    normalize_tx_hash,
    parse_query_response,
)
from runtime_config import ClientRuntimeConfig

logger = logging.getLogger(__name__)


async def fetch_transaction_status(
    tx_hash: str,
    runtime_config: ClientRuntimeConfig,
    http_client: httpx.AsyncClient,
    timeout: int,
) -> dict[str, str]:
    """
    Build, sign, submit and decode an Iroha query.
    Keeps bytes internal until API response rendering to avoid conversion overhead.
    """
    tx_hash_bytes = normalize_tx_hash(tx_hash)
    # Build and sign query bytes entirely in memory for low overhead.
    payload = build_query_request_with_authority(runtime_config.authority, tx_hash_bytes)
    signed_query = build_signed_query(payload, runtime_config.signing_key)

    query_url = f"{runtime_config.torii_url}/query"

    try:
        response = await http_client.post(
            query_url,
            headers={"Content-Type": "application/octet-stream"},
            data=signed_query,
            auth=runtime_config.auth,
            timeout=timeout,
        )
    except httpx.ConnectError as exc:
        logger.error(
            "Cannot connect to Iroha Torii",
            extra={
                "scenario": "iroha_connect_error",
                "torii_url": runtime_config.torii_url,
                "timeout_seconds": timeout,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except httpx.ReadTimeout as exc:
        logger.error(
            "Iroha Torii response timed out",
            extra={
                "scenario": "iroha_read_timeout",
                "torii_url": runtime_config.torii_url,
                "timeout_seconds": timeout,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except httpx.TimeoutException as exc:
        logger.error(
            "Iroha Torii request timed out",
            extra={
                "scenario": "iroha_timeout",
                "torii_url": runtime_config.torii_url,
                "timeout_seconds": timeout,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except httpx.RequestError as exc:
        logger.error(
            "Iroha Torii transport request failed",
            extra={
                "scenario": "iroha_transport_error",
                "torii_url": runtime_config.torii_url,
                "timeout_seconds": timeout,
                "error_type": type(exc).__name__,
            },
        )
        raise

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Iroha Torii returned non-success HTTP status",
            extra={
                "scenario": "iroha_http_error",
                "torii_url": runtime_config.torii_url,
                "status_code": exc.response.status_code if exc.response is not None else None,
                "error_type": type(exc).__name__,
            },
        )
        raise

    # Optional hotspot profiling, enabled only when explicitly requested.
    profile_scale_decoding = os.getenv("PROFILE_SCALE_DECODING", "0") == "1"
    try:
        if profile_scale_decoding:
            started_at = time.perf_counter()
            block_hash, status = parse_query_response(response.content)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            slow_decode_threshold_ms = float(os.getenv("SLOW_SCALE_DECODE_MS", "2.0"))
            if elapsed_ms >= slow_decode_threshold_ms:
                logger.warning("SCALE decode took %.3f ms", elapsed_ms)
        else:
            block_hash, status = parse_query_response(response.content)
    except RuntimeError as exc:
        logger.error(
            "Failed to decode Iroha query response payload",
            extra={
                "scenario": "iroha_response_decode_error",
                "torii_url": runtime_config.torii_url,
                "response_size_bytes": len(response.content),
                "error_type": type(exc).__name__,
            },
        )
        raise

    logger.info(
        "Iroha transaction status fetched successfully",
        extra={
            "scenario": "iroha_query_success",
            "torii_url": runtime_config.torii_url,
            "status": status,
            "block_hash_present": block_hash != "UNKNOWN",
        },
    )

    return {
        "transaction_hash": tx_hash_bytes.hex().upper(),
        "block_hash": block_hash,
        "status": status,
    }
