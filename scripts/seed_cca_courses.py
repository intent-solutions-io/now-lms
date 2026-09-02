#!/usr/bin/env python3.12
"""Idempotent seeder for the preliminary CCA-F prep curriculum on NOW-LMS.

Builds four courses (see ``COURSES`` below) from the Intent Solutions question
banks (``<content>/banks/*.json``) and the authored lesson prose
(``<content>/lessons/<course-dir>/<domainKey>.md``):

  * Course 0 — Getting Started on Intent Solutions Learn (onboarding, no exam)
  * Course A — Claude Foundations (Associate onramp)
  * Course B — Building with Claude (Developer)
  * Course C — Claude Certified Architect — Foundations (CCA-F) prep

Each quiz course becomes a ``Curso`` with one ``CursoSeccion`` per question-bank
domain; every section carries a ``text`` lesson resource (the authored markdown)
plus a practice ``Evaluation`` (unlimited attempts) seeded from that domain's
questions. Every course also gets a final mock-exam section (``is_exam=True``,
``passing_score=72.0``); Course C's mock mirrors the CCA-F blueprint — ~60
questions weighted across the five official domains.

The importer is a pure DB operation and is **idempotent**: it guards on the
course ``codigo`` already existing and skips that whole course, so re-running
adds nothing. Each course is committed independently.

**The curriculum is not in this repository.** Teaching content (banks + lesson
prose) lives in the private ``intent-solutions-io/intent-curriculum`` repo:
publishing graded answer keys beside the courses that grade them is an
assessment-integrity problem, and this fork is public so it can carry platform
fixes upstream. Point ``CCA_CONTENT_DIR`` at a checkout of that repo's ``cca/``
directory::

    git clone git@github.com:intent-solutions-io/intent-curriculum.git
    docker compose exec -T -e CCA_CONTENT_DIR=/path/to/intent-curriculum/cca \\
        app python3.12 scripts/seed_cca_courses.py

Production is already seeded and the importer is idempotent, so this is needed
only for a reseed or a disaster-recovery rebuild.

Question shape (per bank item): ``{id, domain, domainName, domainKey, text,
options[], answerIndex | answerIndexes, rationale, source}``. Mapping onto
NOW-LMS: the correct positions -> the matching ``QuestionOption.is_correct``;
``rationale`` (+ appended ``source`` attribution) -> ``Question.explanation``.

SINGLE- AND MULTI-CORRECT ITEMS
===============================
Banks may carry ``answerIndexes`` (a list of 0-based positions) for
"select TWO"-style items, alongside or instead of the single ``answerIndex``.
Both are honoured; ``answerIndexes`` wins when present.

The platform already grades multi-correct: every question is seeded as
``type="multiple"``, and ``_answer_is_correct`` compares the full selected set
against the full correct set (``set(selected_ids) == correct_ids``). The gap was
only here, in the importer.
"""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from os import environ
from pathlib import Path

from flask import has_app_context

# The curriculum lives in the private intent-curriculum repo, not here, so the
# content root is supplied at run time. The fallback to the historical in-repo
# path is kept ONLY so an old tag (or a local gitignored checkout at
# content/cca) still seeds — it must never again resolve to tracked files:
# they were removed 2026-07-28 and content/cca is gitignored, because this fork
# is public and answer keys beside the courses that grade them is an
# assessment-integrity failure (ADR 000-docs/008-AT-ADEC).
# _require_content_dir() below turns a missing directory into a clear message
# instead of a confusing FileNotFoundError deep in the import.
REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(environ.get("CCA_CONTENT_DIR") or (REPO_ROOT / "content" / "cca"))
BANKS_DIR = CONTENT_DIR / "banks"
LESSONS_DIR = CONTENT_DIR / "lessons"

# Column limits from now_lms/db/__init__.py (Question.text 1000, explanation
# 1000, QuestionOption.text 500). The current banks fit, but guard anyway so a
# future bank edit degrades gracefully instead of raising a DB error.
MAX_QUESTION_TEXT = 1000
MAX_EXPLANATION = 1000
MAX_OPTION_TEXT = 500
MAX_DOMAIN_KEY = 50
MAX_DOMAIN_NAME = 150

# Matthew Purcell's set is one full-length form matched to the live exam's item count.
# --- Published exam shapes -------------------------------------------------
# Item count, minutes and domain weights as published in each Exam Guide v1.0
# (July 2026). These drive the per-attempt draw, so a mock is weighted the way the
# real paper is rather than the way the bank happens to be stocked. The cut is 720
# on a 100-1000 scale for all four; the scale itself is ours and is disclosed as
# such on the result, because Anthropic's real conversion is not published.
SITTINGS = {
    "CCA-F": {
        "items": 60, "minutes": 120, "cut": 720,
        "blueprint": {"agentic": 27, "claudecode": 20, "prompt": 20, "tools": 18, "context": 15},
    },
    "CCAO-F": {
        "items": 60, "minutes": 120, "cut": 720,
        "blueprint": {"assoc-evaluation": 21, "assoc-workflow": 16, "assoc-governance": 15,
                      "assoc-prompting": 14, "assoc-selection": 12, "assoc-config": 12,
                      "assoc-troubleshoot": 10},
    },
    "CCD": {
        "items": 53, "minutes": 120, "cut": 720,
        "blueprint": {"dev-integration": 33.1, "dev-modelselect": 16.8, "dev-agents": 14.7,
                      "dev-promptcontext": 11.0, "dev-tools": 10.6, "dev-security": 8.1,
                      "dev-claudecode": 3.1, "dev-eval": 2.6},
    },
    "CCA-P": {
        "items": 63, "minutes": 120, "cut": 720,
        "blueprint": {"archp-integration": 19, "archp-design": 17, "archp-eval": 16,
                      "archp-governance": 14, "archp-stakeholder": 14, "archp-models": 13,
                      "archp-devprod": 7},
    },
}

