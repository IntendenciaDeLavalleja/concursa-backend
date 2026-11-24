"""add tipo llamado to concursos

Revision ID: 7d4b5f4fd2a1
Revises: 2c8d2dd5df8b
Create Date: 2026-05-20 00:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d4b5f4fd2a1'
down_revision = '2c8d2dd5df8b'
branch_labels = None
depends_on = None


TIPOS_LLAMADO = [
    ('Función Pública', 'funcion-publica', 'Llamados para ingreso o cobertura de cargos dentro de la estructura funcional departamental.'),
    ('Zafral', 'zafral', 'Llamados orientados a tareas temporales, de temporada o refuerzo operativo puntual.'),
    ('Arrendamiento de Obra', 'arrendamiento-de-obra', 'Llamados para contratación por obra, proyecto o entregables definidos.'),
    ('Pasantía', 'pasantia', 'Llamados de carácter formativo para estudiantes o perfiles de inicio profesional.'),
    ('Beca', 'beca', 'Llamados de apoyo formativo o inserción inicial vinculados a becas institucionales.'),
    ('Contrato Temporal', 'contrato-temporal', 'Llamados para vínculos temporales distintos de la estructura permanente.'),
]

MAPEO_POR_TIPO_CONTRATACION = {
    'Contrato de Función Pública': 'funcion-publica',
    'Zafral': 'zafral',
    'Arrendamiento de Obra': 'arrendamiento-de-obra',
    'Pasantía': 'pasantia',
    'Beca': 'beca',
}


def upgrade():
    op.create_table(
        'tipos_llamado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('slug', sa.String(length=180), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nombre'),
        sa.UniqueConstraint('slug'),
    )

    with op.batch_alter_table('tipos_llamado', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tipos_llamado_slug'), ['slug'], unique=True)

    with op.batch_alter_table('concursos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo_llamado_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_concursos_tipo_llamado_id'), ['tipo_llamado_id'], unique=False)
        batch_op.create_foreign_key('fk_concursos_tipo_llamado_id', 'tipos_llamado', ['tipo_llamado_id'], ['id'])

    bind = op.get_bind()
    now = datetime.utcnow()

    tipos_llamado = sa.table(
        'tipos_llamado',
        sa.column('id', sa.Integer),
        sa.column('nombre', sa.String),
        sa.column('slug', sa.String),
        sa.column('descripcion', sa.Text),
        sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime),
    )
    tipos_contratacion = sa.table(
        'tipos_contratacion',
        sa.column('id', sa.Integer),
        sa.column('nombre', sa.String),
    )
    concursos = sa.table(
        'concursos',
        sa.column('id', sa.Integer),
        sa.column('tipo_contratacion_id', sa.Integer),
        sa.column('tipo_llamado_id', sa.Integer),
    )

    op.bulk_insert(
        tipos_llamado,
        [
            {
                'nombre': nombre,
                'slug': slug,
                'descripcion': descripcion,
                'is_active': True,
                'created_at': now,
            }
            for nombre, slug, descripcion in TIPOS_LLAMADO
        ],
    )

    tipos_llamado_rows = bind.execute(sa.select(tipos_llamado.c.id, tipos_llamado.c.slug)).fetchall()
    tipos_por_slug = {row.slug: row.id for row in tipos_llamado_rows}
    tipos_contratacion_rows = bind.execute(sa.select(tipos_contratacion.c.id, tipos_contratacion.c.nombre)).fetchall()
    slugs_por_tipo_contratacion_id = {
        row.id: MAPEO_POR_TIPO_CONTRATACION.get(row.nombre)
        for row in tipos_contratacion_rows
    }

    concursos_rows = bind.execute(sa.select(concursos.c.id, concursos.c.tipo_contratacion_id)).fetchall()
    for row in concursos_rows:
        slug = slugs_por_tipo_contratacion_id.get(row.tipo_contratacion_id)
        tipo_llamado_id = tipos_por_slug.get(slug)
        if tipo_llamado_id:
            bind.execute(
                concursos.update().where(concursos.c.id == row.id).values(tipo_llamado_id=tipo_llamado_id)
            )


def downgrade():
    with op.batch_alter_table('concursos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_concursos_tipo_llamado_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_concursos_tipo_llamado_id'))
        batch_op.drop_column('tipo_llamado_id')

    with op.batch_alter_table('tipos_llamado', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tipos_llamado_slug'))

    op.drop_table('tipos_llamado')