# Output Evaluation and Validation

A fluent, confident answer is not the same as a correct one. This domain is about the judgment you apply *after* Claude responds: verifying facts, catching bias and contradiction, deciding when human review is mandatory, and shaping output so it fits its real reader.

## Define success before you grade

You cannot evaluate what you have not defined. Anthropic recommends setting success criteria that are specific and measurable rather than vague — "less than 0.1% of outputs flagged for toxicity across 10,000 trials" beats "safe outputs" (Anthropic docs: test-and-evaluate/develop-tests). Most real work needs multidimensional criteria: task accuracy, consistency, relevance, tone, privacy handling, and cost all matter at once. Knowing which dimensions the deliverable must satisfy tells you exactly what to check.

## Treat confident, specific claims as unverified until sourced

Hallucination often wears the costume of precision. A made-up statutory clause number or an unsourced market-share percentage *looks* authoritative precisely because it is specific. The only reliable check is the authoritative source itself — the statute text, the original document, the primary data. Asking Claude whether it is "certain" does not help: that just generates another answer, not a verification. Anthropic's evaluation guidance leans on grading against ground truth (exact match, reference metrics, or a separate evaluator) rather than trusting a model's self-report (Anthropic docs: develop-tests). If a figure is going into anything client-facing, verify it against an independent source first.

## Catch contradiction and skew

Two kinds of internal signal should stop a publish. First, contradiction: if a drafted FAQ says the return window is 30 days in one answer and 45 in another, that is a factual error to resolve against the real policy — not a stylistic quirk to ship. Second, skew: if a summary of five departments' survey comments devotes most of its detail to one department despite similar comment volume from all five, suspect a summarization bias, check the underlying inputs, and ask for a balanced re-summary. Anthropic explicitly counts consistency and faithful use of context among the criteria worth measuring (Anthropic docs: develop-tests).

## Escalate high-stakes output to human experts

Some documents carry legal, financial, or employment consequences that no amount of polish removes. A Claude-drafted termination letter, for instance, should route through HR and legal review before it is sent — and the model's own assurance that something is "legally sound" is not a substitute for that review. Matching the level of human scrutiny to the stakes of the decision is a core validation habit, not optional caution.

## Fit the output to its reader and its use

Accuracy is necessary but not sufficient; the output also has to land with its audience and its workflow. A jargon-heavy write-up for the IT team needs to be re-rendered as a short, plain-language, business-impact summary for an executive committee — same facts, different framing. Likewise, twenty SKUs with prices and stock levels belong in a sortable table or data file, not a prose paragraph or an image, because the category manager needs to sort and filter them. When two drafts differ in emphasis, choose by comparing each against the actual situation and the communication goal, not by picking the longer one or flipping a coin.

## Common pitfalls

- Treating a specific-looking citation or statistic as evidence of accuracy.
- Asking Claude to self-assess its confidence and accepting that as verification.
- Publishing internally contradictory content because "minor variation is expected."
- Sending high-stakes legal or HR text without expert review.
- Delivering the right facts in a format or register the reader cannot use.

## Further reading

- Anthropic: [Define success criteria and build evaluations](https://docs.claude.com/en/docs/test-and-evaluate/develop-tests) (mapped doc for this lesson)
- Anthropic: [Define success](https://docs.claude.com/en/docs/test-and-evaluate/define-success) — writing measurable criteria
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
