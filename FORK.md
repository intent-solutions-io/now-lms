# Intent Solutions fork of NOW-LMS

This repository is [Intent Solutions](https://intentsolutions.io)' fork of
[`bmosoluciones/now-lms`](https://github.com/bmosoluciones/now-lms) (Apache-2.0). We run NOW-LMS
as the learning platform for the Claude Partner Network cohort.

## Posture: use it as-is, mature it **upstream** — no private forks of behavior

Our governing rule is **we do not build custom.** We use NOW-LMS's native features, and where
something is missing or broken we fix it **upstream** as a real contribution — maintained by the
project, benefiting everyone — rather than carrying a private patch. This keeps our fork a thin
tracking mirror of upstream, not a divergent product.

Concretely:

- **Branding is data, not code.** User-facing name/logo/colors come from NOW-LMS's native
  theme/config layer (`NOW_LMS_THEMES_DIR`). We do **not** rename the `now_lms` package or edit
  core views for branding — renaming is a permanent merge-conflict tax on every upstream sync.
- **Fixes and features go upstream.** Bug fixes and missing capabilities are PR'd to
  `bmosoluciones/now-lms`. We only keep in this fork what is genuinely fork-local (deploy manifest,
  this file, CI wiring) and never touches core source.
- **`main` tracks `upstream/main`.** We keep our `main` in sync with upstream and branch fixes off
  it.

## Working the fork

```bash
# one-time
git clone git@github.com:intent-solutions-io/now-lms.git
cd now-lms
git remote add upstream https://github.com/bmosoluciones/now-lms.git

# keep main current with upstream
git fetch upstream
git checkout main && git merge --ff-only upstream/main && git push origin main

# author a fix (destined for upstream)
git checkout -b fix/<short-description> upstream/main
# ...change only what's needed, match upstream conventions (conventional commits, dev/lint.sh, dev/test.sh)...
git commit -s -m "fix(scope): imperative subject"
git push -u origin fix/<short-description>
gh pr create --repo bmosoluciones/now-lms --base main \
  --head intent-solutions-io:fix/<short-description>
```

Include in every upstream PR: **what** changed, **why**, and **how it was verified** (link the
proving artifact — a test run or a reproduced-then-fixed behavior), so a maintainer can accept it
without re-deriving it.

## Contributing conventions (inherited from upstream)

Follow `docs/CONTRIBUTING.md`: conventional-commit messages (`type(scope): subject`),
`python dev/lint.sh` clean, and `python dev/test.sh` green (PostgreSQL/MySQL/SQLite paths). Sign
commits off (`git commit -s`).

## Open upstream contributions

- [`bmosoluciones/now-lms#179`](https://github.com/bmosoluciones/now-lms/pull/179) — fix: bootstrap
  a fresh PostgreSQL database correctly on first boot (three linked fresh-DB boot defects).
