#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Upsert the repository-owned Learn About page and factual data overview.

The public About content is maintained in now_lms/content/intent_learn/about.html.
The data overview describes existing behavior without inventing legal terms.
Existing public slugs remain reachable, including from older member bookmarks.

Usage: python3 scripts/seed_intent_pages.py [--dry-run]
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Factual Learn data overview; no invented legal, retention or contract terms.
PRIVACY = """
<h2>What this page covers</h2>
<p>
  Intent Solutions Learn is the private learning platform for the Intent Solutions
  cohort. This page describes what the platform stores about you, who can see it,
  and what happens to it. It is written from the platform's own data model, so it
  describes what actually happens rather than what a template says usually happens.
</p>

<h2>What the platform stores</h2>
<p><strong>Your account.</strong> Your name, email address, and whether that email
  has been verified. Your password is stored only as a hash and cannot be read back
  by anyone, including staff. If you fill them in, your profile may also hold a
  title, biography, date of birth, gender, profile photo, and links to your own
  website, LinkedIn, GitHub, X, Facebook or YouTube. Every one of those profile
  fields is optional and blank unless you enter it.</p>

<p><strong>Your learning.</strong> Which courses you are enrolled in, which
  resources you have completed, your percentage progress in each course, your
  evaluation attempts including the answers you selected and the scores you
  received, and any certificates issued to you.</p>

<p><strong>Credentials you record.</strong> If you use the prior-credentials page,
  the credential name, its issuer verification link, the date, and any certificate
  image you upload. Uploaded images are stored outside the public files directory
  and served only through an access-checked route.</p>

<p><strong>What you write.</strong> Community posts and replies, which posts you
  have liked, messages you send through the platform, and anything you submit
  through the access-request or contact forms.</p>

<p><strong>Technical records.</strong> Your last sign-in time, your session, and
  ordinary web server logs. If you pay for something, the payment is processed by
  PayPal and the platform stores the resulting payment record; card details never
  reach this platform.</p>

<h2>Who can see it</h2>
<p><strong>Other members</strong> see your name and anything you deliberately
  publish: your community posts, your replies, and the fact that a post has a
  number of likes. <em>Who</em> liked a post is never shown to anyone, including
  staff, and no page or export exposes that list. Your email address is never shown
  to other members. If you set your profile to not visible, your name still appears
  on what you wrote — attribution is how a discussion stays useful — but it does not
  link to a profile page.</p>

<p><strong>Instructors, moderators and administrators</strong> can see the same
  member-visible content, plus your enrolment and progress, your evaluation
  attempts, credentials you have recorded, and the moderation history of any post.
  Staff can hide a post from other members; hiding is reversible, always records a
  reason, and never deletes what you wrote.</p>

<p><strong>Nobody outside the platform.</strong> Every page described here requires
  you to be signed in. The community is not indexed by search engines and is not
  visible to the public web.</p>

<h2>Your account, in your hands</h2>
<p>You can edit or clear any optional profile field yourself at any time. To ask
  for a copy of your data, to correct something you cannot edit, or to have your
  account closed, use the contact route below and say so plainly; a person will
  answer you.</p>

<h2>Questions about your information</h2>
<p>For questions about the information described here, contact
<a href="mailto:support@intentsolutions.io">support@intentsolutions.io</a>.
This page describes Learn's data handling; it does not set a retention schedule or contract terms.</p>
<p><a href="/">Back to Learn</a> ·
<a href="https://intentsolutions.io/projects/">Explore all Intent</a></p>
""".strip()

ABOUT = (Path(__file__).resolve().parents[1] / "now_lms/content/intent_learn/about.html").read_text().strip()

PAGINAS = [
    {"slug": "privacy-policy", "title": "Privacy Policy", "content": PRIVACY, "footer": True},
    {"slug": "about-us", "title": "About Intent Solutions Learn", "content": ABOUT, "footer": True},
]

def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert the Intent Solutions footer pages.")
    parser.add_argument("--dry-run", action="store_true", help="report what would change and exit")
    args = parser.parse_args()

    from now_lms import app, database
    from now_lms.db import CustomPage

    with app.app_context():
        cambios = []
        for pagina in PAGINAS:
            fila = database.session.execute(
                database.select(CustomPage).filter_by(slug=pagina["slug"])
            ).scalars().first()

            if fila is None:
                cambios.append(f"create {pagina['slug']}")
                if not args.dry_run:
                    database.session.add(
                        CustomPage(
                            slug=pagina["slug"],
                            title=pagina["title"],
                            content=pagina["content"],
                            is_active=True,
                            mostrar_en_footer=pagina["footer"],
                        )
                    )
                continue

            # UPSERT, not skip: the upstream seeder guards on existence, which is
            # why a row seeded in the wrong language stays wrong forever.
            diferencias = []
            if fila.title != pagina["title"]:
                diferencias.append(f"title {fila.title!r} -> {pagina['title']!r}")
            if fila.content != pagina["content"]:
                diferencias.append(f"content ({len(fila.content)} -> {len(pagina['content'])} chars)")
            if not fila.is_active:
                diferencias.append("is_active -> True")
            if fila.mostrar_en_footer != pagina["footer"]:
                diferencias.append(f"footer -> {pagina['footer']}")

            if diferencias:
                cambios.append(f"update {pagina['slug']}: " + "; ".join(diferencias))
                if not args.dry_run:
                    fila.title = pagina["title"]
                    fila.content = pagina["content"]
                    fila.is_active = True
                    fila.mostrar_en_footer = pagina["footer"]

        if not args.dry_run:
            database.session.commit()

        if cambios:
            for c in cambios:
                print(("would " if args.dry_run else "") + c)
        else:
            print("No change: pages already match.")




if __name__ == "__main__":
    main()
