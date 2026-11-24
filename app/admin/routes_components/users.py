from email_validator import EmailNotValidError, validate_email
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db, limiter
from app.models.user import AdminUser, TwoFactorCode
from app.utils.logging_helper import log_activity
from .. import admin_bp


ROLES = {
    'admin': 'Administrador',
    'super_admin': 'Super Admin',
}


def _usuario_gestionado(usuario_id):
    if not current_user.is_superuser:
        abort(403)

    if request.method != 'POST':
        return db.get_or_404(AdminUser, usuario_id) if usuario_id is not None else None

    # Bloquear al gestor y a la cuenta afectada en el mismo orden para revalidar el acceso.
    gestor_id = current_user.id
    ids = (gestor_id,) if usuario_id is None else (gestor_id, usuario_id)
    consulta = (
        select(AdminUser).where(AdminUser.id.in_(ids)).order_by(AdminUser.id)
        .with_for_update().execution_options(populate_existing=True)
    )
    usuarios = {usuario.id: usuario for usuario in db.session.scalars(consulta)}
    gestor = usuarios.get(gestor_id)
    if gestor is None or not gestor.is_active or not gestor.is_superuser:
        abort(403)
    if usuario_id is not None and usuario_id not in usuarios:
        abort(404)
    return usuarios.get(usuario_id)


def _guardar_usuario(datos, password, usuario):
    creando = usuario is None
    cambia_correo = creando or datos['email'] != usuario.email
    errores = {}
    nombre = datos['username']
    rol = datos['role']
    correo = datos['email']

    if (creando or nombre != usuario.username) and not 2 <= len(nombre) <= 64:
        errores['username'] = 'Ingresá un nombre de usuario de entre 2 y 64 caracteres.'

    if cambia_correo:
        try:
            correo = validate_email(correo, check_deliverability=False).normalized.lower()
            if len(correo) > 120:
                errores['email'] = 'El correo admite hasta 120 caracteres.'
        except EmailNotValidError:
            errores['email'] = 'Ingresá un correo electrónico válido.'

    if rol not in ROLES:
        errores['role'] = 'Elegí un rol válido.'
    elif not creando and usuario.id == current_user.id and rol != 'super_admin':
        errores['role'] = 'Tu cuenta requiere el rol de Super Admin.'

    if creando or password:
        if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            errores['password'] = 'Usá al menos 8 caracteres, con una letra y un número.'
        elif password != password.strip():
            errores['password'] = 'Quitá los espacios al principio o al final de la contraseña.'

    if errores:
        return errores

    if cambia_correo:
        consulta = select(AdminUser.id).where(func.lower(AdminUser.email) == correo).limit(1)
        if not creando:
            consulta = consulta.where(AdminUser.id != usuario.id)
        if db.session.scalar(consulta) is not None:
            return {'email': 'Ya existe un usuario con ese correo electrónico.'}

    es_superuser = rol == 'super_admin'
    if creando:
        usuario = AdminUser(is_active=True)
        db.session.add(usuario)
    invalidar_codigos = not creando and (
        correo != usuario.email or bool(password) or es_superuser != usuario.is_superuser
    )
    usuario.username = nombre
    usuario.email = correo
    usuario.is_superuser = es_superuser
    if password:
        usuario.set_password(password)

    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return {'general': 'Ya existe un usuario con ese nombre o correo.'}

    if invalidar_codigos:
        db.session.execute(delete(TwoFactorCode).where(
            TwoFactorCode.user_id == usuario.id,
            TwoFactorCode.consumed_at.is_(None),
        ))

    accion = 'ADMIN_USER_CREATE' if creando else 'ADMIN_USER_UPDATE'
    detalle = f'Usuario #{usuario.id} ({usuario.username}). Rol {ROLES[rol]}.'
    log_activity(accion, detalle, commit=False)
    db.session.commit()
    return {}


@admin_bp.route('/users', methods=['GET', 'POST'])
@admin_bp.route('/users/<int:usuario_id>/edit', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per hour', methods=['POST'])
def users(usuario_id=None):
    usuario = _usuario_gestionado(usuario_id)
    datos = {
        'username': usuario.username if usuario is not None else '',
        'email': usuario.email if usuario is not None else '',
        'role': 'super_admin' if usuario is not None and usuario.is_superuser else 'admin',
    }
    errores = {}
    if request.method == 'POST':
        datos = {
            'username': request.form.get('username', '').strip(),
            'email': request.form.get('email', '').strip(),
            'role': request.form.get('role', datos['role']),
        }
        errores = _guardar_usuario(datos, request.form.get('password', ''), usuario)
        if not errores:
            flash('Usuario actualizado.' if usuario is not None else 'Usuario creado.', 'success')
            return redirect(url_for('admin.users'))

    pagination = db.paginate(
        select(AdminUser).order_by(AdminUser.username, AdminUser.id),
        per_page=20,
        error_out=False,
    )
    return render_template(
        'admin/users.html',
        pagination=pagination,
        roles=ROLES,
        datos=datos,
        errores=errores,
        usuario_editado=usuario,
    ), 422 if errores else 200, {'Cache-Control': 'no-store'}


@admin_bp.route('/users/<int:usuario_id>/delete', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per hour', methods=['POST'])
def user_delete(usuario_id):
    usuario = _usuario_gestionado(usuario_id)
    if usuario.id == current_user.id:
        abort(403)

    if request.method != 'POST':
        return render_template('admin/user_delete.html', usuario=usuario), 200, {'Cache-Control': 'no-store'}

    if request.form.get('confirmar') != '1':
        abort(400, description='Confirmá la eliminación del usuario.')

    nombre = usuario.username
    log_activity('ADMIN_USER_DELETE', f'Usuario #{usuario.id} ({nombre}).', commit=False)
    db.session.delete(usuario)
    db.session.commit()
    flash(f'Se eliminó el usuario «{nombre}».', 'success')
    return redirect(url_for('admin.users'))
