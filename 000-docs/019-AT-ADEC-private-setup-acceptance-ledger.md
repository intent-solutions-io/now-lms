# ADR-11 — Private participant setup page with an immutable click-to-accept ledger

## ADR Metadata

| Field | Value |
|---|---|
| **ADR Number** | ADR-11 |
| **Title** | Private participant setup page with an immutable click-to-accept ledger |
| **Status** | **Accepted** (build approved by the owner 2026-09-30; not yet deployed) |
| **Date** | 2026-09-30 |
| **Author** | Filed with the implementation on `feat/catalyst-setup-page` |
| **Scope** | Phase 2 of the admission pipeline: setup link, details, agreement acceptance, receipt, CRM hand-off, release job. Phase 3 (mailbox provisioning and the welcome email) is out of scope. |

## 1. Decision summary

> **We will** give each admitted applicant one private, single-person, expiring link
> (`/setup/<token>`) to a mobile-first save-and-resume page where they confirm their
> legal name, a structured mailing address and phone, read the full User Agreement,
> and accept it with an unchecked box and an explicit button; the acceptance is written
> once to an insert-only table and every follow-up (receipt, CRM update, release) runs
> from durable, idempotent job rows, **in order to** replace ad hoc, meeting-dependent
> onboarding with a record that says exactly who accepted which bytes, when, **accepting
> that** this adds five fork-local tables (a deliberate ADR-1 deviation: the platform has
> no concept of an agreement ledger) and one outbound integration.

## 2. What is recorded

`agreement_acceptance` (insert-only; ORM listeners refuse UPDATE/DELETE, and on
PostgreSQL a trigger refuses them at the database, attached both by the migration
and on `create_all()` so fresh installs carry it):

- acceptance id, case id, the personal email the link was issued to;
- confirmed legal given name(s) and family name(s) exactly as entered (a single-name
  person is a first-class case), plus the full name used in the agreement;
- structured mailing address: ISO country code, line 1, optional line 2, locality,
  region where the country uses one, postal code (a string: leading zeros survive);
- phone in E.164; optional WhatsApp permission, recorded separately from assent;
- agreement document id, version, SHA-256 of the exact text file displayed, SHA-256
  of the PDF offered for download;
- exact assent text and its version, the explanation/notice copy version, access scope;
- server UTC timestamp, client IP and user agent (attribution support, not identity proof).

The page embeds the displayed file's hash in the form; if the file changes between
display and submit, acceptance is refused and the person reviews the new version.

## 3. Why these choices

- **Token stored only as SHA-256.** A database leak does not yield working links. A lost
  link is reissued (old one revoked), never recovered.
- **One acceptance per case (UNIQUE `case_id`) plus a row lock.** Double-clicks and
  replays are idempotent by construction, not by timing.
- **Jobs, not inline side effects.** The acceptance commit is the durability boundary.
  Receipt email and the Twenty update are rows claimed with an atomic conditional
  UPDATE and retried with back-off (5 min doubling to 6 h, 10 attempts), so a mail or
  CRM outage delays a step and never loses or repeats one. The release job is created
  only after the receipt is sent, matching the approved order.
- **CRM matching never guesses.** Exactly one Twenty person whose primary email equals
  the case email is updated. Zero or several goes to the failed-work list; an operator
  can pin the person id (`lmsctl setup resolve-crm`). Errors recorded on jobs are status
  codes and fixed strings only, because Twenty echoes submitted values in error bodies.
- **No analytics on this page.** It does not use the theme's `headertags()` (ad code) or
  the Umami snippet; it sets a nonce CSP with `default-src 'none'`, `no-store`,
  `no-referrer` and `noindex`.
- **Countries are not US-shaped.** The country is chosen first; region and postal rules
  are per country (US/CA/AU use code lists; GB/DE/FR/NL and others have no state line);
  unlisted countries fall back to permissive, still-sanitised rules. No address
  verification vendor is called.
- **The agreement is not in this public repository.** It is read at request time from
  a server-side path; only its id, version and hashes are stored.

Rejected: Documenso APPROVER for this step (proven engine, but the one-recipient
approval cannot stand in for the existing two-party release gate and would make
applicants retype structured data into PDF boxes); storing the agreement in the repo
(public fork); a lone CRM boolean as the record of assent.

## 4. Configuration

