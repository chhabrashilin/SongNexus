# Quota exhausted or abuse

**Confirm:** a sustained share of 429s (alert) from our own rate limiter (`RESOURCE_EXHAUSTED` body), or errors from a
Google API quota (Identity Toolkit during sign-in).

**Our limiter:** per signed-in user, or per client address when anonymous. Defaults per minute: reads 600, analysis and
puzzle moves 120, writes 60 (`SONGNEXUS_RATE_LIMIT_*`). Find the source in the request log by `route` and client.
- A legitimate client in a retry loop: fix the client; the API returns `Retry-After`.
- One address flooding: block it at Cloud Armor or the load balancer; do not raise the limits to absorb it.
- A real traffic surge: raise `max-instances` first, limits second.

**Google quota:** sign-in failures with quota errors need a quota increase request; browsing is unaffected.

**Cost guard:** the $25 / month budget alert; scale `max-instances` down to cap spend if abuse continues.
