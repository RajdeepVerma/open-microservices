# Iroha Transaction Status API

FastAPI service that queries Iroha Torii for transaction status by transaction hash.

## Features

- High-throughput async HTTP with shared connection pooling
- Startup-time config and key parsing (no per-request file parsing)
- Optional per-request `client.toml` override with in-memory cache
- Optional SCALE decode profiling hooks

## Project Structure

- `main.py` - process entrypoint (`main:app`)
- `app_factory.py` - FastAPI app creation + lifecycle resources
- `api_routes.py` - HTTP routes and error mapping
- `transaction_service.py` - business flow: build/sign/query/decode
- `runtime_config.py` - `client.toml` loading and config cache
- `iroha_protocol.py` - Iroha binary protocol encode/decode logic
- `scale_codec.py` - SCALE primitive helpers
- `env_loader.py` - simple `.env` loader
- `logging_config.py` - structured logging and request ID correlation

## Requirements

- Python 3.11+ (recommended)
- Accessible Iroha Torii endpoint
- Valid `client.toml` in project root (or custom path)

## Configuration

### `client.toml` (required)

Expected sections:

- `torii_url`
- `[account]` with:
  - `domain`
  - `public_key`
  - `private_key`
- `[basic_auth]` (optional):
  - `web_login`
  - `password`

### Environment variables

- `PORT` (default: `8000`)
- `LOG_LEVEL` (default: `INFO`)
- `LOG_FORMAT` (`simple`, `text`, `logfmt`, `json`; `color` alias to `simple`; `otlp`/`oltp` alias to `logfmt`; default `simple`)
- `LOG_COLOR` (`auto`, `1`, `0`; default `1`)
- `LOG_JSON` (legacy compatibility switch; prefer `LOG_FORMAT`)
- `ENABLE_SERVER_ACCESS_LOGS` (`1` keeps gunicorn/uvicorn access logs, default `0`)
- `QUERY_TIMEOUT` (default: `30`)
- `CLIENT_TOML_PATH` (default: `client.toml`)
- `MAX_HTTP_CONNECTIONS` (default: `500`)
- `MAX_HTTP_KEEPALIVE_CONNECTIONS` (default: `100`)
- `UVICORN_WORKERS` (default: `4`, when running `python main.py`)
- `PROFILE_SCALE_DECODING` (`1` to enable; default disabled)
- `SLOW_SCALE_DECODE_MS` (default: `2.0`)
- `WEB_CONCURRENCY` (Docker/Gunicorn worker override)

## Run Locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirement.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Alternative run (uses uvloop + workers from `main.py`):

```bash
python main.py
```

## Run with Docker

Build:

```bash
docker build -t iroha-tx-api .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e CLIENT_TOML_PATH=client.toml \
  -e WEB_CONCURRENCY=4 \
  iroha-tx-api
```

If you use a custom config path, mount it into the container and set `CLIENT_TOML_PATH` accordingly.

## API Usage

### Health

```bash
curl "http://localhost:8000/health"
```

Response:

```json
{"status":"ok"}
```

### Transaction status

```bash
curl "http://localhost:8000/transaction-status?tx_hash=<64_hex_hash>"
```

Optional query params:

- `client_toml` - custom path to `client.toml` (cached after first load)
- `timeout` - request timeout in seconds (`1..300`)

Example:

```bash
curl "http://localhost:8000/transaction-status?tx_hash=D61C41A79ADC705D84400475F6C3BD0C3DF68C4E8D8A1012863AC42268F5A105"
```

Typical response:

```json
{
  "transaction_hash": "D61C41A79ADC705D84400475F6C3BD0C3DF68C4E8D8A1012863AC42268F5A105",
  "block_hash": "....",
  "status": "COMMITTED"
}
```

## Logging

- Default logs are colorized `simple` mode for interactive terminal use.
- Every request gets an `X-Request-ID` response header for trace correlation.
- Request completion and failure logs include method, path, status, duration, and client IP.
- For Grafana or Loki pipelines, set `LOG_FORMAT=logfmt` or `LOG_FORMAT=otlp`.
- If you still want JSON logs, set `LOG_FORMAT=json`.

## Author

Raj (Rajdeep Verma)

- X: [x.com/rajdeepverma](https://x.com/rajdeepverma)
- LinkedIn: [linkedin.com/in/rajdeepverma](https://www.linkedin.com/in/rajdeepverma)
