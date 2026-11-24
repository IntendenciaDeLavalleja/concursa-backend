"""Administración de los catálogos que usan los llamados públicos."""

from dataclasses import dataclass
from functools import wraps

from flask import abort, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.concurso import AreaConvocante, Concurso, TipoContratacion, TipoLlamado
from app.models.user import AdminUser
from app.utils.logging_helper import log_activity
from .. import admin_bp


@dataclass(frozen=True)
class CatalogoConcurso:
    modelo: type[AreaConvocante] | type[TipoContratacion] | type[TipoLlamado]
    campo: str
    titulo: str
    nuevo: str
    evento: str

    @property
    def limite_nombre(self):
        return self.modelo.nombre.type.length


CATALOGOS_CONCURSOS = {
    'areas': CatalogoConcurso(AreaConvocante, 'area_convocante_id', 'Áreas convocantes', 'Nueva área convocante', 'AREA_CONVOCANTE'),
    'tipos-vinculo': CatalogoConcurso(TipoContratacion, 'tipo_contratacion_id', 'Tipos de vínculo', 'Nuevo tipo de vínculo', 'TIPO_CONTRATACION'),
    'tipos-llamado': CatalogoConcurso(TipoLlamado, 'tipo_llamado_id', 'Clasificaciones de llamado', 'Nueva clasificación de llamado', 'TIPO_LLAMADO'),
}

_CLAVES_CATALOGO = ','.join(repr(clave) for clave in CATALOGOS_CONCURSOS)
_RUTA_CATALOGO = f'/concursos/<any({_CLAVES_CATALOGO}):catalogo>'


def _solo_super_admin(vista):
    @login_required
    @wraps(vista)
    def comprobar_acceso(*args, **kwargs):
        if not current_user.is_superuser:
            abort(403)
        if request.method == 'POST':
            gestor = db.session.get(AdminUser, current_user.id, with_for_update=True, populate_existing=True)
            if gestor is None or not gestor.is_active or not gestor.is_superuser:
                abort(403)

        respuesta = make_response(vista(*args, **kwargs))
        respuesta.headers['Cache-Control'] = 'private, no-store'
        return respuesta

    return comprobar_acceso


def _guardar_opcion(catalogo, opcion, nombre, descripcion):
    modelo = catalogo.modelo
    duplicado_aviso = (
        'Ya existe una clasificación con ese nombre o con el mismo slug.'
        if modelo is TipoLlamado else 'Ya existe una opción con ese nombre en este catálogo.'
    )
    if not nombre:
        raise ValueError('Ingresá un nombre.')
    if len(nombre) > catalogo.limite_nombre:
        raise ValueError(f'El nombre admite hasta {catalogo.limite_nombre} caracteres.')
    if descripcion and len(descripcion.encode('utf-8')) > 65535:
        raise ValueError('La descripción es demasiado larga.')

    coincide = func.lower(modelo.nombre) == nombre.lower()
    if modelo is TipoLlamado and opcion.id is None:
        slug = TipoLlamado.generate_slug(nombre)
        if not slug:
            raise ValueError('Ingresá un nombre con letras o números para generar el slug de la clasificación.')
        opcion.slug = slug
        coincide = or_(coincide, modelo.slug == slug)

    duplicado = select(modelo.id).where(coincide)
    if opcion.id is not None:
        duplicado = duplicado.where(modelo.id != opcion.id)
    if db.session.scalar(duplicado) is not None:
        raise ValueError(duplicado_aviso)

    opcion.nombre = nombre
    opcion.descripcion = descripcion
    db.session.add(opcion)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValueError(duplicado_aviso) from exc


def _renderizar_catalogo(clave, opcion, nombre='', descripcion='', error=None):
    catalogo = CATALOGOS_CONCURSOS[clave]
    modelo = catalogo.modelo
    uso = (
        select(func.count(Concurso.id))
        .where(getattr(Concurso, catalogo.campo) == modelo.id)
        .scalar_subquery()
    )
    opciones = db.session.execute(select(modelo, uso).order_by(modelo.nombre)).all()
    return render_template(
        'admin/catalogos_concursos.html',
        clave_catalogo=clave,
        catalogo=catalogo,
        catalogos=CATALOGOS_CONCURSOS,
        opciones=opciones,
        editando=opcion,
        nombre=nombre,
        descripcion=descripcion,
        error=error,
    )


