# Eval, Testing, and Debugging

You cannot improve what you cannot measure, and you cannot debug what you cannot classify. This lesson covers how to build evaluations for a Claude-powered system, the grading methods available, and — just as important — how to tell a *model* failure apart from an *infrastructure* failure when something breaks in production.

## Start with success criteria

Good evaluation begins with success criteria that are **SMART**: specific, measurable, achievable, and relevant (Test and evaluate: develop tests). "Good performance" is not a criterion; "F1 score ≥ 0.85 on a held-out set" or "fewer than 0.1% of 10,000 outputs flagged for toxicity" is. Anthropic groups common criteria into categories such as **task fidelity** (how well the core task is performed), **consistency**, **relevance and coherence**, **tone and style**, **privacy preservation**, **latency**, and **cost**. Most production systems need to be evaluated across *several* of these at once, not just one.

## Build an eval set

An eval is a set of test cases that mirrors your real-world task distribution — and deliberately includes the hard parts. Design test cases for **edge cases**: irrelevant or empty input, overly long input, sarcasm and implicit meaning, mixed or ambiguous sentiment, typos and formatting noise, out-of-domain queries, and multi-topic inputs. A sentiment eval that only contains clearly-positive and clearly-negative examples will pass in the lab and fail on the sarcastic tweet in production.

A key principle: **prefer volume with automated grading over a handful of hand-graded cases.** More test cases you can grade automatically will tell you more, faster, than a small set you grade by hand.

## Grading methods

The docs lay out a spectrum:

- **Exact match / string matching** — for categorical tasks with a clear right answer (sentiment = positive/negative/neutral). Normalize case and whitespace, then compare to a reference.
- **Semantic similarity (cosine)** — for consistency: embed the output and a reference, measure closeness. Similar questions should yield semantically similar answers.
- **Reference-based metrics (e.g. ROUGE-L)** — for summarization, measuring overlap with a reference summary.
- **LLM-based grading** — a model grades the output on a **Likert** scale (1–5 for subjective qualities like empathy), a **binary** check (does this contain PHI? yes/no), or an **ordinal** scale (how well was context used?). Best practice: grade with a *different* model than the one under test.

Grading feeds the loop: define criteria → build the test set → automate grading → run → analyze failures → refine the prompt → validate on held-out data. Evaluation is empirical and iterative, not one-and-done.

## Debugging: classify before you fix

When production breaks, the first move is to identify *which layer* failed — because the fix and the owner differ. Consider two very different symptoms:

- **An HTTP 429** during a traffic spike, with prompt content and output quality unchanged in the logs, is a **rate-limiting / infrastructure** signal at the integration layer — not a model failure. The response is backoff/retry and reviewing request concurrency, *not* rewriting the prompt or switching models.
- A response that returns **well-formed JSON describing an outdated refund policy** is a **model output / content** issue — likely stale context or retrieval — calling for a prompt or retrieval fix.

Now imagine both arriving under the same vague report ("the bot gives wrong answers"). If some requests return valid JSON with a wrong policy *and* others throw exceptions from a field-name mismatch after a client upgrade, those are two distinct bugs: one is a content/context problem, the other is an **integration-layer** breaking schema change. They need different fixes and different owners. Rolling back the model would address neither cleanly.

The discipline is to read the signal — the status code, whether logs changed, whether the output is syntactically valid — and resist the reflex to blame "the model" for everything. Note especially that **well-formed output is not correct output**: syntactically valid JSON can still carry a factually wrong answer, which is exactly why content-level evals exist.

## Common pitfalls

- Writing vague success criteria that can't be measured or automated.
- Building an eval set of only easy cases and omitting sarcasm, ambiguity, and out-of-domain inputs.
- Hand-grading a few cases instead of automating many.
- Grading with the same model you're testing (self-grading bias).
- Misattributing an infrastructure error (429, timeout, schema mismatch) to the model and "fixing" the prompt.
- Assuming well-formed JSON means the answer is factually correct.
- Treating evaluation as a launch gate rather than a continuous loop.

## Further reading

- [Define success criteria and develop tests (Anthropic docs)](https://docs.claude.com/en/docs/test-and-evaluate/develop-tests)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
