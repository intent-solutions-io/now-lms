# Workflow Integration and Solution Design

Claude delivers the most value when it is woven into how work already happens, not bolted on as a novelty. This domain is about designing solutions: clarifying the real requirement, integrating Claude into existing processes, keeping humans in control, and setting honest expectations with the people who approve the work.

## Start simple, add complexity only when needed

Anthropic's guidance on building agentic systems is deliberately conservative: start with simple prompts, optimize them with good evaluation, and add multi-step or agentic complexity only when simpler solutions fall short (Anthropic docs: engineering/building-effective-agents). The same instinct applies at the associate level. Most business tasks are well served by a well-scoped prompt or a light workflow — drafting, summarizing, comparing — long before anything elaborate is warranted. Design the smallest thing that solves the problem, and let real limitations pull you toward more structure rather than reaching for it first.

## Clarify the requirement before you design

A vague ask — "make our intake process better" — is not a specification, and designing straight from it builds the wrong thing. The most useful first step is to clarify: use Claude to help draft the questions worth taking back to the requester (current volume, specific pain points, stakeholders, constraints), then design once the requirements are real. Copying a generic template that ignores the specific context, or silently guessing what "better" means, both skip the requirements analysis that makes the eventual solution fit.

## Integrate to augment, and keep humans in the loop

Good integration inserts Claude where it removes drudgery while preserving the judgment the process needs. If a team spends an hour every Monday compiling a status report from five source documents, the integration is to feed Claude those five documents each week and have it draft the compiled report for a human editor to review and finalize — cutting the manual time without removing oversight. Anthropic stresses that humans should retain control over how goals are pursued, especially before high-stakes decisions (Anthropic docs: news/our-framework-for-developing-safe-and-trustworthy-agents). So Claude can surface likely bottlenecks in an invoice-approval process from cycle-time data, or lay out the trade-offs among three staffing schedules given real constraints — but the approval authority and the final call stay with the human.

## Treat design as iterative

A first draft workflow from Claude is a starting point, not a finished system. The way design work actually progresses is to put the draft in front of a few frontline staff, gather their concrete objections, feed those specifics back to Claude to revise, and repeat. Treating the first pass as final skips validation; discarding it and starting over by hand wastes the groundwork. Iteration with real stakeholder feedback is how a rough draft becomes something the team will actually use.

## Communicate value *and* limitations

When you propose adopting Claude for something like first-draft client correspondence, leadership needs a balanced picture to set expectations: where Claude genuinely speeds up drafting, *and* where it has limits — the need for human review of facts and tone, for example. Pitching only the upside, promising it will "never make a mistake," or omitting the review steps to avoid slowing adoption all misrepresent the trade-offs the decision-makers are responsible for weighing. Honest framing is what makes an integration durable.

## Common pitfalls

- Designing a full solution from a one-line request instead of clarifying requirements first.
- Reaching for complex, multi-step automation when a simple prompt would do.
- Handing Claude actual decision authority (approvals, final calls) instead of decision *support*.
- Treating a first-draft workflow as final and shipping it without stakeholder validation.
- Selling only the benefits and hiding the need for human review from leadership.

## Further reading

- Anthropic: [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (mapped doc for this lesson)
- Anthropic: [A framework for safe and trustworthy agents](https://www.anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents) — autonomy vs. human oversight
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
