# ADR-003 — Language and runtime environment

Status: Accepted
Date: 2026-10-26
Decision owners: the author
Accepted by: the author, 2026-10-26, «Python (Recommended)»
Related: CAP-001 to CAP-005, NFR-007, NFR-008, §14 (future ML)

## Context
Polyquack downloads data, stores it, evaluates methods with numerical computation and shows a dashboard. The future scope includes ML to predict which funding differences persist (PRD §14). Polymarket offers an official SDK for TypeScript and for Python (S-067). The discovery probes are already in Python (`docs/discovery/spikes/`).

## Decision Drivers
- Numerical and ML ecosystem for the evaluator and the future scope.
- Reuse what was learned in the probes.
- A single language for the whole system.

## Options Considered
### Option A — Python
- Benefits: pandas, NumPy, DuckDB and scikit-learn or PyTorch for the future ML. Official Polymarket SDK and libraries for Hyperliquid. The probes can be reused as a reference.
- Costs/risks: typing is optional; it has to be enforced with a type checker.

### Option B — TypeScript (Node)
- Benefits: official Polymarket SDK, strong typing and a single language with a possible web dashboard.
- Costs/risks: the numerical and ML ecosystem is weaker, and the probe logic has to be rewritten.

## Decision
**Option A**, Python, with strict type checking across all of our own code.

## Consequences
### Positive
- The evaluator and the future ML use the standard tools of the field.

### Negative / Trade-offs
- If the dashboard is built as a complex web application, it may require separate JavaScript (see ADR-005).

## Verification / Revisit Trigger
- Review whether the dashboard ends up needing a single-page web application.