MATTHEW_EXAM_ITEMS = 60


def _truncate(value: str, limit: int) -> str:
    """Clip ``value`` to ``limit`` chars, appending an ellipsis if clipped."""
    if value is None:
        return ""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


# Which certification each bank prepares for. Only Matthew's bank declares this in its
# own header; the other five are mapped here rather than by editing them, because the
# two licensed banks are used unchanged under their authors' reuse grants and the
# in-house banks predate the field.
#
# Practice is organised by certification, not by course (Max, 2026-08-09: "practice
# tests are their own domain ... outside of courses"). A course is the wrong key: CCA-F
# alone carries questions for TWO credentials, so grouping practice by course showed a
# member 12 mashed-together domains instead of the 5 or 7 that belong to the
# certification they are sitting.
BANK_CERTIFICATIONS = {
    "questions-associate.json": ("CCAO-F", "Claude Certified Associate — Foundations"),
    "matthew-purcell-practice-exams.json": ("CCAO-F", "Claude Certified Associate — Foundations"),
    "questions-developer.json": ("CCD", "Claude Certified Developer"),
    "questions.json": ("CCA-F", "Claude Certified Architect — Foundations"),
    "rick-practice-exams.json": ("CCA-F", "Claude Certified Architect — Foundations"),
    "questions-architect-professional.json": ("CCA-P", "Claude Certified Architect — Professional"),
}


def _correct_positions(item: dict) -> set[int]:
    """Return the 0-based option positions that are correct for ``item``.

    Honours ``answerIndexes`` (multi-correct, "select TWO") and the older single
    ``answerIndex``. ``answerIndexes`` wins when both are present.

    REFUSES rather than importing an unanswerable question. The previous version
    computed ``is_correct=(position == item.get("answerIndex"))``, so an item whose
    ``answerIndex`` was missing or ``None`` — exactly how a multi-correct item is
    encoded — silently imported with EVERY option marked incorrect. The question
    then looks fine in the UI and cannot be answered correctly by anyone, and
    nothing anywhere reports a problem. A hard failure at seed time is the only
    honest outcome: a certification-prep exam with an unanswerable question is
    worse than one that refused to import.
    """
    # Messages here are operator-facing CLI output for someone running a reseed from a
    # terminal; intentionally not gettext-wrapped (raised in review of PR #76).
    options = item.get("options") or []
    if not options:
        raise ValueError(f"question {item.get('id', '<no id>')!r}: has no options to mark correct")

    raw = item.get("answerIndexes")
    if raw is None:
        single = item.get("answerIndex")
        raw = [] if single is None else [single]
    elif not isinstance(raw, (list, tuple)):
        # `answerIndexes: 1` instead of `[1]` would otherwise die on Python's native
        # "'int' object is not iterable", which tells the operator nothing about which
        # bank item is malformed (raised in review of PR #76).
        raise TypeError(f"question {item.get('id', '<no id>')!r}: answerIndexes must be a list, got {type(raw).__name__}")

    positions = set()
    for value in raw:
        # TypeError for a type problem, ValueError for a value problem — `bool` is excluded
        # explicitly because it IS an int subclass, so `answerIndexes: [true]` would otherwise
        # silently mean position 1.
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"question {item.get('id', '<no id>')!r}: answer position {value!r} is not an int")
        if not 0 <= value < len(options):
            raise ValueError(
                f"question {item.get('id', '<no id>')!r}: answer position {value} is outside "
                f"its {len(options)} options"
            )
        positions.add(value)

    if not positions:
        raise ValueError(
            f"question {item.get('id', '<no id>')!r}: no correct answer "
            "(needs answerIndex or answerIndexes) — refusing to import a question "
            "no learner could ever answer correctly"
        )
    return positions


def _load_bank(filename: str) -> list[dict]:
    """Load a vendored question bank and return its ``questions`` list.

    Each item is stamped with the certification its bank prepares for, taken from the
    bank's own ``certification`` header when it has one and from BANK_CERTIFICATIONS
    otherwise. Stamping here rather than at each call site means every path that
    reaches a question — section quiz, mock, extra exam — carries it without having to
    remember to.
    """
    path = BANKS_DIR / filename
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    questions = data["questions"] if isinstance(data, dict) else data

    declared = data.get("certification") if isinstance(data, dict) else None
    if declared and declared.get("code"):
        key, name = declared["code"], declared.get("name") or declared["code"]
    else:
        key, name = BANK_CERTIFICATIONS.get(filename, (None, None))

    if key:
        for item in questions:
            item.setdefault("certificationKey", key)
            item.setdefault("certificationName", name)
    return questions


def _load_bank_optional(filename: str) -> list[dict]:
    """Like ``_load_bank`` but returns ``[]`` if the bank file is absent."""
    if (BANKS_DIR / filename).is_file():
        return _load_bank(filename)
    return []


def _load_lesson(course_dir: str, stem: str, fallback_title: str) -> str:
    """Return authored lesson markdown, or a minimal stub if the file is absent.

    Lessons are keyed by the bank's ``domainKey`` (quiz courses) or an explicit
    stem (Getting Started), so the mapping is deterministic. A missing file must
    never crash the import — the section still seeds with a stub the team can
    fill in on the follow-on authoring pass.
    """
    path = LESSONS_DIR / course_dir / f"{stem}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return (
        f"# {fallback_title}\n\n"
        "_Lesson prose for this section is being authored. Use the practice "
        "questions below and the Further reading links in the course sources._"
    )


