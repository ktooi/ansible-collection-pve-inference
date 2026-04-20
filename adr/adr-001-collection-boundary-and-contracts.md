# ADR-001: Collection Boundary and Configuration Contracts

- Status: Accepted
- Date: 2026-04-20

## Context
The collection contains multiple roles spanning host preparation, CT management, runtime deployment, and validation. Without explicit boundaries and contracts, role responsibilities can blur, causing regressions and inconsistent user experience.

## Decision
1. Keep strict responsibility boundaries:
   - Host roles configure host prerequisites only.
   - `ct_instance` manages CT lifecycle only.
   - Runtime common roles provide shared CT runtime foundation.
   - Runtime-specific roles deploy and operate each inference runtime.
   - Validation role performs post-deployment checks.
2. Treat role defaults and README variable tables as the public configuration contract.
3. Require behavior-documentation synchronization in the same change whenever role behavior changes.
4. Record future cross-role architecture changes through ADRs.

## Consequences
### Positive
- Lower regression risk from accidental cross-role coupling.
- Predictable user-facing configuration surface.
- Easier review and maintenance across many roles.

### Negative
- Some changes require touching multiple files (tasks + defaults + README + possible ADR).
- Short-term overhead increases for contributors, but improves long-term consistency.

## Alternatives considered
- **Single monolithic role**: rejected due to poor separation of concerns.
- **No explicit contract policy**: rejected due to high drift risk between implementation and documentation.
