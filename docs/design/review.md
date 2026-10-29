# System Design Review

This file is review evidence and workflow state for the current baseline. It is not an authority for product, architecture, schema, or contracts. A new baseline rewrites it and keeps, with their IDs, the findings that remain `OPEN`, `ACCEPTED`, or `BLOCKED`. Resolved and invalid findings stay in git history.

Enumeration values are left in English.

## Review State

- Baseline ID: `RV-001`
- Current review mode: `follow_up`
- Reconciliation cycles used: `1`
- Maximum automatic reconciliation cycles: `3`
- Current verdict: `Approved for build planning`
- Escalate exit: `none`
- Baseline reviewer: independent subagent that did not write the package. Date: 2026-10-26.
- Follow-up reviewer: another independent subagent, which wrote neither the package nor its reconciliation. Date: 2026-10-26.
- Note: `Polyquack/` is not a git repository. Both reviews were done on the files as they are on disk.

## Mechanical Checks

### Baseline (cycle 0)

| Command | Result |
|---|---|
| `node <skill dir>/scripts/check-package.mjs "C:\Users\Josue Escobar\Documents\projects\mine\Polyquack"` | **Fail** (exit 1): `[enums] PRD §15 PD-005 status not Open/Decided: Decided (replaced by PD-006)`. Found 1 problem, recorded as F-006. |
| `checks:` in the manifest | Not applicable: the manifest has no `checks:` key. |
| Structurizr CLI v2025.11.09 (structurizr-java 5.0.2; official GitHub zip downloaded to the scratchpad): `validate -workspace docs/design/architecture/architecture.dsl` | **Pass** (exit 0, no errors). Negative control: a deliberately broken DSL gave exit 1 with the message "destination element does not exist", so the validator does detect errors. |
| `npx -p @dbml/cli dbml2sql docs/design/data/schema.dbml` (@dbml/cli 11.0.0) | **Pass** (exit 0). Generated SQL with 21 `CREATE TABLE` statements, one per DBML table. The first attempt, `npx @dbml/cli dbml2sql`, failed because of a bad invocation ("could not determine executable"), not because of the file. |
| `npx -p @mermaid-js/mermaid-cli mmdc -i docs/design/ux/flows.mmd` (mmdc 12.0.0) | **Pass** (exit 0). The SVG was generated. |
| `npx -p @mermaid-js/mermaid-cli mmdc -i docs/design/domain.md` | **Pass** (exit 0). The 2 Mermaid diagrams of the domain were generated. |

### Follow-up after cycle 1

| Command | Result |
|---|---|
| `node <skill dir>/scripts/check-package.mjs "C:\Users\Josue Escobar\Documents\projects\mine\Polyquack"` | **Fail** (exit 1), with a single problem: `[enums] PRD §15 PD-005 status not Open/Decided: Decided (replaced by PD-006)`. This is F-006 (MINOR). The reconciliation added no new problems. |
| `checks:` in the manifest | Not applicable: still no `checks:` key. |
| Structurizr CLI from the baseline scratchpad, with Java 17.0.12: `java -cp "<scratchpad>/structurizr/cli/lib/*" com.structurizr.cli.StructurizrCliApplication validate -workspace docs/design/architecture/architecture.dsl` | **Pass** (exit 0, no errors). The negative control `broken.dsl` gave exit 1 with «The destination element "zzz" does not exist». |
| `npx --yes -p @dbml/cli dbml2sql docs/design/data/schema.dbml` | **Pass** (exit 0). 22 `CREATE TABLE`: the previous 21 plus `excluded_pair`. |
| `npx --yes -p @mermaid-js/mermaid-cli mmdc -i docs/design/ux/flows.mmd -o <scratchpad>/fv1-flows.svg` | **Pass** (exit 0). The SVG does not contain «syntax error» and includes the accrual node. |
| `npx --yes -p @mermaid-js/mermaid-cli mmdc -i docs/design/domain.md -o <scratchpad>/fv1-domain.md` | **Pass** (exit 0). The 2 diagrams were generated. |

Decision status at follow-up:
- PD-020 (`prd.md:366`) and PD-021 (`prd.md:367`) are `Decided`, with author, date 2026-10-26, and verbatim quote: «Máximo usado a la vez (Recomendado)» and «Por par, excluyendo el par (Recomendado)».
- ADR-006 is `Accepted`, with "Accepted by: the author, 2026-10-26, «Acepto ADR-006 (Recomendado)»" (`ADR-006-price-capture.md:3-6`).
- No authority depends on an ADR in `Proposed`.

