# Prompt Engineering & Structured Output

**Exam weight: 20%**

Prompt engineering is where an architect turns a vague "make it more reliable" into concrete, testable design. At the Foundations level the exam is less interested in clever wording and more in *the reliability hierarchy*: knowing which technique actually fixes a given failure mode, and knowing when the right answer is a *feature* (like Structured Outputs) rather than more prose. A recurring theme: before you prompt-engineer at all, you should already have success criteria and a way to test against them (Anthropic: prompt-engineering/overview).

## Clarity, context, and structure first

Anthropic's techniques are meant to be applied roughly in order of leverage, starting with the cheapest, highest-impact moves (Anthropic: prompting-best-practices):

- **Be clear and direct.** State exactly what you want, and prefer telling Claude *what to do* over what *not* to do ("write in flowing prose paragraphs" beats "don't use markdown"). Vague instructions like "give helpful feedback" produce generic output; if you have a concrete definition of "good," put it *in* the prompt.
- **Add context.** Explaining *why* a task matters and who the audience is measurably improves results.
- **Structure with XML tags.** When a prompt mixes instructions, reference rules, examples, and the actual user input into one undifferentiated blob, Claude can misread which part is which. Wrapping each part in its own tag — `<instructions>`, `<context>`, `<transcript>`, `<input>` — removes that ambiguity. Use consistent tag names and nest them when content is hierarchical.
- **Give Claude a role** via the system prompt. Even a single sentence ("You are a senior claims adjuster") focuses tone and behavior.

## Examples (multishot) and letting Claude think

**Examples are the most reliable steering tool** for nuanced tasks. When a written definition of twelve subtle categories still yields inconsistent classification, adding a few labeled examples of correct behavior usually moves the needle further than more definition text. One caveat the exam probes: examples must be *representative*. Few-shot examples all drawn from short marketing copy will mislead a tool that mostly sees long technical documents — the examples set the pattern, so match them to production reality.

**Chain of thought** — instructing Claude to reason step by step before answering — improves accuracy on multi-step problems like tiered-discount math or reconciliation. But give the thinking somewhere to go: if you force a rigid final format too early (or historically, prefilled the answer), you can suppress the reasoning that made the answer correct. And beware *overthinking* — for simple tasks, demanding exhaustive reasoning wastes tokens and latency for no accuracy gain (Anthropic: prompting-best-practices).

## Structured and reliable output

Making output *machine-consumable* is a distinct skill from making it readable. The core options, strongest first:

1. **Structured Outputs** — a feature that constrains the response to a supplied JSON **schema** programmatically, rather than trusting an instruction. This is the recommended path when downstream code must parse a fixed shape and a stray sentence would break it. For a fixed set of labels (e.g., five triage categories feeding a switch statement), an **enum** field in the schema pins the output to valid values.
2. **Tool schemas** — defining a tool with a typed `input_schema` similarly forces the model's arguments into your shape, useful for entity extraction into a fixed JSON object.
3. **Instructions + XML + retries** — asking clearly for the structure and validating/retrying. Modern Claude models follow complex schemas reliably when *told* to, especially with a retry on the occasional miss.

Two important nuances. **Prefilling the assistant turn** — historically a common trick to force JSON by starting the reply with `{` — is *no longer supported on the last assistant turn* for Claude 4.6+ models (such requests return a 400 error); Structured Outputs and tool enums are the modern replacement (Anthropic: prompting-best-practices, "Migrating away from prefilled responses"). And when a schema has a genuinely optional field that is *sometimes legitimately absent*, design for that explicitly (nullable, or documented omission) rather than letting downstream code crash on a missing key.

## Grounding, refusal, and hallucination control

For tasks that must answer *only* from supplied material — summarizing a policy PDF, answering over a retrieved document set — the failure mode is plausible fabrication: details that appear nowhere in the source. Reduce it by instructing Claude to ground every claim in the provided text, to quote or cite the supporting passage, and — critically — to **refuse or say "not found" when the source doesn't contain the answer**. An assistant that must decline out-of-scope questions needs that permission stated explicitly, or it will helpfully invent.

## Prompts as maintained systems

Architect-level prompt engineering treats prompts like code. A single system prompt that grew to thousands of words by appending every edge case eventually contradicts itself and new rules stop taking effect — refactor and deduplicate instead of piling on. When you maintain many near-identical prompts, factor the shared core into one template with variables so a fix lands once, not thirty times with drift. And when a production failure appears, add it to a **regression suite** and make a targeted change, rather than rewriting the whole prompt from scratch each time (Anthropic: prompting-best-practices). Prompt chaining — splitting a complex prompt into focused steps — is itself a reliability technique.

## What trips up candidates

- **Adding more instruction text where examples would work better** (or vice versa) — match the technique to the failure.
- **Trusting a prose instruction for machine-parsed output** instead of Structured Outputs or a tool schema/enum.
- **Assuming prefill is still the way to force JSON** — it's deprecated on the last turn for 4.6+ models.
- **Unrepresentative few-shot examples** that don't match production input length or domain.
- **Forgetting to grant "refuse / not found"** for grounded-only tasks, inviting hallucination.
- **Over-forcing format before reasoning**, or demanding heavy chain-of-thought on trivial tasks.
- **Estimating tokens by characters ÷ 4** and sizing a batch right at the limit — it's an approximation that fails on dense or non-English text; count tokens properly.

## Further reading

- Anthropic, *Prompt engineering overview* — https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview
- Anthropic, *Prompting best practices* and *Structured outputs* — https://docs.claude.com/en/docs/build-with-claude/prompt-engineering
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower, *The Reliability Hierarchy*, Towards AI on Medium (supplemental, external link)
