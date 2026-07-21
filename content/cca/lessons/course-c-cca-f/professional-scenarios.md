# Professional-level scenario practice

**How to reason through applied, architect-level scenarios.**

The five domain lessons teach the concepts. This lesson teaches the *move* the Claude Certified Architect (CCA) — Foundations exam actually rewards: reading a realistic scenario, spotting which principle governs it, and choosing the design that fits the constraints — usually the *simplest* one that meets the requirement. Scenario questions rarely test recall of a field name; they test whether you'd make the right architectural call under real pressures of cost, latency, reliability, and blast radius.

## A repeatable way to reason

For any applied scenario, walk the same five steps:

1. **Name the failure mode or requirement.** Is the pain *wrong tool selection*, *context overflow*, *non-deterministic output*, *unbounded cost*, *an irreversible action*, *a cache miss*? Naming it points straight at the relevant domain.
2. **Match it to a principle**, not a gadget — e.g., "reliability comes from schemas and gates, not more prose"; "workflows beat agents when the path is known."
3. **Choose the simplest design that satisfies the constraint.** Anthropic's standing guidance is to start simple and add complexity only when it *measurably* helps (Anthropic: building-effective-agents). A single agent or plain workflow often beats a multi-agent system.
4. **Check the guardrails.** Irreversible or high-consequence steps need a human checkpoint; unattended loops need budget/iteration caps; side effects need idempotency.
5. **Confirm it's observable and testable** — could you reproduce a failure and catch a regression?

## The scenario families to rehearse

The practice bank draws from five recurring, real-world archetypes. Learn the *shape* of each:

- **Multi-agent research systems.** A lead agent decomposes a question and dispatches subagents that investigate independently and return summaries. Reason about *whether* fan-out helps (are the subtasks genuinely independent and parallelizable?), context isolation per subagent, synthesis of returns, and the cost/latency tax. The trap is assuming more agents equals better answers.
- **Customer-support agents.** Routing by request type, escalation to humans when confidence is low, answering account questions from the live system of record (never model memory), and idempotent side effects like refunds. Watch for mis-calibrated escalation (escalates nothing, or everything) and double-action on retried writes.
- **Structured data extraction.** Converting documents into a fixed JSON shape for downstream code. Reason about Structured Outputs / tool schemas / enums over prose instructions, genuinely-optional fields, representative examples, and parallelizing independent sections of a large document.
- **CI/CD and automation.** Headless Claude Code running unattended — pre-granted and tightly-scoped permissions, deterministic enforcement via hooks, gating completion on a green build, and secrets kept out of context. The trap is an unattended job that hangs on an approval prompt or declares success over a failing build.
- **Developer productivity.** `CLAUDE.md` memory (and nested per-directory memory), plan vs. execute mode, skills for shared procedures, and MCP servers shared at project scope. The trap is using memory to *enforce* a guarantee that actually needs a hook or a managed/enterprise policy.

## Distractor discipline

Applied questions are built around plausible wrong answers. The most common distractor is the *over-engineered* option — a five-subagent orchestra where one agent suffices, an MCP server where a single stable API needs none, heavy chain-of-thought on a trivial task. A second is the *wrong-layer* fix — an instruction where the requirement demands enforcement (a hook, a schema, a permission, idempotency). A third is the *plausible-but-brittle* option — sizing by characters ÷ 4, retrying a side effect without an idempotency key, caching volatile data with a long TTL. When two answers both "work," prefer the one that is simpler, enforced rather than requested, and safe under failure.

## How to use the practice bank

Do the questions in the same posture you'll use on exam day. For each: name the failure mode before reading the options, predict your answer, then read the rationale to see *why* the right design wins and *why* each distractor is the wrong altitude. Track which of the five families you miss most and re-read that domain lesson — the exam's weighting means Agentic Architecture (27%) and the two 20% domains reward the deepest fluency, but the scenario reasoning above is what ties all five together.

## Further reading

- Anthropic, *Building Effective Agents* — https://www.anthropic.com/engineering/building-effective-agents
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower's Towards AI (Medium) CCA-F series — the per-domain articles referenced in the five domain lessons (supplemental, external link)
