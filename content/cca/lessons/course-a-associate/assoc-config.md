# Configuration and Knowledge Management

Consistency at scale comes from configuration, not from remembering to re-type instructions. This domain covers how to give Claude persistent instructions and knowledge, how to keep connected sources trustworthy, and why configuration is something you maintain rather than set once and forget.

## Persist instructions instead of re-entering them

If a team needs every response to follow the same tone rules and reference the current FAQ, the wrong answer is to rely on each person's memory or to paste the material into one chat and hope it carries forward — it does not. The right answer is a persistent configuration: a Project whose standing instructions hold the tone guidelines and formatting requirements, and whose knowledge sources hold the current reference material. Written once into the Project's instructions, a requirement like "bullet-point summary, then recommended action" applies automatically to every conversation in that Project, so no one has to restate it. Persistent configuration is what turns individual good prompts into consistent team output.

## Put stable knowledge at the front and reuse it

The same principle shows up at the API level in how Anthropic recommends structuring context. Prompt caching lets you reuse a stable prefix — system instructions plus a large document or knowledge base — across many requests, placing the static content at the beginning and letting the dynamic, per-request content (the user's actual question) come after (Anthropic docs: build-with-claude/prompt-caching). This is the mental model for knowledge management generally: keep the durable, shared context in one stable place the tool reads every time, and vary only the specific question. It is cheaper and faster (cached reads cost a fraction of fresh input) and, more importantly for associates, it keeps every interaction grounded in the same source of truth.

## Keep connected knowledge sources current

Connecting Claude to a shared drive or knowledge source is only useful if the source stays accurate. If a connected folder still contains a pricing sheet that was replaced last month, Claude can reference the stale file — and you should not assume the model will reliably infer which version is newer. The right action is to maintain the source: remove or update the outdated file so Claude references only current information. Disconnecting the integration to avoid the problem throws away a useful capability; guessing at recency each time does not fix the underlying data. Managing a connector well means curating what it can see.

## Configuration is maintained, not set once

Configurations drift as the underlying facts change. A Project whose instructions were written six months ago and still describe a pricing structure the company has since changed twice will start producing answers that cite the old tiers. The fix is to review and update the Project's instructions and knowledge sources to reflect current reality — and to treat that review as a recurring maintenance task, not a one-time setup. Correcting the facts verbally in a single throwaway chat does not persist; deleting the Project entirely overcorrects. Schedule periodic config reviews the way you would any other upkeep, so the persistent context stays true.

## Common pitfalls

- Relying on individual memory or a one-time paste instead of persistent Project configuration.
- Scattering formatting or tone rules into every prompt rather than standing instructions.
- Assuming Claude will ignore or de-prioritize an outdated file in a connected source.
- Treating configuration as set-and-forget while the underlying facts change beneath it.
- Fixing a stale configuration with a single verbal correction that does not carry forward.

## Further reading

- Anthropic: [Prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) (mapped doc for this lesson — stable context reuse and knowledge-base placement)
- Anthropic: [Prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview) — instructions and context structure
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