| Variable | Required | Meaning |
|---|---|---|
| `SETUP_AGREEMENT_TEXT_PATH` | yes | Server path of the agreement shown in full (`.md`, `.html` sanitised by allowlist, or `.txt`). Unset means the page answers 503 and nothing can be accepted. |
| `SETUP_AGREEMENT_PDF_PATH` | recommended | Server path of the PDF offered for download (behind the same token) and attached to the receipt. |
| `SETUP_AGREEMENT_DOCUMENT_ID` | yes | Stable identifier of the agreement, recorded on each acceptance. |
| `SETUP_AGREEMENT_VERSION` | yes | Version label recorded on each acceptance (bump whenever the files change). |
| `SETUP_TOKEN_TTL_DAYS` | no | Link lifetime in days; default 14, capped at 90. |
| `SETUP_BASE_URL` | for the CLI | Public origin used to print links, e.g. `https://learn.intentsolutions.io`. |
| `SETUP_HELP_EMAIL` | recommended | Where applicants ask for a new link or help; shown on error pages and in the receipt. |
| `TWENTY_API_URL` | for CRM sync | Twenty base URL, e.g. `https://crm.intentsolutions.io`. Unset means CRM jobs wait (retry) without calling out. |
| `TWENTY_API_KEY` | for CRM sync | Twenty API key. Environment/SOPS only; never logged, never stored. |

Mail uses the existing `MAIL_*` configuration. If mail is not configured, receipt jobs
wait and retry; acceptance is unaffected.

## 5. Deployment steps

1. Merge to `deploy/now-lms-fixed`; deploy with `scripts/deploy-vps.sh` as usual.
2. Apply the migration (the deploy script does not run migrations; production does not
   set `NOW_LMS_AUTO_MIGRATE`):
   `docker compose exec -T app lmsctl database migrate`
   Verify: `docker compose exec -T db psql -U nowlms -d nowlms -c '\dt setup_*'` shows
   `setup_case`, `setup_token`, `setup_draft`, `setup_job`, and
   `\d agreement_acceptance` lists the `agreement_acceptance_no_modify` trigger.
3. Place the counsel-approved agreement files in the data volume, outside the repo,
   e.g. `docker compose cp user-agreement.md app:/app/data/agreements/` (and the PDF).
4. Set the variables in section 4 in the VPS environment (SOPS), add them to the `app`
   service environment in `docker-compose.yml` (already wired with empty defaults), and
   `docker compose up -d app`.
5. Twenty: run `scripts/twenty_add_mailing_address_field.py` once, **dry run first**, then
   `--apply`; restrict the field's visibility in Twenty's permissions if addresses must
   be staff-limited. Until the field exists, CRM jobs retry with a clear reason.
6. Schedule the job runner (cron or systemd timer on the VPS), e.g. every 10 minutes:
   `docker compose exec -T app lmsctl setup process-jobs`. The page runs the jobs
   immediately after acceptance; the runner is the retry path.
7. Confirm the edge (Caddy) access log does not retain `/setup/*` request paths, or
   redact them there: the token is in the path. The application itself never logs it.
8. Smoke with a synthetic case only: `lmsctl setup issue --email <test inbox> --name Test`,
   open the link, save, accept, confirm the receipt and `lmsctl setup list`.

## 6. Operator commands

`lmsctl setup issue --email --name [--phone] [--application-ref] [--person-id]
[--access-scope] [--expiry-days] [--base-url]` prints the link once.
`lmsctl setup reissue <case>`, `lmsctl setup list [--status] [--show-email]`,
`lmsctl setup process-jobs`, `lmsctl setup failed-work`, `lmsctl setup requeue <job>`,
`lmsctl setup resolve-crm <case> --person-id <id>`.

## 7. Left for phase 3

Consume `setup_job` rows with `kind='release'` and `status='release_pending'` (case status
`release_pending`): check eligibility and owner/delegate release, provision the mailbox,
send the one canonical welcome, and move the job and case forward with their own
idempotent receipts. No mailbox or welcome email is created by this phase.

## 8. Known limits

- The rate limiter is in-process (same model as `/request-access`); Caddy is the outer wall.
- Twenty matching uses the primary email only; people whose personal email is only an
  additional email land in failed work for a pin.
- Deleting an acceptance (for example on a verified erasure request) is a deliberate
  DBA operation: the trigger must be disabled for that statement.