## Current Blocking Summary

| Severity | Open | Ready for verification | Resolved | Accepted/Invalid |
|---|---:|---:|---:|---:|
| BLOCKER | 0 | 0 | 0 | 0 |
| MAJOR | 0 | 0 | 5 | 0 |
| MINOR | 9 | 0 | 1 | 0 |
| NOTE | 0 | 0 | 0 | 0 |

## Findings

### F-001 — A position opened at hour t collects the funding of that same hour t

- Severity: `MAJOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `MAJOR_INCONSISTENCY`
- Owner: `docs/design/ux/flows.mmd` (and the missing rule in `docs/design/domain.md`)
- Related requirements: FR-020, FR-022, BR-004, NFR-007, NFR-008, BR-009
- Evidence:
  - `flows.mmd:24` triggers the E1 hour "after saving the funding". `flows.mmd:47` (`M --> P`) shows that it is triggered by saving the hour's funding reading.
  - `flows.mmd:29-32`: `open → walk the snapshot → record trade (W) → W --> X "Credit or debit funding to each leg"`. So the newly opened position receives funding that the platform charged before it existed.
  - `domain.md:101` (`open --> open : funding payment`) and FR-022 (`prd.md:197`) say "every time a platform charges funding". No authority clarifies that only payments with a time after the leg's opening count, or what happens at closing.
  - The NFR-008 test (`quality-attributes.md:14`) only checks `data_until <= hour`. It does not catch this error, because the funding of hour t has source_time = t ≤ t.
- Why it matters: if implemented as the flow draws it, every opening gains one hour of funding that it would never have collected. That optimistic bias goes straight into the return that decides the E1 verdict (BR-009). It is a classic look-ahead error that the planned test does not catch.
- Required resolution: the domain must fix the accrual rule: a leg only receives payments with a time strictly after its opening and less than or equal to its close or liquidation (or whichever rule the design chooses, stated explicitly). `flows.mmd` must stop crediting funding to a position in the same step in which it opens. The NFR-007/NFR-008 evidence in `quality-attributes.md` must include a test that no `paper_funding_payment.source_time` is less than or equal to `paper_position.opened_at`.
- Changed paths (cycle 1): `docs/design/domain.md` (term «Funding accrual», Paper position invariant, state diagram transition); `docs/design/ux/flows.mmd` (F-002: the accrual of hour t happens before deciding and only for legs opened before t; a leg opened at t collects from t+1); `docs/design/data/schema.dbml` (note on `paper_funding_payment.amount`); `docs/design/architecture/quality-attributes.md` (NFR-008, test 2).
- Verification evidence (follow-up, 2026-10-26):
  - The domain fixes the rule. `domain.md:27` defines «Funding accrual»: time strictly after the opening and less than or equal to the close or liquidation. `domain.md:84` is the Paper position invariant and covers both edges: a position that opens at t does not receive the payment of t, and one that closes at t does. `domain.md:110` says in the transition «funding payment after opening».
  - The flow no longer credits on opening. In `flows.mmd:26-27`, the accrual of t (`P --> X`) happens before deciding and «only to legs opened before t». `flows.mmd:34` says «a leg opened at t collects from t+1». The `W --> X` edge no longer exists: after recording the trade, `W` only goes to `Y` (`flows.mmd:36`).
  - The schema repeats it: the note on `paper_funding_payment.amount` at `schema.dbml:213` requires `source_time > opened_at` and `<=` close or liquidation.
  - The NFR-008 evidence includes the requested test. `quality-attributes.md:14`, test (2): no `paper_funding_payment.source_time` is less than or equal to `paper_position.opened_at`.
  - Impact on reversal: the payment of t goes to the old position, which closes at t, and not to the new one, which opens at t. This matches `domain.md:81` and `domain.md:84`.
  - No regression.
- Routed to: —
- Accepted by: —

### F-002 — Collateral is not defined when there are several positions at once or they change over time

- Severity: `MAJOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `DESIGN_GAP`
- Owner: `docs/product/prd.md` (BR-003; requires an author decision in §15)
- Related requirements: BR-003, FR-016, FR-017, FR-030, BR-009, PD-009, PD-015, SC-002
- Evidence:
  - `prd.md:278` (BR-003) defines "collateral = the sum, over both legs, of the notional ÷ reference leverage". That formula works for one position: 2 × 1,000 / 2 = 1,000 USD.
  - E1 decides every hour for every pair (`prd.md:192`) and there are 38 pairs, with a target of 100 (NFR-010). In a single period there can be from 0 to N open positions, and also hours with none.
  - Neither the PRD, nor `domain.md:26`, nor the DBML (`verdict.annual_return_on_collateral`, `schema.dbml:221`) say whether the denominator is the maximum collateral used, the time-weighted average, the collateral per position, or a fixed collateral for the run.
