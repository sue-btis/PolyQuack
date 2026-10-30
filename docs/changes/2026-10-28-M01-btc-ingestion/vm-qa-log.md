# M01 — VM QA log

VM `duma-sidon` (Ubuntu, systemd 249), 2026-10-30. Commands were run by the author on the VM and their outputs pasted into the session; excerpts below are copied from those outputs.

## Step 1 — Preconditions
- System Python 3.10.12, below the project's `>=3.12`. Not a blocker: `uv sync` installs its own interpreter for the `polyquack` user.
- `systemd 249`.
- Clock: `System clock synchronized: no` with the NTP service active. `timedatectl timesync-status` showed `Server: n/a`, `Packet count: 0`, although a manual NTP query reached `ntp.ubuntu.com`, `time.google.com`, `time.cloudflare.com` and `pool.ntp.org`. After `sudo systemctl restart systemd-timesyncd` it synchronized (`Offset: +16.218ms`, stratum 2).

## Step 2 — Install
Deviations from the written procedure, all now fixed in `execution.md`:
- The repository is public, so it is cloned over HTTPS on branch `feat/btc-ingestion/josueDev`.
- `/opt/polyquack` is created with mode 750, so the operator's shell cannot `cd` into it; `uv sync` now takes `--directory /opt/polyquack/app`.
- Without a pin, uv picked CPython 3.15.2, a version the tests never ran on. `.python-version` now pins 3.13 (tests ran on 3.13.12); the VM venv uses CPython 3.13.18.

Result: `active`, `enabled`; the journal shows 90 Polymarket and 179 Hyperliquid instruments stored, both feeds `connected` and `subscribed`, and a REST `resync … done` for each book.

## Step 3 — 2 h run (18:39:08 → 20:39:08 UTC)
| Check | Expected | Result |
|---|---|---|
| `price request` lines | about 240 | 240 |
| ` 429` lines | 0 | 0 |
| gap lines in the window | — | 0 |
| book snapshots 18:40–20:40, instruments 6 and 91 | 120 each | 120, 120 |
| price readings 18:40–20:40, instruments 6 and 91 | 120 each | 120, 120 |
| minutes with both a snapshot and a `book_snapshot` gap | 0 | 0 |
| funding | one per hour and platform | 18:00 and 20:00 shown by `status`; 19:00 not queried |

Book reach: Polymarket covered past ±0.5% on both sides (for example `0.00531/0.01151`); Hyperliquid's 20 levels covered about ±0.03% (`0.00033/0.00048`), so its band volume is truncated, as DEC-1 expects. Hyperliquid prices have `source_time=None`.

## Incident after the window (20:58–20:59 UTC)
The author reports that the VM's DNS broke, so outbound requests failed until the author fixed it by hand. The VM itself did not restart: `uptime -s` is `2026-10-21 23:41:14` and the current boot started `2026-10-21 23:48:14 UTC`. The database shows `price` gaps for 20:58 and 20:59 on both platforms with `cause=RestError('ConnectError') status=final`, while the 20:58 book snapshot was stored, which fits new connections failing while the open book channels stayed up. The journal from 18:39:09 shows one process (PID 398, started by the 18:39:08 restart) running through the incident with no exit, restart or traceback, and no `connection lost` line: the book channels never dropped. The incident is therefore no evidence for AC-5 or AC-6. Funding of 21:00 was stored on both platforms at 21:01.

The author keeps the VM's DNS configuration as it is: restarts are rare and are not to be worked around.

## Steps 4 and 5 — not run
The author decided not to run the 5-minute network cut (AC-5) or the planned reboot (AC-6).
