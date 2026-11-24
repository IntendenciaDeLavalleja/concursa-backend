"""add licitacion ai reports

Revision ID: f6f7a2ac09d1
Revises: c0439fc8d622
"""

from alembic import op
import sqlalchemy as sa


revision = 'f6f7a2ac09d1'
down_revision = 'c0439fc8d622'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'licitacion_informes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('licitacion_id', sa.Integer(), nullable=False),
        sa.Column('estado', sa.String(length=16), nullable=False),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('resumen_interno', sa.Text(), nullable=False),
        sa.Column('hallazgos', sa.JSON(), nullable=False),
        sa.Column('limitaciones', sa.JSON(), nullable=False),
        sa.Column('fuentes', sa.JSON(), nullable=False),
        sa.Column('huella_fuentes', sa.String(length=64), nullable=False),
        sa.Column('modelo', sa.String(length=160), nullable=False),
        sa.Column('version_prompt', sa.String(length=16), nullable=False),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('creado_por_id', sa.Integer()),
        sa.Column('publicado_en', sa.DateTime()),
        sa.Column('publicado_por_id', sa.Integer()),
        sa.Column('titulo_publico', sa.String(length=160)),
        sa.Column('resumen_publico', sa.Text()),
        sa.ForeignKeyConstraint(['licitacion_id'], ['licitaciones.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['creado_por_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['publicado_por_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_licitacion_informes_licitacion_id', 'licitacion_informes', ['licitacion_id'])


def downgrade():
    op.drop_index('ix_licitacion_informes_licitacion_id', table_name='licitacion_informes')
    op.drop_table('licitacion_informes')