- Why it matters: depending on the option, the annual return can change by a factor of 10 or more, and that number decides whether E1 passes the threshold of ≥ 10% (BR-009). Two people would implement different verdicts with the same data.
- Required resolution: the author decides in PRD §15 (a new PD with a verbatim quote) how the collateral of a run with simultaneous or changing positions is calculated. Then BR-003 and the domain definition are updated citing that PD. This cannot be inferred: it is a product rule.
- Changed paths (cycle 1): `docs/product/prd.md` (new PD-020, decided by the author with a quote; BR-003 cites PD-020); `docs/design/domain.md` (term Collateral; Run invariant); `docs/design/data/schema.dbml` (`verdict.max_collateral`); `docs/design/ux/flows.mmd` (F-003, return step).
- Verification evidence (follow-up, 2026-10-26):
  - PD-020 is at `prd.md:366`: `Decided`, author, 2026-10-26, «Máximo usado a la vez (Recomendado)». The decision is "the maximum collateral committed at the same time during the run".
  - BR-003 (`prd.md:278`) defines the collateral of a position and of a run, and cites PD-020. FR-016 (`prd.md:180`) refers to BR-003.
  - The domain is aligned. `domain.md:26` defines the term. `domain.md:76` is the Run invariant and limits the maximum to non-excluded positions, which matches PD-021.
  - The DBML has `verdict.max_collateral` at `schema.dbml:235`, with a PD-020 note.
  - The flow applies it: `flows.mmd:49` computes the return over the maximum used at the same time.
  - All five authorities use the same denominator. No regression.
- Routed to: —
- Accepted by: —

### F-003 — PD-013 does not say at what level gaps are counted (per pair or in total)

