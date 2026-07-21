# Claude Code

Claude Code is Anthropic's agentic coding tool: it reads your codebase, edits files, runs commands, and works with git and your other development tools, available in the terminal, IDE, desktop app, and browser (Claude Code docs: overview). For the CCA, the point isn't memorizing flags — it's understanding *how* Claude Code takes project context, *how* you steer and constrain it, and *how* it runs unattended in automation.

## Persistent context with CLAUDE.md

`CLAUDE.md` is a markdown file Claude Code reads at the start of every session. You use it to encode coding standards, architecture decisions, preferred libraries, and review checklists so the model doesn't have to rediscover them each time (Claude Code docs: memory).

The file is **hierarchical**. In a monorepo, a root `CLAUDE.md` might hold general conventions while `apps/billing/CLAUDE.md` holds billing-specific rules. When Claude Code works on a file inside `apps/billing/`, **both** files load — the nested, more-specific file layers additional context on top of the root file. Neither is discarded, and they aren't merged alphabetically; proximity to the working directory determines what gets layered on. Claude Code also builds **auto memory** as it works, saving learnings like build commands across sessions.

## Plan mode

Plan mode lets Claude Code investigate and propose an approach *before* touching anything. It reads and reasons but holds off on edits and commands until you approve the plan. For non-trivial or architectural changes this is the safe default: you see the intended steps, catch a wrong turn early, and only then let execution proceed. Think of it as a read-only reconnaissance phase that separates "decide what to do" from "do it."

## Hooks: deterministic control

**Hooks** run shell commands before or after Claude Code actions — auto-formatting after every edit, running lint before a commit, or *blocking* a dangerous operation (Claude Code docs: hooks). This is the enforcement layer. If you must guarantee that a specific command never executes — a force-push to main, a `rm -rf` outside a scoped directory — a **pre-tool-execution hook** inspects the proposed command and denies it before it runs, regardless of what the model decided. A `CLAUDE.md` instruction telling the model "never do X" is advisory; a hook is a control. That distinction is worth internalizing: instructions guide behavior, hooks enforce it.

## Skills, slash commands, and MCP

**Skills** (and slash commands like `/review-pr` or `/deploy-staging`) package repeatable workflows your team can invoke by name and share across a project. **MCP** — the Model Context Protocol — connects Claude Code to external data sources and tools (design docs, ticketing systems, databases) through a standard interface, so the same integration is reusable rather than re-coded per project (Claude Code docs: MCP). Together these turn Claude Code from a chat box into a configurable, team-shared engineering surface — the same `CLAUDE.md`, settings, and MCP servers work across every surface.

## Headless mode for CI and automation

Claude Code isn't only interactive. Its **headless / print mode** (`claude -p "..."`) is a scriptable, non-interactive invocation with no terminal UI and structured or streaming output — exactly what a CI pipeline needs to, say, auto-generate a changelog from git history or review changed files for security issues. It composes in the Unix sense:

```bash
git diff main --name-only | claude -p "review these changed files for security issues"
```

Because it's non-interactive, headless mode is the answer whenever a task must run inside a pipeline or on a schedule — not the interactive REPL, and not a human manually pasting into web chat after each run.

## Permissions and scope

`settings.json` configures Claude Code's permissions, and it distinguishes **project-level** defaults from **local/user-level** overrides. That scoping is what lets a CI environment auto-approve a safe set of bash commands while an interactive developer on the same repo is still prompted before a risky command runs. Keep permission policy in `settings.json`; keep instructions and context in `CLAUDE.md`. Conflating the two — expecting `CLAUDE.md` to *enforce* permissions — is a common misconception.

## Common pitfalls

- Assuming a nested `CLAUDE.md` *replaces* the root file, or that the root is ignored once a more specific file exists — both load and layer.
- Treating a `CLAUDE.md` "never do X" line as a hard guarantee; use a hook when the constraint must be enforced.
- Believing Claude Code can only run interactively — headless/print mode is built for CI and automation.
- Putting permission rules in `CLAUDE.md` instead of `settings.json`, or ignoring the project-vs-local scope distinction.
- Skipping plan mode on a large architectural change and letting the model edit first, reason later.

## Further reading

- [Claude Code overview](https://code.claude.com/docs/en/overview)
- [Manage Claude's memory (CLAUDE.md)](https://code.claude.com/docs/en/memory)
- [Hooks](https://code.claude.com/docs/en/hooks) · [Settings](https://code.claude.com/docs/en/settings)
- [hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's *Claude Certified Architect (CCA) — Foundations* series on Towards AI (Medium) — supplemental
