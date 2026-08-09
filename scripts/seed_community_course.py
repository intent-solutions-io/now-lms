# SPDX-License-Identifier: Apache-2.0
"""Create the canonical Community Hub container course. Idempotent.

Not part of the Alembic revision on purpose: a migration must be a no-op on a
fresh database, and a data insert in a schema revision breaks that.

`foro_habilitado` stays False deliberately. That shuts the native forum route on
this course, so Hub posts cannot be reached through /course/<code>/forum and
bypass the moderation filter, and it never trips the validator forbidding
foro_habilitado on a self_paced course.
"""

from now_lms import app, database
from now_lms.db import Curso
from now_lms.vistas.comunidad import COMMUNITY_COURSE_CODE


def main() -> None:
    with app.app_context():
        existente = database.session.execute(
            database.select(Curso).filter_by(codigo=COMMUNITY_COURSE_CODE)
        ).scalars().first()
        if existente:
            print(f"Community course {COMMUNITY_COURSE_CODE} already present; nothing to do.")
            return
        database.session.add(
            Curso(
                nombre="Community",
                codigo=COMMUNITY_COURSE_CODE,
                descripcion_corta="Container for the Community Hub. Not a course.",
                descripcion="Holds Community Hub posts. Members reach it at /community, never here.",
                estado="open",
                modalidad="self_paced",
                publico=False,
                pagado=False,
                certificado=False,
                foro_habilitado=False,
            )
        )
        database.session.commit()
        print(f"Created Community course {COMMUNITY_COURSE_CODE}.")


if __name__ == "__main__":
    main()
