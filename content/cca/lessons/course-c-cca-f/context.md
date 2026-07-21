# Context Management & Reliability

**Exam weight: 15%**

Every request to Claude is stateless: the model sees only what you send in the **context window**, and everything — system prompt, tool schemas, conversation history, retrieved documents, tool results — competes for that finite budget. Managing it well is what separates a demo from a production system that stays fast, cheap, and correct over long sessions. This domain pairs context discipline with the operational reliability practices that keep an agent trustworthy: caching, batching, retries, idempotency, and observability.

## The context window is a budget

Context is finite and shared. As a long agent session accumulates hundreds of tool results, it approaches the limit and quality degrades — the model can lose the thread, and important early instructions get crowded out by stale detail. Two failure modes recur:

- **Overflow / truncation.** Around hour two of a long-horizon task, accumulated tool output can approach the ceiling; without a strategy the request fails or silently drops content.
- **Lost-in-the-middle.** A long single prompt (a 340-line bill of materials, a large document set) can produce a confidently *wrong* answer because the relevant fact sat in a low-salience position, not because the data was absent.

Architectural responses: **retrieve, don't stuff** — for a 12-million-token, ~900-document knowledge base, no context window holds it all, so use retrieval (RAG) to pull only the relevant passages per query. **Summarize and compact** long histories — replace a wall of raw tool transcripts with a distilled state so the agent keeps the decisions, not the noise. And for long-context prompts, put the *documents first and the question last*, and ask the model to ground answers in specific quoted passages to fight lost-in-the-middle (Anthropic: long-context tips).

## Estimating size correctly

A common production bug is estimating request size as *characters ÷ 4*. That heuristic is only a rough approximation; dense text, code, and non-English content tokenize differently, so a batch sized right at the limit will intermittently overflow on the "heavy" items. Count tokens with the real tokenizer (the token-counting API) when you're sizing anything near the boundary, and leave headroom for the response — a non-streaming request reserves `max_tokens` of space, so an inflated `max_tokens` (16,000 for an 800-token summary) both wastes budget and can trip size limits.

## Prompt caching: the reliability-and-cost workhorse

**Prompt caching** lets you cache a stable prefix so repeated requests skip re-processing it, cutting cost and latency dramatically (Anthropic: prompt-caching). The mechanics you must know:

- You mark a cacheable point with **`cache_control`** on a content block; the cache is written *at that breakpoint* and matched by **exact prefix**. The hierarchy is **`tools` → `system` → `messages`**.
- **Order is everything.** Put stable content (system instructions, a product handbook, tool definitions, a pricing sheet) *first*, and volatile content (a per-request timestamp, the user's changing question) *last*. If a value that changes every request — a UTC timestamp in the system block — sits *before* your stable prefix, it invalidates the cache on every call and you get zero hits. This is the most-tested caching mistake.
- A change at any level invalidates that level **and everything after it**: editing tool definitions busts the whole cache; changing a later message doesn't touch the cached `tools`/`system`.
- The default cache TTL is **5 minutes**, refreshed on each hit; an **extended 1-hour TTL** (`"cache_control": {"type": "ephemeral", "ttl": "1h"}`) costs more to write but survives bursty, spread-out traffic. Beware staleness: if you cache a pricing sheet for an hour but pricing is edited unpredictably in a CMS, cached reads can serve outdated prices — match TTL to how often the source really changes, or invalidate on edit.
- There's a **minimum cacheable length** (e.g., 1,024 tokens on current top models) and a small cap on breakpoints; the response reports `cache_creation_input_tokens` and `cache_read_input_tokens` so you can verify hits.

## Reliability patterns: idempotency, retries, batching

Context discipline is half the story; the other half is behaving correctly under failure and load.

- **Idempotency for side effects.** If an `issue_refund` tool call times out *after* the refund service already processed it, a naive retry double-refunds. Side-effecting operations need idempotency keys (or a check-then-act) so a retry after an ambiguous timeout can't duplicate the action — a favorite exam scenario.
- **Rate limits and backoff.** A nightly job firing 200,000 classification calls concurrently will hit sustained 429s. The fix is client-side concurrency control and **exponential backoff with jitter**, not blind immediate retries that amplify the overload.
- **Right-sizing spend.** When most traffic is cheap intent classification with a repeated large prefix, the levers are a *smaller/faster model* for the trivial share (route by difficulty), *caching* the repeated prefix, and *batch* processing where latency isn't critical.

## Observability and change control

You cannot debug what you didn't record. Logging only the final assistant text makes a customer-reported bad answer unreproducible during an incident — capture the *full request context*: the exact prompt, system version, retrieved documents, tool calls and their results, and model/settings. Treat prompt changes like code: a triage classifier edited several times a week with **no automated checks** will eventually ship a regression, so gate prompt edits behind an **eval/regression suite** rather than eyeballing them. Reliability here means the system is *inspectable and testable*, not just usually correct.

## What trips up candidates

- **Putting volatile content (timestamps, per-request data) before the stable prefix**, silently killing cache hits.
- **Trusting characters ÷ 4** to size requests near the limit.
- **Stuffing a giant corpus into context** instead of retrieving the relevant slice.
- **Ignoring lost-in-the-middle** — assuming a fact present in a huge prompt will be used.
- **Retrying side-effecting calls without idempotency**, causing duplicate refunds/writes.
- **Firing high-volume jobs without backoff/concurrency limits**, turning a rate limit into an outage.
- **Caching volatile source data with a long TTL** and serving stale results.
- **Logging only final output**, leaving incidents unreproducible; shipping prompt edits with no eval gate.

## Further reading

- Anthropic, *Prompt caching* — https://docs.claude.com/en/docs/build-with-claude/prompt-caching
- Anthropic, *Context windows* and long-context guidance — https://docs.claude.com/en/docs/build-with-claude
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower, *The Memory Leak in Your AI Strategy*, Towards AI on Medium (supplemental, external link)
