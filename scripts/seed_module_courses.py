#!/usr/bin/env python3
"""Idempotent seeder for the Intent Solutions agency-building modules on NOW-LMS.

Sibling of ``seed_cca_courses.py``. That script seeds the CCA-F prep curriculum,
which is question-bank shaped. This one seeds the *module* curriculum, which is
not: a module is cycles of practice, each carrying a video, a lesson, and gates
that are graded on artifacts rather than on selected answers.

Every resource is a ``text`` resource on a ``CursoSeccion``. **No ``Evaluation``
is created**, and that is deliberate, not an omission. Module gates are scored
against a rubric applied to a repository state plus a session transcript, and
NOW-LMS has nowhere to put that: ``Question.type`` accepts only ``multiple`` or
``boolean`` (``now_lms/db/__init__.py``), and the older ``CursoRecursoPregunta``
model, which does define an instructor-graded ``texto`` type, is dead code that
nothing under ``now_lms/`` references. Seeding a boolean self-attestation in its
place would write a passing score into the gradebook with no evidence behind it,
so gates are seeded as required text resources that record completion only.

**The curriculum is not in this repository.** It lives in the private
``intent-solutions-io/intent-curriculum`` repo, for the same assessment-integrity
reason the question banks moved there. Point ``AGENCY_CONTENT_DIR`` at a checkout
of that repo's ``agency/`` directory::

    git clone git@github.com:intent-solutions-io/intent-curriculum.git
    AGENCY_CONTENT_DIR=/path/to/intent-curriculum/agency \\
        python3 scripts/seed_module_courses.py

Content contract, per module directory::

    agency/module-01/
      module.json      # course metadata + ordered sections and resources
      lessons/**.md    # learner-facing prose, one file per resource
      PLACEHOLDERS.md  # every stub, its swap-in step, its blocking dependency

A resource carrying a ``placeholder`` key is seeded with that state in its
*title*, so the gap is visible in the course outline and not only in the body:
an unrecorded video reads as unrecorded before a learner opens it. Placeholder
videos are seeded ``optional`` so a video nobody has made cannot block a
learner's completion; every other resource is ``required``.

Idempotent: a course whose ``codigo`` already exists is skipped whole, exactly as
the CCA seeder does. That means editing content and re-running changes nothing.
Use ``--reset=IS-M01`` to delete and rebuild, which is safe only while the course
carries no learner data.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from os import environ
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(environ.get("AGENCY_CONTENT_DIR") or (REPO_ROOT / "content" / "agency"))

# PLACEHOLDER. No real Bucket 5 price has been ruled on yet (see the education-
# economics open item in Tasks/todo.md). This value only exists so `pagado=True`
# enrollment pricing is non-zero (a zero price is treated as free self-enroll by
# `enrollment.py::_is_free_enrollment`, which would silently remove the gate). A
# module.json may override it with its own top-level `"precio"` number. Do not
# treat this number as a real quote to a learner.
PLACEHOLDER_PRICE = Decimal("2500.00")

MAX_NOMBRE = 150
MAX_CURSO_NOMBRE = 150
MAX_DESCRIPCION_CORTA = 280
MAX_DESCRIPCION_LARGA = 1000
MAX_SECCION_NOMBRE = 100
MAX_SECCION_DESCRIPCION = 250

# A placeholder's title suffix. The body carries the full banner; this is what a
# learner sees in the course outline before opening anything, which is the only
# place a stub can be mistaken for finished work.
PLACEHOLDER_SUFFIX = {
    "video-not-recorded": "(not yet recorded)",
    "gate-manual": "(manual check, instructor-verified)",
    "commands-unverified": "(commands not yet verified)",
    "launcher-unpublished": "(download not live yet)",
}

# Only an unrecorded video is optional. A gate is required even as a stub: the
# learner still does the work and still hands it in, the platform simply does not
# score it.
OPTIONAL_PLACEHOLDERS = {"video-not-recorded"}


def _truncate(value: str, limit: int) -> str:
    """Trim to the column width, with an ellipsis when something was cut."""
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _load_markdown(module_dir: Path, relative: str) -> str:
    """Read one learner-facing markdown file, or fail loudly naming the path."""
    path = module_dir / relative
    if not path.is_file():
        raise SystemExit(f"ERROR: content file missing: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"ERROR: content file is empty: {path}")
    return text


def _resource_title(resource: dict) -> str:
    """The title as a learner sees it in the outline, placeholder state included."""
    nombre = resource["nombre"]
    suffix = PLACEHOLDER_SUFFIX.get(resource.get("placeholder", ""))
    return _truncate(f"{nombre} {suffix}" if suffix else nombre, MAX_NOMBRE)


def _load_modules(only: list[str]) -> list[tuple[Path, dict]]:
    """Discover module directories and parse each one's ``module.json``."""
    if not CONTENT_DIR.is_dir():
        print(
            f"ERROR: module content not found at {CONTENT_DIR}\n"
            "\n"
            "The curriculum is NOT in this repository — it lives in the private\n"
            "intent-solutions-io/intent-curriculum repo. Clone it and point this\n"
            "script at its agency/ directory:\n"
            "\n"
            "    git clone git@github.com:intent-solutions-io/intent-curriculum.git\n"
            "    AGENCY_CONTENT_DIR=/path/to/intent-curriculum/agency \\\n"
            "        python3 scripts/seed_module_courses.py\n",
            file=sys.stderr,
        )
        raise SystemExit(2)

    modules: list[tuple[Path, dict]] = []
    seen_codes: dict[str, Path] = {}
    for module_dir in sorted(CONTENT_DIR.glob("module-*")):
        manifest = module_dir / "module.json"
        if not manifest.is_file():
            continue
        if only and module_dir.name not in only:
            continue
        try:
            spec = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"ERROR: malformed module.json at {manifest}: {exc}") from exc
        codigo = spec.get("codigo")
        if not codigo:
            raise SystemExit(f"ERROR: module.json at {manifest} has no 'codigo' field")
        if codigo in seen_codes:
            raise SystemExit(
                f"ERROR: duplicate course code '{codigo}' in both {seen_codes[codigo]} and {module_dir}"
            )
        seen_codes[codigo] = module_dir
        modules.append((module_dir, spec))
    if not modules:
        raise SystemExit(f"ERROR: no module.json found under {CONTENT_DIR}")
    return modules


