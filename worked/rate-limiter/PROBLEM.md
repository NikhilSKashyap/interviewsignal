# API Rate Limiter

**Role:** Backend Engineer | **Time:** 90 minutes | **Stack:** Python 3.10+, stdlib only

---

## Context

You're joining an API-first developer tools company. Our customers embed our API in their products — payment processors, notification services, data pipelines. We currently have a naive per-minute request counter that resets on the clock boundary. Customers are complaining:

- Burst traffic at the top of each minute gets through, then everything is blocked for 59 seconds
- There's no way to distinguish between a customer doing 100 small reads vs 10 expensive writes
- When we restart the service, all rate limit state is lost and customers get a free burst

## Your Task

Build a production-ready rate limiter that solves these problems.

### Requirements

1. **Sliding window or token bucket** — no fixed-window resets. Pick whichever algorithm you think fits better and explain why.

2. **Weighted operations** — different API operations cost different amounts. A `GET /status` costs 1 token. A `POST /process` costs 5 tokens. The limiter should accept a cost parameter.

3. **Per-client tracking** — each client is identified by an API key string. Clients are independent.

4. **Thread-safe** — our API server is multi-threaded. The limiter will be called from multiple threads concurrently.

5. **Clean interface** — design an interface you'd be comfortable code-reviewing in a real PR:

   ```python
   class RateLimiter:
       def allow(self, client_id: str, cost: int = 1) -> bool:
           """Return True if the request should proceed, False if rate-limited."""
   ```

6. **Tests** — write tests that cover:
   - Basic allow/reject behavior
   - Weighted operations exhaust tokens faster
   - Token replenishment over time
   - Concurrent access from multiple threads
   - Multiple clients don't interfere with each other

7. **Stretch: pluggable storage** — design (but don't implement) an interface so the backing store could be swapped from in-memory to Redis. What changes? What doesn't?

### Constraints

- Python 3.10+, standard library only (no Redis, no Flask, no external packages)
- The rate limiter is a library, not an HTTP server — don't build an API around it

### What we're evaluating

How you break down the problem, what tradeoffs you consider, and how you use AI tools. We can see every prompt, every edit, every decision. The AI assistant is fully available — we're evaluating your engineering judgment, not your ability to memorize algorithms.
