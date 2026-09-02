# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Add exam-form columns to evaluation and evaluation_attempt

Revision ID: 20260902_010000
Revises: 20260810_010000
Create Date: 2026-09-02 01:00:00

Five columns on ``evaluation`` and two on ``evaluation_attempt``, plus
``evaluation.section_id`` becoming nullable so a practice sitting can exist
without a course, turn a fixed
question list into a timed, drawn, scaled sitting. Every one is nullable, and
null means exactly the behaviour the tables had before this revision: all
questions, in stored order, untimed, scored as a percentage.

``evaluation.draw_size`` is the load-bearing one. Without it an evaluation is a
fixed list, so a bank of several hundred questions still serves the same subset
in the same order on every attempt, and depth in the bank buys a candidate
nothing.

``evaluation_attempt.form_json`` records the paper an attempt was actually
given: which questions were drawn and what order their options appeared in. It
lives here rather than in the browser so a refresh, a crash or a move to another
device resumes the SAME paper, and so grading reads the same order the candidate
saw. Attempts that predate the column have none, and read back as the
evaluation's stored questions.

The columns are added only when absent. A fresh install builds the current model
with ``database.create_all()`` and then stamps the migration head, so this
revision must be a no-op there and do real work only on a database that ran the
earlier history.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260902_010000"
down_revision = "20260810_010000"
branch_labels = None
depends_on = None

EVALUATION = "evaluation"
ATTEMPT = "evaluation_attempt"
# One sitting per candidate per evaluation may be open at a time. Enforced in the
# database rather than by a read-then-write in the view, because two requests can
# both read "no open attempt" and both insert. Partial unique indexes are supported
# by PostgreSQL and by SQLite since 3.8, which covers every backend this fork runs.
OPEN_ATTEMPT_INDEX = "uq_evaluation_attempt_open_per_user"
# `Evaluation.certification_key` is declared index=True, so a create_all() install
# builds this index. A migrated database has to build it too, or the two diverge —
# and the downgrade has to drop it BEFORE the column, because SQLite refuses to drop
# a column an index still names.
CERTIFICATION_INDEX = "ix_evaluation_certification_key"

EVALUATION_COLUMNS = {
    "time_limit_minutes": sa.Integer(),
    "draw_size": sa.Integer(),
    "scaled_cut": sa.Integer(),
    "blueprint_json": sa.Text(),
    "certification_key": sa.String(50),
}
ATTEMPT_COLUMNS = {
    "form_json": sa.Text(),
    "answers_json": sa.Text(),
    "scaled_score": sa.Integer(),
}
ANSWER = "answer"
# One answer per question per attempt. Without it two concurrent autosaves could
# both insert, and the score counted every row: a one-question paper scored 200.
UNIQUE_ANSWER_INDEX = "uq_answer_one_per_attempt_question"


def _column_names(inspector, table: str) -> set:
    return {column["name"] for column in inspector.get_columns(table)}


def _table_names(inspector) -> set:
    return set(inspector.get_table_names())


