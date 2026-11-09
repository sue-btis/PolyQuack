# Polyquack

Ingestion of hourly funding, per-minute mark and index prices and per-minute order book
snapshots from Polymarket Perps and Hyperliquid, for every paired pair that is not delisted
(optionally narrowed by a filter), and paper evaluation of preregistered methods on that data.
Design: `docs/`. Current change: `docs/changes/2026-11-09-M03-e1-paper-evaluation/`.

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
uv run polyquack status   # derived status of each pair, latest readings and gaps of the last 24 h
uv run polyquack completeness [--days N]   # share of hours with funding and minutes with a book snapshot (default 7 days)
uv run polyquack preregister FILE   # store a method's preregistration (JSON) as its next variant
uv run polyquack evaluate           # decide every due hour on paper; run hourly by the timer
uv run polyquack variants           # variants registered and run, per method
```

When the set of pairs to ingest changes (a pair is added, delisted or leaves the filter), the service logs the change and exits with status 0; systemd restarts it with the new set.

Configuration is read from environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `POLYQUACK_DB` | `polyquack.db` | SQLite file |
| `POLYQUACK_ASSETS` | empty | optional comma-separated filter; when empty, every pair that is not delisted is ingested |
| `POLYQUACK_MIN_INTERVAL_POLYMARKET` | `0.8` | minimum seconds between REST requests |
| `POLYQUACK_MIN_INTERVAL_HYPERLIQUID` | `0.8` | minimum seconds between REST requests |

All APIs used are public and read-only; there are no credentials.

## Paper evaluation

`preregister` reads a JSON file and stores it verbatim as the method's next variant; while the
latest variant has not run, preregistering again replaces it. Fields: `method`, `rules`
(`window_hours`, `entry`, `exit`, with `0 <= exit < entry`), `metric`, and the fixed
`horizon_days` 28, `criterion.min_annual_net_return_on_collateral` 0.10, `size_per_leg_usd` 1000,
`leverage` 2, `decision_minute` 21, `snapshot_max_age_seconds` 120. The author chooses the rules
before the first run; from the variant's first run on, the database rejects any change to it.

`evaluate` starts a live run for each variant without one and decides, for every in-progress run, each
hour not yet decided: at hour H plus 21 minutes it reads only data with a source time up to that
instant, then opens, holds, reverses or closes per pair, walking the stored order book with the
taker fee, and credits funding to open legs. An hour that cannot be decided is recorded as
`no_action` with a cause. Missed hours are decided on the next run. It exits 1 when a write was
deferred by lock contention; the next run decides it.

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

Restart the ingestion service on the new code before the first `evaluate`: it stores the Polymarket `crypto` fee row, and without it every open is recorded as `no_action` with cause `missing_fee`.

The evaluation runs hourly at minute 22 from a systemd timer next to the ingestion service:

```
sudo install -m 644 /opt/polyquack/app/deploy/polyquack-evaluation.service /etc/systemd/system/
sudo install -m 644 /opt/polyquack/app/deploy/polyquack-evaluation.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polyquack-evaluation.timer
systemctl list-timers polyquack-evaluation.timer
```

Preregister on the VM with
`sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack preregister FILE`.
Evaluation logs: `journalctl -u polyquack-evaluation`.

Logs: `journalctl -u polyquack-ingestion -f`. Status:
`sudo -u polyquack env POLYQUACK_DB=/var/lib/polyquack/polyquack.db /opt/polyquack/app/.venv/bin/polyquack status`.