- Severity: `MAJOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `DESIGN_GAP`
- Owner: `docs/product/prd.md` (PD-013 and FR-018; requires an author decision)
- Related requirements: FR-018, PD-013, SC-002, FR-003, FR-005
- Evidence:
  - `prd.md:359` (PD-013) says "more than 5% of hours without funding or more than 10% of minutes without an order book snapshot in the period". It does not say whether it is counted per pair, summing all pair-hours, or whether it is enough for a single pair to pass the limit.
  - `schema.dbml:151` marks `not_qualifiable` on the whole run. `flows.mmd:39-40` applies the rule to the entire run.
  - It does not say how pairs that are paired or delisted mid-period are counted (FR-003). Order books have no history (`findings.md:101`), so a new pair has no snapshots before it is paired.
- Why it matters: with 38 to 100 pairs, the option "it is enough for one pair to pass the limit" can leave the E1 run unqualified because of a single problem pair. That breaks SC-002. The option "sum everything" can hide a pair with no data. The two implementations give different results on whether the verdict comes out or not.
- Required resolution: the author decides in §15 the counting level (per pair, summed, or excluding the pair instead of the whole run) and how expected hours or minutes are counted for pairs that enter or leave. FR-018 and PD-013 are left with that precision.
- Changed paths (cycle 1): `docs/product/prd.md` (new PD-021, decided by the author with a quote; FR-018 rewritten citing PD-021); `docs/design/domain.md` (term Excluded pair; Run lifecycle and invariants); `docs/design/data/schema.dbml` (table `excluded_pair`; note on `run.status`); `docs/design/ux/flows.mmd` (F-003 per pair).
- Verification evidence (follow-up, 2026-10-26):
  - PD-021 is at `prd.md:367`: `Decided`, author, 2026-10-26, «Por par, excluyendo el par (Recomendado)». What it says: counting is per pair; the pair that passes the limit is left out and reported; each pair counts only between its pairing and its delisting. Affects lists PD-013, so it refines PD-013 without contradicting it.
  - FR-018 (`prd.md:186`) applies the limit per pair, measures only between pairing and delisting, qualifies with the remaining pairs, and leaves the run unqualified only if none remains.
  - The domain is aligned:
    - `domain.md:28` defines «Excluded pair».
    - `domain.md:71` is the lifecycle: `not qualifiable` only if all pairs were excluded.
    - `domain.md:75` is the invariant: measurement per pair between pairing and delisting; the profit and collateral of the excluded pair do not enter the verdict.
  - The DBML is aligned. `schema.dbml:152` is the note on `run.status`. `schema.dbml:156-167` is the `excluded_pair` table, with expected and missing hours and minutes per pair, and the reason.
  - The flow applies it at `flows.mmd:42-51`: count per pair, exclusion with report, «Are there pairs left?», `not_qualifiable` only if none remains, and verdict with the excluded pairs.
  - CAP-002 (`prd.md:118`, «Refuses to qualify a period with too many gaps») stays as a general summary and does not clash with FR-018.
  - No regression.
- Routed to: —
- Accepted by: —

### F-004 — Visibility is stored twice (method and variant) with no rule on which one governs

- Severity: `MAJOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `MAJOR_INCONSISTENCY`
- Owner: `docs/design/data/schema.dbml`
- Related requirements: FR-031, FR-033, CON-003, PD-002
- Evidence:
  - FR-031 (`prd.md:225`) and the domain (`domain.md:32`) put visibility on the study and on the method.
  - The DBML adds a second flag on the variant: `variant.visibility` (`schema.dbml:139`), in addition to `method.visibility` (`schema.dbml:129`).
  - No authority says what happens with a public method that has a private variant, or the reverse, nor which flag the exporter filters on (`architecture.dsl:26`, ADR-005:37).
- Why it matters: FR-033 is the product's privacy boundary. If the exporter filters only on `method.visibility`, it publishes the parameters of variants marked private, which are exactly the ones that show an edge (CON-003). It is data leaked by accident.
- Required resolution: remove the flag from the variant or define in `domain.md` a single, safe rule (for example, "published only if both the method and the variant are public"). The DBML is aligned with that rule.
- Changed paths (cycle 1): `docs/design/data/schema.dbml` (`variant.visibility` removed); `docs/design/domain.md` (term Visibility; Publishing rule: a variant datum is published only if its method is public).
- Verification evidence (follow-up, 2026-10-26):
  - The `variant` table (`schema.dbml:134-144`) no longer has `visibility`. I searched for `visibility` in `docs/design`: it only appears in `method.visibility` (`schema.dbml:131`) and `study.visibility` (`schema.dbml:247`). The note at `schema.dbml:140` says «No visibility of its own: takes that of its method».
  - The domain fixes a single rule:
    - `domain.md:34`: only studies and methods have visibility, and the variant takes that of its method.
    - `domain.md:129`: a variant datum is published only if its method is public, and no other flag exists that could enable it.
  - The exporter (`architecture.dsl:26`, «Reads only what is marked as public») and ADR-005 (`ADR-005-dashboard-and-public-view.md:26,37`) are left with a single flag to apply. FR-031 (`prd.md:225`) and FR-033 (`prd.md:231`) are consistent with this.
  - No regression.
- Routed to: —
- Accepted by: —

### F-005 — How the mark price and index price are captured every minute is not decided