def _group_by_domain(questions: list[dict]) -> list[tuple[int, str, str, list[dict]]]:
    """Group bank questions by domain, preserving first-seen order.

    Returns ``[(domain_number, domain_name, domain_key, [questions...]), ...]``
    ordered by the integer ``domain`` field so sections come out 1..N.
    """
    buckets: dict[str, dict] = {}
    for question in questions:
        key = question.get("domainKey") or str(question.get("domain"))
        bucket = buckets.setdefault(
            key,
            {
                "domain": question.get("domain", 0),
                "name": question.get("domainName", key),
                "key": key,
                "questions": [],
            },
        )
        bucket["questions"].append(question)
    ordered = sorted(buckets.values(), key=lambda b: (b["domain"], b["name"]))
    return [(b["domain"], b["name"], b["key"], b["questions"]) for b in ordered]


def _weighted_mock(questions: list[dict], weights: dict[str, int], total: int) -> list[dict]:
    """Deterministically pick ~``total`` questions weighted by domain.

    ``weights`` maps a ``domainKey`` to that domain's CCA-F percentage; we scale
    those to ``total`` and take the first K questions of each domain (order
    preserved), so the selection is stable across re-runs (no RNG).
    """
    by_key: dict[str, list[dict]] = {}
    for question in questions:
        by_key.setdefault(question.get("domainKey"), []).append(question)
    weight_sum = sum(weights.values()) or 1
    selected: list[dict] = []
    for key, weight in weights.items():
        take = round(total * weight / weight_sum)
        selected.extend(by_key.get(key, [])[:take])
    return selected


def _weighted_exam_series(questions: list[dict], weights: dict[str, int], per_exam: int,
                          max_exams: int) -> list[list[dict]]:
    """Partition ``questions`` into up to ``max_exams`` weighted, NON-overlapping
    full-length exams of ~``per_exam`` questions each (deterministic).

    Each exam draws ``round(per_exam * weight / sum)`` fresh questions per domain
    from that domain's remaining queue, so no question repeats across exams. The
    series stops when the pool can no longer fill a full exam or ``max_exams`` is
    reached.
    """
    queues: dict[str, list[dict]] = {}
    for question in questions:
        queues.setdefault(question.get("domainKey"), []).append(question)
    cursors = {key: 0 for key in queues}
    weight_sum = sum(weights.values()) or 1
    targets = {key: round(per_exam * w / weight_sum) for key, w in weights.items()}

    exams: list[list[dict]] = []
    for _ in range(max_exams):
        # Only build a full exam if every domain still has its target available.
        if any(cursors.get(key, 0) + targets[key] > len(queues.get(key, [])) for key in weights):
            break
        exam: list[dict] = []
        for key in weights:
            start = cursors[key]
            exam.extend(queues[key][start:start + targets[key]])
            cursors[key] = start + targets[key]
        exams.append(exam)
    return exams


# ---------------------------------------------------------------------------
# Persistence helpers (each commits independently for crash-safe partial runs)
# ---------------------------------------------------------------------------


def _add_section(db, models, curso_codigo: str, indice: int, nombre: str, descripcion: str):
    """Create one published section and return it."""
    seccion = models["CursoSeccion"](
        curso=curso_codigo,
        nombre=_truncate(nombre, 100),
        descripcion=_truncate(descripcion, 250),
        indice=indice,
        estado=True,  # published (Boolean: True == public)
    )
    db.session.add(seccion)
    db.session.commit()
    return seccion


def _add_lesson_resource(db, models, curso_codigo: str, section_id: str, nombre: str, markdown: str):
    """Attach the authored markdown as a ``text`` resource on the section."""
    recurso = models["CursoRecurso"](
        curso=curso_codigo,
        seccion=section_id,
        tipo="text",
        nombre=_truncate(f"Lesson: {nombre}", 150),
        descripcion=_truncate(f"Reading for {nombre}", 500),
        indice=1,
        publico=False,
        requerido="required",
        text=markdown,
    )
    db.session.add(recurso)
    db.session.commit()


def _add_evaluation(db, models, section_id: str | None, title: str, description: str, is_exam: bool,
                    passing_score: float, questions: list[dict], sitting: dict | None = None,
                    certification_key: str | None = None) -> int:
    """Create an evaluation on a section and import its questions.

    The correct positions -> the matching options' ``is_correct``; ``rationale`` +
    appended ``source`` attribution -> ``explanation``. Returns the number of
    questions imported.

    NOT all-or-nothing across the batch. Each question is committed individually, so a
    malformed item at position 7 of 10 leaves items 1-6 persisted and the course
    half-imported. That is deliberate — a reseed should keep the progress it made — and
    the seeder is idempotent, so a corrected re-run completes it. What IS guaranteed is
    that the failing item leaves no partial row of its own: answers are resolved before
    the question is written (raised in review of PR #76).
    """
    evaluation = models["Evaluation"](
        section_id=section_id,
        title=_truncate(title, 200),
        description=_truncate(description, 1000),
        is_exam=is_exam,
        passing_score=passing_score,
        max_attempts=None,  # unlimited (practice and first-pass mock alike)
        certification_key=certification_key,
    )
    # A mock exam is a POOL, not a paper: `draw_size` makes each attempt draw its own
    # blueprint-weighted questions from everything seeded here, so a second sitting is a
    # different exam. Without it the bank's depth is invisible to a candidate, who would
    # see the same questions in the same order every time. A domain quiz passes no
    # sitting and keeps the old behaviour: every question, in order, untimed.
    if sitting:
        evaluation.time_limit_minutes = sitting.get("minutes")
        evaluation.draw_size = sitting.get("items")
        evaluation.scaled_cut = sitting.get("cut")
        if sitting.get("blueprint"):
            evaluation.blueprint_json = json.dumps(sitting["blueprint"])
    db.session.add(evaluation)
    db.session.commit()

    imported = 0
    for order, item in enumerate(questions, start=1):
        # VALIDATE BEFORE WRITING. _correct_positions raises on a malformed item, and the
        # question row is committed a few lines down to obtain its id — so resolving the
        # answers first is what keeps a bad bank from leaving a half-imported course behind
        # (an orphan Question with no options). Raised in review of PR #76.
        correct_positions = _correct_positions(item)

        rationale = (item.get("rationale") or "").strip()
        source = (item.get("source") or "").strip()
        explanation = rationale + (f"\n\nSource: {source}" if source else "")
        # Carry the bank's domain onto the row. Every bank item already declares one;
        # until now the importer read it only to group questions into sections and then
        # dropped it, so a full-length exam — whose items span every domain inside ONE
        # evaluation — could not be scored per domain, and no bank could be drilled one
        # domain at a time. Falling back to the integer `domain` keeps items from an
        # older bank shape usable rather than silently unlabelled.
        domain_key = (item.get("domainKey") or "").strip() or None
        if domain_key is None and item.get("domain") is not None:
            domain_key = str(item["domain"])
        domain_name = (item.get("domainName") or "").strip() or None

        question = models["Question"](
            evaluation_id=evaluation.id,
            type="multiple",
            text=_truncate(item["text"], MAX_QUESTION_TEXT),
            explanation=_truncate(explanation, MAX_EXPLANATION),
            order=order,
            domain_key=_truncate(domain_key, MAX_DOMAIN_KEY) or None,
            domain_name=_truncate(domain_name, MAX_DOMAIN_NAME) or None,
            certification_key=_truncate(item.get("certificationKey"), MAX_DOMAIN_KEY) or None,
            certification_name=_truncate(item.get("certificationName"), MAX_DOMAIN_NAME) or None,
        )
        db.session.add(question)
        db.session.commit()  # flush so question.id is available for options

        for position, option_text in enumerate(item.get("options", [])):
            db.session.add(
                models["QuestionOption"](
                    question_id=question.id,
                    text=_truncate(option_text, MAX_OPTION_TEXT),
                    is_correct=(position in correct_positions),
                )
            )
        db.session.commit()
        imported += 1
    return imported


