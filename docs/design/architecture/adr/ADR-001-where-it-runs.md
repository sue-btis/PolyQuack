# ADR-001 — Where Polyquack runs 24/7

Status: Accepted
Date: 2026-10-26
Decision owners: the author
Accepted by: the author, 2026-10-26, «tengo unas vm que podria usar son locales, y sqlite»; team facts confirmed that day: «Sí, es un servidor siempre prendido», «Sí, estable», «Linux»
Related: NFR-002, NFR-003, NFR-004, NFR-006, NFR-013, CON-009, CON-010

## Context
Ingestion has to run without stopping. NFR-003 asks for one book snapshot per minute in at least 95% of the minutes of any 4-week window, and NFR-004 asks it to resume on its own within 10 minutes or less after an outage. The budget is 20 USD per month (CON-009) and servers next to the platforms are not allowed (CON-010).

## Decision Drivers
- 24/7 availability during the 4 weeks of the E1 verdict.
- Cost within 20 USD per month.
- Little operations work: the author spends 5 to 15 h per week.

## Options Considered
### Option A — The author's everyday computer
- Benefits: cost 0.
- Costs/risks: it gets turned off, suspended or restarted. NFR-003 is at risk.

### Option B — A small virtual server (VPS) with a monthly fee
- Benefits: on 24/7, with a stable network.
- Costs/risks: monthly cost and administration away from home.

### Option C — Scheduled serverless functions (cloud cron)
- Benefits: nothing to administer.
- Costs/risks: one execution per minute usually exceeds the free tier; a separate database is needed; cold starts complicate NFR-003.

### Option D — A local Linux VM of the author, on an always-on server
- Benefits:
  - The author already has it: additional cost of 0 USD.
  - The server is on 24/7 and its network is stable, according to the author on Oct 26, 2026.
  - It is far from the platforms' engines, as CON-010 requires.
- Costs/risks:
  - A power or internet outage at the site stops ingestion. The lost minutes are recorded as gaps (BR-001), and funding is recovered later with FR-011.
  - Backups are done by the author.

## Decision
**Option D**: Polyquack runs on a local Linux VM of the author, on a server that stays on. The services start on their own when the VM starts and restart on their own if they fail (NFR-004). Development and testing are done on the author's computer.

## Consequences
### Positive
- Compute cost 0 USD: the whole budget stays free.
- No data or credentials at an external provider.

### Negative / Trade-offs
- Availability depends on the site's power and internet. NFR-003 tolerates up to 5% of minutes without a snapshot in 4 weeks, about 34 hours.
- The public view is published outside, on static hosting (ADR-005), because the VM is not exposed to the internet.

## Verification / Revisit Trigger
- Measure NFR-003 in the first 2 weeks. If site outages push it below 95%, review Option B.
