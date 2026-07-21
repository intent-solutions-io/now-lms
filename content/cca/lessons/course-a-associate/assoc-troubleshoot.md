# Troubleshooting and Optimization

When Claude underperforms, the fix is almost never "the tool is broken" and almost always a diagnosable input problem. This domain is about reading the failure, changing the right thing, and then optimizing recurring work so you stop paying the same cost every time.

## Diagnose before you retry

The reflex to resubmit the same prompt and hope for a better result by chance is the single least productive troubleshooting move. Anthropic frames prompt engineering as an iterative loop — draft, test against your success criteria, refine — which means each failure should teach you what to change (Anthropic docs: build-with-claude/prompt-engineering/overview). Before concluding anything about the model, ask what the prompt actually gave it to work with. Most "bad Claude output" traces to a fixable gap in the input, not a limit of the tool.

## Under-specified prompts produce generic output

If asking Claude to "write a training summary" yields generic, unusable answers, the most likely root cause is missing context: which training, for whom, what it should cover, and how long it should be. Adding that specificity is the direct fix. This is the same clarity principle from prompting, seen from the debugging side — vague in, vague out. When results are flat and generic, the first hypothesis is under-specification, and the first experiment is to supply the audience, scope, and constraints the prompt omitted.

## Turn rejection into a specific diagnosis and an example

When a manager rejects a draft twice as "too salesy," resending minor wording variations repeats an approach that has already failed. The optimization is to diagnose what specifically reads as salesy — adjective density, exaggerated claims, hype phrasing — give Claude that concrete diagnosis, and include an example of the tone you actually want, then revise the prompt against it. Anthropic recommends examples as one of the most reliable ways to steer output (Anthropic docs: prompt-engineering/overview). Feedback only helps when it is specific enough to change the prompt; "make it better" is not a diagnosis.

## Supply adequate material and structure for complex tasks

Some tasks fail not for lack of tone guidance but for lack of substance. If a job genuinely requires multi-step reasoning across a large set of source documents but you have been using a single short prompt with nothing attached, the shallow answers are expected — the model is under-supplied. The fix is to provide the relevant documents and break the request into the sub-steps the task needs, then re-test. Concluding the model "can't do this" or abandoning AI assistance skips the actual diagnosis; decomposition plus real source material is what makes complex work tractable (Anthropic docs: engineering/building-effective-agents).

## Optimize recurring work with reusable structure

Once a task is working, the next lever is efficiency. A team that re-types similar instructions every week for a recurring status update is paying an avoidable cost. The optimization is to save a reusable prompt template — or a Project with standing instructions — that captures the recurring structure and requirements, so each cycle only needs the week's new data added. Continuing to retype from scratch keeps the inefficiency; reassigning the same manual process to someone else does not change it; dropping the deliverable eliminates value rather than optimizing how it is produced. Systematizing what repeats is where real time savings come from.

## Common pitfalls

- Resubmitting an unchanged prompt and hoping for a different result by chance.
- Concluding "the tool is broken" or "can't do this" before diagnosing the input.
- Responding to rejection with cosmetic wording tweaks instead of a specific diagnosis plus an example.
- Attempting complex, multi-document reasoning with a short prompt and no source material attached.
- Re-typing full instructions for a recurring task instead of saving a reusable template.

## Further reading

- Anthropic: [Prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) (mapped doc for this lesson)
- Anthropic: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — decomposition for complex tasks
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
