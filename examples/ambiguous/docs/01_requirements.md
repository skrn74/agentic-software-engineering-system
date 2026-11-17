# 01 Requirement analysis

**Input:** Make the URL shortener faster and better for our users.

**Type:** brownfield  |  **Domain:** url_shortener  |  **Ambiguity level:** high

## Normalised engineering problem

Improve redirect-lookup performance of the existing URL shortener by caching hot lookups in a bounded in-memory LRU with correct invalidation. (Interpretation of an under-specified request; needs confirmation.)

## Functional requirements

- FR1 Repeated redirect lookups avoid a database round trip
- FR2 A changed or overwritten code is never served stale

## Non-functional requirements

- NFR1 Bounded memory (fixed-size cache)
- NFR2 No change to the public API

## Ambiguities and proposed assumptions

| ID | Topic | Question | Proposed assumption | Severity | Source |
|---|---|---|---|---|---|
| B1 | Meaning of 'faster' | Which operation must be faster (redirect lookup, link creation, stats) and by how much? | Redirect lookup. Success = repeated lookups of the same code are served without a database read. | blocking | rules |
| B2 | Meaning of 'better' | 'Better' is undefined: which quality attribute (speed, reliability, features, usability)? | Out of scope until defined. Only the performance change is made. | blocking | rules |
| B3 | Which users / traffic | Which users or traffic pattern should benefit? | Read-heavy redirect traffic with a skewed set of popular links. | assumable | rules |