def _create_course(db, models, spec: dict) -> None:
    """Create one course + its sections/lessons/evaluations, or skip if it exists."""
    Curso = models["Curso"]
    existing = db.session.execute(
        db.select(Curso).filter_by(codigo=spec["codigo"])
    ).scalar_one_or_none()
    if existing is not None:
        # Belt-and-braces for pre-gating databases (e.g. a backup restored from
        # before the 2026-07-27 gating SQL ran): an existing course is left
        # structurally untouched, but its VISIBILITY is enforced — a reseed must
        # never leave a CCA course (or its free-preview resources, which leak
        # the outline) publicly listed. Idempotent: no-op when already gated.
        flipped = []
        if existing.publico:
            existing.publico = False
            flipped.append("curso")
        public_resources = (
            db.session.execute(
                db.select(models["CursoRecurso"]).filter_by(curso=spec["codigo"], publico=True)
            )
            .scalars()
            .all()
        )
        for recurso in public_resources:
            recurso.publico = False
        if public_resources:
            flipped.append(f"{len(public_resources)} recurso(s)")
        if flipped:
            db.session.commit()
            print(f"  [gate] course '{spec['codigo']}' exists — publico=False enforced on {', '.join(flipped)}")
        else:
            print(f"  [skip] course '{spec['codigo']}' already exists — no changes")
        return

    curso = Curso(
        nombre=_truncate(spec["nombre"], 150),
        codigo=spec["codigo"],
        descripcion_corta=_truncate(spec["descripcion_corta"], 280),
        descripcion=_truncate(spec["descripcion"], 1000),
        estado="open",
        # Courses are gated (2026-07-27): members reach them via enrollment, the
        # public catalog is the practice-tracks teaser. A reseed must not
        # resurrect a publicly listed course.
        publico=False,
        modalidad="self_paced",
        nivel=spec["nivel"],
        duracion=spec.get("duracion", 4),
        certificado=False,
        auditable=False,
        pagado=False,
        limitado=False,
        foro_habilitado=False,
        portada=False,
    )
    db.session.add(curso)
    db.session.commit()

    indice = 1
    total_questions = 0

    # --- Content sections (each: lesson + optional practice evaluation) ---
    for section in spec["sections"]:
        seccion = _add_section(
            db, models, spec["codigo"], indice, section["nombre"], section["descripcion"]
        )
        _add_lesson_resource(db, models, spec["codigo"], seccion.id, section["nombre"], section["lesson"])
        if section.get("questions"):
            total_questions += _add_evaluation(
                db,
                models,
                seccion.id,
                title=f"Practice quiz — {section['nombre']}",
                description="Unlimited-attempt practice. Rationale shown after each question.",
                is_exam=False,
                passing_score=72.0,
                questions=section["questions"],
            )
        indice += 1

    # --- Final mock exam section (if this course has one) ---
    if spec.get("mock_questions"):
        seccion = _add_section(
            db,
            models,
            spec["codigo"],
            indice,
            "Final mock exam",
            "Timed-style mock exam. Passing score 72% mirrors the CCA-F scale.",
        )
        _add_lesson_resource(
            db,
            models,
            spec["codigo"],
            seccion.id,
            "Final mock exam",
            "# Final mock exam\n\nThis exam mirrors the real assessment's shape. "
            "Passing is **72%**. Take it under exam-like conditions once you have "
            "worked through every section's practice quiz.",
        )
        sitting = SITTINGS.get(spec.get("certification"))
        total_questions += _add_evaluation(
            db,
            models,
            seccion.id,
            title=f"Mock exam — {spec['nombre']}",
            description=(
                f"Final mock exam. {sitting['items']} items drawn to the published blueprint, "
                f"{sitting['minutes']} minutes, {sitting['cut']} to pass."
                if sitting else "Final mock exam. Passing score 72%."
            ),
            is_exam=True,
            passing_score=72.0,
            questions=spec["mock_questions"],
            sitting=sitting,
        )
        indice += 1

    # --- Extra full-length practice exams (e.g. Rick Hightower's set) ---
    for exam in spec.get("extra_exams", []):
        seccion = _add_section(db, models, spec["codigo"], indice, exam["nombre"], exam["descripcion"])
        _add_lesson_resource(db, models, spec["codigo"], seccion.id, exam["nombre"], exam["lesson"])
        # An authored full-length exam IS the paper its author wrote, so it is timed
        # and scaled but never drawn: sampling 60 of its 60 items would only reorder
        # someone else's deliberate form, and sampling fewer would silently shorten it.
        shape = SITTINGS.get(spec.get("certification"))
        exam_sitting = (
            {"minutes": shape["minutes"], "cut": shape["cut"], "items": None, "blueprint": None}
            if shape else None
        )
        total_questions += _add_evaluation(
            db,
            models,
            seccion.id,
            title=exam["nombre"],
            description="Full-length practice exam. Unlimited attempts.",
            is_exam=True,
            passing_score=72.0,
            questions=exam["questions"],
            sitting=exam_sitting,
        )
        indice += 1

    print(
        f"  [ok]   course '{spec['codigo']}' — {indice - 1} sections, "
        f"{total_questions} questions imported"
    )


