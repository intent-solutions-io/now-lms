# Model Selection and Optimization

Picking a model is an engineering tradeoff, not a default. Every task has a profile — how much capability it needs, how fast it must respond, how much you're willing to spend — and the job is to match that profile to the right model tier and the right optimization levers. This lesson also clears up a few mechanics developers routinely get wrong: tokens, non-determinism, transport, and cost math.

## The model tiers and the tradeoff

Claude ships in a small family of tiers that trade capability against speed and cost (Models overview). Broadly:

- **Opus** — the most capable tier, for complex, high-stakes reasoning where accuracy matters more than speed or price.
- **Sonnet** — the balanced tier, a strong combination of intelligence and speed for moderate-complexity work used at scale.
- **Haiku** — the fastest, cheapest tier, for high-volume, latency-sensitive, lower-complexity work.

So for a product with three components — a real-time typeahead feature needing sub-second responses at huge volume, a complex multi-step contract-analysis feature where accuracy dominates, and a mid-complexity summarizer used moderately — the right mapping is fast/cheap (Haiku-class) for the typeahead, most-capable (Opus-class) for the contract analysis, and balanced (Sonnet-class) for the summarizer. Using the biggest model everywhere wastes cost and latency; using the weakest model on the highest-stakes task inverts the tradeoff.

## Tokens are not words

The model reads **tokens**, which are subword fragments, not whole words. For typical English text, token count runs roughly 1.3× the word count — so a 3,000-word document consuming ~4,000 tokens is expected, not a bug (Models overview; token counting). The ratio varies by language and content type. Two practical consequences: context windows are measured in tokens, and cost is per token, so estimating either from a word count alone will mislead you. Use the token-counting endpoint when you need a precise number before sending.

## Non-determinism is by design

Run the same prompt twice at default settings and you may get two different, both-reasonable outputs. That is not a bug — LLM generation *samples* from a probability distribution, so some variation is inherent even with identical input. You can *reduce* variation with parameters like **temperature** (lower temperature concentrates the distribution), but you cannot fully guarantee identical output. This holds for plain text generation, not just tool use or thinking modes. Design downstream systems to tolerate reasonable variation rather than assuming byte-for-byte repeatability.

## SDK vs. raw HTTP, and streaming transport

The official SDKs are **convenience wrappers** around the same REST API: they add typed request/response objects, retry and error handling, and streaming helpers. They are not mandatory and not a different protocol — raw HTTP calls to the Messages endpoint work fine, because it's REST underneath (API overview). Use the SDK to save yourself boilerplate, not because tool use or anything else requires it.

For a live "typing" UI, the Messages API streams tokens **incrementally over a standard HTTP request** (server-sent-event style). You do *not* open a raw WebSocket to the model API to get streaming, and streaming is not exclusive to any other endpoint. HTTP is fully capable of partial/incremental delivery here.

## Cost modeling and optimization

Input and output tokens are **priced separately**, and typically at different rates (output usually costs more per token). So model cost properly:

1. Estimate volume (e.g. 500,000 requests/month).
2. Estimate per-request input and output tokens (e.g. ~2,000 in, ~500 out).
3. Multiply each by its per-token price and its volume, sum the two.
4. Reconcile against actual usage after launch.

Beyond trimming unnecessary prompt content, the big optimization lever for a large, mostly-static prompt sent on every request is **prompt caching**: place a cache breakpoint after the static portion, and repeated requests read those tokens from cache at a **reduced rate** (roughly a tenth of the base input rate) instead of paying full price each time (prompt caching). For big non-urgent batch jobs, the **Batches API** cuts cost by 50%. Reducing `max_tokens` limits output length — it does *not* reduce input cost.

## Common pitfalls

- Defaulting to the largest model everywhere, ignoring cost and latency.
- Assuming a 1:1 token-to-word mapping when estimating context or cost.
- Reporting non-deterministic output as a bug, or expecting temperature=0 to make output perfectly identical.
- Believing the SDK is mandatory, or that it uses a faster/different protocol than HTTP.
- Thinking streaming requires WebSockets or the Batches API.
- Modeling cost with a single blended per-request price instead of separate input/output rates — and never reconciling against real usage.
- Confusing `max_tokens` (an output cap) with input-cost control.

## Further reading

- [Models overview (Anthropic docs)](https://docs.claude.com/en/docs/about-claude/models/overview)
- [Prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) · [Token counting](https://docs.claude.com/en/docs/build-with-claude/token-counting)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
