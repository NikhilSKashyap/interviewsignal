# Rate Limiter — Grading Rubric

Grade this session on five dimensions. Score each 1-10. Weight as shown.

---

## Problem Decomposition (25%)

- Did the candidate identify the core concerns (algorithm choice, weighted ops, thread safety, storage abstraction) before diving into code?
- Did they make an explicit choice between sliding window and token bucket, with reasoning?
- Did they sequence their work deliberately (e.g., core algorithm → weighted ops → thread safety → tests → stretch) or write everything at once?
- Did they identify edge cases unprompted: zero cost, negative tokens, capacity exhaustion, clock behavior?

**9-10:** Clear plan articulated before coding. Correct algorithm tradeoff analysis. Edge cases identified proactively.
**7-8:** Reasonable sequence, but some concerns discovered mid-implementation rather than upfront.
**5-6:** Started coding immediately. Discovered thread safety or weighted ops as afterthoughts.
**1-4:** No visible decomposition. Dumped the whole problem to AI and accepted the result.

---

## AI Collaboration Quality (25%)

This is the core signal. Evaluate HOW the candidate used AI, not WHETHER they used it.

- **High-leverage (8-10):** Candidate outlines approach, asks AI for specific implementation help, reviews and modifies AI output, catches AI mistakes, uses AI to accelerate not to think.
- **Medium-leverage (5-7):** Candidate uses AI as a capable pair programmer. Asks reasonable questions. Accepts most output but makes some independent modifications.
- **Low-leverage (1-4):** Candidate pastes the problem statement, accepts whatever comes back, says "yes" or "looks good" without meaningful review. The AI drove the thinking, the candidate was along for the ride.

Key signals in the transcript:
- Does the candidate ever disagree with or modify AI suggestions?
- Do they ask follow-up questions that show understanding?
- Do they verify AI output by running tests or reading the code critically?
- Do they use AI for the tedious parts (boilerplate, test scaffolding) while doing the interesting parts (design decisions, tradeoff analysis) themselves?

---

## Code Quality (20%)

- Is the code clean, readable, idiomatic Python?
- Are types consistent (type hints present or absent — not mixed)?
- Is the token bucket / sliding window implementation correct?
- Does the weighted cost parameter actually work (not just accepted and ignored)?
- Is thread safety implemented correctly (Lock granularity, no race conditions)?
- Is the pluggable storage interface reasonable if attempted?

**Deduction:** If the AI produced the code and the candidate accepted it without modification, score based on what the CANDIDATE contributed to the design, not the final code quality. Great code written by AI is the AI's achievement.

---

## Testing (20%)

- Do tests cover all five required scenarios?
- Are tests testing behavior, not implementation details?
- Did the candidate think about time-dependent test strategies (mocking vs sleeping)?
- Are thread-safety tests meaningful (actually exercising concurrency, not just calling from one thread)?
- Did the candidate run their tests and react to failures?

**Bonus:** Tests that reveal edge cases not in the requirements (e.g., what happens at exact capacity boundary, concurrent weighted requests that race for the last tokens).

---

## Engineering Judgment (10%)

- Did the candidate make reasonable tradeoffs given the 90-minute constraint?
- Did they know when to stop (e.g., not building a Redis backend when the stretch goal says "design, don't implement")?
- Did they handle the constraint "stdlib only" gracefully, or fight it?
- Would you want to review this code in a real PR?

---

## Scoring

Weighted score: `decomposition×0.25 + ai_quality×0.25 + code×0.20 + testing×0.20 + judgment×0.10`

**8.0+** → Strong hire signal. Candidate drove the thinking, used AI as a force multiplier.
**6.0-7.9** → Promising. Some good instincts, but either over-relied on AI or missed key concerns.
**4.0-5.9** → Weak signal. Candidate was mostly a passenger. AI did the interesting work.
**Below 4.0** → No signal or negative signal. Minimal engagement with the problem.
