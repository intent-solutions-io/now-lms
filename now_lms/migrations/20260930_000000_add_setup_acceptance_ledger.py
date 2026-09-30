"""Add the private participant setup and agreement acceptance ledger

Revision ID: 20260930_000000
Revises: 20260810_010000
Create Date: 2026-09-30 00:00:00

Adds five tables behind the private /setup/<token> page:

- setup_case: one person's setup, the stable case id.
- setup_token: single-use expiring links, stored only as SHA-256 hashes.
- setup_draft: saved, not-yet-accepted profile fields (save and resume).
- agreement_acceptance: insert-only click-to-accept evidence. On PostgreSQL a
  trigger refuses UPDATE and DELETE so an accepted record cannot be rewritten.
- setup_job: durable, idempotent follow-up work (receipt, CRM sync, release).

Each table is created only when absent. A fresh install builds the full current-model
schema with `database.create_all()` and then stamps the migration head (the model
attaches the same trigger on table creation), so this revision must be a no-op there
and do real work only on an existing database.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260930_000000"
down_revision = "20260810_010000"
branch_labels = None
depends_on = None

FUNCTION_SQL = (
    "CREATE OR REPLACE FUNCTION agreement_acceptance_immutable() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'agreement_acceptance rows are immutable'; END; $$ LANGUAGE plpgsql"
)
TRIGGER_SQL = (
    "CREATE TRIGGER agreement_acceptance_no_modify BEFORE UPDATE OR DELETE ON agreement_acceptance "
    "FOR EACH ROW EXECUTE FUNCTION agreement_acceptance_immutable()"
)


def upgrade():
    """Create the setup ledger tables (and the PostgreSQL immutability trigger) if absent."""
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())

    if "setup_case" not in existing:
        op.create_table(
            "setup_case",
            sa.Column("id", sa.String(26), nullable=False),
            sa.Column("application_ref", sa.String(64), nullable=True, index=True),
            sa.Column("person_ref", sa.String(64), nullable=True, index=True),
            sa.Column("personal_email", sa.String(254), nullable=False, index=True),
            sa.Column("display_name", sa.String(150), nullable=False),
            sa.Column("known_phone", sa.String(32), nullable=True),
            sa.Column("access_scope", sa.String(300), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "setup_token" not in existing:
        op.create_table(
            "setup_token",
            sa.Column("id", sa.String(26), nullable=False),
            sa.Column("case_id", sa.String(26), nullable=False, index=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["setup_case.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_setup_token_token_hash", "setup_token", ["token_hash"], unique=True)

    if "setup_draft" not in existing:
        op.create_table(
            "setup_draft",
            sa.Column("id", sa.String(26), nullable=False),
            sa.Column("case_id", sa.String(26), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["case_id"], ["setup_case.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_setup_draft_case_id", "setup_draft", ["case_id"], unique=True)

    if "agreement_acceptance" not in existing:
        op.create_table(
            "agreement_acceptance",
            sa.Column("id", sa.String(26), nullable=False),
            sa.Column("case_id", sa.String(26), nullable=False),
            sa.Column("personal_email", sa.String(254), nullable=False),
            sa.Column("legal_given_names", sa.String(200), nullable=False),
            sa.Column("legal_family_names", sa.String(200), nullable=True),
            sa.Column("legal_full_name", sa.String(401), nullable=False),
            sa.Column("single_name", sa.Boolean(), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("address_line1", sa.String(200), nullable=False),
            sa.Column("address_line2", sa.String(200), nullable=True),
            sa.Column("locality", sa.String(120), nullable=False),
            sa.Column("region", sa.String(120), nullable=True),
            sa.Column("postal_code", sa.String(20), nullable=True),
            sa.Column("phone_e164", sa.String(16), nullable=False),
            sa.Column("whatsapp_permission", sa.Boolean(), nullable=False),
            sa.Column("access_scope", sa.String(300), nullable=True),
            sa.Column("explanation_version", sa.String(50), nullable=False),
            sa.Column("agreement_document_id", sa.String(100), nullable=False),
            sa.Column("agreement_version", sa.String(50), nullable=False),
            sa.Column("agreement_sha256", sa.String(64), nullable=False),
            sa.Column("agreement_pdf_sha256", sa.String(64), nullable=True),
            sa.Column("assent_text_version", sa.String(50), nullable=False),
            sa.Column("assent_text", sa.Text(), nullable=False),
            sa.Column("accepted_at_utc", sa.DateTime(), nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["setup_case.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agreement_acceptance_case_id", "agreement_acceptance", ["case_id"], unique=True)
        if conn.dialect.name == "postgresql":
            op.execute(FUNCTION_SQL)
            op.execute(TRIGGER_SQL)

    if "setup_job" not in existing:
        op.create_table(
            "setup_job",
            sa.Column("id", sa.String(26), nullable=False),
            sa.Column("case_id", sa.String(26), nullable=False, index=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, index=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.String(300), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["setup_case.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("case_id", "kind", name="setup_job_unico_por_caso"),
        )


def downgrade():
    """Drop the setup ledger tables. Refuses to drop recorded acceptances."""
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())

    if "agreement_acceptance" in existing:
        count = conn.execute(sa.text("SELECT COUNT(*) FROM agreement_acceptance")).scalar()
        if count:
            raise RuntimeError(
                "Refusing to drop agreement_acceptance: it holds accepted agreement evidence. Export it first."
            )

    for table in ("setup_job", "agreement_acceptance", "setup_draft", "setup_token", "setup_case"):
        if table in existing:
            op.drop_table(table)
    if conn.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS agreement_acceptance_immutable()")