- Severity: `MAJOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `MAJOR_INCONSISTENCY`
- Owner: `docs/design/architecture/adr/ADR-004-order-book-capture.md` (and `architecture.dsl`)
- Related requirements: FR-007, NFR-005, NFR-010, FR-023, FR-024
- Evidence:
  - `architecture.dsl:14` says the Ingestion "requests funding, prices, parameters, and fees over REST".
  - `schema.dbml:99-107` stores `price_reading` per instrument and per minute.
  - `flows.mmd:10` stores the "order book snapshot and price" at the close of each minute, as if they came from the live channel.
  - ADR-004 says what goes over REST (`ADR-004:41`: funding, instruments, parameters, history) and does not mention prices. Its own calculation (`ADR-004:26`) shows that 200 requests per minute (about 1.7 per second) exceed the tested rate of 1.25 per second on Polymarket, whose limit is not published.
  - It was not verified whether a batch endpoint exists (for example "tickers", `findings.md:497`) or a live mark price channel.
- Why it matters: if implemented as written at `architecture.dsl:14`, with one REST request per instrument every minute, it repeats the option that ADR-004 rejected and puts NFR-005 (zero bans) at risk. The per-minute prices feed the basis and the liquidation distance (FR-023, FR-024).
- Required resolution: ADR-004 (or a new ADR) decides the source and frequency of the mark price and index price: live channel, batch endpoint, or REST per instrument, with its rate calculation against NFR-005 and NFR-010. `architecture.dsl` and `flows.mmd` are aligned with that decision.
- Changed paths (cycle 1): `docs/design/architecture/adr/ADR-006-price-capture.md` (new, Accepted by the author with the quote «Acepto ADR-006 (Recomendado)»); `docs/design/architecture/architecture.dsl` (Ingestion description); `docs/design/ux/flows.mmd` (F-001, batch prices every minute); `docs/design/data/schema.dbml` (`price_reading.source_time` null if the source does not provide it, `received_at`); `docs/design/architecture/quality-attributes.md` (NFR-005, NFR-010).
- Verification evidence (follow-up, 2026-10-26):
  - ADR-006 is `Accepted`, with «Accepted by: the author, 2026-10-26, «Acepto ADR-006 (Recomendado)»» (`ADR-006:3-6`).
  - It weighed three options (`ADR-006:25-35`) and chose B: one batch request per platform every minute (`ADR-006:37-42`).
  - The rate calculation is at `ADR-006:12,30`: 2 requests per minute in total regardless of how many pairs there are, versus about 200 for the per-instrument option. That answers NFR-005 and NFR-010.
  - The endpoints appear as verified on Oct 26, 2026 at `ADR-006:14-17`: Polymarket Perps `GET /v1/info/tickers` and Hyperliquid `POST /info {"type":"metaAndAssetCtxs"}`. They were not queried again in this follow-up.
  - The architecture is aligned: `architecture.dsl:14` requests prices in a single request per platform every minute (ADR-006). Structurizr validates with exit 0.
  - The flow is aligned: `flows.mmd:14-16` makes one request per platform every minute and records a price gap if it does not arrive. This matches `ADR-006:42` and `gap.kind` `price` in `schema.dbml:115`.
  - The schema is aligned: `price_reading.source_time` is null when the source does not provide it, and `received_at` becomes the reading time (`schema.dbml:104-105`, `ADR-006:41`).
  - The quality attributes are aligned: NFR-005 and NFR-010 cite ADR-006 at `quality-attributes.md:11,16`.
  - ADR-004 does not mention prices, so it does not clash with ADR-006.
  - No regression.
- Routed to: —
- Accepted by: —

### F-006 — PD-005 uses a status that does not exist in the enum (the mechanical check fails)

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `EDITORIAL`
- Owner: `docs/product/prd.md`
- Related requirements: PD-005, PD-006
- Evidence: `prd.md:351` has the status `Decided (replaced by PD-006)`. `check-package.mjs` only accepts `Open` or `Decided` and exits with 1.
- Why it matters: the meaning is understandable, but the package does not pass its own mechanical check.
- Required resolution: leave the status as `Decided` and put the replacement by PD-006 in the Decision or Affects column. `check-package.mjs` must exit with 0.
- Verification evidence: follow-up of 2026-10-26: still not fixed. `check-package.mjs` exits with 1 and this is its only problem.
- Routed to: —
- Accepted by: —

### F-007 — Position states and decision actions do not match between the domain and the DBML

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/design/domain.md`
- Related requirements: FR-020, BR-006
- Evidence:
  - `domain.md:75` and `domain.md:103-104` have the state `reversed` and the transition `reversed --> open`, as if it were the same position. In contrast, `paper_position.status` (`schema.dbml:176`) only admits `open | leg_liquidated | closed` and fixes `polymarket_side` per position, so reversing means closing and opening another position.
  - `decision.action` (`schema.dbml:159`) and `flows.mmd:25` add `no_action`, which is not in the domain (`domain.md:21`) nor in FR-020.
