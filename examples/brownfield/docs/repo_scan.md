# Repository scan

Repository: `legacy_shortener`

| Module | LOC | Imports | Functions |
|---|---|---|---|
| app | 57 | codegen | shorten_handler, redirect_handler, _match, make_app |
| codegen | 6 | - | make_code |
| store | 16 | - | Store.__init__, Store.save, Store.get |

## Data flows

- `POST /shorten` -> app.shorten_handler -> codegen.make_code -> store.Store.save  (tables: links)
- `GET /<code>` -> app.redirect_handler -> store.Store.get  (tables: links)

## Findings

- `codegen.py:6` truncated_hash: md5 digest truncated to 4 hex chars = 65,536 possible codes; birthday collisions are expected after about 301 links
- `store.py:11` silent_overwrite: INSERT OR REPLACE silently overwrites an existing row with the same key