def _build_specs() -> list[dict]:
    """Assemble the course specifications from the vendored banks + lessons."""
    associate = _load_bank("questions-associate.json")
    developer = _load_bank("questions-developer.json")
    architect = _load_bank("questions-architect-professional.json")
    general = _load_bank("questions.json")

    # Matthew Purcell's authored CCAO-F practice exam (optional, reuse-granted on
    # condition of credit) -> one full-length exam appended to Course A.
    #
    # This bank is the ONLY source of select-TWO items in the curriculum. Until it was
    # loaded here, `_correct_positions` had correct multi-correct handling that nothing
    # ever exercised: a real end-to-end seed imported 533 questions from these banks
    # (539 rows in the database, the difference being upstream's own demo courses),
    # every one with exactly one correct option and no two-correct group at all.
    #
    # Left exam-shaped rather than partitioned through `_weighted_exam_series`, because
    # the author wrote it as a single full-length form against the published blueprint.
    # That shape is asserted rather than assumed: the bank's own `examShape.items` is
    # unreachable here because `_load_bank` returns only the questions list, so the
    # count is checked directly. A bank that grows to 75 items would otherwise become a
    # 75-question "full-length" exam with nothing anywhere noticing.
    matthew = _load_bank_optional("matthew-purcell-practice-exams.json")
    if matthew and len(matthew) != MATTHEW_EXAM_ITEMS:
        raise ValueError(
            f"matthew-purcell-practice-exams.json is exam-shaped at {MATTHEW_EXAM_ITEMS} items; "
            f"got {len(matthew)}. Update MATTHEW_EXAM_ITEMS deliberately if the author revised it."
        )
    # Matthew Purcell's 60 items stay in the associate POOL and are drawn from like
    # any other. His separate named exam is gone (Max, 2026-09-02): all 60 are in the
    # pool already, so it was a fixed copy of what the draw composes. The reuse grant
    # is conditional on credit, which is carried by each item's own `source` field and
    # by the named credit in the practice page's disclosure.
    associate_extra_exams: list[dict] = []
    specs: list[dict] = []

    # --- Course 0: Getting Started (onboarding, no exam) ---
    getting_started_lessons = [
        ("student-login", "Signing in as a student", "Create your account, verify your email, and log in."),
        ("admin-and-roles", "Roles, admin & instructor access", "How the four roles work and how staff reach the admin panel."),
        ("enrolling-and-progress", "Enrolling and tracking progress", "Find a course, enroll, and complete resources."),
        ("password-reset", "Resetting your password", "Recover access with the forgot-password flow."),
    ]
    specs.append({
        "codigo": "IS-START",
        # Display-name only: "Start AI Tools" is the learner-facing brand
        # (2026-07-30 rename, bead now-lms-0iq); codigo stays IS-START as the
        # URL- and FK-stable internal handle. Do not migrate the codigo.
        "nombre": "Start AI Tools",
        "descripcion_corta": "Free orientation + free practice exams on Courses A/B/C. The on-ramp to "
                             "Intent Solutions certification.",
        "descripcion": "Start AI Tools is the free on-ramp to Intent Solutions certification: how to "
                       "sign in, enroll, and track progress on Learn, plus free practice-exam access on "
                       "Courses A, B, and C. Work through the orientation first, then pick your "
                       "certification path — Associate, Developer, or CCA-F.",
        "nivel": 0,
        "duracion": 1,
        "sections": [
            {
                "nombre": title,
                "descripcion": desc,
                "lesson": _load_lesson("getting-started", stem, title),
            }
            for stem, title, desc in getting_started_lessons
        ],
    })

    # --- Course A: Associate onramp ---
    specs.append({
        "codigo": "CCA-A",
        # Which credential this course preps for, so its mock draws to that
        # exam's published shape rather than a generic one.
        "certification": "CCAO-F",
        "nombre": "Claude Foundations (Associate onramp)",
        "descripcion_corta": "Foundational Claude skills: prompting, evaluation, product selection, workflows, governance.",
        "descripcion": "The associate-level onramp toward the Claude Certified Architect path. Covers "
                       "prompting and task execution, output evaluation, product and model selection, "
                       "workflow integration, configuration, responsible use, and troubleshooting.",
        "nivel": 1,
        "duracion": 4,
        "sections": [
            {
                "nombre": name,
                "descripcion": f"{name} — lesson and practice quiz.",
                "lesson": _load_lesson("course-a-associate", key, name),
                "questions": qs,
            }
            for _num, name, key, qs in _group_by_domain(associate)
        ],
        # Purcell's items join the POOL as well as standing as their own full-length
        # exam. Without them the pool is 36 items under a 60-item draw, which serves 36
        # while the description promises 60.
        "mock_questions": associate + (matthew or []),
        "extra_exams": associate_extra_exams,
    })

    # --- Course B: Developer ---
    specs.append({
        "codigo": "CCA-B",
        # Which credential this course preps for, so its mock draws to that
        # exam's published shape rather than a generic one.
        "certification": "CCD",
        "nombre": "Building with Claude (Developer)",
        "descripcion_corta": "Developer-level Claude: agents, integration, Claude Code, eval, tools & MCP, security.",
        "descripcion": "The developer-level course: building agents and workflows, application integration, "
                       "Claude Code, evaluation and debugging, model selection, prompt and context engineering, "
                       "security, and tools & MCP.",
        "nivel": 2,
        "duracion": 5,
        "sections": [
            {
                "nombre": name,
                "descripcion": f"{name} — lesson and practice quiz.",
                "lesson": _load_lesson("course-b-developer", key, name),
                "questions": qs,
            }
            for _num, name, key, qs in _group_by_domain(developer)
        ],
        "mock_questions": developer,
    })

    # --- Course C: CCA-F prep (five official domains from the general bank) ---
    cca_sections = [
        {
            "nombre": name,
            "descripcion": f"{name} — lesson and practice quiz.",
            "lesson": _load_lesson("course-c-cca-f", key, name),
            "questions": qs,
        }
        for _num, name, key, qs in _group_by_domain(general)
    ]
    # Architect-professional bank feeds an extra professional-scenario practice section.
    cca_sections.append({
        "nombre": "Professional-level scenario practice",
        "descripcion": "Architect Professional scenario bank — extra practice beyond the five domains.",
        "lesson": _load_lesson("course-c-cca-f", "professional-scenarios", "Professional-level scenario practice"),
        "questions": architect,
    })
    # Rick Hightower's authored practice-exam pool (optional, reuse-granted) →
    # up to 3 full-length weighted practice exams appended to Course C.
    # Rick Hightower's 480 items live in the certification's pooled sitting, which
    # draws a fresh weighted paper every attempt. The three fixed exams that used to
    # be cut from them here are gone (Max, 2026-09-02): `_weighted_exam_series` was
    # partitioning his pool with the same blueprint the draw uses, so they were three
    # memorisable copies of what the draw produces anew each time. Nothing is lost:
    # every one of those items is still drawn from.
    extra_exams: list[dict] = []

    specs.append({
        "codigo": "CCA-F",
        # Which credential this course preps for, so its mock draws to that
        # exam's published shape rather than a generic one.
        "certification": "CCA-F",
        "nombre": "Claude Certified Architect — Foundations (CCA-F) prep",
        "descripcion_corta": "Prep for the CCA-F credential: the five official domains + a weighted 60-question mock.",
        "descripcion": "Preliminary preparation toward Anthropic's Claude Certified Architect (CCA) — "
                       "Foundations credential. One section per official domain (Agentic Architecture, "
                       "Claude Code Workflows, Prompt Engineering, Tool Design & MCP, Context Management) "
                       "with a practice quiz each, plus a weighted 60-question mock exam at the 72% pass mark "
                       "and additional full-length scenario practice exams. "
                       "This course prepares you for the real Anthropic exam; it is not the exam itself.",
        "nivel": 3,
        "duracion": 6,
        "sections": cca_sections,
        # The WHOLE bank, not a pre-selected 60: the mock carries `draw_size`, so each
        # attempt composes its own weighted paper from the pool. Handing it a form that
        # was already chosen would leave the draw with nothing to do but reshuffle.
        "mock_questions": general,
        "extra_exams": extra_exams,
    })

    return specs


