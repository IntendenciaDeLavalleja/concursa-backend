"""prevent duplicate postulaciones per concurso

Revision ID: b7a1c9d4e2f3
Revises: 6b9f4bb6e7f1
Create Date: 2026-05-20 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7a1c9d4e2f3'
down_revision = '6b9f4bb6e7f1'
branch_labels = None
depends_on = None


def upgrade():
    constraints = {
        'uq_postulaciones_concurso_documento': 'documento',
        'uq_postulaciones_concurso_email': 'email',
    }
    existing = set()
    if not op.get_context().as_sql:
        connection = op.get_bind()
        existing = {
            constraint['name']
            for constraint in sa.inspect(connection).get_unique_constraints('postulaciones')
        }
        postulaciones = sa.table(
            'postulaciones', sa.column('concurso_id'), sa.column('documento'), sa.column('email'),
        )
        # MariaDB confirma cada ALTER por separado. Validar ambos campos antes de aplicar el primero.
        for column in constraints.values():
            value = postulaciones.c[column]
            duplicates = (
                sa.select(1).where(value.is_not(None))
                .group_by(postulaciones.c.concurso_id, value)
                .having(sa.func.count() > 1).limit(1)
            )
            if connection.scalar(duplicates) is not None:
                raise RuntimeError(
                    f'Hay postulaciones con {column} repetido dentro de un mismo concurso. '
                    'Revisá esos registros antes de volver a ejecutar la migración.'
                )

    # Una ejecución anterior pudo haber aplicado solo una de las restricciones.
    with op.batch_alter_table('postulaciones', schema=None) as batch_op:
        for name, column in constraints.items():
            if name not in existing:
                batch_op.create_unique_constraint(name, ['concurso_id', column])


def downgrade():
    with op.batch_alter_table('postulaciones', schema=None) as batch_op:
        batch_op.drop_constraint(
            'uq_postulaciones_concurso_email',
            type_='unique',
        )
        batch_op.drop_constraint(
            'uq_postulaciones_concurso_documento',
            type_='unique',
        )
