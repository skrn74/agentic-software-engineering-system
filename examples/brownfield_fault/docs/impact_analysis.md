# Impact analysis

**Root cause / driver:** Short codes are a truncated hash, so different URLs can map to the same code, and the store overwrites on conflict. md5 digest truncated to 4 hex chars = 65,536 possible codes; birthday collisions are expected after about 301 links. INSERT OR REPLACE silently overwrites an existing row with the same key.

## Modules to modify

- `codegen`: md5 digest truncated to 4 hex chars = 65,536 possible codes; birthday collisions are expected after about 301 links
- `store`: INSERT OR REPLACE silently overwrites an existing row with the same key; persistence layer: a clicks table and recorder are needed
- `app`: route table: a new stats endpoint is needed; calls a function whose contract changes (make_code / save)

## Affected but not modified: none

## APIs impacted: GET /<code>, POST /shorten

## Existing tests covering these modules: tests.test_basic