def _add_section(db, models, curso_codigo: str, indice: int, nombre: str, descripcion: str):
    """Create one published section and return it."""
    seccion = models["CursoSeccion"](
        curso=curso_codigo,
        nombre=_truncate(nombre, MAX_SECCION_NOMBRE),
        descripcion=_truncate(descripcion, MAX_SECCION_DESCRIPCION),
        indice=indice,
        estado=True,  # published (Boolean: True == public)
    )
    db.session.add(seccion)
    db.session.commit()
    return seccion


def _add_text_resource(db, models, curso_codigo: str, section_id: str, indice: int,
                       nombre: str, markdown: str, requerido: str) -> None:
    """Attach one markdown body as a ``text`` resource on the section.

    The body is written to **both** ``descripcion`` and ``text``, which looks
    redundant and is not. ``learning/resources/type_text.html`` renders only
    ``markdown2html(recurso.descripcion)``; it never reads ``recurso.text``,
    even though the platform's own authoring form writes the editor body there
    (``nuevo_recurso_text``). A resource whose body lives only in ``text`` is
    therefore invisible to a learner: the page loads, the title is right, and
    the content is simply absent.

    So ``descripcion`` carries the body, which is what actually renders today,
    and ``text`` carries the same bytes so nothing has to be re-seeded once the
    upstream template is fixed. ``CursoRecurso.descripcion`` is ``Text()``, so
    a full lesson fits and must not be truncated here.
    """
    recurso = models["CursoRecurso"](
        curso=curso_codigo,
        seccion=section_id,
        tipo="text",
        nombre=_truncate(nombre, MAX_NOMBRE),
        descripcion=markdown,
        indice=indice,
        # Never publicly previewable: a free-preview resource leaks the outline,
        # and here it would also leak gate prompts.
        publico=False,
        requerido=requerido,
        text=markdown,
    )
    db.session.add(recurso)
    db.session.commit()