- Why it matters: the behavior can be deduced, but the domain's state diagram suggests a model that the schema does not allow.
- Required resolution: the domain describes reversing as "closing and opening a new position on the opposite side" and recognizes `no_action` (or the DBML removes it).
- Verification evidence: follow-up of 2026-10-26: still open, although with the lines moved.
  - `domain.md:112-113` still has `reversed` and `reversed --> open`.
  - `domain.md:21` does not include `no_action`.
  - `schema.dbml:173` and `schema.dbml:190` remain as before.
  - `domain.md:81` now says «the opposite one is closed and opened», but the state diagram did not change.
- Routed to: —
- Accepted by: —

### F-008 — `gap.ends_at` is required even though the gap is still open

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/design/data/schema.dbml`
- Related requirements: FR-010, FR-028, BR-001
- Evidence: `schema.dbml:115` declares `ends_at datetime [not null]`, but `schema.dbml:117` allows the status `open` and `domain.md:57` defines `open` as a gap that has not ended yet. FR-028 shows the "open gaps".
- Why it matters: for a gap in progress an end time would have to be invented, which clashes with BR-001.
- Required resolution: `ends_at` accepts null while the gap is open, or the design documents how a gap in progress is represented.
- Verification evidence: follow-up of 2026-10-26: still not fixed. `schema.dbml:117` still has `ends_at datetime [not null]`.
- Routed to: —
- Accepted by: —

### F-009 — `price_reading` does not store the source time

- Severity: `MINOR`
- Status: `RESOLVED`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/design/data/schema.dbml`
- Related requirements: FR-007, BR-004, NFR-001, NFR-008
- Evidence: the identity of a Reading is "source + instrument + kind + source time" (`domain.md:51`), and the Evaluation reads "only by source time" (`domain.md:118`). `funding_reading` and `book_snapshot` have `source_time`, but `price_reading` (`schema.dbml:99-107`) only has `minute`, with no `source_time` or `received_at`.
- Why it matters: the BR-004 cutoff and the NFR-001 audit cannot be applied the same way to prices. Those prices feed the basis and the liquidation.
- Required resolution: add `source_time` (and `received_at`, if applicable) to `price_reading`, or document why the minute is enough.
- Verification evidence (follow-up, 2026-10-26): resolved by the cycle 1 change made for F-005.
  - `price_reading` now has `source_time`, null only when the source does not provide it, as on Hyperliquid, and `received_at [not null]` (`schema.dbml:104-105`).
  - Why the reception time is enough on Hyperliquid is documented at `ADR-006:41,49`.
- Routed to: —
- Accepted by: —

### F-010 — ADR-002 assumes a single writer, but the architecture has two

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/design/architecture/adr/ADR-002-storage.md`
- Related requirements: NFR-003, NFR-007
- Evidence: `ADR-002:15` says "A single process writes" and `ADR-002:18` sets "A single writer" as a criterion. But `architecture.dsl:23-24` has the Ingestion and the Evaluator writing to the same database, which are different processes (`architecture.dsl:14,16`).
- Why it matters: SQLite in WAL mode allows one writer at a time. If a long evaluator write blocks the per-minute snapshots, with no defined wait timeout, minutes can be lost (NFR-003). Right now the ADR reasons from a premise that is not true.
- Required resolution: ADR-002 acknowledges the two writers and sets how they coexist: short transactions, a lock wait timeout, or whatever is decided.
- Verification evidence: follow-up of 2026-10-26: cycle 1 did not touch it and it remains open.
- Routed to: —
- Accepted by: —

### F-011 — No container writes visibility or studies, and the exporter needs data that is not marked as public

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `COVERAGE_GAP`
- Owner: `docs/design/architecture/architecture.dsl`
- Related requirements: FR-031, FR-032, FR-009
- Evidence:
  - The dashboard only reads (`architecture.dsl:25`). The evaluator's command line only "preregisters variants and requests re-evaluations" (`architecture.dsl:29`). No path allows marking something as public or private (FR-031) or loading `study` (`schema.dbml:228-234`).
  - The exporter "reads only what is marked as public" (`architecture.dsl:26`), but FR-032 asks it to publish the ingestion status and the methodology, which have no visibility flag.
  - Not verified: whether the fee schedule (FR-009) can be obtained through a public API or has to be loaded by hand.
- Why it matters: these responsibilities are not assigned. They can be resolved with little work, but today they have no owner.
- Required resolution: assign in the architecture who writes visibility, studies and, if needed, the fee schedule. Specify which data without a visibility flag, such as the ingestion status, the exporter may read.
- Verification evidence: follow-up of 2026-10-26: still open. Nothing changed at `architecture.dsl:25,26,29` that affects this finding.
- Routed to: —
- Accepted by: —

### F-012 — It is not stated how old the order book snapshot used to compute the price can be

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/design/domain.md`
- Related requirements: FR-021, BR-001, CON-004
- Evidence:
  - FR-021 (`prd.md:195`) uses "the most recent order book snapshot before the decision", with no age limit. `flows.mmd:29` repeats that rule.
  - BR-001 (`prd.md:276`) forbids replacing a datum with the last known value. ADR-001:48 accepts up to about 34 hours of outages in 4 weeks.
