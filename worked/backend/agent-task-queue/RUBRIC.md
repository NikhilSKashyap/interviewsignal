# AI Agent Task Queue — Grading Rubric

Grade this session on five dimensions. Score each 1-10. Weight as shown.

This problem tests whether the candidate can direct AI through a systems problem with real concurrency. AI will generate a topological sort instantly — the signal is in how the candidate handles the hard parts (retry + failure propagation + timeout under concurrency).

---

## Problem Decomposition (25%)

- Did the candidate identify the key subproblems: DAG validation, topological ordering, parallel execution, retry logic, failure propagation, timeout enforcement?
- Did they choose a reasonable implementation order? (Good: cycle detection → basic DAG execution → parallelism → retries → failure propagation → timeout. Bad: trying to build everything at once.)
- Did they recognize that "failure propagation" (skipping downstream tasks) is the hardest part and plan for it?
- Did they sketch the execution model before coding? (e.g., "ready queue of tasks whose deps are satisfied, worker threads pull from the queue")

**9-10:** Clear mental model of the execution engine before coding. Identified failure propagation as the crux. Built incrementally.
**7-8:** Reasonable approach but discovered some complexity mid-implementation.
**5-6:** Started coding without a plan. Parallelism or failure propagation was an afterthought.
**1-4:** No decomposition. Gave AI the full problem.

---

## AI Collaboration Quality (25%)

- **High-leverage (8-10):** Candidate uses AI for the mechanical parts (topological sort algorithm, ThreadPoolExecutor boilerplate) and drives the design decisions themselves (how to propagate failures, how to enforce timeout without killing threads, how to pass dependency outputs as kwargs). Reviews AI code for concurrency bugs.
- **Medium-leverage (5-7):** Mixes direction and delegation. Uses AI for implementation but makes some independent calls. May miss concurrency issues in AI-generated code.
- **Low-leverage (1-4):** Gives AI the full problem or the "hard parts." Doesn't review the concurrency logic. Accepts first output without testing edge cases.

Key signals:
- When AI generates the DAG executor, does the candidate trace through a failure scenario mentally or in a test?
- Does the candidate catch concurrency bugs (e.g., shared mutable state without locking, race in the ready-queue)?
- Does the candidate ask AI to explain its approach, or just accept code?
- When the timeout logic gets tricky (threads can't be killed in Python), does the candidate reason about it or let AI hand-wave?

---

## Code Quality & Correctness (20%)

- Is cycle detection correct? (Kahn's algorithm or DFS-based — either is fine)
- Does parallel execution actually parallelize? (Not just "submit to executor" but actually running independent tasks concurrently)
- Is retry logic correct? (Retries the right number of times, passes on the last exception)
- Does failure propagation work? (If B fails, D which depends on B is skipped — even if C succeeded)
- Is the timeout mechanism sound? (Returns partial results, doesn't hang indefinitely)
- Is dependency output passing correct? (Task receives outputs of its deps as kwargs with task_id as key)
- Thread safety: is shared state (results dict, ready queue, execution log) properly synchronized?

**Critical bug:** If the candidate's executor can deadlock (e.g., a task waits on a dep that was skipped but never marked as resolved), that's a maximum 4 on this dimension regardless of code cleanliness.

---

## Testing (20%)

- Do tests cover all six required scenarios?
- Linear chain test: does it actually verify order, not just that all tasks ran?
- Diamond DAG test: does it verify B and C ran in parallel (or at least concurrently), not just that D got both results?
- Cycle detection: does it test the right exception type?
- Retry test: does it verify the task ran exactly max_retries+1 times?
- Failure propagation: does it verify downstream tasks were NOT executed (not just that they returned None)?
- Timeout test: does it use a task that actually sleeps, not just assert on a fast DAG?

**Bonus:** Tests for edge cases — empty task list, single task with no deps, task that depends on a nonexistent ID, diamond with one branch failing.

---

## Engineering Judgment (10%)

- Did the candidate scope correctly for 90 minutes?
- Did they make a pragmatic threading choice (ThreadPoolExecutor vs raw threads)?
- Did they handle the "threads can't be killed" Python limitation gracefully?
- Did they leave clean TODOs for what they'd improve?
- Would you trust this code as a foundation to build on?

---

## Scoring

Weighted score: `decomposition×0.25 + ai_quality×0.25 + code×0.20 + testing×0.20 + judgment×0.10`

**8.0+** → Strong hire signal. Candidate understood the concurrency model, directed AI through the hard parts, tested real edge cases.
**6.0-7.9** → Promising. Got the DAG running but may have gaps in failure propagation or timeout handling. Used AI well but didn't catch everything.
**4.0-5.9** → Weak. Basic topological sort works but concurrency is broken or untested. AI did most of the thinking.
**Below 4.0** → No signal. Couldn't get beyond cycle detection, or the submission is entirely AI-generated with no candidate direction visible.
