# Tools and MCPs

Tools are how Claude reaches beyond text to *do* things — look up weather, query a pricing service, edit a file. This lesson covers the mechanics of tool use, what makes a tool reliable, the human-in-the-loop pattern for dangerous actions, and when to graduate from an in-process tool to a **Model Context Protocol (MCP)** server.

## How tool use works

You define a tool with a **name**, a **description**, and an **`input_schema`** (a JSON Schema for its arguments). Claude decides, based on the user's request and the description, whether to call it. When it does, the response carries a `tool_use` block naming the tool and its arguments with `stop_reason: "tool_use"`. Your code executes the operation and sends the result back in a **`tool_result`** block; Claude then uses that to answer (Tool use overview).

There are two execution locations. **Client tools** — the ones you define, plus Anthropic-schema tools like `bash` and `text_editor` — run in *your* application; you execute the call. **Server tools** like `web_search` run on Anthropic's infrastructure and return results directly. By default `tool_choice` is `auto` (Claude decides each turn); you can force a call, and `strict: true` guarantees the tool input matches your schema exactly.

## What makes a tool reliable

The model leans almost entirely on the **description** to decide when and how to call a tool. A description like `"get_weather: gets weather"` is why Claude calls it with malformed input or skips it when it should call it. The fix is a **detailed description** — specify exactly *when* to call it and the expected input format and constraints — paired with **structured error responses**. When the tool receives bad input, it should return a clear, structured error rather than crashing, so Claude can read the error and self-correct on the next turn. Renaming the tool, deleting the description, or adding more tools does not address the real usability problem; the description and the error contract do.

## Human-in-the-loop for dangerous actions

Some actions are irreversible. A coding agent with a tool that deletes files from the local filesystem should not execute the moment the model requests it. The right pattern is **human-in-the-loop approval**: when the model requests the delete tool, the harness surfaces the proposed action to the user for explicit confirmation *before* the client executes it, keeping it a client-side, locally controlled tool. Auto-executing for "speed" removes the safety check; moving execution server-side doesn't add local approval; and hiding the capability from the description while leaving the function callable relies on obscurity rather than an actual gate. For destructive operations, pause and confirm.

## When to reach for MCP

MCP is an **open standard** for connecting AI applications to external tools, data sources, and workflows — described as "a USB-C port for AI applications" (Model Context Protocol: introduction). An **MCP server** exposes capabilities (tools, resources, prompts) over a standard protocol; independent **MCP clients** — Claude Code, a Slack deployment, a custom API app — connect to that one server and reuse it without re-implementing the integration.

That reusability is the deciding factor. When a retailer's internal pricing service (or ticketing REST API) needs to be reachable from **three different Claude applications**, and the owning team wants to **version and maintain it independently**, an MCP server is the fit: one integration, many consumers, one place to update. The weaker options all drift or don't fit:

- **A custom in-process tool duplicated in each app** guarantees drift and triples the maintenance.
- **Baking a price list into each system prompt** yields stale data and burns context every request.
- **A shared shell script** offers some reuse but no schema, no discovery, and no clean versioning contract.
- **A Skill** packages instructions and context — it is not a general mechanism for calling an arbitrary internal REST API across every surface via a server.
- **Built-in tools** don't automatically reach arbitrary internal APIs.

MCP earns its overhead precisely when the same capability is reused across multiple clients under independent ownership. For a single app calling one API once, a plain custom tool is simpler — don't stand up a server you don't need.

## Common pitfalls

- Writing a thin tool description and blaming the model when it misuses the tool.
- Letting a tool crash on bad input instead of returning a structured error the model can recover from.
- Auto-executing destructive tools (file deletes, force-pushes) with no approval gate.
- Trying to hide a dangerous capability by removing its description while leaving the function callable.
- Duplicating the same integration across three codebases instead of exposing it once via MCP.
- Standing up an MCP server for a one-off, single-application tool where a custom tool is simpler.
- Confusing a Skill (instructions/context) with MCP (protocol-level, cross-client integration).

## Further reading

- [Tool use overview (Anthropic docs)](https://docs.claude.com/en/docs/build-with-claude/tool-use/overview)
- [MCP in Claude Code](https://code.claude.com/docs/en/mcp) · [Model Context Protocol — introduction](https://modelcontextprotocol.io/introduction)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
