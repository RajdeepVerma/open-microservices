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

    response = await http_client.post(
        f"{runtime_config.torii_url}/query",
        headers={"Content-Type": "application/octet-stream"},
        data=signed_query,
        auth=runtime_config.auth,
        timeout=timeout,
    )
    response.raise_for_status()

    # Optional hotspot profiling, enabled only when explicitly requested.
    profile_scale_decoding = os.getenv("PROFILE_SCALE_DECODING", "0") == "1"
    if profile_scale_decoding:
        started_at = time.perf_counter()
        block_hash, status = parse_query_response(response.content)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        slow_decode_threshold_ms = float(os.getenv("SLOW_SCALE_DECODE_MS", "2.0"))
        if elapsed_ms >= slow_decode_threshold_ms:
            logger.warning("SCALE decode took %.3f ms", elapsed_ms)
    else:
        block_hash, status = parse_query_response(response.content)

    return {
        "transaction_hash": tx_hash_bytes.hex().upper(),
        "block_hash": block_hash,
        "status": status,
    }