def _count_learner_data(db, models, code: str) -> tuple[int, int]:
    """Count what a ``--reset`` of this course would destroy: enrollments and
    graded evaluation attempts. Both are real member data — enrollments via
    ``EstudianteCurso``, attempts via ``EvaluationAttempt`` reached through the
    course's evaluations (``EvaluationAttempt.evaluation_id`` cascades on
    delete, so dropping the evaluations silently takes the attempts with them).
    """
    from sqlalchemy import func

    EstudianteCurso = models["EstudianteCurso"]
    EvaluationAttempt = models["EvaluationAttempt"]
    Evaluation = models["Evaluation"]
    CursoSeccion = models["CursoSeccion"]

    enrollments = db.session.execute(
        db.select(func.count()).select_from(EstudianteCurso).filter(EstudianteCurso.curso == code)
    ).scalar_one()

    evaluation_ids = (
        db.session.execute(
            db.select(Evaluation.id).join(CursoSeccion, Evaluation.section_id == CursoSeccion.id).filter(
                CursoSeccion.curso == code
            )
        )
        .scalars()
        .all()
    )
    attempts = 0
    if evaluation_ids:
        attempts = db.session.execute(
            db.select(func.count())
            .select_from(EvaluationAttempt)
            .filter(EvaluationAttempt.evaluation_id.in_(evaluation_ids))
        ).scalar_one()

    return enrollments, attempts


def _required_ack_flag(total_enrollments: int, total_attempts: int) -> str:
    """The exact flag ``--reset`` requires when it would destroy learner data.

    Naming the counts in the flag forces the operator to have actually seen
    them (from this function's own prior refusal) rather than muscle-memoried
    a bare boolean past this gate; a mismatch also catches new enrollments or
    attempts landing between the check and the re-run.
    """
    return f"--i-know-this-deletes-{total_enrollments}-enrollments-and-{total_attempts}-attempts"


