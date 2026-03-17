"""Runtime config loading and request-time config cache helpers."""

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Request

logger = logging.getLogger(__name__)


def parse_private_key_seed(private_key: str) -> bytes:
    """Accept 32-byte seed or 64-byte secret key and normalize to 32 bytes."""
    normalized = private_key.strip()
    if normalized.lower().startswith("802620"):
        normalized = normalized[6:]

    seed = bytes.fromhex(normalized)
    if len(seed) == 64:
        return seed[:32]
    if len(seed) != 32:
        raise ValueError("Private key must contain 32-byte seed (or 64-byte secret key).")
    return seed


@dataclass(frozen=True)
class ClientRuntimeConfig:
    """Fully parsed runtime settings reused across requests."""

    authority: str
    signing_key: Ed25519PrivateKey
    torii_url: str
    auth: tuple[str, str] | None


def load_client_config(client_toml: str) -> ClientRuntimeConfig:
    """Load and parse client.toml only once per unique file path."""
    client_toml_path = client_toml or os.getenv("CLIENT_TOML_PATH", "client.toml")
    client_path = Path(client_toml_path)
    config = tomllib.loads(client_path.read_text(encoding="utf-8"))

    account = config["account"]  # Fail fast with KeyError for malformed config.
    authority = f"{account['public_key']}@{account['domain']}"
    private_seed = parse_private_key_seed(account["private_key"])
    torii_url = str(config["torii_url"]).rstrip("/")

    # Basic auth is optional and only attached when fully configured.
    basic_auth = config.get("basic_auth", {})
    auth: tuple[str, str] | None = None
    if basic_auth.get("web_login") and basic_auth.get("password"):
        auth = (basic_auth["web_login"], basic_auth["password"])

    # Parse once to avoid expensive key construction in the request hot path.
    signing_key = Ed25519PrivateKey.from_private_bytes(private_seed)
    logger.info(
        "Loaded client runtime configuration",
        extra={
            "scenario": "client_config_loaded",
            "client_toml_path": client_toml_path,
            "torii_url": torii_url,
            "has_basic_auth": auth is not None,
        },
    )
    return ClientRuntimeConfig(
        authority=authority,
        signing_key=signing_key,
        torii_url=torii_url,
        auth=auth,
    )


def get_runtime_config(request: Request, client_toml: str | None) -> ClientRuntimeConfig:
    """
    Resolve config for this request.
    - default config is loaded at startup
    - custom client_toml paths are cached after first load
    """
    if client_toml is None:
        logger.debug("Using default startup runtime config", extra={"scenario": "config_default_used"})
        return request.app.state.runtime_config

    cached = request.app.state.config_cache.get(client_toml)
    if cached is not None:
        logger.debug(
            "Using cached client runtime config",
            extra={"scenario": "config_cache_hit", "client_toml_path": client_toml},
        )
        return cached

    loaded = load_client_config(client_toml)
    request.app.state.config_cache[client_toml] = loaded
    logger.info(
        "Cached client runtime config",
        extra={"scenario": "config_cache_miss_loaded", "client_toml_path": client_toml},
    )
    return loaded
