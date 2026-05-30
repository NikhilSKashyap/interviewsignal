export type Problem = {
  slug: string         // e.g. 'backend/rate-limiter'
  category: string     // 'backend' | 'mle' | 'frontend'
  title: string
  role: string
  time: string
  tags: string[]       // e.g. ['Python 3.10+', 'TypeScript'] — drives subtag filters
  problem: string      // full markdown
  rubric: string       // full markdown
}

export const problems: Problem[] = [
  {
    slug:     'backend/rate-limiter',
    category: 'backend',
    title:    'API Rate Limiter',
    role:     'Backend Engineer',
    time:     '90 min',
    tags:     ['Python 3.10+'],
    problem: `## Context

You're joining an API-first developer tools company. Our customers embed our API in their products — payment processors, notification services, data pipelines. We currently have a naive per-minute request counter that resets on the clock boundary. Customers are complaining:

- Burst traffic at the top of each minute gets through, then everything is blocked for 59 seconds
- There's no way to distinguish between a customer doing 100 small reads vs 10 expensive writes
- When we restart the service, all rate limit state is lost and customers get a free burst

## Your Task

Build a production-ready rate limiter that solves these problems.

### Requirements

1. **Sliding window or token bucket** — no fixed-window resets. Pick whichever algorithm you think fits better and explain why.

2. **Weighted operations** — different API operations cost different amounts. A \`GET /status\` costs 1 token. A \`POST /process\` costs 5 tokens. The limiter should accept a cost parameter.

3. **Per-client tracking** — each client is identified by an API key string. Clients are independent.

4. **Thread-safe** — our API server is multi-threaded. The limiter will be called from multiple threads concurrently.

5. **Clean interface** — design an interface you'd be comfortable code-reviewing in a real PR:

\`\`\`python
class RateLimiter:
    def allow(self, client_id: str, cost: int = 1) -> bool:
        """Return True if the request should proceed, False if rate-limited."""
\`\`\`

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

How you break down the problem, what tradeoffs you consider, and how you use AI tools. We can see every prompt, every edit, every decision. The AI assistant is fully available — we're evaluating your engineering judgment, not your ability to memorize algorithms.`,
    rubric: `Grade this session on five dimensions. Score each 1-10. Weight as shown.

## Problem Decomposition (25%)

- Did the candidate identify the core concerns (algorithm choice, weighted ops, thread safety, storage abstraction) before diving into code?
- Did they make an explicit choice between sliding window and token bucket, with reasoning?
- Did they sequence their work deliberately?
- Did they identify edge cases unprompted?

**9-10:** Clear plan articulated before coding. Correct algorithm tradeoff analysis.
**7-8:** Reasonable sequence, but some concerns discovered mid-implementation.
**5-6:** Started coding immediately. Thread safety or weighted ops were afterthoughts.
**1-4:** No visible decomposition. Dumped the whole problem to AI.

## AI Collaboration Quality (25%)

- **High-leverage (8-10):** Candidate outlines approach, asks AI for specific implementation help, reviews and modifies AI output, catches AI mistakes.
- **Medium-leverage (5-7):** Candidate uses AI as a capable pair programmer. Makes some independent modifications.
- **Low-leverage (1-4):** Candidate pastes the problem, accepts whatever comes back without meaningful review.

Key signals: Does the candidate ever disagree with or modify AI suggestions? Do they verify AI output by running tests? Do they use AI for tedious parts while doing design decisions themselves?

## Code Quality (20%)

- Is the token bucket / sliding window implementation correct?
- Does the weighted cost parameter actually work?
- Is thread safety implemented correctly?
- Is the pluggable storage interface reasonable if attempted?

## Testing (20%)

- Do tests cover all five required scenarios?
- Are thread-safety tests meaningful (actually exercising concurrency)?
- Did the candidate run tests and react to failures?

## Engineering Judgment (10%)

- Did the candidate make reasonable tradeoffs given the 90-minute constraint?
- Did they know when to stop?
- Would you want to review this code in a real PR?

## Scoring

Weighted score: \`decomposition×0.25 + ai_quality×0.25 + code×0.20 + testing×0.20 + judgment×0.10\`

**8.0+** Strong hire signal. **6.0-7.9** Promising. **4.0-5.9** Weak. **Below 4.0** No signal.`,
  },

  {
    slug:     'backend/agent-task-queue',
    category: 'backend',
    title:    'AI Agent Task Queue',
    role:     'Backend Engineer',
    time:     '90 min',
    tags:     ['Python 3.10+'],
    problem: `## Context

You're joining an AI infrastructure startup. Our product lets customers define AI agent workflows — chains of tool calls that an LLM orchestrates. Each step is a task that runs a tool. Tasks can depend on other tasks. Some tasks can run in parallel. Tasks can fail and need retries. The whole workflow has a timeout.

Our current implementation runs tasks sequentially in a single thread. Customers with 20-step workflows are waiting 10x longer than necessary because independent tasks aren't parallelized.

## Your Task

Build a task queue that executes a DAG (directed acyclic graph) of tasks with parallelism, retries, and timeout enforcement.

### Requirements

1. **Task definition**

\`\`\`python
@dataclass
class Task:
    id: str
    fn: Callable[..., Any]
    depends_on: list[str] = []
    max_retries: int = 2
\`\`\`

2. **DAG execution** — tasks run as soon as their dependencies are satisfied. Independent tasks run in parallel.

\`\`\`python
class TaskQueue:
    def submit(self, tasks: list[Task]) -> dict[str, Any]:
        """Execute tasks respecting dependency order. Returns {task_id: result}."""
\`\`\`

3. **Cycle detection** — raise \`ValueError\` before executing anything if the DAG has a cycle.

4. **Retry on failure** — retry up to \`max_retries\` times. If all retries fail, downstream tasks are skipped.

5. **Timeout** — configurable timeout on \`submit()\`. Returns partial results if timeout expires.

6. **Execution log** — record start time, end time, status, attempt count, and error for each task.

7. **Tests** — covering linear chain, diamond DAG, cycle detection, retry behavior, failure propagation, and timeout.

### Constraints

- Python 3.10+, stdlib only (\`threading\`, \`concurrent.futures\`, \`dataclasses\`)
- Use \`ThreadPoolExecutor\` or raw threads — no asyncio

### What we're evaluating

DAG scheduling is a well-known problem. AI can generate a topological sort in seconds. What we're watching: do you understand what the AI generates? Can you extend it when requirements get specific? Do you test concurrent behavior?`,
    rubric: `Grade this session on five dimensions. Score each 1-10.

This problem tests whether the candidate can direct AI through a systems problem with real concurrency. AI will generate a topological sort instantly — the signal is in how the candidate handles retry + failure propagation + timeout under concurrency.

## Problem Decomposition (25%)

- Did the candidate identify key subproblems: DAG validation, topological ordering, parallel execution, retry logic, failure propagation, timeout?
- Did they choose a reasonable implementation order?
- Did they recognize failure propagation as the hardest part?

**9-10:** Clear mental model before coding. Built incrementally.
**7-8:** Reasonable approach, discovered some complexity mid-implementation.
**1-4:** No decomposition. Gave AI the full problem.

## AI Collaboration Quality (25%)

- **High-leverage (8-10):** Uses AI for mechanical parts (topological sort, ThreadPoolExecutor boilerplate), drives design decisions themselves. Reviews AI code for concurrency bugs.
- **Low-leverage (1-4):** Gives AI the full problem or the hard parts. Doesn't review concurrency logic.

Key signals: When AI generates the DAG executor, does the candidate trace through a failure scenario? Does the candidate catch concurrency bugs (shared mutable state without locking)?

## Code Quality & Correctness (20%)

- Is cycle detection correct?
- Does parallel execution actually parallelize?
- Is retry logic correct?
- Does failure propagation work (downstream tasks skipped)?
- Is timeout mechanism sound?
- Thread safety: is shared state properly synchronized?

**Critical:** If the executor can deadlock, max score is 4 on this dimension regardless of code cleanliness.

## Testing (20%)

- Do tests cover all six required scenarios?
- Does the diamond DAG test verify parallel execution?
- Does the timeout test use a task that actually sleeps?
- Does the failure propagation test verify downstream tasks were NOT executed?

## Engineering Judgment (10%)

- Did the candidate handle the "threads can't be killed" Python limitation gracefully?
- Would you trust this code as a foundation to build on?

## Scoring

**8.0+** Strong hire. **6.0-7.9** Promising. **4.0-5.9** Weak. **Below 4.0** No signal.`,
  },

  {
    slug:     'backend/webhook-delivery',
    category: 'backend',
    title:    'Webhook Delivery Service',
    role:     'Backend Engineer',
    time:     '90 min',
    tags:     ['Python 3.10+'],
    problem: `## Context

You're joining a B2B platform that integrates with customer systems via webhooks. Our current implementation is fire-and-forget: one POST, no retries, no logging. Customers are losing events and we're losing trust. Last week a customer's server was down for 20 minutes and they missed 340 events with no way to recover them.

## Your Task

Build a reliable webhook delivery service.

### Requirements

1. **Endpoint registration**

\`\`\`python
class WebhookService:
    def register(self, customer_id: str, url: str, event_types: list[str]) -> str:
        """Register a webhook endpoint. Returns a registration ID."""

    def deliver(self, event_type: str, payload: dict) -> None:
        """Deliver an event to all registered endpoints matching this event type."""
\`\`\`

2. **Retry with backoff** — retry with exponential backoff on failure. At least 3 retry attempts.

3. **Delivery log** — every attempt logged: timestamp, endpoint, event type, attempt number, success/failure, response status code.

\`\`\`python
    def get_delivery_log(self, customer_id: str, limit: int = 50) -> list[dict]:
\`\`\`

4. **Dead letter queue** — after all retries exhausted, event goes to DLQ. Customer can list and replay.

\`\`\`python
    def get_dead_letters(self, customer_id: str) -> list[dict]
    def replay(self, dead_letter_id: str) -> None
\`\`\`

5. **Thread-safe** — \`deliver()\` returns immediately; HTTP calls happen asynchronously.

6. **Tests** — successful delivery, retry behavior, DLQ population, event type filtering, delivery log accuracy, replay.

### Constraints

- Python 3.10+, stdlib only (\`urllib.request\` for HTTP)
- All state in-memory
- Mock HTTP calls in tests

### What we're evaluating

This problem has more scope than 90 minutes allows. How you prioritize, what you build first, and what you consciously defer tells us about your engineering judgment.`,
    rubric: `Grade this session on five dimensions. Score each 1-10.

This problem intentionally has more scope than 90 minutes allows. A candidate who tries to build everything and finishes nothing scores lower than one who builds the core well and explicitly defers the rest.

## Prioritization & Decomposition (25%)

- Did the candidate identify what's core vs stretch?
- Reasonable order: registration + delivery → retry → delivery log → DLQ → replay.
- Did they articulate what they'd defer?

**9-10:** Explicit prioritization before coding. Built core delivery loop first. Deferred DLQ gracefully.
**1-4:** No visible planning. Features in random order or problem dumped to AI wholesale.

## AI Collaboration Quality (25%)

- **High-leverage (8-10):** Designs architecture, uses AI for specific well-defined pieces, reviews output, catches issues.
- **Low-leverage (1-4):** Gives AI the full problem or large chunks without specific direction.

Key signals: Does the candidate break the problem into AI-sized pieces? When AI generates retry logic, does the candidate verify the backoff math?

## Code Quality & Design (20%)

- Is retry logic correct? (Exponential backoff, bounded retries)
- Is thread safety correct? (Locking around shared state, not around HTTP calls)
- Are HTTP calls properly mocked in tests?

## Testing (20%)

- Do tests cover the six required scenarios?
- Do retry tests verify backoff behavior, not just that retries happened?
- Did the candidate run tests and respond to failures?

## Engineering Judgment (10%)

- Did the candidate make good use of 90 minutes?
- Is the code structured so a new team member could understand it?

## Scoring

**8.0+** Strong hire. **6.0-7.9** Promising. **4.0-5.9** Weak. **Below 4.0** No signal.`,
  },
]

export const categories = [...new Set(problems.map(p => p.category))].sort()
export const allTags    = [...new Set(problems.flatMap(p => p.tags))].sort()
