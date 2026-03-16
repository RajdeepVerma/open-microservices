"""Simple .env reader used by app startup."""

import os
from pathlib import Path


def load_env_file(env_path: Path = Path(".env")) -> None:
    """Populate process env from a simple KEY=VALUE .env file."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            # Keep any already-exported values from shell/container.
            os.environ.setdefault(key, value)
