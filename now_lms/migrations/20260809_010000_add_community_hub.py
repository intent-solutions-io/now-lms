"""Add the Community Hub sidecar tables

Revision ID: 20260809_010000
Revises: 20260730_000000
Create Date: 2026-08-09 01:00:00

Three tables backing the Community Hub (ADR-8, 000-docs/015-AT-ADEC):
post metadata, reactions, and the append-only moderation trail. Post bodies and
the reply tree stay in the native ``foro_mensaje``, which this revision does not
touch — so downgrading cannot reach a single member post or reply.

A fresh install builds the full current-model schema with ``database.create_all()``
and then stamps the migration head, so this revision must be a no-op there and do
real work only on an existing database.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260809_010000"
down_revision = "20260730_000000"
branch_labels = None
depends_on = None

AUDIT_COLUMNS = (
    ("id", sa.String(26), {"nullable": False, "index": True}),
    ("timestamp", sa.DateTime(), {"nullable": False}),
    ("creado", sa.Date(), {"nullable": False}),
    ("creado_por", sa.String(150), {"nullable": True}),
    ("modificado", sa.DateTime(), {"nullable": True}),
    ("modificado_por", sa.String(150), {"nullable": True}),
)


def _audit():
    return [sa.Column(name, type_, **kwargs) for name, type_, kwargs in AUDIT_COLUMNS]


def upgrade():
    """Create the three Community Hub tables, each only when absent."""
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())

    if "comunidad_publicacion" not in existing:
        op.create_table(
            "comunidad_publicacion",
            *_audit(),
            sa.Column("mensaje_id", sa.String(26), nullable=False, index=True),
            sa.Column("titulo", sa.String(160), nullable=False),
            sa.Column("tipo", sa.String(20), nullable=False, index=True),
            sa.Column("estado_moderacion", sa.String(20), nullable=False, index=True),
            sa.Column("fijado", sa.Boolean(), nullable=False),
            sa.Column("enlace_build", sa.String(500), nullable=True),
            sa.Column("reportes_abiertos", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["mensaje_id"], ["foro_mensaje.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("mensaje_id", name="uq_comunidad_publicacion_mensaje"),
        )
        op.create_index(
            "ix_comunidad_publicacion_tipo_estado",
            "comunidad_publicacion",
            ["tipo", "estado_moderacion"],
        )

    if "comunidad_reaccion" not in existing:
        op.create_table(
            "comunidad_reaccion",
            *_audit(),
            sa.Column("mensaje_id", sa.String(26), nullable=False, index=True),
            sa.Column("usuario", sa.String(150), nullable=False, index=True),
            sa.ForeignKeyConstraint(["mensaje_id"], ["foro_mensaje.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["usuario"], ["usuario.usuario"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            # The constraint the whole feature rests on: one member, one like.
            sa.UniqueConstraint("mensaje_id", "usuario", name="uq_comunidad_reaccion_una_por_miembro"),
        )

    if "comunidad_evento_moderacion" not in existing:
        op.create_table(
            "comunidad_evento_moderacion",
            *_audit(),
            sa.Column("mensaje_id", sa.String(26), nullable=False, index=True),
            sa.Column("tipo", sa.String(20), nullable=False),
            sa.Column("actor", sa.String(150), nullable=False, index=True),
            sa.Column("motivo", sa.String(500), nullable=True),
            sa.Column("ocurrido_en", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mensaje_id"], ["foro_mensaje.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor"], ["usuario.usuario"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_comunidad_evento_mensaje_fecha",
            "comunidad_evento_moderacion",
            ["mensaje_id", "ocurrido_en"],
        )


def downgrade():
    """Drop the three tables. ``foro_mensaje`` is never touched, so no member content is at risk."""
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())

    if "comunidad_evento_moderacion" in existing:
        op.drop_index("ix_comunidad_evento_mensaje_fecha", table_name="comunidad_evento_moderacion")
        op.drop_table("comunidad_evento_moderacion")
    if "comunidad_reaccion" in existing:
        op.drop_table("comunidad_reaccion")
    if "comunidad_publicacion" in existing:
        op.drop_index("ix_comunidad_publicacion_tipo_estado", table_name="comunidad_publicacion")
        op.drop_table("comunidad_publicacion")
