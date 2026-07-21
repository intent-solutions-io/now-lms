# Prompting and Task Execution

Prompting is the primary interface between you and Claude, so the quality of what you get back is largely governed by the quality of what you send in. This domain is about writing prompts that give Claude enough to work with and structuring larger tasks so the model can actually complete them.

## Start by knowing what "good" looks like

Anthropic frames prompt engineering as the *last* step, not the first. Before you tune wording, you should already have a clear definition of success for the task, some way to check output against that definition, and a first-draft prompt to improve (Anthropic docs: build-with-claude/prompt-engineering/overview). If you cannot say what a usable answer looks like, Claude cannot infer it for you — so decide the audience, the format, and the acceptance bar up front.

## Be clear, specific, and direct

The single biggest lever on output quality is specificity. A prompt that names the audience, the length, the tone, the topic, and the desired action gives Claude the constraints it needs to produce a usable first draft; a vague prompt like "write a marketing email" forces the model to guess, and guessing produces generic output (Anthropic docs: prompt-engineering/overview). Treat every prompt as a brief you would hand a new contractor: who is this for, how long, what tone, and what should the reader do next. Providing a concrete example of the target style or reading level makes the target even more unambiguous.

## Decompose complex tasks into reviewable stages

When a request spans multiple systems or stakeholders — say, redesigning an onboarding checklist that touches HR, IT, and facilities — do not ask for the whole thing in one shot. Break it into ordered stages: first surface the current pain points per department, then draft the changes for each, then merge into one checklist, reviewing each stage before moving on. Anthropic recommends chaining a task into fixed subtasks precisely because each smaller step is easier for the model to get right and easier for you to verify (Anthropic docs: engineering/building-effective-agents). Decomposition also keeps a human in the loop at each checkpoint rather than only at the end.

## Match your prompting strategy to the task type

Different tasks reward different framing. Generative, divergent work — brainstorming ten icebreakers, drafting alternative subject lines — benefits from open-ended prompts that ask for volume and variety. Analytical, convergent work — reviewing survey data for notable trends — benefits from the opposite: give the model the actual data, ask for a methodical review, and require supporting evidence for each finding. Applying a brainstorming frame to an analysis task (or vice versa) works against the outcome you want. The same prompt structure will not serve both, so adjust deliberately.

## Iterate with targeted feedback

A first draft that is accurate but wrong in tone is not a failure of the tool — it is the start of a normal refinement loop. Resending the identical prompt and hoping for a different result wastes a turn. Instead, tell Claude specifically what missed (too technical for a non-technical client, for example), supply an example at the target reading level, and ask it to revise. Prompt engineering is iterative by design; each round of concrete feedback moves the output closer to the goal (Anthropic docs: prompt-engineering/overview).

## Common pitfalls

- Under-specifying the audience, length, tone, or format and then blaming the model for generic output.
- Dumping an entire handbook or codebase with an instruction to "improve everything" instead of focusing the request.
- Resending the same prompt with only cosmetic tweaks when it has already failed.
- Using an open, creative frame for a task that actually needs precision and evidence.
- Skipping the up-front definition of what a successful answer looks like.

## Further reading

- Anthropic: [Prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) (mapped doc for this lesson)
- Anthropic: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — task decomposition and prompt chaining
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
