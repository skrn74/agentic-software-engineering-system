# Impact analysis

**Root cause / driver:** Every redirect performs a database read; there is no caching layer.

## Modules to modify

- `store`: Store.get runs a SELECT on the hot read path

## Affected but not modified: app

## APIs impacted: GET /<code>, POST /shorten

## Existing tests covering these modules: tests.test_basic
