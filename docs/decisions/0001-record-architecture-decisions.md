---
status: accepted
date: 2026-10-18
---

# Record architecture decisions

## Context and problem statement

Many choices in brzask rest on measurements and trade-offs that are not visible
in the code: why a threshold has its value, why one approach was picked over a
simpler one. Without a record, these reasons get lost and the same questions are
reopened. How do we keep them?

## Decision drivers

- Reasons should live next to the code and be versioned with it.
- A decision should state what was measured, not only what was chosen.
- Writing one should take minutes, not hours.

## Considered options

- Architecture Decision Records in MADR format under `docs/decisions/`
- Comments in the code only
- A wiki outside the repository

## Decision outcome

Chosen option: ADRs in MADR format under `docs/decisions/`, published with the
documentation site. Each ADR records the context, the options considered, the
decision and, where it applies, the evidence behind it.

### Consequences

- Good, because the reasoning is reviewed and versioned together with the code.
- Good, because MADR is lightweight and widely understood.
- Bad, because ADRs need to be kept in step with the code; a superseded decision
  gets a new ADR rather than an edit.

## Pros and cons of the options

### Comments in the code only

- Good, because they sit exactly where the decision applies.
- Bad, because they cannot capture rejected options or decisions that span modules.

### A wiki outside the repository

- Good, because it is easy to edit.
- Bad, because it drifts from the code and is not part of review.
