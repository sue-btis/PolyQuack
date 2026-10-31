# Polyquack

Ingestion of hourly funding, per-minute mark and index prices and per-minute order book
snapshots from Polymarket Perps and Hyperliquid, for the pairs listed in the configuration.
Design: `docs/`. Current change: `docs/changes/2026-10-28-M01-btc-ingestion/`.

## Development

```
uv sync
uv run mypy --strict src tests
uv run ruff check
uv run ruff format --check
uv run pytest
gitleaks detect --no-git --source .
```

Tests never touch the network.

## Running

```
uv run polyquack run      # ingestion service, logs to stderr
uv run polyquack status   # latest readings and gaps of the last 24 h per pair and platform
```

Configuration is read from environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `POLYQUACK_DB` | `polyquack.db` | SQLite file |
| `POLYQUACK_ASSETS` | `BTC` | comma-separated assets to ingest |
| `POLYQUACK_MIN_INTERVAL_POLYMARKET` | `0.8` | minimum seconds between REST requests |
| `POLYQUACK_MIN_INTERVAL_HYPERLIQUID` | `0.8` | minimum seconds between REST requests |

All APIs used are public and read-only; there are no credentials.

## Service on the VM

```
sudo useradd --system --create-home --home-dir /opt/polyquack --shell /usr/sbin/nologin polyquack
sudo -u polyquack -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u polyquack -H git clone <repository> /opt/polyquack/app
cd /opt/polyquack/app
sudo -u polyquack -H /opt/polyquack/.local/bin/uv sync --no-dev
sudo install -m 644 /opt/polyquack/app/deploy/polyquack-ingestion.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polyquack-ingestion
```

The service user owns its home `/opt/polyquack`, where it gets its own `uv` (and, if the VM has
no Python 3.12 or newer, a Python that `uv` downloads), the checkout in `/opt/polyquack/app` and the
`.venv`. If the tree is copied instead of cloned, run `sudo chown -R polyquack:polyquack /opt/polyquack/app`.
The unit creates `/var/lib/polyquack` for the database.

Logs: `journalctl -u polyquack-ingestion -f`. Status:
`sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack status`.
