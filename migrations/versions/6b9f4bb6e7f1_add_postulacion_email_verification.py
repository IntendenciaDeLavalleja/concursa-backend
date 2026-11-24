"""add postulacion email verification

Revision ID: 6b9f4bb6e7f1
Revises: 28d30b783403
Create Date: 2026-05-20 18:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b9f4bb6e7f1'
down_revision = '28d30b783403'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('postulaciones', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verification_uid', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('email_verification_token_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('email_verification_sent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))
        batch_op.alter_column('estado', existing_type=sa.String(length=20), nullable=False, server_default='preinscripta')
        batch_op.create_index(batch_op.f('ix_postulaciones_email_verification_uid'), ['email_verification_uid'], unique=True)


def downgrade():
    with op.batch_alter_table('postulaciones', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_postulaciones_email_verification_uid'))
        batch_op.alter_column('estado', existing_type=sa.String(length=20), nullable=False, server_default='recibida')
        batch_op.drop_column('email_verified_at')
        batch_op.drop_column('email_verification_sent_at')
        batch_op.drop_column('email_verification_token_hash')
        batch_op.drop_column('email_verification_uid')