# Session Debrief Prompt

This is the prompt Claude uses to generate the session debrief shown to every candidate
after `/submit`. It's community-editable — open a PR if you have a better framing.

The debrief is Claude's analysis of the session, not the hiring manager's evaluation.
It should be honest, specific, and immediately useful to the candidate.

---

## Instructions (used verbatim by SKILL.md Flow 3 Step 4)

Read `~/.interview/sessions/<CODE>/events.jsonl` and write an honest, specific debrief
of the candidate's session. Save it to `~/.interview/sessions/<CODE>/debrief.txt`.

Frame the debrief as a direct reflection addressed to the candidate. Cover:

1. **What they did well** — specific moments where their thinking was strong
2. **What they missed or underexplored** — gaps in the solution, tests not written, edge
   cases skipped, assumptions not stated
3. **How they used the AI** — were their prompts high-leverage (directing the AI toward
   a plan) or low-leverage (asking it to just write code)? Did they verify the output?
4. **One concrete thing** they could do differently next time

Keep it under 300 words. Be honest but constructive. Do not score or rank — just observe.
Avoid generic praise. Every sentence should be something only possible to write after
reading *this* session.

---

## Contributing

Good debrief prompts share a few properties:
- They push Claude toward specificity ("what happened at timestamp X") not generics
- They distinguish signal (candidate's thinking) from noise (boilerplate AI output)
- They stay useful to a candidate who got rejected, not just one who got hired

To suggest an improvement: open a PR editing this file. Include a worked example showing
the before/after debrief output on a real or synthetic session from `worked/`.