def _plan_course(module_dir: Path, spec: dict) -> list[tuple[dict, list[dict]]]:
    """Resolve every resource to its markdown BEFORE any row is written.

    A missing file, an empty file, or an unknown placeholder flag has to fail
    while the database is still untouched. Discovering it halfway through leaves
    a partial course, and the next run reports ``[skip]`` on that wreckage and
    never repairs it.
    """
    planned: list[tuple[dict, list[dict]]] = []
    for section in spec["sections"]:
        resources = []
        for resource in section["resources"]:
            placeholder = resource.get("placeholder", "")
            if placeholder and placeholder not in PLACEHOLDER_SUFFIX:
                raise SystemExit(
                    f"ERROR: unknown placeholder flag '{placeholder}' on "
                    f"'{resource['nombre']}'. Add it to PLACEHOLDER_SUFFIX or fix module.json."
                )
            resources.append(
                {
                    "nombre": _resource_title(resource),
                    "markdown": _load_markdown(module_dir, resource["file"]),
                    "requerido": "optional" if placeholder in OPTIONAL_PLACEHOLDERS else "required",
                    "placeholder": placeholder,
                }
            )
        planned.append((section, resources))
    return planned


def _create_course(db, models, module_dir: Path, spec: dict) -> None:
    """Create one module course and its sections, or skip if the code exists."""
    Curso = models["Curso"]
    codigo = spec["codigo"]
    existing = db.session.execute(db.select(Curso).filter_by(codigo=codigo)).scalar_one_or_none()
    if existing is not None:
        # Match the CCA seeder's belt-and-braces: leave an existing course
        # structurally untouched, but enforce that it is not publicly listed
        # and not self-enrollable outside the paid/admitted path.
        flipped = []
        if existing.publico:
            existing.publico = False
            flipped.append("curso.publico")
        if not existing.pagado:
            existing.pagado = True
            existing.precio = existing.precio or PLACEHOLDER_PRICE
            flipped.append("curso.pagado")
        if existing.auditable:
            existing.auditable = False
            flipped.append("curso.auditable")
        public_resources = (
            db.session.execute(db.select(models["CursoRecurso"]).filter_by(curso=codigo, publico=True))
            .scalars()
            .all()
        )
        for recurso in public_resources:
            recurso.publico = False
        if public_resources:
            flipped.append(f"{len(public_resources)} recurso(s)")
        if flipped:
            db.session.commit()
            print(f"  [gate] course '{codigo}' exists — enforced on {', '.join(flipped)}")
        else:
            print(f"  [skip] course '{codigo}' already exists — no changes")
        return

    # Resolve all content first: this raises before anything is written.
    planned = _plan_course(module_dir, spec)

    curso = Curso(
        nombre=_truncate(spec["nombre"], MAX_CURSO_NOMBRE),
        codigo=codigo,
        descripcion_corta=_truncate(spec["descripcion_corta"], MAX_DESCRIPCION_CORTA),
        descripcion=_truncate(spec["descripcion"], MAX_DESCRIPCION_LARGA),
        estado="open",
        # Not in the public catalog and not self-enrollable by an ordinary
        # authenticated member. This is the Bucket 5 / admitted-practitioner
        # layer, distinct from the free CCA-F prep courses (seed_cca_courses.py,
        # publico=False but pagado=False — any authenticated student self-enrolls
        # free). `enrollment.py::_is_free_enrollment` treats `pagado=False` as
        # instant free self-enroll for ANY authenticated student regardless of
        # `publico`, so pagado must be True here or the Bucket 5 boundary does
        # not exist. auditable=False closes the matching free-audit loophole.
        # Reaching this course therefore requires either a completed PayPal
        # payment (self-serve, once pricing is live) or an admin/instructor
        # `bypass_payment` enrollment (native `course.admin_course_enrollment`)
        # for a manually admitted practitioner-cohort member.
        publico=False,
        modalidad="self_paced",
        nivel=spec.get("nivel", 1),
        duracion=spec.get("duracion", 4),
        certificado=False,
        auditable=False,
        pagado=True,
        precio=spec.get("precio", PLACEHOLDER_PRICE),
        limitado=False,
        foro_habilitado=False,
        portada=False,
    )
    db.session.add(curso)
    db.session.commit()

    placeholders = 0
    resources = 0
    for section_index, (section, planned_resources) in enumerate(planned, start=1):
        seccion = _add_section(
            db, models, codigo, section_index, section["nombre"], section["descripcion"]
        )
        for resource_index, resource in enumerate(planned_resources, start=1):
            _add_text_resource(
                db,
                models,
                codigo,
                seccion.id,
                resource_index,
                resource["nombre"],
                resource["markdown"],
                resource["requerido"],
            )
            resources += 1
            if resource["placeholder"]:
                placeholders += 1

    print(
        f"  [ok]   course '{codigo}' — {len(planned)} sections, "
        f"{resources} resources, {placeholders} of them placeholders"
    )


