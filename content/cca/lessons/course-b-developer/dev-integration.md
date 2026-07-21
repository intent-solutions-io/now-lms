# Applications and Integration

Building *with* Claude is mostly ordinary software engineering with one probabilistic component in the middle. This lesson covers how you talk to the model (the API and its features), how you fit it into a real application lifecycle, and the integration discipline — requirements, review, validation, configuration — that keeps a Claude-powered feature from becoming a liability.

## The Messages API and its shape

The Claude API is a RESTful service; the **Messages API** (`POST /v1/messages`) is the core endpoint for conversational interactions (Claude API overview). You authenticate with an API key sent in the `x-api-key` header alongside an `anthropic-version`. Official **SDKs** (Python, TypeScript, and others) wrap this REST surface with typed objects, retry logic, and streaming helpers — but raw HTTP works too, because it's REST underneath.

Choose the right feature for the shape of the work:

- **Streaming** delivers tokens incrementally over a standard HTTP request so a live UI renders as the response is generated instead of waiting for the full completion — ideal for chat, especially long answers.
- **Vision / multimodal input** lets you pass an image (a photo of a whiteboard, a PDF page) directly in a message for transcription or analysis.
- **The Message Batches API** processes large volumes of requests asynchronously within a 24-hour window at **50% cost reduction** — the right tool for a non-urgent, latency-tolerant job like re-classifying 250,000 archived reviews (Build with Claude: batch processing).
- **Prompt caching** marks a stable prefix (a big system prompt, a reference document) as cached so repeated requests reuse it instead of reprocessing it, cutting cost and latency on cache hits.

Matching the feature to the requirement is the skill: batching is for throughput, not a live UI; caching is for reused static content, not one-off uploads.

## Requirements and the software lifecycle

A Claude feature is still a software feature, so the SDLC still applies. Separate **functional** requirements (what the system must do — "answer the requesting customer's shipping question correctly") from **non-functional / infrastructure** requirements (constraints like low latency and strict data isolation between accounts). Both matter for design and testing; conflating them hides real constraints.

Define **acceptance criteria** — schema conformance, hallucination-rate thresholds, latency bounds — during the *requirements/design* phase, before implementation, so evaluation is built in from the start. Because model output is inherently variable, explicit criteria become *more* necessary, not less.

## Integration discipline

Several failure modes are pure engineering, not model behavior:

- **Async correctness.** A Node route handler that forgets to `await` (or return) the Claude promise can send its HTTP response before the call resolves. The fix is to await/return the promise — not retries, not a "synchronous" call, not raising `max_tokens`.
- **Defensive parsing.** Never pass a model's JSON straight into a downstream API. Wrap parsing in error handling, validate the parsed object against an expected **schema**, and provide a graceful error/retry path. Better still, use **structured outputs** — typed fields and enums that constrain the response shape — and *still* validate downstream (Build with Claude: structured outputs).
- **Human review of generated code.** A 400-line, 12-file refactor produced by Claude Code gets reviewed like any pull request: logic, test coverage, side effects, and a reviewable commit history. AI origin does not exempt code from verification.

## Configuration and operational hygiene

- **Pin the model version.** An always-latest alias silently changes behavior when a new model ships. Pin the exact model ID in production config and roll forward deliberately after testing.
- **Session hygiene.** A single months-long conversation per account will start surfacing stale, resolved tickets. Scope conversations to a topic, start fresh sessions for new issues, and pull in prior context explicitly rather than accumulating everything.
- **Scoped permissions.** In Claude Code, `settings.json` distinguishes project-level defaults from local/user overrides, so CI can auto-approve safe commands while interactive developers are still prompted for risky ones. `CLAUDE.md` carries instructions and context — not permission enforcement.

## Match the surface to the use case

**Claude Code** is built for local, terminal- and file-integrated developer workflows. The **Messages API (via SDK)** is the integration point for embedding Claude into a scalable, customer-facing product. `claude.ai` is the hosted chat surface. Mismatching a surface to a job — a chat UI as your production API, or the API as your local dev tool — fights each surface's design.

## Common pitfalls

- Using the Batches API (or high real-time concurrency) for a live user-facing response.
- Skipping acceptance criteria because "LLM output is unpredictable anyway."
- Feeding tool-call JSON straight to a downstream API with no validation or error handling.
- Referencing an always-latest model alias in production, then being surprised by behavior drift.
- Letting one conversation accumulate forever instead of practicing session hygiene.
- Treating AI-generated code as exempt from review, tests, or a sane commit structure.

## Further reading

- [Claude API overview](https://docs.claude.com/en/api/overview)
- [Build with Claude — capabilities overview](https://docs.claude.com/en/docs/build-with-claude/overview)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
