# Agents and Workflows

Not every problem needs an "agent." One of the most valuable judgment calls a Claude developer makes is deciding *how much autonomy* a system should have — and the honest answer is usually "less than you'd think." This lesson builds the mental model that separates a **workflow** from an **agent**, walks the common orchestration patterns, and shows where control lives when a model is allowed to act.

## Workflows vs. agents

Anthropic draws a sharp line between the two. A **workflow** orchestrates one or more LLM calls through *predefined code paths* — your code decides the sequence, and the model fills in the reasoning at each step. An **agent** lets the model *dynamically direct its own process and tool usage*, deciding what to do next based on what it observes (Anthropic engineering: Building Effective Agents).

The design principle is "start simple." For a well-specified, fixed task — say, classifying a support ticket into one of five categories and drafting a canned reply — a single LLM call inside a code-orchestrated pipeline is the right fit. The steps never vary, so autonomy adds cost, latency, and unpredictability with no upside. Reach for an agent only when the task is genuinely open-ended: when you can't enumerate the steps in advance and need the model to explore.

## The augmented LLM and workflow patterns

The building block underneath both is the **augmented LLM** — a model enhanced with retrieval, tools, and memory (Building Effective Agents). Anthropic catalogs five recurring workflow patterns:

- **Prompt chaining** — decompose a task into sequential steps, each call consuming the last one's output.
- **Routing** — classify an input, then send it to a specialized handler.
- **Parallelization** — run subtasks concurrently (sectioning) or take multiple attempts and aggregate (voting).
- **Orchestrator-workers** — a central model breaks a task into subtasks and delegates to workers when the breakdown isn't known ahead of time.
- **Evaluator-optimizer** — one call produces, another critiques, and the loop iterates toward a better result.

These are composable — a router can feed a chain, an orchestrator can spawn parallel workers.

## Subagents and the manager pattern

When several *independent, deep* concerns must be investigated — for example a code review checking security, style, and test coverage — a **manager/supervisor** architecture with **subagents** shines. Each subagent runs in its own **isolated context window** with its own system prompt and its own tool access; the supervisor dispatches them and synthesizes their findings (Claude Code docs: sub-agents). The payoff is twofold: **context isolation** keeps each investigation's raw material out of the main conversation, and parallel dispatch handles fan-out work. A single large agent inspecting everything sequentially risks context bloat and blended reasoning across unrelated concerns.

## Building agents: SDK, frameworks, and enforcement

To build a custom agent loop, the **Claude Agent SDK** provides the harness — the tool-use loop, permissions, and built-in tools — and runs under *your* infrastructure as a client-side framework rather than an Anthropic-hosted service (Claude Code docs). Graph-oriented frameworks like **LangGraph**, **PydanticAI**, or Strands *complement* the model API: they orchestrate explicit state machines and conditional branching around Claude calls; they don't replace Claude or force a different provider.

Autonomy demands guardrails. When a control must be *guaranteed* — say, never letting the agent run `git push --force` on main — a system-prompt instruction is only advisory; the model can still be talked into ignoring it. A **pre-tool-execution hook** deterministically inspects the proposed command and blocks it *before* it reaches the shell, regardless of what the model decided (Claude Code docs: hooks). Enforcement belongs in code, not in prose.

Finally, long-running agents accumulate large raw tool outputs (full web-page dumps, verbose logs) and quality degrades as context bloats. The fix is **context engineering**: prune or summarize stale, oversized outputs, keeping only the distilled findings.

## Common pitfalls

- Reaching for a "fully autonomous agent" when a fixed workflow would be cheaper, faster, and more predictable.
- Cramming independent concerns into one long context instead of isolating them in subagents.
- Trusting the system prompt to *enforce* a hard constraint — advisory text is not a control; hooks are.
- Assuming more tools always means more reliability. Unnecessary tool access widens blast radius without improving results.
- Letting raw tool output pile up until the model drifts — never pruning or summarizing.
- Believing a framework like LangGraph replaces the Claude API rather than orchestrating around it.

## Further reading

- [Building Effective Agents (Anthropic engineering)](https://www.anthropic.com/engineering/building-effective-agents)
- [Subagents (Claude Code docs)](https://code.claude.com/docs/en/sub-agents)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
