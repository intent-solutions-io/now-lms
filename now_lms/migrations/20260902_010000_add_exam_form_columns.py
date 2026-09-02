"""Add exam-form columns to evaluation and evaluation_attempt

Revision ID: 20260902_010000
Revises: 20260810_020000
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
down_revision = "20260810_020000"
branch_labels = None
depends_on = None

EVALUATION = "evaluation"
ATTEMPT = "evaluation_attempt"

EVALUATION_COLUMNS = {
    "time_limit_minutes": sa.Integer(),
    "draw_size": sa.Integer(),
    "scaled_cut": sa.Integer(),
    "blueprint_json": sa.Text(),
    "certification_key": sa.String(50),
}
ATTEMPT_COLUMNS = {
    "form_json": sa.Text(),
    "scaled_score": sa.Integer(),
}


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


def downgrade() -> None:
    """Drop the columns again, tolerating any that are already absent.

    Dropping ``form_json`` discards the record of which paper each attempt was
    given. The scores survive, because they are stored on the attempt, but the
    per-question review of an old attempt reverts to the evaluation's stored
    question order, which is not necessarily the order that attempt was shown.
    """
    inspector = sa.inspect(op.get_bind())
    tables = _table_names(inspector)

    for table, columns in ((ATTEMPT, ATTEMPT_COLUMNS), (EVALUATION, EVALUATION_COLUMNS)):
        if table not in tables:
            continue
        existing = _column_names(inspector, table)
        for name in columns:
            if name not in existing:
                continue
            op.drop_column(table, name)
