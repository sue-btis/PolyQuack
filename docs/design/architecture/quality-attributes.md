# Quality Attributes — Polyquack

The targets of each NFR live in `docs/product/prd.md` §8. Here we only say how the design meets them and where they will be verified.

| NFR | Design response | Evidence |
|---|---|---|
| NFR-001 | Readings are stored exactly as they arrive, with the source time, and the reading tables only receive INSERT (`docs/design/data/schema.dbml`). No code fills in values: a hole is stored as a `gap`. | Audit test: compare 200 random funding readings and 200 snapshots against the source. Ingestion milestone |
| NFR-002 | Funding over REST every hour and, after each reconnection, recovery from the platform's history (FR-011), which closes gaps with real data. The VM runs on an always-on server (ADR-001). | Completeness report per pair over a 4-week window. SC-001 |
| NFR-003 | Snapshots taken from the in-memory order book, fed by the live channel and resynced over REST (ADR-004). Taking each minute's snapshot does not depend on a request. | Report of minutes with a snapshot per instrument over 4 weeks. SC-001 |
| NFR-004 | Services supervised by the VM's system: they start with it and restart on their own if they fail. Ingestion reconnects with increasing backoff. | VM restart test and network cut test; measure the time until the first new reading |
| NFR-005 | A single rate control per platform for all REST, with increasing backoff on "429". Order books arrive over the live channel, not by polling (ADR-004). Mark and index prices are requested in a single request per platform every minute (ADR-006). Since the Polymarket Perps limit is not published, the initial rate is 1 request every 0.8 s, the one that worked in the probe. | Log of 429 responses and blocks over 4 weeks |
| NFR-006 | Local VM on the author's server (ADR-001) and SQLite with no separate service (ADR-002). The public view goes on free static hosting (ADR-005). | human task: the author confirms the total monthly cost does not exceed 20 USD |
| NFR-007 | Readings are not edited; the preregistration does not change after the first run; the evaluator is deterministic and rounds amounts to cents in a single place. | Test: re-evaluate the E1 run and compare decision by decision. SC-005 |
| NFR-008 | Each decision stores `data_until`. The evaluator only requests readings with a source time less than or equal to the decision hour. Funding is credited with the accrual rule (`docs/design/domain.md`, Paper position): only payments after the opening. | Automated tests over a run: (1) `data_until <= hour` in every decision; (2) no `paper_funding_payment.source_time` is less than or equal to `paper_position.opened_at`. SC-004 |
| NFR-009 | The dashboard reads the database directly on each load, and ingestion writes every minute. | Test: compare the displayed time against the last stored reading |
| NFR-010 | One live connection per platform for all instruments (ADR-004), prices in batches (ADR-006), and indexes by instrument and hour (`schema.dbml`). | Load test with 100 simulated pairs, or measurement once there are 100 real ones |
| NFR-011 | The MVP uses no trading credentials. Local configuration and the database stay outside the repository. | Automated secret scan of the repository on each commit |
| NFR-012 | Platforms and instruments are data, not code: a new source adds rows in `platform` and `instrument`, and an ingestion adapter. Already registered variants do not change (`docs/design/domain.md`, Cross-Boundary Rules). | Design review when the first new source comes in |
| NFR-013 | The fastest decision is hourly and snapshots are per minute; nothing requires reacting in under 1 minute (ADR-001, ADR-004). | Review: no function depends on latency under 1 minute |
