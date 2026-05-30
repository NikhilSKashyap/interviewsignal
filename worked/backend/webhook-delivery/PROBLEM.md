# Webhook Delivery Service

**Role:** Backend Engineer | **Time:** 90 minutes | **Stack:** Python 3.10+, stdlib only

---

## Context

You're joining a B2B platform that integrates with customer systems via webhooks. When events happen in our product (e.g., a ticket is created, a payment fails, a user signs up), we POST a JSON payload to URLs our customers have registered.

Our current implementation is fire-and-forget: one POST, no retries, no logging. Customers are losing events and we're losing trust. Last week a customer's server was down for 20 minutes and they missed 340 events with no way to recover them.

## Your Task

Build a reliable webhook delivery service that customers can depend on.

### Requirements

1. **Endpoint registration** — customers register webhook URLs with an event type filter. One customer might register `https://api.acme.com/hooks` for `ticket.created` and `ticket.resolved` events, and a different URL for `payment.failed` events.

   ```python
   class WebhookService:
       def register(self, customer_id: str, url: str, event_types: list[str]) -> str:
           """Register a webhook endpoint. Returns a registration ID."""

       def deliver(self, event_type: str, payload: dict) -> None:
           """Deliver an event to all registered endpoints matching this event type."""
   ```

2. **Retry with backoff** — if delivery fails (network error, non-2xx response), retry with exponential backoff. At least 3 retry attempts. The candidate chooses the backoff schedule and max attempts.

3. **Delivery log** — every delivery attempt is logged: timestamp, endpoint, event type, attempt number, success/failure, response status code. Customers can query their delivery history.

   ```python
       def get_delivery_log(self, customer_id: str, limit: int = 50) -> list[dict]:
           """Return recent delivery attempts for a customer, newest first."""
   ```

4. **Dead letter queue** — after all retries are exhausted, the failed event goes to a dead letter queue. The customer can list and replay events from the DLQ.

   ```python
       def get_dead_letters(self, customer_id: str) -> list[dict]:
           """Return all dead-lettered events for a customer."""

       def replay(self, dead_letter_id: str) -> None:
           """Retry delivery of a dead-lettered event."""
   ```

5. **Thread-safe** — delivery runs in background threads, not blocking the caller. `deliver()` returns immediately; actual HTTP calls happen asynchronously.

6. **Tests** — write tests covering:
   - Successful delivery to registered endpoints
   - Retry behavior on failure (mock the HTTP call)
   - Dead letter queue population after max retries
   - Event type filtering (endpoint only gets events it subscribed to)
   - Delivery log accuracy
   - Replay from dead letter queue

### Constraints

- Python 3.10+, standard library only (use `urllib.request` for HTTP, not `requests`)
- All state is in-memory — no database, no file system
- You can mock HTTP calls in tests — don't actually POST to external URLs

### What we're evaluating

This problem has more surface area than 90 minutes allows. How you prioritize, what you build first, and what you consciously defer tells us about your engineering judgment. We can see every prompt, tool call, and iteration in the transcript. Use AI however you want — we're watching how you steer it.