- Why it matters: after an outage, the current rule would allow simulating a trade with an order book from hours earlier. In practice that is carrying forward a stale datum.
- Required resolution: the domain fixes the maximum age of the snapshot that can be used (for example, the minute before the decision). If there is no valid snapshot, the decision is `no_action` and a gap is recorded.
- Verification evidence: follow-up of 2026-10-26: still open. `flows.mmd:33` («Walk the previous order book snapshot») still has no age limit.
- Routed to: —
- Accepted by: —

### F-013 — It is not stated which price is used for the basis and liquidation, nor what happens if there is no liquidation fee

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `DESIGN_GAP`
- Owner: `docs/design/domain.md`
- Related requirements: FR-023, FR-024, FR-025, BR-001, BR-002, NFR-007
- Evidence:
  - `domain.md:28-29` and `schema.dbml:208` speak of "price" without saying whether it is the mark price, the index price, or the order book mid.
  - FR-025 requires recording the liquidation fee, but `instrument_parameters.liquidation_fee` accepts null "if the platform publishes it" (`schema.dbml:48`). There is no rule for when it is missing.
  - It also does not say which price sets the notional of the funding payment (`paper_funding_payment.amount`, `schema.dbml:199`).
- Why it matters: NFR-007 asks for results exact to the cent. Choosing one price or another changes when a leg is liquidated and how much the basis measures. The effect is bounded, because with 2x a liquidation is rare.
- Required resolution: the domain names the reference price for the basis, the liquidation, and the funding, and defines the treatment of an unknown liquidation fee without inventing it (for example, marking the result as incomplete).
- Verification evidence: follow-up of 2026-10-26: still open. The lines moved, but the content did not change:
  - `domain.md:30-31` still does not name the reference price.
  - `schema.dbml:222` still only says «Polymarket price − Hyperliquid price».
  - `schema.dbml:48` did not change.
- Routed to: —
- Accepted by: —

### F-014 — The NFR-008 test checks a field written by the same evaluator

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `COVERAGE_GAP`
- Owner: `docs/design/architecture/quality-attributes.md`
- Related requirements: NFR-008, SC-004, BR-004
- Evidence: the evidence at `quality-attributes.md:14` is `data_until <= hour`, a value that the evaluator itself writes in `decision` (`schema.dbml:160`). That test does not detect a later reading that the evaluator used without recording it, nor the F-001 case.
- Why it matters: SC-004 would be considered met with a test that cannot fail on the very error it looks for.
- Required resolution: the NFR-008 evidence must check the data actually used: for example, `paper_trade.snapshot_minute` and the snapshot's `source_time` against the decision hour, the payments against the opening, or a log of the readings consulted.
- Verification evidence: follow-up of 2026-10-26: partially fixed, so it remains `OPEN`.
  - `quality-attributes.md:14` added test (2), which compares the payments against the opening and checks data actually used for the funding.
  - The readings used by the decision, such as `paper_trade.snapshot_minute` against the hour or the `source_time` of the rates, are still checked only with `data_until <= hour`, which the same evaluator writes.
- Routed to: —
- Accepted by: —

### F-015 — UX-003 refers to a brief glossary that does not have those terms