@admin_bp.route(_RUTA_CATALOGO, methods=['GET', 'POST'])
@_solo_super_admin
def catalogos_concursos(catalogo):
    config = CATALOGOS_CONCURSOS[catalogo]
    modelo = config.modelo

    if request.method == 'POST':
        opcion_id = request.form.get(config.campo, type=int)
        opcion = db.get_or_404(modelo, opcion_id) if opcion_id is not None else modelo()
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        respuesta_json = request.accept_mimetypes.best_match(['text/html', 'application/json']) == 'application/json'
        try:
            _guardar_opcion(config, opcion, nombre, descripcion or None)
        except ValueError as exc:
            if respuesta_json:
                return jsonify(mensaje=str(exc)), 422
            return _renderizar_catalogo(catalogo, opcion, nombre, descripcion, error=str(exc)), 422

        log_activity(f'{config.evento}_SAVE', f'Opción guardada: «{opcion.nombre}» (#{opcion.id})')
        if respuesta_json:
            return jsonify(opcion.to_dict()), 200 if opcion_id is not None else 201
        flash(f'Se guardó «{opcion.nombre}».', 'success')
        return redirect(url_for('admin.catalogos_concursos', catalogo=catalogo))

    opcion_id = request.args.get('edit', type=int)
    if opcion_id is None:
        return _renderizar_catalogo(catalogo, None)

    opcion = db.get_or_404(modelo, opcion_id)
    return _renderizar_catalogo(catalogo, opcion, opcion.nombre, opcion.descripcion or '')


@admin_bp.post(f'{_RUTA_CATALOGO}/<int:opcion_id>/toggle')
@_solo_super_admin
def catalogo_concurso_toggle(catalogo, opcion_id):
    config = CATALOGOS_CONCURSOS[catalogo]
    opcion = db.get_or_404(config.modelo, opcion_id)
    opcion.is_active = not opcion.is_active
    db.session.commit()
    accion = 'activó' if opcion.is_active else 'desactivó'
    log_activity(f'{config.evento}_TOGGLE', f'Se {accion} «{opcion.nombre}» (#{opcion_id})')
    flash(f'Se {accion} «{opcion.nombre}».', 'success')
    return redirect(url_for('admin.catalogos_concursos', catalogo=catalogo))


def _eliminar_opcion(config, opcion_id, reemplazo):
    modelo = config.modelo
    sin_clasificacion = reemplazo == 'sin-clasificacion' and modelo is TipoLlamado
    reemplazo_id = None
    if reemplazo and not sin_clasificacion:
        try:
            reemplazo_id = int(reemplazo)
        except ValueError as exc:
            raise ValueError('Elegí otra opción activa de este catálogo.') from exc
        if reemplazo_id == opcion_id or not 0 < reemplazo_id <= 2_147_483_647:
            raise ValueError('Elegí otra opción activa de este catálogo.')

    # Bloquear ambas opciones por ID para ordenar las reasignaciones concurrentes.
    ids = [opcion_id] if reemplazo_id is None else [opcion_id, reemplazo_id]
    consulta = select(modelo).where(modelo.id.in_(ids)).order_by(modelo.id).with_for_update()
    opciones = {opcion.id: opcion for opcion in db.session.scalars(consulta)}
    origen = opciones.get(opcion_id)
    if origen is None:
        abort(404)
    destino = opciones.get(reemplazo_id)
    if reemplazo_id is not None and (destino is None or not destino.is_active):
        raise ValueError('Elegí otra opción activa de este catálogo.')

    reasignados = 0
    if destino is not None or sin_clasificacion:
        campo = getattr(Concurso, config.campo)
        valores = {config.campo: reemplazo_id}
        if modelo is AreaConvocante:
            # Conservar descripciones históricas de dependencia distintas al nombre del área.
            valores['dependencia'] = case(
                (Concurso.dependencia == origen.nombre, destino.nombre), else_=Concurso.dependencia,
            )
        actualizar = Concurso.__table__.update().where(campo == origen.id).values(**valores)
        reasignados = db.session.execute(actualizar).rowcount

    nombre = origen.nombre
    eliminar = modelo.__table__.delete().where(modelo.id == origen.id, ~modelo.concursos.any())
    if db.session.execute(eliminar).rowcount != 1:
        raise ValueError('La opción tiene llamados asociados. Elegí cómo reasignarlos antes de eliminarla.')

    detalle = f'Opción eliminada: «{nombre}» (#{opcion_id}).'
    if reasignados:
        asignacion = 'sin clasificación' if sin_clasificacion else f'a «{destino.nombre}» (#{destino.id})'
        detalle += f' Llamados reasignados {asignacion}: {reasignados}.'
    log_activity(f'{config.evento}_DELETE', detalle, commit=False)
    db.session.commit()
    return nombre, reasignados


@admin_bp.post(f'{_RUTA_CATALOGO}/<int:opcion_id>/eliminar')
@_solo_super_admin
def catalogo_concurso_eliminar(catalogo, opcion_id):
    listado = url_for('admin.catalogos_concursos', catalogo=catalogo)
    if request.form.get('confirmar') != '1':
        flash('Confirmá la eliminación desde el catálogo.', 'error')
        return redirect(listado)

    try:
        nombre, reasignados = _eliminar_opcion(
            CATALOGOS_CONCURSOS[catalogo], opcion_id, request.form.get('reemplazo', ''),
        )
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    except IntegrityError:
        db.session.rollback()
        flash('No se pudo eliminar la opción. Revisá las asociaciones y volvé a intentar.', 'error')
    else:
        mensaje = f'Se eliminó «{nombre}».'
        if reasignados == 1:
            mensaje += ' Se actualizó 1 llamado asociado.'
        elif reasignados:
            mensaje += f' Se actualizaron {reasignados} llamados asociados.'
        flash(mensaje, 'success')

    return redirect(listado)
