#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Upsert the repository-owned Learn About page and canonical privacy-policy handoff.

The public About content is maintained in now_lms/content/intent_learn/about.html.
Privacy terms are maintained on the company website, not duplicated in this database.
Existing public slugs remain reachable, including from older member bookmarks.

Usage: python3 scripts/seed_intent_pages.py [--dry-run]
"""

from __future__ import annotations

import argparse
from pathlib import Path

# The company policy is canonical; this legacy route remains a clear handoff.
PRIVACY = """
<h2>Intent Solutions privacy information</h2>
<p>The current Privacy Policy is published on the Intent Solutions company website.</p>
<p><a href="https://intentsolutions.io/privacy/">Read the Privacy Policy</a></p>
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
