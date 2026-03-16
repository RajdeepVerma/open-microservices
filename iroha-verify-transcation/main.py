"""Process entrypoint used by uvicorn/gunicorn."""

import os

from app_factory import create_app


# Build FastAPI app once at import time for worker startup.
app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Local/dev runner. Production uses gunicorn command from Dockerfile.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        loop="uvloop",
        workers=int(os.getenv("UVICORN_WORKERS", "4")),
    )