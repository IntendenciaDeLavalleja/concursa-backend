"""Agrega publicaciones por etapa de concurso.

Revision ID: 73ed98ab48c2
Revises: f6f7a2ac09d1
"""

from alembic import op
import sqlalchemy as sa


revision = '73ed98ab48c2'
down_revision = 'f6f7a2ac09d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'concurso_actualizaciones',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('concurso_id', sa.Integer(), sa.ForeignKey('concursos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('etapa', sa.String(length=32), nullable=False),
        sa.Column('titulo', sa.String(length=200), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('pdf_key', sa.String(length=500), nullable=True),
        sa.Column('publicada', sa.Boolean(), nullable=False),
    )
    op.create_index('ix_concurso_actualizaciones_concurso_id', 'concurso_actualizaciones', ['concurso_id'])


def downgrade():
    op.drop_index('ix_concurso_actualizaciones_concurso_id', table_name='concurso_actualizaciones')
    op.drop_table('concurso_actualizaciones')
