# 01 Requirement analysis

**Input:** Build a scalable URL shortener service with APIs, persistence, and analytics.

**Type:** greenfield  |  **Domain:** url_shortener  |  **Ambiguity level:** medium

## Normalised engineering problem

Build a URL shortener service exposing a REST JSON API to create short links and redirect to the original URL (HTTP 302), persist links durably and record click analytics (total, per day, top referrers). Assumed targets: 100M new URLs/month, 100:1 read:write, p95 redirect < 100 ms, 99.9% availability.

## Functional requirements

- FR1 Create a short link for a long URL (optional custom alias) via a REST JSON API
- FR2 Redirect a short code to the original URL (HTTP 302)
- FR3 Persist links durably so they survive restarts
- FR4 Record clicks and expose analytics per link
- FR5 Validate input and return a consistent JSON error contract

## Non-functional requirements

- NFR1 Scalable: read-heavy workload, horizontally scalable stateless API tier
- NFR2 Safe: only http/https destinations, no SQL injection, no PII in analytics
- NFR3 Operable: health endpoint, structured errors, documented API

## Ambiguities and proposed assumptions

| ID | Topic | Question | Proposed assumption | Severity | Source |
|---|---|---|---|---|---|
| A1 | Scale | What does 'scalable' mean in numbers (new URLs per month, redirects per second, latency, availability)? | 100M new URLs/month, 100:1 read:write, p95 redirect < 100 ms, 99.9% availability, 5-year retention. | assumable | rules |
| A2 | Datastore | Which datastore, and how long must links be retained? | SQLite behind a repository interface for the prototype; PostgreSQL or DynamoDB recommended in production. | assumable | rules |
| A3 | Analytics scope | Which metrics are needed, and may IP address or user agent be stored? | Total clicks, clicks per day and top referrer hosts. No IP address or user agent is stored. | assumable | rules |
| A4 | Access control | Who may create links, and is authentication or rate limiting required? | No authentication in the prototype. API keys and rate limits are listed as production follow-up. | assumable | rules |
| A5 | Link semantics | Must the same URL always return the same code? Are custom aliases or expiry needed? | Every request creates a new random 7-char base62 code; optional custom alias; no expiry; redirects use 302 so every click is observable. | assumable | rules |
