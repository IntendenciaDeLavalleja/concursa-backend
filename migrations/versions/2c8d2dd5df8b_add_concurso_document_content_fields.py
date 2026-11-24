"""add concurso document content fields

Revision ID: 2c8d2dd5df8b
Revises: ee11d6aedaf1
Create Date: 2026-05-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2c8d2dd5df8b'
down_revision = 'ee11d6aedaf1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('concursos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bases_concurso_html', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('bases_llamado_html', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('anexo_declaracion_jurada_html', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('concursos', schema=None) as batch_op:
        batch_op.drop_column('anexo_declaracion_jurada_html')
        batch_op.drop_column('bases_llamado_html')
        batch_op.drop_column('bases_concurso_html')