# Worked Examples

Real interview problems with rubrics, transcripts, and AI-graded results.

Each example is a complete, ready-to-use interview you can deploy with `interview dashboard` in under 3 minutes. Copy the problem into the "Create Interview" form, paste the rubric, share the code.

---

## Available Examples

| | Rate Limiter | Webhook Delivery | Agent Task Queue |
|---|---|---|---|
| **Target role** | Backend Engineer | Backend Engineer | Backend Engineer |
| **Time** | 90 min | 90 min | 90 min |
| **Core algorithm** | Token bucket | Retry + backoff | DAG topo sort |
| **AI generates core** | ✓ easily | ✓ easily | ✓ easily |
| **Where signal lives** | Edge cases + threading | Scope triage + DLQ design | Failure propagation + timeout |
| **Prioritization required** | Low — fits in 90 min | High — too much for 90 min | Medium — concurrency eats time |
| **Startup type** | API/infra, dev tools | SaaS, B2B integrations | AI agent infra (YC hot) |
| **Difficulty** | Mid-senior | Senior | Senior+ |
| **Folder** | [rate-limiter/](rate-limiter/) | [webhook-delivery/](webhook-delivery/) | [agent-task-queue/](agent-task-queue/) |

> All three problems share the same structure: AI generates the core algorithm instantly, but the engineering judgment (edge cases, failure modes, concurrency) is where candidates differentiate. That's by design — it's what makes them good interviewsignal problems.

---

## What's in each example

```
worked/
  rate-limiter/
    PROBLEM.md              ← what the candidate sees
    RUBRIC.md               ← what the AI grader evaluates against
    candidate-a-strong.md   ← transcript of a strong session (scored 8.2)
    candidate-b-weak.md     ← transcript of a weak session (scored 4.8)
    grading-a.json          ← graded result for candidate A
    grading-b.json          ← graded result for candidate B
    review.md               ← what the grader got right and missed
```

**PROBLEM.md** is what you paste into the "Create Interview" form. It's written as a real engineering problem with context, not a LeetCode puzzle.

**RUBRIC.md** is what you paste into the rubric field. The AI grader uses these dimensions and weights to score the session. Tweak the weights to match what your team values.

**candidate-a / candidate-b** are the showcase. Same problem, same rubric, same AI tools — completely different signal. Candidate A drives the thinking and uses AI as a force multiplier. Candidate B pastes the problem and goes along for the ride. The transcript captures the difference no resume ever could.

---

## Contributing a worked example

Run an interview. Export it. PR it.

### 1. Run the interview

Create an interview with your own problem + rubric, have someone complete it, and review the result in the dashboard.

### 2. Export the session

From the dashboard detail page, click **Export as worked example** to download a ZIP containing PROBLEM.md, RUBRIC.md, the anonymized transcript, and the grading result.

### 3. Open a PR

```bash
git clone https://github.com/NikhilSKashyap/interviewsignal
cd interviewsignal
# unzip the export into worked/your-problem-name/
cp -r ~/Downloads/worked-example worked/your-problem-name
git checkout -b worked/your-problem-name
git add worked/your-problem-name
git commit -m "Add worked example: your-problem-name"
# open PR on GitHub
```

### Format requirements

- **PROBLEM.md** must include: role, time limit, stack constraints, context paragraph, numbered requirements, "what we're evaluating" section
- **RUBRIC.md** must include: 4-6 scored dimensions with weights that sum to 100%, score bands (what 9-10 vs 1-4 looks like), an "AI Collaboration Quality" dimension worth at least 20%
- **AI Collaboration Quality** is required as a rubric dimension — it's the whole point. If your rubric doesn't evaluate how the candidate uses AI, it belongs in a different repo
- Problems should be completable in 60-120 minutes with AI assistance
- Problems should be real engineering tasks, not algorithm puzzles

### What makes a great worked example

- **It's a real problem.** Something your startup actually needs built. "Build a rate limiter" is more useful than "reverse a linked list."
- **The rubric has teeth.** Score bands with concrete descriptions. Not "good code quality" but "correctly handles the race condition in the retry loop."
- **The transcript is interesting.** The best transcripts show a candidate making real decisions — disagreeing with AI, catching bugs, pivoting their approach. Boring transcripts where AI does everything aren't worth contributing.
- **The review is honest.** What did the grader get right? What did it miss? This is how we calibrate.
