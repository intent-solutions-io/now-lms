# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Regressions for the sitting lifecycle, from an audit of the exam engine.

Each test here is a defect that shipped, not a hypothetical. The comments name the
observed behaviour rather than the rule, because the rule is what the assertion
already says.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parent.parent / "now_lms" / "migrations"


# --- the migration graph ---------------------------------------------------


def _revisions():
    found = []
    for path in MIGRATIONS.glob("*.py"):
        source = path.read_text()
        revision = re.search(r"^revision\s*=\s*[\"']([^\"']+)", source, re.MULTILINE)
        down = re.search(r"^down_revision\s*=\s*([\"']([^\"']+)[\"']|None)", source, re.MULTILINE)
        if revision:
            found.append((revision.group(1), down.group(2) if down and down.group(2) else None))
    return found


def test_the_migration_graph_has_exactly_one_head():
    """Two heads make `alembic upgrade head` ambiguous and can skip a revision.

    20260902_010000 was based on 20260810_020000, which already had a child, so it
    forked the graph rather than extending it.
    """
    revisions = _revisions()
    children = {}
    for revision, down in revisions:
        children.setdefault(down, []).append(revision)
    heads = [revision for revision, _ in revisions if revision not in children]
    assert len(heads) == 1, f"expected one head, found {sorted(heads)}"


def test_every_down_revision_names_a_revision_that_exists():
    revisions = _revisions()
    known = {revision for revision, _ in revisions}
    dangling = [(r, d) for r, d in revisions if d is not None and d not in known]
    assert dangling == []


def test_the_exam_form_migration_creates_the_open_attempt_index():
    """The one-open-attempt rule is a database invariant, not a view convention."""
    source = (MIGRATIONS / "20260902_010000_add_exam_form_columns.py").read_text()
    assert "create_index" in source
    assert "submitted_at IS NULL" in source
    assert "unique=True" in source


def test_the_downgrade_refuses_rather_than_deleting_sectionless_evaluations():
    source = (MIGRATIONS / "20260902_010000_add_exam_form_columns.py").read_text()
    assert "RuntimeError" in source, "downgrade must refuse when section_id cannot be NOT NULL"

    # Scoped to downgrade(). The UPGRADE deliberately deletes duplicate answer rows
    # before adding the uniqueness constraint they would otherwise violate, so a
    # whole-file scan flags that legitimate statement.
    downgrade = source[source.index("def downgrade("):]
    for destructive in ("DELETE FROM", "session.delete", "op.drop_table", "TRUNCATE"):
        assert destructive not in downgrade, f"downgrade must not {destructive}"


def test_the_upgrade_dedupes_answers_before_constraining_them():
    """Adding a unique index over existing duplicates fails the migration outright."""
    source = (MIGRATIONS / "20260902_010000_add_exam_form_columns.py").read_text()
    upgrade = source[source.index("def upgrade(") : source.index("def downgrade(")]
    dedupe = upgrade.index("DELETE FROM")
    constrain = upgrade.index("UNIQUE_ANSWER_INDEX, ANSWER")
    assert dedupe < constrain, "duplicates must be folded before the constraint is added"
    assert "GROUP BY attempt_id, question_id" in upgrade
    assert "MIN(id)" in upgrade, "keep the earliest row rather than an arbitrary one"


def test_the_open_attempt_index_is_not_created_on_a_backend_that_cannot_scope_it():
    """On MySQL the same DDL compiles to a plain unique (evaluation_id, user_id),
    which means one attempt EVER rather than one OPEN attempt, and would stop a
    candidate ever sitting a second time."""
    source = (MIGRATIONS / "20260902_010000_add_exam_form_columns.py").read_text()
    assert 'dialect in ("sqlite", "postgresql")' in source


def test_the_open_attempt_index_is_declared_on_the_model_too():
    """A fresh install builds its schema with create_all() and stamps the head, so a
    constraint that lives only in a migration is missing exactly there."""
    from now_lms.db import EvaluationAttempt

    names = {index.name: index for index in EvaluationAttempt.__table__.indexes}
    assert "uq_evaluation_attempt_open_per_user" in names
    assert names["uq_evaluation_attempt_open_per_user"].unique is True


# --- next= ------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "/%0d%0aLocation:%20//evil.test/x",  # CRLF reached redirect() and raised
        "%2f%2fevil.test",
        "//evil.test/x",
        "https://evil.test/x",
        "javascript:alert(1)",
        "/a\\b",
        "%09/tab",
        "/%00nul",
        "%68ttps://evil.test",
        "practice",
    ],
)
def test_safe_next_rejects_hostile_targets(hostile):
    from now_lms.vistas.users import _safe_next

    assert _safe_next(hostile) is None


@pytest.mark.parametrize("ok", ["/practice", "/practice/CCD", "/course/CCA-B/view", "/ok?x=1#y"])
def test_safe_next_keeps_same_site_paths(ok):
    from now_lms.vistas.users import _safe_next

    assert _safe_next(ok) == ok


# --- the stored paper -------------------------------------------------------


class _Option:
    def __init__(self, option_id, text, is_correct=False):
        self.id = option_id
        self.text = text
        self.is_correct = is_correct