- Severity: `MINOR`
- Status: `OPEN`
- Origin: `BASELINE`
- Classification: `MINOR_INCONSISTENCY`
- Owner: `docs/product/prd.md`
- Related requirements: UX-003
- Evidence: `prd.md:292` asks to use "the language of the brief glossary (funding, leg, basis)". The brief glossary (`brief.md:87-102`) belongs to the earlier approach, prediction markets, and does not define funding, leg, or basis. Those terms live in `domain.md:3-32`, which is the authority for the common language according to the manifest.
- Why it matters: it points to an outdated historical source instead of the current authority.
- Required resolution: UX-003 must refer to the common language of `docs/design/domain.md`.
- Verification evidence: follow-up of 2026-10-26: cycle 1 did not touch it and it remains open.
- Routed to: —
- Accepted by: —

## Cycle History

### Baseline — cycle 0

- BLOCKER open: `0`
- MAJOR open: `5`
- MINOR open: `10`
- NOTE open: `0`
- Verdict: `Needs design revision`
- Note: F-002 and F-003 need the author to decide a product rule in PRD §15, with a verbatim quote. The reconciliation cannot invent it. If that decision is not obtained, those findings move to `BLOCKED` and the package to `blocked`.

### Reconciliation — cycle 1

- Date: 2026-10-26. Scope: only the 5 open MAJOR findings (F-001 to F-005). The 10 MINOR findings (F-006 to F-015) remain `OPEN` as non-blocking debt.
- Author decisions used: PD-020 («Máximo usado a la vez (Recomendado)») and PD-021 («Por par, excluyendo el par (Recomendado)»), both of 2026-10-26 and recorded in PRD §15. ADR-006 accepted by the author on 2026-10-26 («Acepto ADR-006 (Recomendado)»).
- Files changed: `docs/product/prd.md`, `docs/design/domain.md`, `docs/design/ux/flows.mmd`, `docs/design/data/schema.dbml`, `docs/design/architecture/architecture.dsl`, `docs/design/architecture/quality-attributes.md`, `docs/design/architecture/adr/ADR-006-price-capture.md` (new).
- Commands run after the changes: `npx -p @dbml/cli dbml2sql schema.dbml` → exit 0, 22 tables; `check-package.mjs` → exit 1 only because of F-006 (MINOR, outside the scope of this cycle). Structurizr and Mermaid were not run again in this cycle.
- Findings moved to `READY_FOR_VERIFICATION`: F-001, F-002, F-003, F-004, F-005. None was marked `RESOLVED`: that is up to the independent verification.

### Follow-up verification — after cycle 1

- Date: 2026-10-26. Done by an independent subagent that wrote neither the package nor the reconciliation. It was a follow-up verification, not a new full review.
- Reconciliation change set: the 7 files of cycle 1, listed above.
- Impact reviewed:
  - PRD: BR-003, FR-016, FR-018, PD-013, PD-020, PD-021, and CAP-002.
  - Domain: terms, Run and Paper position invariants, state diagram, and Publishing rule.
  - DBML: `price_reading`, `run`, `excluded_pair`, `variant`, `paper_funding_payment`, and `verdict`.
  - Flows F-001 to F-003.
  - Ingestion in `architecture.dsl`.
  - NFR-005, NFR-008, and NFR-010.
  - ADR-004, ADR-005, and ADR-006.
- Findings verified:
  - F-001, F-002, F-003, F-004, and F-005 move to `RESOLVED`.
  - F-009 (MINOR) moves to `RESOLVED` because of the F-005 change.
  - F-006, F-007, F-008, F-010, F-011, F-012, F-013, F-014, and F-015 remain `OPEN`. F-014 is only partially fixed.
- New regressions: none
- Critical new blockers: none
- BLOCKER open: `0`
- MAJOR open: `0`
- MINOR open: `9`
- Previous BLOCKER+MAJOR open: `5`
- Current BLOCKER+MAJOR open: `0`
- Consecutive increases: `0`
- Commands and results:
  - `check-package.mjs`: exit 1, with 1 problem, the one from F-006.
  - Structurizr CLI `validate`: exit 0. The negative control gave exit 1.
  - `npx --yes -p @dbml/cli dbml2sql schema.dbml`: exit 0, with 22 `CREATE TABLE`.
  - `mmdc` of `flows.mmd`: exit 0.
  - `mmdc` of `domain.md`: exit 0, with 2 diagrams.
- Not verified: the ADR-006 endpoints were not queried again against the real APIs, because this verification does not touch external systems.
- Verdict: `Approved for build planning`. Corresponds to manifest `status: approved`.
