# Runbook

| Symptom | Check | Action |
|---|---|---|
| 5xx on create | Application log, database file permissions or disk space | Fix storage; retry is safe (codes are unique) |
| Redirects 404 | `GET /api/v1/links/<code>/stats` | Confirm the code exists in the `links` table |
| Slow redirects | Datastore latency; click insert on the request path | Add a cache; make analytics asynchronous |
| Analytics missing | `clicks` table and recent deployments | Roll back the last release |
