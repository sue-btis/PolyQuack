# ADR-006 — How the mark price and index price are captured every minute

Status: Accepted
Date: 2026-10-26
Decision owners: the author
Accepted by: the author, 2026-10-26, «Acepto ADR-006 (Recomendado)»
Related: FR-007, FR-023, FR-024, NFR-005, NFR-010, ADR-004

## Context
FR-007 asks to store the mark price and index price of each paired instrument. The basis (FR-023) and the distance to liquidation (FR-024) are computed every minute from those prices. ADR-004 decided the books, but not the prices.

Querying the price per instrument every minute would repeat the option that ADR-004 rejected: about 200 requests per minute, against an unpublished limit on Polymarket Perps.

What was verified on Oct 26, 2026 with the public APIs:

- **Polymarket Perps:** `GET /v1/info/tickers` returns in a single response the 89 instruments, each with `mark_price`, `index_price`, `funding_rate` and `timestamp`. **Confirmed.**
- **Hyperliquid:** `POST /info` with `{"type":"metaAndAssetCtxs"}` returns in a single response the 234 instruments, each with `markPx` and `oraclePx` (index). It has no source time. **Confirmed.**

## Decision Drivers
- Do not exceed unpublished limits (NFR-005).
- Scale to 100 pairs with no extra requests (NFR-010).
- Price of each minute with a known time (BR-004).

## Options Considered
### Option A — One request per instrument every minute
- Benefits: one data point per instrument, with no large responses to process.
- Costs/risks: about 200 requests per minute. It is the same risk that ADR-004 rejected.

### Option B — One batch request per platform every minute
- Benefits: 2 requests per minute in total, no matter how many pairs there are.
- Costs/risks: the Hyperliquid response has no source time.

### Option C — Live mark price channel
- Benefits: no periodic requests.
- Costs/risks: it was not verified that it exists on both platforms; it would be another connection to maintain.

## Decision
**Option B**.

- Every minute the full price list is requested once per platform, and those of the paired instruments are stored.
- The reading time is the source `timestamp` when it exists (Polymarket). When it does not exist (Hyperliquid), it is the reception time, marked as such.
- If the request fails, the minute is left as a price gap (BR-001).

## Consequences
### Positive
- Price capture does not weigh on the limits, even as pairs grow.

### Negative / Trade-offs
- On Hyperliquid, the price time is the reception time and not the source time.

## Verification / Revisit Trigger
- Count the requests per minute in the ingestion log: there must be 2 for prices.
- Review whether either platform publishes a live mark price channel.
