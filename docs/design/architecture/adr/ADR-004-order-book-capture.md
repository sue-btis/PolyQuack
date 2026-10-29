# ADR-004 — How order books are captured

Status: Accepted
Date: 2026-10-26
Decision owners: the author
Accepted by: the author, 2026-10-26, «Canal en vivo + REST (Recomendado)»
Related: FR-006, FR-007, FR-010, NFR-003, NFR-005, NFR-010, PD-012

## Context
FR-006 and PD-012 ask for a snapshot of the book of each paired instrument every 60 s, on both platforms. With 100 pairs that is 200 snapshots per minute.

- **Polymarket Perps** does not publish usage limits for its perpetuals API. **Issue**: they were not found in the documentation. In the probe, requests every 0.2 s received "429, too many requests"; every 0.8 s worked (`docs/discovery/findings.md`, Angle E).
- **Hyperliquid** limits by weight per minute and per IP. The exact value was not verified for this design. Minor **Issue**.
- Both platforms have live channels (WebSocket) for the book and best price. On Polymarket they are `book` and `bbo` (S-067).

Funding changes once per hour, and its history can be requested later, so it does not have this tension.

## Decision Drivers
- Do not exceed limits that are not documented (NFR-005).
- One snapshot per minute in at least 95% of minutes (NFR-003).
- Detect gaps clearly (FR-010).

## Options Considered
### Option A — Query the book over REST every 60 s
- Benefits: simple; each snapshot is one request and a gap is a failed request.
- Costs/risks: 200 requests per minute, about 1.7 per second, above the pace of 1.25 per second that was tested without error on Polymarket. With the limit unknown, the risk of being blocked is real.

### Option B — Subscribe to the live channel and take one snapshot per minute of the in-memory state
- Benefits: one connection per platform, no pressure on request limits. Each minute's snapshot reflects the real state of the book at that instant.
- Costs/risks: reconnections must be handled and the in-memory book must be validated to stay correct. If the connection drops, the minutes without data are recorded as gaps.

### Option C — Hybrid: live channel as the main source and REST only to resync
- Benefits: what B offers, plus an explicit way to correct the book after a reconnection.
- Costs/risks: two code paths for the same data.

## Decision
**Option C**.

- Each platform's live book channel is the source of each minute's snapshots.
- After each connection or reconnection, the book is resynced with a REST query.
- Funding, instruments, parameters and history are requested over REST with controlled pacing and backoff on "429".

## Consequences
### Positive
- 200 snapshots per minute without getting close to request limits.
- Minutes without a connection are recorded as gaps (BR-001).

### Negative / Trade-offs
- More connection logic than a periodic query.

## Verification / Revisit Trigger
- Measure NFR-003 and the number of reconnections per day in the first 2 weeks.
- Review whether Polymarket publishes its limits or changes its channels.
