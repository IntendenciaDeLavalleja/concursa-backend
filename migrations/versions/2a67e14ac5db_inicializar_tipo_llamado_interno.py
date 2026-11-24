"""Inicializar el tipo de llamado Interno en el historial de migraciones.

Revision ID: 2a67e14ac5db
Revises: 73ed98ab48c2
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = '2a67e14ac5db'
down_revision = '73ed98ab48c2'
branch_labels = None
depends_on = None


def upgrade():
    tipos = sa.table(
        'tipos_llamado',
        sa.column('nombre', sa.String),
        sa.column('slug', sa.String),
        sa.column('descripcion', sa.Text),
        sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime),
    )
    bind = op.get_bind()
    existe = sa.exists().where((tipos.c.slug == 'interno') | (tipos.c.nombre == 'Interno'))
    if bind.scalar(sa.select(existe)):
        return

    bind.execute(tipos.insert().values(
        nombre='Interno',
        slug='interno',
        descripcion='Convocatorias dirigidas al personal que cumpla las condiciones de las bases.',
        is_active=True,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    ))


def downgrade():
    # El tipo puede formar parte de llamados creados después de la migración.
    pass