class _Question:
    def __init__(self, question_id, domain_key="d1", correct=0):
        self.id = question_id
        self.text = f"stem {question_id}"
        self.explanation = f"why {question_id}"
        self.domain_key = domain_key
        self.domain_name = "Domain One"
        self.options = [_Option(f"{question_id}-{i}", f"opt {i}", i == correct) for i in range(4)]


class _Evaluation:
    def __init__(self, questions, draw_size=None):
        self.questions = questions
        self.draw_size = draw_size


def test_the_paper_is_the_exam_that_was_sat_not_the_bank_as_it_stands():
    """A 60-item attempt over a 583-item pool rendered all 583 on the result page,
    marking 523 never-shown questions unanswered and publishing their answers."""
    from now_lms.vistas import exam_forms

    pool = [_Question(f"q{i}") for i in range(20)]
    evaluation = _Evaluation(pool, draw_size=5)
    form = exam_forms.build_form(pool, evaluation, None)
    paper = exam_forms.form_questions(form, evaluation)

    assert len(paper) == 5
    shown = {q.id for q in paper}
    assert len(shown) == 5
    assert shown < {q.id for q in pool}


def test_a_paper_survives_every_edit_to_the_questions_underneath_it():
    from now_lms.vistas import exam_forms

    pool = [_Question("q1"), _Question("q2")]
    evaluation = _Evaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None)
    before = [(q.id, q.text, [(o.id, o.text, o.is_correct) for o in q.options])
              for q in exam_forms.form_questions(form, evaluation)]

    # every mutation an instructor can make mid-sitting
    evaluation.questions = [pool[0]]              # q2 deleted
    pool[0].text = "REWRITTEN"                    # stem edited
    pool[0].options.append(_Option("late", "new"))  # option added
    pool[0].options[0].text = "EDITED"            # option text edited
    for index, option in enumerate(pool[0].options):
        option.is_correct = index == 2            # key moved

    after = [(q.id, q.text, [(o.id, o.text, o.is_correct) for o in q.options])
             for q in exam_forms.form_questions(form, evaluation)]
    assert after == before


def test_score_denominator_is_the_paper_not_the_pool():
    """A perfect 53-question sitting drawn from 106 scored 50 percent."""
    from now_lms.vistas import exam_forms

    pool = [_Question(f"q{i}") for i in range(10)]
    evaluation = _Evaluation(pool, draw_size=4)
    form = exam_forms.build_form(pool, evaluation, None)
    assert len(exam_forms.load_form(exam_forms.dump_form(form))["items"]) == 4


# --- the clock --------------------------------------------------------------


def test_the_module_clock_is_naive_utc():
    """`started_at` is stored naive; comparing it to an aware `utc_now()` raises,
    and comparing it to local time is wrong by the server's offset."""
    from now_lms.vistas.evaluations import _now

    now = _now()
    assert now.tzinfo is None
    drift = abs((now - datetime.now(UTC).replace(tzinfo=None)).total_seconds())
    assert drift < 5, "the clock must be UTC, not local"


def test_a_deadline_is_measured_from_the_stored_start():
    from now_lms.vistas.evaluations import _deadline

    class _Attempt:
        started_at = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

    class _Timed:
        time_limit_minutes = 120

    class _Untimed:
        time_limit_minutes = None

    assert _deadline(_Attempt(), _Timed()) == _Attempt.started_at + timedelta(minutes=120)
    assert _deadline(_Attempt(), _Untimed()) is None


# --- the seeder -------------------------------------------------------------


def _seeder_source():
    return (Path(__file__).resolve().parent.parent / "scripts" / "seed_cca_courses.py").read_text()


def test_the_seeder_refuses_undersized_pools_before_writing_anything():
    """The check used to run after the course and its sections were committed, so a
    refusal left a half-built course that the idempotent re-run then skipped."""
    source = _seeder_source()
    assert "def _preflight(" in source
    preflight_call = source.index("_preflight(specs)")
    first_create = source.index("_create_course(database, models, spec)")
    assert preflight_call < first_create, "preflight must run before the first course is created"


def test_the_seeder_backfills_existing_evaluations_without_deleting_anything():
    source = _seeder_source()
    assert "def _backfill_sitting_fields(" in source
    body = source[source.index("def _backfill_sitting_fields("):]
    body = body[: body.index("\ndef ")]
    for destructive in ("session.delete", "DELETE FROM", "drop("):
        assert destructive not in body, f"backfill must not {destructive}"


def test_practice_sittings_are_seeded_without_a_course():
    source = _seeder_source()
    assert "def _seed_practice_sittings(" in source
    assert "certification_key=cert_key" in source


# --- ADR-3 ------------------------------------------------------------------


def test_no_question_bank_is_committed_to_this_public_repository():
    """Answer keys beside the courses that grade them is an assessment-integrity
    failure; ADR-3 moved the curriculum to a private repository."""
    repo = Path(__file__).resolve().parent.parent
    banks = list((repo / "content").glob("**/banks/*.json")) if (repo / "content").exists() else []
    assert banks == [], f"question banks must not live here: {banks}"


def test_the_seeder_reads_curriculum_from_outside_the_repository():
    assert "CCA_CONTENT_DIR" in _seeder_source()
