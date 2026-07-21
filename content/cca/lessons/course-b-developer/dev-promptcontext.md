# Prompt and Context Engineering

Two related crafts sit at the heart of building reliable Claude applications. **Prompt engineering** shapes *what you ask* — instructions, examples, structure. **Context engineering** manages *what the model sees* — what goes into the finite context window and what stays out. This lesson covers both, plus the healthy skepticism you should keep toward confident-sounding output.

## When to prompt-engineer, and where things go

Prompt engineering is the right lever when a failure is controllable through better instructions — not every problem is (latency and cost, for instance, are often better solved by choosing a different model) (Prompt engineering overview). Before you tune, you should already have success criteria and a way to test against them, so you can tell whether a change actually helped.

Placement matters. Put **persistent, per-application** content — the persona, the behavioral rules that should hold on every conversation — in the **system prompt**. Put the **per-request** content — the user's actual question — in the **user turn**. This is the standard, supported division of labor; the system prompt is not deprecated, and you don't put the user's question in the system prompt to "prioritize" it. Then refine the system prompt **iteratively**, driven by observed failure cases, rather than rewriting it from scratch each time or freezing it forever at launch.

## Core prompting techniques

Anthropic's prompting guidance centers on a handful of reliable techniques (Claude prompting best practices):

- **Be clear and direct** — state exactly what you want; vague instructions get inconsistent results.
- **Give explicit output constraints** — spell out the exact allowed values and format.
- **Use examples (few-shot)** — show labeled examples of the exact expected output.
- **Give Claude a role** via the system prompt — an effective way to set behavior.
- **Structure with XML tags** — delimit sections (`<request>...</request>`) so the model can tell instruction from data.
- **Let the model think** (chain-of-thought) for multi-step reasoning.

A concrete case: a ticket classifier returns inconsistent labels — `billing_issue`, `Billing`, `billing`. The fix is not a bigger model or chanting "be consistent." It's **explicit output constraints** (the exact allowed category strings) plus a few **labeled examples** showing the precise format. Lowering temperature reduces randomness but doesn't tell the model *which* labels are legal — you still have to specify the set.

## Context engineering for large workloads

The context window is finite and expensive, and quality degrades when it bloats with raw material. When a research agent must read and summarize 50 long documents, don't paste all 50 into the main conversation. **Dispatch each document (or a batch) to an isolated subagent** that reads it and returns only a condensed summary; the main context then synthesizes the summaries, never the raw source text. This **context isolation** keeps the main conversation focused, and it scales fan-out work that a single context could never hold. The context window is not a per-request dial you turn up, and a bigger window wouldn't fix the bloat anyway — nor would skipping most of the documents, which sacrifices completeness. Related techniques include pruning or summarizing stale tool outputs as a session grows, and prompt caching to keep a reused prefix cheap.

## Skepticism toward confident output

A model states a wrong answer with exactly the same confidence as a right one, so confidence is not evidence. In high-stakes paths this matters enormously. If Claude extracts an invoice total that flows straight into a **payment-processing call**, the correct pattern is to **validate before acting**: check the extracted value against sanity constraints (is it numeric? is it in a plausible range? does it reconcile against line items if available?), and flag or reject on failure rather than trusting a confidently stated number. Asking the model "are you sure?" and trusting a "yes" is not verification — the model's self-confirmation is not ground truth. This is the same defensive posture you apply to any untrusted input, applied to the model's own output.

## Common pitfalls

- Reaching for prompt engineering when the real fix is a different model (latency/cost) or a data/retrieval change.
- Putting the user's per-request question in the system prompt, or believing system prompts are deprecated.
- Relying on "be consistent" or a bigger model instead of explicit allowed values plus few-shot examples.
- Never revising the system prompt after launch — or rewriting it wholesale instead of iterating on failure cases.
- Pasting massive source material into the main context instead of isolating it in subagents.
- Treating the context window as an adjustable per-request lever, or assuming a larger window cures context bloat.
- Trusting a confidently stated value in a high-stakes path without sanity checks.

## Further reading

- [Prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview)
- [Prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
