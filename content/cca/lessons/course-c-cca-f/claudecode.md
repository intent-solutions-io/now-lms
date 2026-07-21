# Claude Code Configuration & Workflows

**Exam weight: 20%**

Claude Code is Anthropic's agentic coding tool — it reads a codebase, edits files, runs commands, and integrates with your development tools from the terminal, IDE, desktop, and web (Claude Code: overview). For the architect, this domain is less about typing commands and more about *configuration as architecture*: knowing which mechanism enforces a behavior, at which scope, and for whom. The exam scenarios almost always turn on picking the *right layer* — memory vs. hook vs. permission vs. skill vs. subagent — for a given requirement.

## CLAUDE.md: persistent project memory

`CLAUDE.md` is a Markdown file Claude Code reads at the *start of every session* to load standing instructions — coding standards, architecture decisions, preferred libraries, review checklists (Claude Code: overview/memory). It is the right tool when you want Claude to *know something by default* every session: the current sprint number, that a service uses fixed-point decimals and never floats, or a house style rule.

Memory is **hierarchical and nested**. A root `CLAUDE.md` applies repo-wide, but a `CLAUDE.md` placed inside a subdirectory (say `services/billing/`) layers *additional*, more-specific instructions that apply when Claude works in that path — the local file doesn't replace the root, it augments it. This is how you give one part of a monorepo unusual constraints without polluting the whole repo's context.

Because memory is loaded into context every session, it has a **cost**: a `CLAUDE.md` that has ballooned to thousands of lines (a full API reference, onboarding docs, architecture essays) wastes context budget and buries the rules that matter. The fix is to keep it lean and *reference* long material — point to a doc or a skill rather than inlining it. Claude Code also builds **auto memory** as it works, saving learnings like build commands across sessions without you writing them (Claude Code: overview).

## Plan mode vs. execute mode

Claude Code has distinct **permission modes**. **Plan mode** keeps the session *read-only*: Claude researches the codebase and proposes a plan but makes no edits until you approve it. This is the correct posture for auditing many files before a risky refactor, or for any change where you want to review the approach first — the built-in **Plan** subagent gathers context in a separate window so the main conversation stays read-only (Claude Code: sub-agents). **Execute / auto-accept mode** lets Claude make edits and run commands as it goes. The architectural instinct the exam rewards: use plan mode to *bound* work before committing to it, and choose the mode that matches how much autonomy the task safely allows.

## Hooks: deterministic enforcement around actions

**Hooks** run *your* shell commands before or after Claude Code actions — for example, auto-formatting after every file edit, or running lint/typecheck before a commit (Claude Code: overview/hooks). The key property is that a hook is **deterministic code, not a polite request**: it fires every time regardless of what the model "decides."

- A **`PreToolUse`** hook inspects a proposed action *before* it runs and can *block* it — e.g., refuse any `Bash` command that would run a migration against production. This is how you turn "please don't" into an actual guarantee.
- A post-action hook (e.g., on Stop) can gate completion — run the TypeScript build and force the session to keep working (or fail) if it's still broken, instead of letting Claude declare victory over a red build.

When a scenario needs something to happen *reliably and automatically*, the answer is usually a hook, not an instruction in `CLAUDE.md` (which the model may or may not honor).

## Skills and slash commands

**Skills** package a repeatable, possibly multi-step workflow — with reference files and scripts — into something the whole team can invoke, like `/review-pr`, `/deploy-staging`, or a documented legacy-migration procedure (Claude Code: overview/skills). A skill is the right home for "we have a detailed, reusable procedure we want every engineer to run the same way." It differs from `CLAUDE.md` (always-on standing context) and from a subagent (a separate-context worker): a skill is an *invocable, named procedure*.

## Permissions and settings: scope is everything

Claude Code's behavior is governed by **settings** with a clear precedence, and the architect must reason about *where* a rule lives:

- **Project settings** (`.claude/settings.json`, committed to the repo) apply to everyone on the repo — the place to standardize team behavior and share an MCP server configured identically for all engineers.
- **Local/user settings** apply to one person or machine — the place to stop *your own* approval prompts for a command only you run, without changing the shared config.
- **Managed / enterprise policy** settings sit *above* individual settings and cannot be overridden by an engineer editing their local file. This is the layer that *guarantees* a tool is disabled on every machine in a regulated environment — the answer whenever the requirement is "no engineer, on any machine, can enable X even if they edit their own settings."

`permissions.allow` / `permissions.deny` rules let you pre-approve or forbid specific tools and commands so the session doesn't stop to ask — the mechanism behind unattended runs.

## CI/CD and headless automation

Claude Code is composable and scriptable. The **headless / non-interactive** mode (`claude -p "..."`, pipeable) lets it run unattended in CI — triaging Sentry issues into a Slack summary, translating strings and opening a PR, reviewing changed files for security issues (Claude Code: overview). Official **GitHub Actions** / **GitLab CI/CD** integrations automate PR review and issue triage. For an unattended job, you must pre-grant the permissions it needs (no human is there to approve prompts) and scope those grants tightly — the same permissions system, used deliberately for automation.

## What trips up candidates

- **Using `CLAUDE.md` to enforce a hard guarantee.** Memory *influences* behavior; a **hook** (or managed policy) *enforces* it.
- **Confusing memory scope with settings scope.** Nested `CLAUDE.md` layers *instructions*; nested settings layer *permissions* — and enterprise/managed settings are the only layer an engineer can't override.
- **Reaching for a subagent when a skill fits.** A reusable named procedure is a skill; a separate-context worker is a subagent.
- **Preventing sensitive files (`.env`, `secrets/*.yaml`) from being read via an instruction** instead of a `permissions.deny` rule or a `PreToolUse` hook.
- **Running CI jobs without pre-granting permissions**, so the unattended session hangs waiting for approval.
- **Letting `CLAUDE.md` grow unbounded**, spending context on reference material that should be linked.

## Further reading

- Claude Code, *Overview* — https://code.claude.com/docs/en/overview
- Claude Code, *Memory (CLAUDE.md)* — https://code.claude.com/docs/en/memory
- Claude Code, *Hooks* — https://code.claude.com/docs/en/hooks · *Skills* — https://code.claude.com/docs/en/skills · *GitHub Actions* — https://code.claude.com/docs/en/github-actions
- Hamza Farooq, *claude-certified-architect* — https://github.com/hamzafarooq/claude-certified-architect (MIT — informs this lesson)
- Timothy Warner, *claude-architect* — https://github.com/timothywarner-org/claude-architect (MIT — informs this lesson)
- Rick Hightower, *Engineering Dynamic Context: The Claude Code Architecture That Survives Production*, Towards AI on Medium (supplemental, external link)