def upgrade() -> None:
    """Add the columns, skipping any that a create_all() install already built."""
    inspector = sa.inspect(op.get_bind())
    tables = _table_names(inspector)

    # A practice sitting belongs to no course, so an evaluation may now have no
    # section. Batch mode because SQLite cannot ALTER a column's nullability in
    # place and rebuilds the table instead.
    if EVALUATION in tables:
        nullable = {c["name"]: c["nullable"] for c in inspector.get_columns(EVALUATION)}
        if nullable.get("section_id") is False:
            with op.batch_alter_table(EVALUATION) as batch:
                batch.alter_column("section_id", existing_type=sa.String(26), nullable=True)

    for table, columns in ((EVALUATION, EVALUATION_COLUMNS), (ATTEMPT, ATTEMPT_COLUMNS)):
        if table not in tables:
            # Nothing to migrate on an install that has not created this table yet.
            continue
        existing = _column_names(inspector, table)
        for name, column_type in columns.items():
            if name in existing:
                continue
            op.add_column(table, sa.Column(name, column_type, nullable=True))

    if EVALUATION in tables:
        evaluation_indexes = {index["name"] for index in inspector.get_indexes(EVALUATION)}
        if CERTIFICATION_INDEX not in evaluation_indexes:
            op.create_index(CERTIFICATION_INDEX, EVALUATION, ["certification_key"])

    dialect = op.get_bind().dialect.name

    open_index_missing = ATTEMPT in tables and OPEN_ATTEMPT_INDEX not in {
        index["name"] for index in inspector.get_indexes(ATTEMPT)
    }
    if open_index_missing and dialect in ("sqlite", "postgresql"):
        # Refuse rather than mutate. Every attempt written before this revision was
        # created and submitted in the same request, so real data should have none of
        # these; if a database does, the extra rows are somebody's unfinished work and
        # deciding which to close is not a migration's call.
        duplicates = op.get_bind().execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT evaluation_id, user_id FROM {ATTEMPT} "
                "WHERE submitted_at IS NULL GROUP BY evaluation_id, user_id "
                "HAVING COUNT(*) > 1) AS clashes"
            )
        ).scalar()
        if duplicates:
            raise RuntimeError(
                f"{duplicates} candidate(s) have more than one unsubmitted attempt at the same "
                "evaluation, so a unique index over open attempts cannot be created. Close or "
                "remove the extra attempts deliberately, then re-run this migration."
            )
        op.create_index(
            OPEN_ATTEMPT_INDEX,
            ATTEMPT,
            ["evaluation_id", "user_id"],
            unique=True,
            sqlite_where=sa.text("submitted_at IS NULL"),
            postgresql_where=sa.text("submitted_at IS NULL"),
        )
            # MySQL has no partial index. The same DDL there compiles to a PLAIN
            # unique index on (evaluation_id, user_id), which does not mean "one
            # OPEN attempt" — it means one attempt EVER, so a candidate could never
            # sit a second time. Skipped rather than shipped wrong; the view's
            # read-then-insert with an IntegrityError fallback still narrows the
            # race there, and the seeded deployments run PostgreSQL.

    # Fold any existing duplicates together before the constraint can reject them.
    if ANSWER in tables and UNIQUE_ANSWER_INDEX not in {i["name"] for i in inspector.get_indexes(ANSWER)}:
        op.get_bind().execute(
            sa.text(
                f"DELETE FROM {ANSWER} WHERE id NOT IN "
                f"(SELECT keep FROM (SELECT MIN(id) AS keep FROM {ANSWER} "
                "GROUP BY attempt_id, question_id) AS survivors)"
            )
        )
        op.create_index(UNIQUE_ANSWER_INDEX, ANSWER, ["attempt_id", "question_id"], unique=True)


def downgrade() -> None:
    """Drop the columns again, tolerating any that are already absent.

    Dropping ``form_json`` discards the record of which paper each attempt was
    given. The scores survive, because they are stored on the attempt, but the
    per-question review of an old attempt reverts to the evaluation's stored
    question order, which is not necessarily the order that attempt was shown.
    """
    inspector = sa.inspect(op.get_bind())
    tables = _table_names(inspector)

    if ATTEMPT in tables and OPEN_ATTEMPT_INDEX in {i["name"] for i in inspector.get_indexes(ATTEMPT)}:
        op.drop_index(OPEN_ATTEMPT_INDEX, table_name=ATTEMPT)

    if ANSWER in tables and UNIQUE_ANSWER_INDEX in {i["name"] for i in inspector.get_indexes(ANSWER)}:
        op.drop_index(UNIQUE_ANSWER_INDEX, table_name=ANSWER)

    # Before the column, never after: SQLite errors with "no such column" when an
    # index still references what was dropped.
    if EVALUATION in tables and CERTIFICATION_INDEX in {i["name"] for i in inspector.get_indexes(EVALUATION)}:
        op.drop_index(CERTIFICATION_INDEX, table_name=EVALUATION)

    for table, columns in ((ATTEMPT, ATTEMPT_COLUMNS), (EVALUATION, EVALUATION_COLUMNS)):
        if table not in tables:
            continue
        existing = _column_names(inspector, table)
        for name in columns:
            if name not in existing:
                continue
            op.drop_column(table, name)

    # Restoring NOT NULL is only safe once nothing violates it. A course-free
    # practice sitting has no section by design, so refuse with an actionable
    # message rather than failing inside the ALTER or, worse, deleting a learner's
    # evaluation to make the constraint fit.
    if EVALUATION in tables:
        orphans = op.get_bind().execute(
            sa.text(f"SELECT COUNT(*) FROM {EVALUATION} WHERE section_id IS NULL")
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"{orphans} evaluation row(s) have no section, so section_id cannot be made "
                "NOT NULL again. These are course-free practice sittings. Reassign them to a "
                "section or delete them deliberately before downgrading."
            )
        with op.batch_alter_table(EVALUATION) as batch:
            batch.alter_column("section_id", existing_type=sa.String(26), nullable=False)
