# Webhook Delivery Service — Grading Rubric

Grade this session on five dimensions. Score each 1-10. Weight as shown.

This problem intentionally has more scope than 90 minutes allows. The candidate MUST make prioritization decisions. A candidate who tries to build everything and finishes nothing scores lower than one who builds the core well and explicitly defers the rest.

---

## Prioritization & Decomposition (25%)

- Did the candidate read the full problem, identify what's core vs stretch, and plan an order?
- Reasonable priority order: registration + delivery → retry logic → delivery log → dead letter queue → replay. Thread safety can be layered in at any point.
- Did they articulate what they would defer if time runs short?
- Did they recognize that the DLQ and replay are lower priority than reliable retry?

**9-10:** Explicit prioritization before coding. Built the core delivery loop first. Deferred DLQ/replay gracefully with a clear "I'd do this next" note.
**7-8:** Reasonable order but no explicit priority call. Got to most features.
**5-6:** Started with a low-priority feature or tried to build everything at once.
**1-4:** No visible planning. Features appear in random order or problem was dumped to AI wholesale.

---

## AI Collaboration Quality (25%)

- **High-leverage (8-10):** Candidate designs the architecture, uses AI for implementation of well-defined pieces (e.g., "write the retry loop with exponential backoff using these parameters"), reviews output, catches issues.
- **Medium-leverage (5-7):** Candidate and AI share the thinking. Some good direction, some passive acceptance. Candidate modifies AI output in meaningful ways.
- **Low-leverage (1-4):** Candidate gives AI the full problem or large chunks without specific direction. Accepts output without review. Doesn't catch issues in AI-generated code.

Key signals:
- Does the candidate break the problem into AI-sized pieces, or hand over the whole thing?
- When AI generates the retry logic, does the candidate verify the backoff math?
- Does the candidate make independent design decisions (e.g., choosing between threading.Thread vs ThreadPoolExecutor) or defer all choices to AI?
- Does the candidate write any code themselves, or is it all AI-generated with minor edits?

---

## Code Quality & Design (20%)

- Is the registration model clean? (Mapping event types to endpoints correctly, handling one customer with multiple endpoints)
- Is retry logic correct? (Exponential backoff, bounded retries, correct error handling)
- Is the delivery log append-only and queryable?
- Is thread safety handled correctly? (Locking around shared state, not around HTTP calls)
- Are HTTP calls properly mocked in tests, not actually making network requests?

**Deduction:** If AI produced clean code but the candidate didn't meaningfully direct or review it, score the candidate's contribution, not the output.

---

## Testing (20%)

- Do tests cover the six required scenarios?
- Are HTTP calls mocked properly (not hitting real URLs)?
- Do retry tests verify the backoff behavior, not just that retries happened?
- Do dead letter tests verify that events land in DLQ after exactly max_retries failures?
- Did the candidate run tests and respond to failures?

**Bonus:** Tests for edge cases — registering the same URL twice, delivering to zero matching endpoints, replaying an event that now succeeds, concurrent deliveries.

---

## Engineering Judgment (10%)

- Did the candidate make good use of the 90 minutes?
- Did they know when to stop refining and move to the next feature?
- Did they handle the stdlib-only constraint naturally?
- Is the code structured in a way that a new team member could understand it?
- Did they leave TODOs or comments about what they'd do differently with more time?

---

## Scoring

Weighted score: `prioritization×0.25 + ai_quality×0.25 + code×0.20 + testing×0.20 + judgment×0.10`

**8.0+** → Strong hire signal. Candidate triaged scope, built the important parts well, used AI as leverage.
**6.0-7.9** → Promising. Decent prioritization but may have over-relied on AI or missed scope management.
**4.0-5.9** → Weak. Tried to build everything, finished little. Or AI drove the session.
**Below 4.0** → No signal. Minimal independent thinking visible in the transcript.
