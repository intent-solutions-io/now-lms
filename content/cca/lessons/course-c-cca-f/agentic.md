# Agentic Architecture & Orchestration

**Exam weight: 27%** — the largest domain on the Claude Certified Architect (CCA) — Foundations exam.

This domain carries the most weight because it is the architect's core judgment call: given a task, do you build a fixed *workflow*, a fully autonomous *agent*, or something in between — and if you go multi-agent, how do you decompose the work without setting money on fire? Most scenario questions here reward the *simplest* design that meets the requirement, not the most elaborate one.

## Workflows vs. agents: the foundational distinction

Anthropic draws a sharp line between two kinds of agentic systems. **Workflows** are systems where LLM calls and tools follow *predefined code paths* — you, the engineer, control the sequence. **Agents** are systems where the model *dynamically directs its own process and tool usage*, deciding what to do next based on feedback from the environment (Anthropic: building-effective-agents).

The architectural takeaway: reach for a workflow when the steps are known and repeatable, because it is more predictable, cheaper, and easier to debug. Reach for a true agent only when the path genuinely can't be predicted in advance and you can tolerate the model's autonomy. The standing advice is to start with a single well-tuned prompt, and add orchestration complexity *only when it measurably improves outcomes* — a five-subagent system that performs no better than one agent is a net loss in cost and latency.

## The augmented LLM and the agent loop

The building block underneath everything is the **augmented LLM** — a model equipped with retrieval, tools, and memory (Anthropic: building-effective-agents). An *agent* is this augmented LLM used *in a loop*: it takes an action (usually a tool call), observes the result from the environment, and decides the next action, repeating until a stopping condition is met.

One full iteration of a hand-written agent loop is: send the model the context and available tools → the model returns either a final answer or a `tool_use` request → your code executes the tool → you feed the `tool_result` back into the context → the model reasons about that result and either finishes or calls another tool. The critical design point is that the loop should terminate on the model's own *stop* signal (a stop reason / final response), **not** on brittle string-scanning of the model's text. Continuation logic that greps the transcript for a keyword is the classic source of phantom tool calls and hung loops.

## Common workflow patterns

Anthropic names five composable patterns you should be able to recognize on sight (Anthropic: building-effective-agents):

- **Prompt chaining** — decompose a task into a fixed sequence, each step consuming the prior step's output. Best when a task cleanly splits into ordered subtasks and you'll trade a little latency for accuracy. Add a programmatic *gate* between steps when an early error would poison everything downstream.
- **Routing** — classify the input, then dispatch to a handler specialized for that category. Ideal when inputs fall into distinct types (e.g., password resets vs. billing disputes) that each deserve a different prompt or even a cheaper model.
- **Parallelization** — run subtasks concurrently. Two flavors: *sectioning* (independent pieces run side by side, then merge) and *voting* (run the same task several times and aggregate, useful when missing a positive case is expensive and you want multiple looks).
- **Orchestrator–workers** — a lead model dynamically breaks a task into subtasks at runtime and dispatches workers. Unlike parallelization, the subtasks aren't known ahead of time. This is the pattern for open-ended work like "investigate this large codebase."
- **Evaluator–optimizer** — one model generates, a second critiques against explicit criteria, and the first revises. Use it when you have a clear rubric and iteration demonstrably improves the output (e.g., translation that keeps missing idiom).

## Multi-agent orchestration and its costs

Multi-agent systems most often take a **hub-and-spoke** (orchestrator/lead-and-subagent) shape: a lead agent decomposes the problem, dispatches subagents, and synthesizes their returns. In Claude Code this is realized with **subagents** — each runs in *its own context window* with its own system prompt, tool access, and permissions, and returns only a summary to the parent (Claude Code: sub-agents). That separate-context property is the whole point: a subagent can churn through a long, noisy investigation and hand back a compact result, keeping the lead agent's context clean.

But multi-agent architecture is not free. It multiplies token spend and latency, and it only pays off when subtasks are genuinely *parallelizable and independent* — for example, three specialists (flights, hotels, policy) each contributing a distinct slice. If subtasks are sequential and dependent, an orchestrator adds coordination overhead with no quality gain. When you *do* fan out, keep each subagent's return summarized, not a raw transcript dump, or you reintroduce the context bloat you were trying to avoid.

## Guardrails, autonomy, and human-in-the-loop

Because agents act autonomously, errors *compound* across the loop and costs accumulate silently — a runaway agent can burn a budget doing 900 iterations and produce nothing (Anthropic: building-effective-agents). Architects mitigate this with:

- **Stopping conditions** — hard iteration and budget caps so a loop can't run unbounded.
- **Human checkpoints** — require approval before high-consequence, irreversible actions (deleting production data, terminating a contract, booking travel above policy). Read-only investigation can run autonomously; the irreversible step gets a gate.
- **Sandboxed testing** and clear success criteria measured over many runs.
- **Well-calibrated escalation** — an agent told to "escalate when unsure" is only useful if it *actually* escalates; over-conservative escalation (never handing off) is as much a failure as reckless autonomy.

## What trips up candidates

- **Reaching for a multi-agent system by default.** The exam rewards the simplest design that works; a single agent or a plain workflow often wins.
- **Confusing routing with orchestrator–workers.** Routing dispatches to *predefined* handlers; orchestrator–workers decomposes *dynamically* at runtime.
- **Ending the loop by scanning text** instead of respecting the model's stop signal — the root cause of phantom/hung loops.
- **Assuming subagents automatically improve quality.** They preserve *context*; they don't add intelligence for free, and they cost more.
- **Skipping human-in-the-loop on irreversible actions** while over-gating harmless read-only steps.
- **No budget/iteration cap** on unattended long-horizon agents.

## Further reading

- Anthropic, *Building Effective Agents* — https://www.anthropic.com/engineering/building-effective-agents
- Claude Code, *Create custom subagents* — https://code.claude.com/docs/en/sub-agents
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower, *Architecting Production-Grade Agents through LLM Orchestration and Agentic Loops*, Towards AI on Medium (supplemental, external link)
