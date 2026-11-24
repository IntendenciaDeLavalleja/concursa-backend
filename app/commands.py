# flake8: noqa
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models.user import AdminUser
from app.seeders.concurso_seed import preparar_catalogos_concursos, seed_concursos as seed_concursos_service


@click.command('create-admin')
@click.argument('username')
@click.argument('email')
@click.argument('password', required=False)
@click.argument('is_superuser', default='false')
@click.option('--super-admin', is_flag=True, help='Asigna el rol de Super Admin.')
@with_appcontext
def create_admin(username, email, password, is_superuser, super_admin):
    """Crea un usuario administrador."""
    if password is None:
        password = click.prompt('Contraseña', hide_input=True, confirmation_prompt=True)
    is_super = super_admin or is_superuser.lower() == 'true'
    user = AdminUser(username=username, email=email, is_superuser=is_super)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    role = "Super Administrador" if is_super else "Administrador"
    print(f"{role} '{username}' creado exitosamente.")


@click.command('init-db')
@with_appcontext
def init_db():
    """Inicializa / actualiza las tablas de la base de datos."""
    db.create_all()
    print("Base de datos inicializada.")


@click.command('init-catalogos-concursos')
@click.option('--sin-tipos-de-llamado', is_flag=True, help='Carga únicamente las áreas y los tipos de vínculo.')
@with_appcontext
def init_catalogos_concursos(sin_tipos_de_llamado):
    """Carga los catálogos institucionales para crear llamados."""
    preparar_catalogos_concursos(incluir_tipos_llamado=not sin_tipos_de_llamado)
    db.session.commit()
    click.echo('Catálogos de concursos disponibles.')


@click.command('seed-concursos')
@click.option('--reset', is_flag=True, help='Elimina primero los concursos de prueba cargados por este seed.')
@with_appcontext
def seed_concursos(reset=False):
    """Siembra datos de ejemplo para concursos y catálogos asociados."""
    summary = seed_concursos_service(reset=reset)
    print(f"Concursos creados: {summary['concursos_creados']}")
    print(f"Postulaciones creadas: {summary['postulaciones_creadas']}")
    print("Por estado:")
    for estado, total in summary['por_estado'].items():
        print(f"- {estado}: {total}")
    print("Por tipo de llamado:")
    for tipo, total in summary['por_tipo_llamado'].items():
        print(f"- {tipo}: {total}")
    print("Por tipo de contratación:")
    for tipo, total in summary['por_tipo'].items():
        print(f"- {tipo}: {total}")


# Backwards-compat stub
@click.command('archive-expired-pre-reservations')
@with_appcontext
def archive_expired_pre_reservations_command():
    """(Stub) Este comando ya no aplica."""
    print("Este comando fue removido.")
