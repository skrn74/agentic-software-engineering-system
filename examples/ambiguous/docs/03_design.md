# 03 Design: change proposal

## Bounded LRU cache in the storage layer

- Add a fixed-size LRU in front of the SQLite lookup
- Invalidate the cached entry whenever a code is saved or overwritten
- Expose a db_reads counter so the effect is measurable in tests

## Scope (from impact analysis)

- Files that may be modified: store
- Files affected but not modified (regression-test targets): app

## Compatibility and rollout

- Public API is unchanged except for one additive endpoint (collision fix with analytics).
- No API or schema change; behaviour is identical apart from speed.
- Rollback is a redeploy of the previous version; the cache is in memory and disappears on restart.

