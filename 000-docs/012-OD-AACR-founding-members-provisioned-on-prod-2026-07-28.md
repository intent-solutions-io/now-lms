# Founding-members beta provisioned on production — 2026-07-28 (executed from intent-os)

**Read this before touching prod accounts, enrollment tables, or mail config.**
The provisioning this platform was waiting for happened tonight — executed from the
**intent-os** session (owner order), not this repo's lane. This record is the now-lms
side of the audit trail; the full evidence lives in intent-os (PRs #269/#271/#272,
cluster issue intent-solutions-io/intent-os#270, bead epic `spine-e4j`).

## What is now live on prod (`now-lms-app-1` / `now-lms-db-1`)

- **50 users total: 6 admin / 44 student.** The owner-approved 49-member roster was
  provisioned through the app's own ORM (in-container, mirrors
  `vistas/users.py::crear_usuario` exactly): 43 students + **3 new admins (Tim Neunzig
  `tim.neunzig@`, James Hazen `james@`, Ope `opeyemiariyo@`)** + `matt@` reactivated with
  a fresh password + Max/Pablo enrolled on their existing admin accounts.
- **Enrollments: 49 × `IS-START` + 49 × `CCA-F`**, with per-resource
  `curso_recurso_avance` rows seeded for each member (196 + 490 = 14 resources × 49) —
  the bulk-enroll caveat handled member-owned, not actor-owned.
- **Owner login test passed** (panel + both courses visible). Rollback path exists and
  was rehearsed (canary → delete → zero residue).
- **Weekly progress digest** runs Mondays 07:30 CT from the dev box (read-only psql) to
  the owner + 6 leads. Registered in intent-os `mission-control/automations.md`.

## Standing constraints for this repo's sessions

1. **Do not create/modify accounts or enrollments ad hoc** — the estate tool is
   `intent-os:ops/lms/provision-founding-members.py` (idempotent, rollback-capable,
   mode-600 credential handling). Route new-member adds through it.
2. **LMS mail stays unconfigured** (`mail_config.email_verificado=f`). All member email
   goes via the estate MXroute sender. Do not wire MAIL_* until the mail lane decides.
3. **The `/user/logon` → `/request-access` 302 lives ONLY in the host Caddyfile** — a
   Caddyfile regen silently reopens self-signup. `/user/login` must stay reachable.
4. **Members hold live credentials** — schema migrations / redeploys of the container are
   fine (accounts are DB rows), but anything touching `usuario`, `estudiante_curso`,
   `curso_recurso_avance`, or course codes `IS-START`/`CCA-F`/`CCA-A`/`CCA-B` now has a
   49-member blast radius. Coordinate via `~/000-projects/CROSS-SESSION-LOG.md`.

## Mid-cutover mail context (matters until Friday's MX flip)

MXroute is authoritative for `intentsolutions.io` mailboxes as of tonight; sends through
the estate sender to `@intentsolutions.io` deliver **locally to MXroute mailboxes**, not
to Google. Member credential emails were therefore also re-sent to personal addresses
(41/41) — six members (eric, fabio, howard, mattijs, opeyemiariyo, riccardo) are
webmail-only until Friday and got the owner's WhatsApp nudge. `jim@`'s MXroute mailbox
was found missing (false "provisioned" in tonight's CSV), re-created, and re-briefed.

- Jeremy Longshore
intentsolutions.io
