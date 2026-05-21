# Worked Examples

Real interview problems with rubrics, transcripts, and AI-graded results.

Each example is a complete, ready-to-use interview you can deploy with `interview dashboard` in under 3 minutes. Copy the problem into the "Create Interview" form, paste the rubric, share the code.

---

## Available Examples

| Example | Target Role | Time | Startup Type |
|---------|------------|------|-------------|
| [rate-limiter/](rate-limiter/) | Backend Engineer | 90 min | API/infra, developer tools (Stripe, Resend, Plaid) |
| [webhook-delivery/](webhook-delivery/) | Backend Engineer | 90 min | SaaS/B2B platforms (Pylon, incident.io, Svix) |
| [agent-task-queue/](agent-task-queue/) | Backend Engineer | 90 min | AI agent infrastructure (30%+ of current YC batch) |

---

## What's in each example

```
worked/
  rate-limiter/
    PROBLEM.md          ← what the candidate sees
    RUBRIC.md           ← what the AI grader evaluates against
    grading.json        ← sample graded result (score + per-dimension breakdown)
    session_transcript  ← sample session showing the thought process
    review.md           ← post-hoc review of grading accuracy
```

**PROBLEM.md** is what you paste into the "Create Interview" form. It's written as a real engineering problem with context, not a LeetCode puzzle.

**RUBRIC.md** is what you paste into the rubric field. The AI grader uses these dimensions and weights to score the session. Tweak the weights to match what your team values.

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
