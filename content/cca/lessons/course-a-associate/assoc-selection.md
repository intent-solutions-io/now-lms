# Product and Model Selection

Getting good results is not only about how you prompt — it is also about choosing the right tool for the job. This domain covers matching a Claude model and a Claude product surface to what the task actually demands, so you neither overpay for capability you don't need nor under-power a task that needs more.

## Match model capability to task difficulty

Anthropic ships a family of models that trade off intelligence, speed, and cost rather than one model for everything. At the time of writing that family spans, roughly from most capable to fastest: Claude Fable 5 (next-generation intelligence for long-running agents), Claude Opus 4.8 (complex agentic coding and enterprise work), Claude Sonnet 5 (the best combination of speed and intelligence), and Claude Haiku 4.5 (the fastest, with near-frontier intelligence). Cost tracks capability — the more capable models cost more per token (Anthropic docs: about-claude/models/overview).

The selection skill is to match the model to the difficulty of the task. Auto-tagging 40,000 support tickets a week into a handful of routing labels is simple, repetitive, high-volume work where per-item cost and throughput matter far more than nuanced reasoning — a faster, cheaper model is the right tool. Reaching for the most capable model there pays a large premium for accuracy the task does not need. Conversely, deep, ambiguous reasoning justifies a more capable model. Anthropic's own advice when unsure is to start with a strong general model and adjust, and to remember that some problems (like latency or cost) are solved better by changing the model than by more prompt engineering (Anthropic docs: prompt-engineering/overview).

## Weigh volume, latency, and cost against reasoning depth

Every model choice is a trade-off across four axes: capability, speed, cost, and context size. For high-throughput classification, optimize for speed and price. For a nuanced, one-off strategic analysis, optimize for reasoning. Routing every trivial ticket through several models and taking a majority vote multiplies cost for marginal benefit — ensemble techniques exist, but they are the wrong reflex on a simple task. Let the task's real requirements, not a habit of always picking the "best" model, drive the decision.

## Choose the right product surface, not just the model

Selection also means picking the right Claude *feature* for a recurring need. A five-person content team that pastes the same 12-page style guide into every new chat is re-entering context that a persistent surface is built to hold — configuring a Project with the guide as a standing knowledge source removes the re-paste and improves consistency. A broad, current, multi-source comparison of competitors' pricing is a research-shaped task that a research capability is designed for, not a single-turn chat reply drawn from the model's memory (which risks stale or incomplete information). Fit the surface to the shape of the work.

## Respect context windows and know when to start fresh

Current top-tier Claude models carry very large context windows — on the order of a million tokens for Fable 5, Opus 4.8, and Sonnet 5, and around 200k for Haiku 4.5 (Anthropic docs: models/overview) — but large is not infinite, and a single conversation run for weeks with documents pasted in daily will eventually degrade: Claude may surface outdated details from early in the thread and miss recent instructions. The fix is to start a fresh conversation, or summarize and carry forward only the still-relevant context, rather than piling more onto an overloaded thread. Repeating an instruction or assuming the model will automatically prioritize the newest information does not resolve context overload.

## Common pitfalls

- Defaulting to the most capable (and most expensive) model for simple, high-volume tasks.
- Using ensemble/majority-vote patterns where a single small model would do.
- Re-pasting the same reference material every session instead of configuring a persistent surface.
- Expecting a single quick chat reply to substitute for a real multi-source research task.
- Letting one conversation grow indefinitely until stale context corrupts the output.

## Further reading

- Anthropic: [Models overview](https://docs.claude.com/en/docs/about-claude/models/overview) (mapped doc for this lesson)
- Anthropic: [Pricing](https://docs.claude.com/en/docs/about-claude/pricing) — cost per token by model
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
