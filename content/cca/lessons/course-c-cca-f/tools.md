# Tool Design & MCP Integration

**Exam weight: 18%**

Tools are how Claude reaches beyond its own knowledge to act on the world — and *tool design is interface design*. Anthropic argues the agent–computer interface (the ACI) deserves as much care as a human-facing UI, because the model can only use a tool as well as the tool is described and shaped (Anthropic: building-effective-agents). The exam here rewards architects who can tell *why an agent keeps picking the wrong tool* and reach for the right fix: a better description, a cleaner schema, fewer tools, error-proofing, or an MCP server at the right scope.

## How tool use works

You give Claude a tool by defining a **`name`**, a **`description`**, and an **`input_schema`** (a JSON Schema describing the parameters) (Anthropic: tool-use/overview). The lifecycle is a round trip: Claude decides a tool applies and returns a **`tool_use`** content block (with the tool name and an `input` object) alongside `stop_reason: "tool_use"`; your application executes the operation and sends the outcome back in a **`tool_result`** block referencing the same `tool_use_id`; Claude then uses that result to answer.

**Client tools** (the ones you define, plus Anthropic-schema tools like `bash` and `text_editor`) execute in *your* application. **Server tools** (like `web_search`, `web_fetch`, `code_execution`) run on Anthropic's infrastructure and return results directly. This distinction drives design: if you need current public web information, the managed `web_search` server tool exists; if you need Claude to compute statistics over retrieved data, `code_execution` runs Python in a sandbox rather than you hand-rolling it.

## Descriptions and schemas are the product

The single highest-leverage investment is a **thorough description**. A tool named `lookup` described only as "Looks up a record" gives the model nothing to disambiguate on; a description that says exactly *what* it queries, *when* to use it, what each parameter means, and what it returns is what lets Claude pick correctly (Anthropic: tool-use/overview). Good schemas also carry the load: constrain values with `enum`s and types so the model can't send garbage, mark truly-required fields `required`, and describe formats. For a `start_time` the model will otherwise fill with "next Tuesday at 3", "3pm CT", or an ISO timestamp interchangeably, the fix is a clearly specified format in the schema (and normalization on your side), not hope.

Anthropic recommends **poka-yoke** — error-proofing through argument design (for example, requiring absolute file paths so a relative path can't break after a directory change) (Anthropic: building-effective-agents). Keep formats close to what the model saw in training and avoid demanding brittle escaping or counting.

## Right-sizing the toolset

More tools is not better. Two anti-patterns the exam probes:

- **Too many thin, overlapping tools.** Forty tools including `get_user_first_name`, `get_user_last_name`, `get_user_email`, or four near-duplicates (`find_user`, `search_users`, `get_user_by_email`, `lookup_employee`) force the model to burn turns and mis-select. Consolidate into fewer, well-scoped tools that each do a coherent job.
- **One overloaded mega-tool.** The opposite failure — a single `hr_operation` tool taking an `action` string ("get_pto_balance", "submit_pto_request", …) — hides real operations behind a stringly-typed dispatch the model can't reason about cleanly. Distinct operations usually deserve distinct tools with distinct schemas.

The judgment call is *coherence*: one tool per meaningful capability, named and described so its purpose is unambiguous.

## Error handling, safety, and observability

When a tool fails, *tell the model*. Returning an empty result on a not-found order teaches Claude nothing; returning a `tool_result` marked with **`is_error: true`** and a descriptive message (the 400's validation detail, "order ID not found") lets the model correct its arguments or change course (Anthropic: tool-use/overview). For **transient** failures (a 429 rate-limit, a 503 from a dependency restart, an intermittent timeout on ~1 call in 20), the right pattern is retry with backoff — distinguishing *retryable* errors from permanent ones — rather than surfacing every blip to the model.

Safety belongs in tool design too. A `delete_customer_record` or `execute_sql`-against-production tool should be scoped and gated: least-privilege database roles, allow-listed operations, and a human-approval checkpoint before irreversible or high-blast-radius actions — you don't hand an agent an arbitrary-SQL tool with write access to prod. And to know whether your tools are well-designed, **instrument** them: track, per tool, how often the model picks it when it should and how often it picks wrong, so you can find the descriptions and schemas that need work.

## Tool choice and parallelism

The **`tool_choice`** parameter steers *whether* Claude calls a tool: `auto` (the default — the model decides), `any` (it must call some tool), `tool` (force one specific tool), or `none`. Use `auto` for compliance-critical reads you *never* want answered from the model's memory only by wording the prompt strongly, but use forced choice when the workflow genuinely requires it. When several independent lookups don't depend on each other (weather, currency, visa for a destination), **parallel tool use** lets Claude call them in one turn instead of serially — faster and cheaper; `disable_parallel_tool_use: true` turns it off when you want at most one call per turn.

## MCP: standardizing tool access

The **Model Context Protocol (MCP)** is an open standard for connecting AI applications to external systems — "a USB-C port for AI" (modelcontextprotocol.io: introduction). Its architecture is **client–server**: an AI host runs an MCP *client* that connects to MCP *servers*, and a server exposes **tools** (actions), **resources** (readable context like a company style guide), and **prompts** (reusable templates). Build MCP once and integrate everywhere.

The architectural win MCP delivers: when *six* separate agent applications each need the same three internal systems, you don't re-implement integrations six times — you stand up one MCP server per system and every application connects to it. In Claude Code, MCP servers can be configured at **local**, **project**, or **user** scope; committing a **`.mcp.json`** at project scope is how you give every engineer on a repo the *same* server configured identically (Claude Code: mcp). MCP has transports for **local (stdio)** servers — right for a tool running on an engineer's laptop reading local files — and **remote (HTTP/SSE)** servers for shared network services. A single well-documented REST API used by exactly one internal assistant may not need MCP at all; MCP earns its keep when access must be *standardized across many consumers*.

## What trips up candidates

- **Blaming the model for wrong tool selection** when the real fix is the description or schema.
- **Too many overlapping thin tools** *or* **one stringly-typed mega-tool** — both hurt selection.
- **Swallowing errors** (empty results) instead of returning `is_error` with a useful message so Claude can recover.
- **Retrying non-retryable errors** (or surfacing transient ones) — distinguish the two.
- **Handing an agent an unbounded/destructive tool** (arbitrary SQL, unguarded delete) without least-privilege scoping and human approval.
- **Assuming MCP is always required** — it shines for many-consumer standardization, not a single-client stable API.
- **Confusing MCP scopes** — `.mcp.json` at project scope is how a team shares one server identically.

## Further reading

- Anthropic, *Tool use overview* — https://docs.claude.com/en/docs/build-with-claude/tool-use/overview
- Claude Code, *MCP* — https://code.claude.com/docs/en/mcp
- Model Context Protocol, *Introduction* — https://modelcontextprotocol.io/introduction
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower, *The Architect's Blueprint: Why Your AI Agent Keeps Picking the Wrong Tool*, Towards AI on Medium (supplemental, external link)
