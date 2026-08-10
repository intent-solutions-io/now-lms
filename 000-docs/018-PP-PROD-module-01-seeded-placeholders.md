# Module 1 seeded with placeholders, and two platform bugs it uncovered

> Production record, 2026-07-28. Local seed only. Nothing was applied to
> `learn.intentsolutions.io` in this pass, and the four open Module 1 rulings still
> gate any production seed.

## Context

Module 1, Terminal 101, is authored: four cycles, three repetitions each, four video
outlines, a course repository, and shell plus PowerShell launchers. Two pieces cannot
exist yet. The videos are outlines only, and the gates are graded on artifacts, a
repository state plus a session transcript judged against a rubric, which this platform
has nowhere to store.

The module goes in with both gaps stubbed, in a form that cannot be read as working
assessment, plus a documented one-command swap for when each gap closes.

## What was added

`scripts/seed_module_courses.py`, a sibling to `seed_cca_courses.py`. It seeds course
`IS-M01` from a module manifest and learner-facing markdown held in the private
`intent-solutions-io/intent-curriculum` repo, at `agency/module-01/`, reached through
`AGENCY_CONTENT_DIR`.

No `now_lms/**` file was changed. This is content plumbing.

Shape as seeded: 6 sections, 24 resources, 18 of them placeholders, 0 evaluations.

## Why no Evaluation is created for a gate

`Question.type` accepts only `multiple` or `boolean` (`now_lms/db/__init__.py`). The older
`CursoRecursoPregunta` model does define an instructor-graded `texto` type, but it is dead
code: nothing under `now_lms/` references it. So there is no written-response path, which
is what ADR-6 (`012-AT-ADEC-short-answer-evaluations.md`, issue #36, PR #37) proposes to
add.

A gate is therefore a **required text resource with no Evaluation attached**. Completing it
records that the learner did the work and produces no score. A boolean self-attestation was
rejected deliberately: it would write a passing grade into the gradebook with no evidence
behind it.

Note that ADR-6 as proposed covers short-answer text with an instructor queue. It does not
cover artifact submission, so gates 1.3, 2.3, 3.3, and 4.3 need a scope extension or an
out-of-band channel even after it lands.

## Two upstream bugs found while verifying

Both are platform defects. Per `FORK.md` they belong upstream, and both are worked around in
content rather than patched here.

**1. A text resource's body is never displayed.** `learning/resources/type_text.html` renders
`markdown2html(recurso.descripcion)` and never reads `recurso.text`, although the platform's
own authoring form `nuevo_recurso_text` writes the editor body into `text`.

This reaches the live CCA curriculum. `seed_cca_courses.py` puts lesson prose in `text` and a
one-liner in `descripcion`. Measured locally: the IS-START lesson "Signing in as a student"
holds 1,871 characters in `text` and renders as the single line "Reading for Signing in as a
student". Every seeded CCA lesson body is invisible on the same code path that serves
production. **This wants checking against the live site.**

Workaround: `seed_module_courses.py` writes the body to both fields, so it renders now and
needs no reseed after a fix.

**2. Markdown tables do not render.** `markdown2html` calls `markdown(text)` with no
extensions, so pipe tables pass through as literal text. `HTML_TAGS` in `now_lms/misc.py`
explicitly allows `table`, `thead`, `tbody`, `tr`, `th`, and `td`, which is good evidence
tables were meant to work. `h4` through `h6` are likewise absent from that list and are
stripped.

Workaround: every table in Module 1 was rewritten as a bold-label list, which also removes
the horizontal-overflow risk a wide table carries on a phone.

## Verification performed

Local SQLite, `lmsctl database init`, seeded and rendered through a logged-in admin session.

- Seeder run twice: the second prints `[skip]` and changes nothing. `--reset=IS-M01` rebuilds.
- A mid-build failure is atomic. All content is resolved before the first row is written, so a
  missing file leaves no partial course. This was proven by removing a file and confirming the
  course was absent afterwards.
- Row counts asserted against `module.json`: 6 sections, 24 resources, 4 optional, 18 labelled
  placeholders, 0 evaluations, 0 non-text resources, 0 publicly-previewable resources.
- All 24 resources return 200 with a rendered body over 40 words.
- Course-page render shows all 18 placeholder labels: 12 gates, 4 videos, 1 reference card,
  1 setup.
- Answer-key leak scan over every seeded body: zero hits for the rubric hit-definitions,
  correctives, and design notes held in `cycles-and-gates.md`.
- `curso.publico` is `False` and gated access returns 403 without enrollment, as intended.

Not run: a browser check at 390px. The module adds no CSS, template, or layout, and its
content is now prose and bullet lists only, so the mobile risk this would catch was removed by
dropping the tables rather than by measuring.

## Placeholder expiry

Every stub, its swap-in command, and its blocking dependency are listed in
`agency/module-01/PLACEHOLDERS.md` in the curriculum repo. A placeholder with no entry there
is a bug.
