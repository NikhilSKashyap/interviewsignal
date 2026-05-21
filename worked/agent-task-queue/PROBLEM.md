# AI Agent Task Queue

**Role:** Backend Engineer | **Time:** 90 minutes | **Stack:** Python 3.10+, stdlib only

---

## Context

You're joining an AI infrastructure startup. Our product lets customers define AI agent workflows — chains of tool calls that an LLM orchestrates. Think: "search the web, summarize results, write a report, email it."

Each step is a **task** that runs a tool (a Python callable). Tasks can depend on other tasks (task B needs the output of task A). Some tasks can run in parallel (tasks B and C both depend only on A). Tasks can fail and need retries. The whole workflow has a timeout.

Our current implementation runs tasks sequentially in a single thread. Customers with 20-step workflows are waiting 10x longer than necessary because independent tasks aren't parallelized.

## Your Task

Build a task queue that executes a DAG (directed acyclic graph) of tasks with parallelism, retries, and timeout enforcement.

### Requirements

1. **Task definition** — a task has an ID, a callable, a list of dependency task IDs, and a retry count.

   ```python
   @dataclass
   class Task:
       id: str
       fn: Callable[..., Any]       # the tool to run
       depends_on: list[str] = []   # task IDs this depends on
       max_retries: int = 2
   ```

2. **DAG execution** — tasks run as soon as their dependencies are satisfied. Independent tasks run in parallel (use threads). A task receives the outputs of its dependencies as keyword arguments:

   ```python
   class TaskQueue:
       def submit(self, tasks: list[Task]) -> dict[str, Any]:
           """
           Execute tasks respecting dependency order.
           Returns {task_id: result} for all completed tasks.
           Raises if the DAG has cycles.
           """
   ```

   Example:
   ```python
   tasks = [
       Task("search", search_web),                              # runs first
       Task("summarize", summarize, depends_on=["search"]),      # waits for search
       Task("translate", translate, depends_on=["search"]),       # parallel with summarize
       Task("report", write_report, depends_on=["summarize", "translate"]),  # waits for both
   ]
   results = queue.submit(tasks)
   ```

3. **Cycle detection** — if the DAG has a cycle, raise `ValueError` before executing anything.

4. **Retry on failure** — if a task's callable raises an exception, retry up to `max_retries` times. If all retries fail, the task is marked as failed. Downstream tasks that depend on a failed task are skipped (not executed).

5. **Timeout** — the entire `submit()` call has a configurable timeout. If the timeout expires, cancel pending tasks and return partial results for whatever completed.

   ```python
   class TaskQueue:
       def __init__(self, timeout_seconds: float = 300):
   ```

6. **Execution log** — record the start time, end time, status (success/failed/skipped/timeout), attempt count, and error message for each task.

   ```python
       def get_log(self) -> list[dict]:
           """Return execution log for the most recent submit() call."""
   ```

7. **Tests** — write tests covering:
   - Linear chain: A → B → C executes in order
   - Diamond DAG: A → (B, C) → D parallelizes B and C
   - Cycle detection raises ValueError
   - Retry behavior: task fails once then succeeds
   - Failed task skips downstream dependents
   - Timeout returns partial results

### Constraints

- Python 3.10+, standard library only (`threading`, `concurrent.futures`, `dataclasses` — no Celery, no asyncio)
- Tasks are CPU-light (they simulate I/O-bound tool calls) — threads are fine
- No asyncio — use `concurrent.futures.ThreadPoolExecutor` or raw threads

### What we're evaluating

DAG scheduling is a well-known problem. AI can generate a topological sort in seconds. What we're watching: do you understand what the AI generates? Can you extend it when the requirements get specific (retry + skip propagation + timeout)? Do you test the concurrent behavior, or just the happy path? The transcript shows everything.
