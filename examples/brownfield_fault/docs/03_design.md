# 03 Design: change proposal

## Collision-safe code generation and click analytics

- Replace truncated MD5 (4 hex chars) with a salted SHA-256 base62 code of 7 characters, retried on conflict
- Replace INSERT OR REPLACE with an atomic insert-if-absent so one URL can never overwrite another
- Add a clicks table (additive) and a GET /stats/<code> endpoint

## Scope (from impact analysis)

- Files that may be modified: app, codegen, store
- Files affected but not modified (regression-test targets): none

## Compatibility and rollout

- Public API is unchanged except for one additive endpoint (collision fix with analytics).
- Existing short codes keep working: lookup is by code and the lookup path is unchanged.
- Schema change is additive (`CREATE TABLE IF NOT EXISTS`), so rollback is a redeploy of the previous version.