def _delete_course(db, models, code: str) -> bool:
    """Delete a course and its sections/lessons/evaluations. Returns True if found.

    Used by ``--reset`` to rebuild a course. Callers MUST call
    ``_count_learner_data`` first and get the operator's explicit
    acknowledgement before calling this — it does not check itself, so it is
    only ever called from ``main()`` after that gate has passed.

    Deliberately does NOT commit. The whole reset is one transaction so that a
    course cannot be dropped while a sibling's re-check is still deciding, and so
    a failure part-way leaves nothing half-deleted. ``main()`` commits once.
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
    db.session.flush()  # surface integrity errors here, still inside the caller's transaction
    return True


def _require_content_dir() -> None:
    """Fail fast, and explain where the curriculum actually lives."""
    if BANKS_DIR.is_dir() and LESSONS_DIR.is_dir():
        return
    print(
        f"ERROR: curriculum content not found at {CONTENT_DIR}\n"
        "\n"
        "The teaching content is NOT in this repository — it lives in the private\n"
        "intent-solutions-io/intent-curriculum repo. Clone it and point this script\n"
        "at its cca/ directory:\n"
        "\n"
        "    git clone git@github.com:intent-solutions-io/intent-curriculum.git\n"
        "    CCA_CONTENT_DIR=/path/to/intent-curriculum/cca python3.12 scripts/seed_cca_courses.py\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _backfill_sitting_fields(db, models) -> int:
    """Give existing mock exams their sitting fields, without touching learner data.

    A course that already exists is skipped wholesale by `_create_course`, so on a
    seeded production database every mock kept the old shape: no clock, no draw, no
    scale. This backfills those four columns on the rows that are already there.
    Idempotent, and it writes nothing but the sitting fields: no course, section,
    question, attempt or answer is created, changed or deleted.
    """
    updated = 0
    for spec in _build_specs():
        sitting = SITTINGS.get(spec.get("certification"))
        if not sitting or not spec.get("mock_questions"):
            continue
        title = f"Mock exam — {spec['nombre']}"
        evaluation = db.session.execute(
            db.select(models["Evaluation"]).filter_by(title=_truncate(title, 200))
        ).scalars().first()
        if evaluation is None:
            continue

        pool = len(evaluation.questions)
        if pool < sitting["items"]:
            # Refuse, do not skip. Leaving it alone means an evaluation that already
            # exists keeps advertising a form its pool cannot fill, which is the
            # thing the preflight exists to prevent for new ones.
            raise ValueError(
                f"{spec['codigo']} ({spec['certification']}): existing '{title}' holds {pool} "
                f"questions but the form draws {sitting['items']}. Refusing to backfill a "
                "sitting that would advertise more questions than it can serve."
            )

        wanted = {
            "time_limit_minutes": sitting["minutes"],
            "draw_size": sitting["items"],
            "scaled_cut": sitting["cut"],
            "blueprint_json": json.dumps(sitting["blueprint"]) if sitting.get("blueprint") else None,
        }
        changed = [f for f, v in wanted.items() if getattr(evaluation, f) != v]
        if not changed:
            continue
        for field, value in wanted.items():
            setattr(evaluation, field, value)
        db.session.commit()
        updated += 1
        print(f"  [set]  '{title}' — {', '.join(changed)}")
    return updated


def _preflight(specs: list[dict]) -> None:
    """Refuse every impossible sitting BEFORE the first row is written.

    The pool checks used to run inside `_create_course`, after the course and its
    sections were already committed. A refusal there left a half-built course
    behind, and because the seeder skips a course whose code already exists, the
    corrected re-run then skipped it entirely and the course stayed half-built.
    Checking everything up front means a bad bank changes nothing at all.
    """
    problems = []
    for spec in specs:
        sitting = SITTINGS.get(spec.get("certification"))
        if not sitting or not sitting.get("items"):
            continue
        pool = spec.get("mock_questions") or []
        if len(pool) < sitting["items"]:
            problems.append(
                f"{spec['codigo']} ({spec['certification']}): mock pool holds {len(pool)} "
                f"questions, the form draws {sitting['items']}"
            )

    for cert_key, sitting in SITTINGS.items():
        bank: list[dict] = []
        for filename, (key, _name) in BANK_CERTIFICATIONS.items():
            if key == cert_key:
                bank.extend(_load_bank_optional(filename) or [])
        if not bank:
            continue
        if len(bank) < sitting["items"]:
            problems.append(
                f"{cert_key} practice sitting: pool holds {len(bank)} questions, "
                f"the form draws {sitting['items']}"
            )

    if problems:
        raise ValueError(
            "Refusing to seed: a sitting would advertise more questions than its pool can "
            "fill.\n  - " + "\n  - ".join(problems)
        )


def _seed_practice_sittings(db, models) -> int:
    """One full-length practice sitting per certification, belonging to no course.

    Practice is its own area of the product, outside courses (Max, 2026-08-09), and
    since 2026-09-02 an Evaluation may carry no section so a sitting can say that in
    the schema rather than by convention. This is what a course-shaped seeder could
    not do: CCA-P has a bank and a certification but no course, so it had no
    full-length exam at all while its 126 items sat reachable only as drills.

    Keyed by certification, idempotent on (certification_key, title). The pool is
    every question in the bank for that credential, so the draw composes a fresh
    paper each attempt.
    """
    created = 0
    for cert_key, sitting in SITTINGS.items():
        bank: list[dict] = []
        cert_name = None
        for filename, (key, name) in BANK_CERTIFICATIONS.items():
            if key != cert_key:
                continue
            cert_name = name
            bank.extend(_load_bank_optional(filename) or [])
        if not bank:
            continue
        # Undersized pools were already refused by _preflight before any write.

        title = f"Practice exam — {cert_name}"
        existing = db.session.execute(
            db.select(models["Evaluation"]).filter_by(certification_key=cert_key, title=title)
        ).scalars().first()
        if existing is not None:
            print(f"  [skip] {cert_key} practice sitting already exists")
            continue

        imported = _add_evaluation(
            db,
            models,
            None,  # no section: this sitting belongs to no course
            title=title,
            description=(
                f"{sitting['items']} items drawn to the published blueprint, "
                f"{sitting['minutes']} minutes, {sitting['cut']} to pass. Unlimited attempts."
            ),
            is_exam=True,
            passing_score=72.0,
            questions=bank,
            sitting=sitting,
            certification_key=cert_key,
        )
        created += 1
        print(f"  [ok]   {cert_key} practice sitting — {imported} questions in the pool")
    return created


def main() -> int:
    """Seed all four courses inside the app context. Returns a shell exit code."""
    _require_content_dir()
    # When run as a script, sys.path[0] is this file's directory (scripts/), not
    # the repo root, so the ``now_lms`` package next to it isn't importable.
    # Put the repo root first so ``import now_lms`` resolves regardless of cwd.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from now_lms import app
    from now_lms.db import (
        Curso,
        CursoRecurso,
        CursoSeccion,
        EstudianteCurso,
        Evaluation,
        EvaluationAttempt,
        Question,
        QuestionOption,
        database,
    )

    models = {
        "Curso": Curso,
        "CursoSeccion": CursoSeccion,
        "CursoRecurso": CursoRecurso,
        "Evaluation": Evaluation,
        "Question": Question,
        "QuestionOption": QuestionOption,
        "EstudianteCurso": EstudianteCurso,
        "EvaluationAttempt": EvaluationAttempt,
    }

    # Optional: `--reset=CODE1,CODE2` deletes those courses before seeding so they
    # can be rebuilt. Refuses when any of them carry learner data (enrollments
    # or graded evaluation attempts) unless the operator passes the exact
    # acknowledgement flag this prints — naming the count forces them to have
    # actually seen it, not just muscle-memoried a boolean flag past this gate.
    reset_codes: list[str] = []
    ack_flag: str | None = None
    for arg in sys.argv[1:]:
        if arg.startswith("--reset="):
            reset_codes = [c.strip() for c in arg.split("=", 1)[1].split(",") if c.strip()]
        elif arg.startswith("--i-know-this-deletes-"):
            ack_flag = arg

    # Reuse a context if the caller already has one. Pushing a second context opens
    # a second connection, and the test suite runs on `sqlite:///:memory:`, where a
    # second connection is a different, empty database: every query from inside here
    # then failed with "no such table". Under a real run there is no outer context
    # and this behaves exactly as before.
    with nullcontext() if has_app_context() else app.app_context():
        print("Seeding CCA-F preliminary prep curriculum...")

        # BEFORE anything is deleted or written. A --reset used to delete and commit
        # first and hit the pool checks afterwards, so an undersized bank destroyed a
        # course and then refused to rebuild it.
        #
        # Missing content is not a bypass: without banks nothing is seeded either, so
        # there is no sitting to advertise wrongly. The build is retried below, where
        # `_require_content_dir` turns it into the operator-facing error it should be
        # rather than a traceback from in here.
        try:
            specs = _build_specs()
        except (FileNotFoundError, OSError):
            specs = None
        if specs:
            _preflight(specs)

        if reset_codes:
            per_course: dict[str, tuple[int, int]] = {}
            total_enrollments = 0
            total_attempts = 0
            for code in reset_codes:
                enrollments, attempts = _count_learner_data(database, models, code)
                per_course[code] = (enrollments, attempts)
                total_enrollments += enrollments
                total_attempts += attempts

            if total_enrollments or total_attempts:
                required_flag = _required_ack_flag(total_enrollments, total_attempts)
                if ack_flag != required_flag:
                    print(
                        "ERROR: --reset would destroy real member data:",
                        file=sys.stderr,
                    )
                    for code, (enrollments, attempts) in per_course.items():
                        if enrollments or attempts:
                            print(
                                f"  {code}: {enrollments} enrollment(s), {attempts} evaluation attempt(s)",
                                file=sys.stderr,
                            )
                    print(
                        "\nThis is not a warning to skim past — it is a refusal. Re-run with the "
                        "exact flag naming what this destroys:\n"
                        f"    {required_flag}\n"
                        "If those counts don't match what you expect, STOP: someone enrolled or "
                        "attempted an evaluation since you last checked, and re-seeding right now "
                        "would delete their record.",
                        file=sys.stderr,
                    )
                    raise SystemExit(3)

            # Re-count inside the deleting transaction and refuse if anything moved.
            #
            # The acknowledgement flag is checked against counts read a moment
            # earlier, and nothing stopped a learner enrolling or submitting an
            # attempt in between — that record would then be destroyed without ever
            # appearing in the number the operator acknowledged. Locking the Curso
            # row does not help, because a new enrollment inserts into
            # EstudianteCurso, which that lock does not cover. So the acknowledged
            # numbers are enforced HERE, at the point of deletion, rather than only
            # at the point of checking. Greptile, PR #78.
            ahora_enrollments = 0
            ahora_attempts = 0
            for code in reset_codes:
                e, a = _count_learner_data(database, models, code)
                ahora_enrollments += e
                ahora_attempts += a

            if (ahora_enrollments, ahora_attempts) != (total_enrollments, total_attempts):
                database.session.rollback()
                print(
                    "ERROR: learner data changed between the check and the delete.\n"
                    f"  acknowledged: {total_enrollments} enrollment(s), {total_attempts} attempt(s)\n"
                    f"  now:          {ahora_enrollments} enrollment(s), {ahora_attempts} attempt(s)\n"
                    "Nothing was deleted. Someone enrolled or submitted an attempt while this ran, "
                    "and their record is not covered by the flag you passed. Re-run to see the "
                    "current numbers.",
                    file=sys.stderr,
                )
                raise SystemExit(4)

            for code in reset_codes:
                if _delete_course(database, models, code):
                    print(f"  [reset] deleted course '{code}' for rebuild")
            database.session.commit()  # one commit for the whole reset

        if specs is None:
            specs = _build_specs()
        for spec in specs:
            _create_course(database, models, spec)
        _backfill_sitting_fields(database, models)
        _seed_practice_sittings(database, models)
        print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