def _delete_course(db, models, code: str) -> bool:
    """Delete a course and its sections/resources. Returns True if found.

    Used by ``--reset`` to rebuild a course that has no learner data yet. It also
    deletes any Evaluation on those sections, so it stays correct if a later
    module gains one.
    """
    Curso = models["Curso"]
    curso = db.session.execute(db.select(Curso).filter_by(codigo=code)).scalar_one_or_none()
    if curso is None:
        return False
    secs = db.session.execute(db.select(models["CursoSeccion"]).filter_by(curso=code)).scalars().all()
    for sec in secs:
        for ev in db.session.execute(db.select(models["Evaluation"]).filter_by(section_id=sec.id)).scalars().all():
            db.session.delete(ev)
        for rec in db.session.execute(db.select(models["CursoRecurso"]).filter_by(seccion=sec.id)).scalars().all():
            db.session.delete(rec)
        db.session.delete(sec)
    db.session.delete(curso)
    db.session.commit()
    return True


def main() -> int:
    """Seed every discovered module inside the app context. Returns an exit code."""
    reset_codes: list[str] = []
    only_modules: list[str] = []
    for arg in sys.argv[1:]:
        if arg.startswith("--reset="):
            reset_codes = [c.strip() for c in arg.split("=", 1)[1].split(",") if c.strip()]
        elif arg.startswith("--modules="):
            only_modules = [m.strip() for m in arg.split("=", 1)[1].split(",") if m.strip()]
        else:
            raise SystemExit(f"ERROR: unknown argument '{arg}'")

    modules = _load_modules(only_modules)

    # sys.path[0] is scripts/ when run as a script, so `import now_lms` would miss
    # the package sitting next to it. Same fix as the CCA seeder.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from now_lms import app
    from now_lms.db import Curso, CursoRecurso, CursoSeccion, Evaluation, database

    models = {
        "Curso": Curso,
        "CursoSeccion": CursoSeccion,
        "CursoRecurso": CursoRecurso,
        "Evaluation": Evaluation,
    }

    with app.app_context():
        print(f"Seeding agency modules from {CONTENT_DIR}...")
        for code in reset_codes:
            if _delete_course(database, models, code):
                print(f"  [reset] deleted course '{code}' for rebuild")
        for module_dir, spec in modules:
            _create_course(database, models, module_dir, spec)
        print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
