"""Agregar llamados a oferentes, documentos, ofertas y etapas.

Revision ID: c0439fc8d622
Revises: b7a1c9d4e2f3
"""

from alembic import op
import sqlalchemy as sa


revision = 'c0439fc8d622'
down_revision = 'b7a1c9d4e2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'licitaciones',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('codigo', sa.String(length=60), nullable=False, unique=True),
        sa.Column('slug', sa.String(length=180), nullable=False, unique=True),
        sa.Column('titulo', sa.String(length=250), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=False),
        sa.Column('unidad_compradora', sa.String(length=200), nullable=False),
        sa.Column('criterios_evaluacion', sa.Text(), nullable=False),
        sa.Column('modalidad_recepcion', sa.String(length=15), nullable=False),
        sa.Column('url_oficial', sa.String(length=600), nullable=True),
        sa.Column('recepcion_desde', sa.DateTime(), nullable=True),
        sa.Column('recepcion_hasta', sa.DateTime(), nullable=True),
        sa.Column('apertura_programada', sa.DateTime(), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('publicado_en', sa.DateTime(), nullable=True),
        sa.Column('abierta_en', sa.DateTime(), nullable=True),
        sa.Column('resultado', sa.String(length=15), nullable=True),
        sa.Column('resultado_detalle', sa.Text(), nullable=True),
        sa.Column('referencia_resolucion', sa.String(length=240), nullable=True),
        sa.Column('oferta_adjudicada_id', sa.Integer(), nullable=True),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.Column('actualizada_en', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_licitaciones_publicado_en', 'licitaciones', ['publicado_en'])
    op.create_table(
        'licitaciones_documentos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('licitacion_id', sa.Integer(), sa.ForeignKey('licitaciones.id'), nullable=False),
        sa.Column('tipo', sa.String(length=25), nullable=False),
        sa.Column('titulo', sa.String(length=180), nullable=False),
        sa.Column('archivo_key', sa.String(length=500), nullable=False),
        sa.Column('nombre_archivo', sa.String(length=255), nullable=False),
        sa.Column('publicado_en', sa.DateTime(), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_licitaciones_documentos_licitacion_id', 'licitaciones_documentos', ['licitacion_id'])
    op.create_table(
        'licitaciones_eventos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('licitacion_id', sa.Integer(), sa.ForeignKey('licitaciones.id'), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('titulo', sa.String(length=180), nullable=True),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('admin_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('fecha', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_licitaciones_eventos_licitacion_id', 'licitaciones_eventos', ['licitacion_id'])
    op.create_table(
        'licitaciones_ofertas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('licitacion_id', sa.Integer(), sa.ForeignKey('licitaciones.id'), nullable=False),
        sa.Column('origen', sa.String(length=15), nullable=False),
        sa.Column('razon_social', sa.String(length=200), nullable=False),
        sa.Column('identificacion_fiscal', sa.String(length=32), nullable=False),
        sa.Column('contacto_nombre', sa.String(length=150), nullable=True),
        sa.Column('contacto_email', sa.String(length=254), nullable=True),
        sa.Column('contacto_telefono', sa.String(length=40), nullable=True),
        sa.Column('monto_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('moneda', sa.String(length=3), nullable=False),
        sa.Column('referencia_externa', sa.String(length=240), nullable=True),
        sa.Column('codigo_hash', sa.String(length=64), nullable=True, unique=True),
        sa.Column('evaluacion', sa.JSON(), nullable=False),
        sa.Column('recibida_en', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('licitacion_id', 'referencia_externa', name='uq_licitacion_referencia_externa'),
    )
    op.create_index('ix_licitaciones_ofertas_licitacion_id', 'licitaciones_ofertas', ['licitacion_id'])
    op.create_table(
        'licitaciones_ofertas_adjuntos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('oferta_id', sa.Integer(), sa.ForeignKey('licitaciones_ofertas.id'), nullable=False),
        sa.Column('tipo', sa.String(length=12), nullable=False),
        sa.Column('nombre_archivo', sa.String(length=255), nullable=False),
        sa.Column('archivo_key', sa.String(length=500), nullable=False),
    )
    op.create_index('ix_licitaciones_ofertas_adjuntos_oferta_id', 'licitaciones_ofertas_adjuntos', ['oferta_id'])
    with op.batch_alter_table('licitaciones') as batch:
        batch.create_foreign_key('fk_licitaciones_oferta_adjudicada', 'licitaciones_ofertas', ['oferta_adjudicada_id'], ['id'])


def downgrade():
    with op.batch_alter_table('licitaciones') as batch:
        batch.drop_constraint('fk_licitaciones_oferta_adjudicada', type_='foreignkey')
    op.drop_table('licitaciones_ofertas_adjuntos')
    op.drop_table('licitaciones_ofertas')
    op.drop_table('licitaciones_eventos')
    op.drop_table('licitaciones_documentos')
    op.drop_table('licitaciones')
