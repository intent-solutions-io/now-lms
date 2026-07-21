# Governance, Risk, and Responsible Use

Using Claude responsibly in a business means respecting data, decisions, regulations, and process — not just producing good output. This domain covers the guardrails that apply before you upload data or ship an AI-assisted result, especially where the stakes for real people are high.

## Minimize sensitive data before it leaves your control

The safest data is the data you never send. If an analysis of attrition patterns does not require employee names, home addresses, or salary bands, strip or pseudonymize those identifying fields before uploading, keeping only what the task actually needs. "It's internal" does not exempt regulated personal data from your organization's handling rules, and a prompt instruction telling Claude not to *mention* personal details governs only what the model writes back — it does nothing about what was already transmitted. Data minimization at the point of upload is the control that actually reduces exposure.

## Keep humans in charge of consequential decisions

Anthropic designates high-risk use cases — including legal, financial, and employment decisions — as requiring additional safeguards such as human-in-the-loop oversight and disclosure that AI was involved (Anthropic: [Usage Policy update](https://www.anthropic.com/news/usage-policy-update)). A hiring manager who wants Claude to review resumes and auto-send rejections with no human in the final decision is removing exactly the oversight those safeguards require. The responsible pattern is to let Claude assist with the lower-risk organizing work — summarizing and structuring resume information for human reviewers — while the actual hiring decision and the communication to the candidate stay under human review. Anthropic frames this as retaining human control over how goals are pursued, particularly before high-stakes actions are taken (Anthropic: [framework for trustworthy agents](https://www.anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents)).

## Confirm regulatory compliance before regulated data moves

Some data is governed by law regardless of your intent. Before asking a general-purpose chat with no confirmed data protections to summarize patient case notes containing protected health information, you pause and confirm that the tool, its configuration, and the data-handling approach meet the applicable regulatory requirements — or you use de-identified data if that approval cannot be confirmed. Converting the file to a PDF or asking the model "not to remember" it does not satisfy a regulatory requirement; only the compliance check does. Operational urgency is never a reason to skip it.

## Follow the organization's governance process

When your company has a documented AI governance process that reviews new use cases before they go live, a new use case involving customer data goes *through* that process — not around it. Starting to use Claude because it "seems low-risk," getting an informal thumbs-up from a colleague, or spinning up a personal account to bypass review all defeat the oversight the process exists to provide. Governance is a control, and the control only works when you use it.

## Preserve authenticity and disclose AI involvement

Responsible use extends to how AI-assisted output is represented. Publishing customer testimonials that Claude significantly rewrote — without disclosing the AI editing and without the customers reviewing the final wording attributed to them — misrepresents those people's own words. That is an authenticity and consent problem independent of how polished the text sounds, and it applies whether the testimonials are positive or negative. High-risk contexts call for AI disclosure precisely so that people are not misled about what a machine produced or edited on their behalf.

## Common pitfalls

- Uploading raw PII because the analysis is "internal" or the output won't be shared externally.
- Believing a prompt instruction ("don't reference personal details") protects data already transmitted.
- Fully automating a consequential decision about a person instead of keeping a human in the loop.
- Treating a file-format change or a "don't remember this" request as regulatory compliance.
- Bypassing a defined governance review, or attributing AI-rewritten words to real people without their consent.

## Further reading

- Anthropic: [Usage Policy update](https://www.anthropic.com/news/usage-policy-update) (mapped topic — high-risk use cases, human oversight, disclosure)
- Anthropic: [Usage Policy](https://www.anthropic.com/legal/aup) and [use-case guides](https://docs.claude.com/en/docs/about-claude/use-case-guides) — responsible business use
- [github.com/hamzafarooq/claude-certified-architect](https://github.com/hamzafarooq/claude-certified-architect) — MIT — informs this lesson
- [github.com/timothywarner-org/claude-architect](https://github.com/timothywarner-org/claude-architect) — MIT — informs this lesson
- Rick Hightower's Towards AI "CCA-F" series on Medium — supplemental reading

*Prepares you toward Anthropic's credential: Claude Certified Architect (CCA) — Foundations.*
