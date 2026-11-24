"""Gestión de contenidos documentales de concursos en el panel admin."""

import csv
import json
from datetime import date, datetime, timedelta
from io import StringIO
import bleach
from flask import Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.concurso import (
    AreaConvocante,
    CONCURSO_TIMEZONE,
    Concurso,
    ConcursoActualizacion,
    Postulacion,
    TipoContratacion,
    TipoLlamado,
    ahora_en_uruguay,
)
from app.services.minio_service import minio_service
from app.services.concurso_documents import descargar_pdf_concurso
from app.utils.logging_helper import log_activity
from .. import admin_bp
from .catalogos_concursos import CATALOGOS_CONCURSOS


_ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 's', 'blockquote',
    'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'a',
]
_ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
}
_SLUGS_RESERVADOS = {'areas', 'destacados', 'estadisticas', 'postulaciones', 'tipos-contratacion', 'tipos-llamado'}
_SLUG_DUPLICADO = 'Este slug ya está en uso. Elegí otro.'


class SlugConcursoError(ValueError):
    pass


def _normalize_rich_html(value: str):
    cleaned = bleach.clean(
        (value or '').strip(),
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=['http', 'https', 'mailto'],
        strip=True,
    ).strip()

    if not cleaned:
        return None

    plain_text = bleach.clean(cleaned, tags=[], strip=True).strip()
    return cleaned if plain_text else None


def _datetime_local_value(value):
    if not value:
        return ''
    return value.strftime('%Y-%m-%dT%H:%M')


def _timeline_form_value(source, concurso=None):
    if source and 'timeline_json' in source:
        return (source.get('timeline_json') or '').strip()
    return (concurso.timeline_json or '').strip() if concurso else ''


def _normalize_timeline_json(raw_value: str):
    raw_value = (raw_value or '').strip()
    if not raw_value:
        return None

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError('El cronograma no tiene un formato JSON válido.') from exc

    if not isinstance(parsed, list):
        raise ValueError('El cronograma debe ser una lista de hitos.')

    normalized_items = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError('Cada hito del cronograma debe ser un objeto válido.')

        fecha = str(item.get('fecha') or '').strip()
        titulo = str(item.get('titulo') or '').strip()
        descripcion = str(item.get('descripcion') or '').strip() or None
        completado = bool(item.get('completado'))

        if not fecha or not titulo:
            raise ValueError(
                'Cada hito del cronograma debe incluir fecha y título.'
            )

        normalized_items.append(
            {
                'fecha': fecha,
                'titulo': titulo,
                'descripcion': descripcion,
                'completado': completado,
            }
        )

    return json.dumps(normalized_items, ensure_ascii=False)


def _parse_filter_date(raw_value: str):
    value = (raw_value or '').strip()
    if not value:
        return None

    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def _read_postulaciones_filters():
    estado_filtro = (request.args.get('estado') or '').strip()
    search = (request.args.get('q') or '').strip()
    area_convocante_id = request.args.get('area_convocante_id', 0, type=int)
    concurso_id = request.args.get('concurso_id', 0, type=int)
    tipo_contratacion_id = (
        request.args.get('tipo_contratacion_id') or ''
    ).strip()
    fecha_desde = (request.args.get('fecha_desde') or '').strip()
    fecha_hasta = (request.args.get('fecha_hasta') or '').strip()

    return {
        'estado_filtro': estado_filtro,
        'search': search,
        'area_convocante_id': area_convocante_id if area_convocante_id > 0 else None,
        'concurso_id': concurso_id if area_convocante_id > 0 and concurso_id > 0 else None,
        'tipo_contratacion_id': (
            tipo_contratacion_id if tipo_contratacion_id.isdigit() else ''
        ),
        'fecha_desde': fecha_desde if _parse_filter_date(fecha_desde) else '',
        'fecha_hasta': fecha_hasta if _parse_filter_date(fecha_hasta) else '',
    }


def _build_postulaciones_query(filters):
    query = Postulacion.query.join(Concurso)
    estado_filtro = filters['estado_filtro']
    search = filters['search']
    area_convocante_id = filters['area_convocante_id']
    concurso_id = filters['concurso_id']
    tipo_contratacion_id = filters['tipo_contratacion_id']
    fecha_desde = filters['fecha_desde']
    fecha_hasta = filters['fecha_hasta']

    if estado_filtro:
        query = query.filter(Postulacion.estado == estado_filtro)

    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                Postulacion.nombre_completo.ilike(term),
                Postulacion.documento.ilike(term),
                Postulacion.email.ilike(term),
                Postulacion.telefono.ilike(term),
                Concurso.titulo.ilike(term),
            )
        )

    if area_convocante_id:
        query = query.filter(
            Concurso.area_convocante_id == area_convocante_id
        )

    if concurso_id:
        query = query.filter(Postulacion.concurso_id == concurso_id)

    if tipo_contratacion_id:
        query = query.filter(
            Concurso.tipo_contratacion_id == int(tipo_contratacion_id)
        )

    if fecha_desde:
        query = query.filter(
            Postulacion.created_at >= _parse_filter_date(fecha_desde)
        )

    if fecha_hasta:
        query = query.filter(
            Postulacion.created_at
            < _parse_filter_date(fecha_hasta) + timedelta(days=1)
        )

    return query


def _build_form_data(source, concurso=None):
    submitted = source is not None
    source = source or {}
    return {
        'titulo': source.get('titulo', concurso.titulo if concurso else ''),
        'slug': source.get('slug', concurso.slug if concurso else ''),
        'subtitulo': source.get('subtitulo', concurso.subtitulo if concurso else ''),
        'area_convocante_id': source.get(
            'area_convocante_id',
            concurso.area_convocante_id if concurso else '',
        ),
        'tipo_contratacion_id': source.get(
            'tipo_contratacion_id',
            concurso.tipo_contratacion_id if concurso else '',
        ),
        'tipo_llamado_id': source.get(
            'tipo_llamado_id', concurso.tipo_llamado_id if concurso else ''
        ),
        'estado': source.get(
            'estado', concurso.estado if concurso else Concurso.ESTADO_BORRADOR
        ),
        'cantidad_cargos': source.get(
            'cantidad_cargos', concurso.cantidad_cargos if concurso else 1
        ),
        'remuneracion': source.get(
            'remuneracion', concurso.remuneracion if concurso else ''
        ),
        'localidad': source.get('localidad', concurso.localidad if concurso else ''),
        'fecha_apertura': source.get(
            'fecha_apertura',
            _datetime_local_value(concurso.fecha_apertura) if concurso else '',
        ),
        'fecha_cierre': source.get(
            'fecha_cierre',
            _datetime_local_value(concurso.fecha_cierre) if concurso else '',
        ),
        'fecha_resolucion_estimada': source.get(
            'fecha_resolucion_estimada',
            _datetime_local_value(concurso.fecha_resolucion_estimada)
            if concurso
            else '',
        ),
        'descripcion': source.get(
            'descripcion', concurso.descripcion if concurso else ''
        ),
        'requisitos_excluyentes': source.get(
            'requisitos_excluyentes',
            concurso.requisitos_excluyentes if concurso else '',
        ),
        'requisitos_valorados': source.get(
            'requisitos_valorados',
            concurso.requisitos_valorados if concurso else '',
        ),
        'perfil_buscado': source.get(
            'perfil_buscado', concurso.perfil_buscado if concurso else ''
        ),
        'tareas_funciones': source.get(
            'tareas_funciones', concurso.tareas_funciones if concurso else ''
        ),
        'documentacion_requerida': source.get(
            'documentacion_requerida',
            concurso.documentacion_requerida if concurso else '',
        ),
        'forma_postulacion': source.get(
            'forma_postulacion', concurso.forma_postulacion if concurso else ''
        ),
        'contacto_consulta': source.get(
            'contacto_consulta', concurso.contacto_consulta if concurso else ''
        ),
        'normativa': source.get(
            'normativa', concurso.normativa if concurso else ''
        ),
        'bases_concurso_html': source.get(
            'bases_concurso_html',
            concurso.bases_concurso_html if concurso else '',
        ),
        'bases_llamado_html': source.get(
            'bases_llamado_html', concurso.bases_llamado_html if concurso else ''
        ),
        'anexo_declaracion_jurada_html': source.get(
            'anexo_declaracion_jurada_html',
            concurso.anexo_declaracion_jurada_html if concurso else '',
        ),
        'timeline_json': _timeline_form_value(source, concurso=concurso),
        'postulacion_web_habilitada': (
            source.get('postulacion_web_habilitada', '') if submitted
            else 'on' if concurso and concurso.postulacion_web_habilitada() else ''
        ),
        'requiere_18_anos': (
            source.get('requiere_18_anos', '') if submitted
            else 'on' if concurso is None or concurso.requiere_18_anos else ''
        ),
    }


def _load_legacy_documents(concurso):
    try:
        documents = json.loads(concurso.documentos_json or '[]')
    except (json.JSONDecodeError, TypeError):
        return []
    return documents if isinstance(documents, list) else []


def _set_postulacion_web(concurso, enabled):
    documents = []
    for document in _load_legacy_documents(concurso):
        if not isinstance(document, dict):
            continue
        tipo = str(document.get('tipo') or '').strip().lower()
        nombre = str(document.get('nombre') or '').strip().lower()
        if tipo == 'formulario' or 'formulario' in nombre:
            continue
        documents.append(document)

    if enabled:
        documents.append({
            'nombre': 'Formulario web de postulación',
            'url': '',
            'tipo': 'formulario',
        })

    concurso.documentos_json = json.dumps(documents) if documents else None


def _opciones_catalogo(modelo, id_asignado):
    return db.session.scalars(
        select(modelo)
        .where(or_(modelo.is_active.is_(True), modelo.id == id_asignado))
        .order_by(modelo.nombre)
    ).all()


def _render_concurso_form(concurso=None, form_data=None, slug_error=None):
    opciones = {
        clave: _opciones_catalogo(catalogo.modelo, getattr(concurso, catalogo.campo, None))
        for clave, catalogo in CATALOGOS_CONCURSOS.items()
    }
    return render_template(
        'admin/concurso_edit.html',
        concurso=concurso,
        form_data=form_data or _build_form_data(None, concurso=concurso),
        slug_error=slug_error,
        slug_max_length=Concurso.SLUG_MAX_LENGTH,
        catalogos=CATALOGOS_CONCURSOS,
        opciones=opciones,
    )


def _parse_required_int(raw_value, label):
    raw_value = str(raw_value or '').strip()
    if not raw_value:
        raise ValueError(f'El campo "{label}" es obligatorio.')

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f'El campo "{label}" no es válido.') from exc


def _parse_optional_int(raw_value, label):
    raw_value = str(raw_value or '').strip()
    if not raw_value:
        return None

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f'El campo "{label}" no es válido.') from exc


def _parse_datetime_field(raw_value, label, required=True):
    raw_value = (raw_value or '').strip()
    if not raw_value:
        if required:
            raise ValueError(f'La fecha de {label} es obligatoria.')
        return None

    try:
        value = datetime.fromisoformat(raw_value)
        return value.astimezone(CONCURSO_TIMEZONE).replace(tzinfo=None) if value.tzinfo else value
    except ValueError as exc:
        raise ValueError(
            f'La fecha de {label} no tiene un formato válido.'
        ) from exc


def _slug_en_uso(slug, concurso_id=None):
    query = select(Concurso.id).where(Concurso.slug == slug)
    if concurso_id is not None:
        query = query.where(Concurso.id != concurso_id)
    return db.session.scalar(query) is not None


def _revisar_slug(valor, concurso=None):
    valor = valor.strip()
    if concurso is not None and valor == concurso.slug:
        return valor, None

    slug = Concurso.generate_slug(valor)
    if not slug:
        return slug, 'Ingresá un slug que incluya letras o números.'
    if len(slug) > Concurso.SLUG_MAX_LENGTH:
        return slug, f'El slug admite hasta {Concurso.SLUG_MAX_LENGTH} caracteres.'
    if slug in _SLUGS_RESERVADOS:
        return slug, 'Esta dirección está reservada por el portal. Elegí otro slug.'
    if _slug_en_uso(slug, concurso.id if concurso is not None else None):
        return slug, _SLUG_DUPLICADO
    return slug, None


def _generate_unique_concurso_slug(titulo):
    base_slug = (Concurso.generate_slug(titulo) or 'concurso')[:Concurso.SLUG_MAX_LENGTH].rstrip('-')
    slug = base_slug
    counter = 2

    while slug in _SLUGS_RESERVADOS or _slug_en_uso(slug):
        suffix = f'-{counter}'
        slug = base_slug[:Concurso.SLUG_MAX_LENGTH - len(suffix)].rstrip('-') + suffix
        counter += 1
    return slug


def _sync_uploaded_documents(concurso, uploaded_keys):
    pdf_uploads = [
        ('bases_concurso_pdf', 'Bases del Concurso', 'bases', 'bases_url'),
        ('bases_llamado_pdf', 'Bases del Llamado', 'bases', None),
        ('anexo_pdf', 'Resolución', 'anexo', None),
    ]

    uploaded_files = {
        field: request.files.get(field)
        for field, _nombre, _tipo, _direct_field in pdf_uploads
    }

    documents = []
    for document in _load_legacy_documents(concurso):
        if not isinstance(document, dict):
            continue

        tipo = str(document.get('tipo') or '').strip().lower()
        nombre = str(document.get('nombre') or '').strip().lower()
        if tipo == 'formulario' or 'formulario' in nombre:
            continue
        if (
            tipo == 'bases'
            and 'llamado' in nombre
            and uploaded_files['bases_llamado_pdf']
            and uploaded_files['bases_llamado_pdf'].filename
        ):
            continue
        if (
            (tipo == 'anexo' or 'anexo' in nombre)
            and uploaded_files['anexo_pdf']
            and uploaded_files['anexo_pdf'].filename
        ):
            continue
        documents.append(document)

    for field, nombre, tipo, direct_field in pdf_uploads:
        pdf_file = uploaded_files[field]
        if not pdf_file or not pdf_file.filename:
            continue

        try:
            key = minio_service.upload_document(pdf_file, prefix='concursos/expedientes/')
        except ValueError as exc:
            raise ValueError(f'{nombre}. {exc}') from exc
        uploaded_keys.append(key)
        source = f'minio:{key}'
        if direct_field:
            setattr(concurso, direct_field, source)
        else:
            documents.append({'nombre': nombre, 'url': source, 'tipo': tipo})

    concurso.documentos_json = json.dumps(documents) if documents else None


def _save_concurso_from_form(concurso, form_data, slug, uploaded_keys):
    titulo = (form_data.get('titulo') or '').strip()
    if not titulo:
        raise ValueError('El título de la convocatoria es obligatorio.')
    for field, limit, label in (
        ('titulo', 300, 'El título'), ('subtitulo', 500, 'El subtítulo'),
        ('remuneracion', 200, 'La remuneración'), ('localidad', 200, 'La localidad'),
        ('contacto_consulta', 500, 'El contacto de consultas'),
    ):
        if len((form_data.get(field) or '').strip()) > limit:
            raise ValueError(f'{label} admite hasta {limit} caracteres.')

    area_convocante_id = _parse_required_int(
        form_data.get('area_convocante_id'),
        'Área convocante',
    )
    tipo_contratacion_id = _parse_required_int(
        form_data.get('tipo_contratacion_id'),
        'Tipo de vínculo',
    )
    tipo_llamado_id = _parse_optional_int(
        form_data.get('tipo_llamado_id'),
        'Clasificación de llamado',
    )
    cantidad_cargos = _parse_required_int(
        form_data.get('cantidad_cargos'),
        'Cantidad de vacantes / cargos',
    )
    if cantidad_cargos < 1:
        raise ValueError('La cantidad de vacantes debe ser al menos 1.')

    estado = (form_data.get('estado') or Concurso.ESTADO_BORRADOR).strip()
    if estado not in Concurso.ESTADOS_ADMIN:
        raise ValueError('El estado seleccionado no es válido.')

    area_convocante = db.session.get(AreaConvocante, area_convocante_id)
    if area_convocante is None or (not area_convocante.is_active and area_convocante_id != concurso.area_convocante_id):
        raise ValueError('El área convocante seleccionada no es válida.')

    tipo_contratacion = db.session.get(TipoContratacion, tipo_contratacion_id)
    if tipo_contratacion is None or (not tipo_contratacion.is_active and tipo_contratacion_id != concurso.tipo_contratacion_id):
        raise ValueError('El tipo de vínculo seleccionado no es válido.')

    tipo_llamado = None
    if tipo_llamado_id is not None:
        tipo_llamado = db.session.get(TipoLlamado, tipo_llamado_id)
        if tipo_llamado is None or (not tipo_llamado.is_active and tipo_llamado_id != concurso.tipo_llamado_id):
            raise ValueError('La clasificación de llamado no es válida.')

    fecha_apertura = _parse_datetime_field(
        form_data.get('fecha_apertura'),
        'apertura',
    )
    fecha_cierre = _parse_datetime_field(
        form_data.get('fecha_cierre'),
        'cierre',
    )
    fecha_resolucion_estimada = _parse_datetime_field(
        form_data.get('fecha_resolucion_estimada'),
        'resolución estimada',
        required=False,
    )

    if fecha_cierre <= fecha_apertura:
        raise ValueError(
            'La fecha de cierre debe ser posterior a la fecha de apertura.'
        )

    if (
        fecha_resolucion_estimada is not None
        and fecha_resolucion_estimada < fecha_apertura
    ):
        raise ValueError(
            'La resolución estimada no puede ser anterior a la apertura.'
        )

    timeline_json = _normalize_timeline_json(form_data.get('timeline_json'))

    concurso.slug = slug
    concurso.titulo = titulo
    concurso.subtitulo = (form_data.get('subtitulo') or '').strip() or None
    concurso.estado = estado
    concurso.area_convocante_id = area_convocante.id
    concurso.tipo_contratacion_id = tipo_contratacion.id
    concurso.tipo_llamado_id = tipo_llamado.id if tipo_llamado else None
    concurso.cantidad_cargos = cantidad_cargos
    concurso.remuneracion = (form_data.get('remuneracion') or '').strip() or None
    concurso.localidad = (form_data.get('localidad') or '').strip() or None
    concurso.dependencia = area_convocante.nombre
    concurso.fecha_apertura = fecha_apertura
    concurso.fecha_cierre = fecha_cierre
    concurso.fecha_resolucion_estimada = fecha_resolucion_estimada
    concurso.descripcion = _normalize_rich_html(form_data.get('descripcion')) or ''
    concurso.requisitos_excluyentes = _normalize_rich_html(
        form_data.get('requisitos_excluyentes')
    )
    concurso.requisitos_valorados = _normalize_rich_html(
        form_data.get('requisitos_valorados')
    )
    concurso.perfil_buscado = _normalize_rich_html(
        form_data.get('perfil_buscado')
    )
    concurso.tareas_funciones = _normalize_rich_html(
        form_data.get('tareas_funciones')
    )
    concurso.documentacion_requerida = _normalize_rich_html(
        form_data.get('documentacion_requerida')
    )
    concurso.forma_postulacion = _normalize_rich_html(
        form_data.get('forma_postulacion')
    )
    concurso.contacto_consulta = (
        (form_data.get('contacto_consulta') or '').strip() or None
    )
    concurso.normativa = _normalize_rich_html(form_data.get('normativa'))
    concurso.bases_concurso_html = _normalize_rich_html(
        form_data.get('bases_concurso_html')
    )
    concurso.bases_llamado_html = _normalize_rich_html(
        form_data.get('bases_llamado_html')
    )
    concurso.anexo_declaracion_jurada_html = _normalize_rich_html(
        form_data.get('anexo_declaracion_jurada_html')
    )
    concurso.timeline_json = timeline_json
    concurso.requiere_18_anos = form_data.get('requiere_18_anos') == 'on'

    _sync_uploaded_documents(concurso, uploaded_keys)
    _set_postulacion_web(
        concurso,
        form_data.get('postulacion_web_habilitada') == 'on',
    )


def _persist_concurso(concurso, form_data):
    uploaded_keys = []
    concurso_id = concurso.id
    slug = concurso.slug
    try:
        valor_slug = (form_data['slug'] or '').strip()
        if valor_slug:
            slug, error = _revisar_slug(valor_slug, concurso)
            if error:
                raise SlugConcursoError(error)
        elif slug is None:
            slug = _generate_unique_concurso_slug(form_data['titulo'] or '')

        _save_concurso_from_form(concurso, form_data, slug, uploaded_keys)
        db.session.add(concurso)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        minio_service.discard_uploads(uploaded_keys)
        if isinstance(exc, IntegrityError) and _slug_en_uso(slug, concurso_id):
            raise SlugConcursoError(_SLUG_DUPLICADO) from exc
        raise


def _build_concurso_admin_filters(args):
    return {
        'q': (args.get('q') or '').strip(),
        'estado': (args.get('estado') or '').strip(),
        'area_convocante_id': (args.get('area_convocante_id') or '').strip(),
        'tipo_contratacion_id': (args.get('tipo_contratacion_id') or '').strip(),
        'tipo_llamado_id': (args.get('tipo_llamado_id') or '').strip(),
        'fecha_campo': (args.get('fecha_campo') or 'apertura').strip(),
        'fecha_desde': (args.get('fecha_desde') or '').strip(),
        'fecha_hasta': (args.get('fecha_hasta') or '').strip(),
    }


def _apply_concurso_admin_filters(query, filter_data):
    search = filter_data['q']
    if search:
        term = f'%{search}%'
        query = query.filter(
            or_(
                Concurso.titulo.ilike(term),
                Concurso.subtitulo.ilike(term),
                Concurso.slug.ilike(term),
                Concurso.localidad.ilike(term),
                AreaConvocante.nombre.ilike(term),
                TipoContratacion.nombre.ilike(term),
                TipoLlamado.nombre.ilike(term),
            )
        )

    estado = filter_data['estado']
    if estado and estado in Concurso.ESTADOS_ADMIN:
        query = query.filter(Concurso.estado_publico == estado)

    area_convocante_id = filter_data['area_convocante_id']
    if area_convocante_id.isdigit():
        query = query.filter(Concurso.area_convocante_id == int(area_convocante_id))

    tipo_contratacion_id = filter_data['tipo_contratacion_id']
    if tipo_contratacion_id.isdigit():
        query = query.filter(
            Concurso.tipo_contratacion_id == int(tipo_contratacion_id)
        )

    tipo_llamado_id = filter_data['tipo_llamado_id']
    if tipo_llamado_id.isdigit():
        query = query.filter(Concurso.tipo_llamado_id == int(tipo_llamado_id))

    fecha_campo = (
        'fecha_cierre'
        if filter_data['fecha_campo'] == 'cierre'
        else 'fecha_apertura'
    )

    fecha_desde = filter_data['fecha_desde']
    if fecha_desde:
        try:
            desde_dt = datetime.fromisoformat(fecha_desde)
            query = query.filter(getattr(Concurso, fecha_campo) >= desde_dt)
        except ValueError:
            pass

    fecha_hasta = filter_data['fecha_hasta']
    if fecha_hasta:
        try:
            hasta_dt = datetime.fromisoformat(fecha_hasta) + timedelta(days=1)
            query = query.filter(getattr(Concurso, fecha_campo) < hasta_dt)
        except ValueError:
            pass

    return query


@admin_bp.route('/concursos')
@login_required
def concursos_admin():
    filter_data = _build_concurso_admin_filters(request.args)
    query = (
        Concurso.query.outerjoin(AreaConvocante)
        .outerjoin(TipoContratacion)
        .outerjoin(TipoLlamado)
    )
    query = _apply_concurso_admin_filters(query, filter_data)
    concursos = query.order_by(Concurso.fecha_apertura.desc()).all()

    return render_template(
        'admin/concursos.html',
        concursos=concursos,
        filter_data=filter_data,
        areas=AreaConvocante.query.order_by(AreaConvocante.nombre.asc()).all(),
        tipos_contra=(
            TipoContratacion.query.order_by(TipoContratacion.nombre.asc()).all()
        ),
        tipos_llamado=TipoLlamado.query.order_by(TipoLlamado.nombre.asc()).all(),
        total_resultados=len(concursos),
    )


@admin_bp.get('/concursos/slug-disponible')
@login_required
def concurso_slug_disponible():
    concurso_id = request.args.get('concurso_id', type=int)
    concurso = db.get_or_404(Concurso, concurso_id) if concurso_id is not None else None
    slug, error = _revisar_slug(request.args.get('slug', ''), concurso)
    response = jsonify(slug=slug, disponible=error is None, mensaje=error)
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.route('/concursos/<int:concurso_id>/edit', methods=['GET', 'POST'])
@login_required
def concurso_edit(concurso_id):
    concurso = Concurso.query.get_or_404(concurso_id)

    if request.method == 'POST':
        form_data = _build_form_data(request.form, concurso=concurso)
        try:
            _persist_concurso(concurso, form_data)
        except SlugConcursoError as exc:
            return _render_concurso_form(concurso=concurso, form_data=form_data, slug_error=str(exc)), 422
        except ValueError as exc:
            flash(str(exc), 'error')
            return _render_concurso_form(concurso=concurso, form_data=form_data), 422
        except Exception:
            current_app.logger.exception('No se pudo guardar el concurso')
            flash('No se pudo guardar el concurso. Revisá los archivos seleccionados y volvé a intentar.', 'error')
            return _render_concurso_form(concurso=concurso, form_data=form_data), 503

        log_activity('CONCURSO_EDIT', f'Concurso actualizado: "{concurso.titulo}"')
        flash(f'Se actualizó el concurso "{concurso.titulo}".', 'success')
        return redirect(url_for('admin.concursos_admin'))

    return _render_concurso_form(concurso=concurso)


@admin_bp.route('/concursos/nuevo', methods=['GET', 'POST'])
@login_required
def concurso_new():
    if request.method == 'POST':
        form_data = _build_form_data(request.form)
        concurso = Concurso()
        try:
            _persist_concurso(concurso, form_data)
        except SlugConcursoError as exc:
            return _render_concurso_form(form_data=form_data, slug_error=str(exc)), 422
        except ValueError as exc:
            flash(str(exc), 'error')
            return _render_concurso_form(form_data=form_data), 422
        except Exception:
            current_app.logger.exception('No se pudo crear el concurso')
            flash('No se pudo guardar el concurso. Revisá los archivos seleccionados y volvé a intentar.', 'error')
            return _render_concurso_form(form_data=form_data), 503

        log_activity('CONCURSO_CREATE', f'Concurso creado: "{concurso.titulo}"')
        flash(f'Concurso "{concurso.titulo}" registrado correctamente.', 'success')
        return redirect(url_for('admin.concursos_admin'))

    return _render_concurso_form()


@admin_bp.route('/concursos/<int:concurso_id>/documentos/<string:documento_slug>/pdf')
@login_required
def concurso_documento_adjunto(concurso_id, documento_slug):
    return descargar_pdf_concurso(db.get_or_404(Concurso, concurso_id), documento_slug)


@admin_bp.route('/concursos/<int:concurso_id>/actualizaciones', defaults={'actualizacion_id': None}, methods=['GET', 'POST'])
@admin_bp.route('/concursos/<int:concurso_id>/actualizaciones/<int:actualizacion_id>', methods=['GET', 'POST'])
@login_required
def concurso_actualizaciones(concurso_id, actualizacion_id):
    concurso = db.get_or_404(Concurso, concurso_id)
    actualizacion = None
    if actualizacion_id is not None:
        actualizacion = concurso.actualizaciones.filter_by(id=actualizacion_id).first_or_404()

    values = {
        'etapa': actualizacion.etapa if actualizacion else 'convocatoria',
        'titulo': actualizacion.titulo if actualizacion else '',
        'fecha': actualizacion.fecha.isoformat() if actualizacion else ahora_en_uruguay().date().isoformat(),
        'descripcion': (actualizacion.descripcion or '') if actualizacion else '',
        'publicada': actualizacion.publicada if actualizacion else False,
    }
    status = 200
    if request.method == 'POST':
        values = {
            field: ((request.form.get(field) or '').strip() if field != 'publicada'
                    else request.form.get(field) == 'on')
            for field in values
        }
        uploaded_keys = []
        try:
            if values['etapa'] not in ConcursoActualizacion.ETAPAS:
                raise ValueError('Elegí una etapa válida.')
            if not values['titulo'] or len(values['titulo']) > 200:
                raise ValueError('Ingresá un título de hasta 200 caracteres.')
            if len(values['descripcion']) > 12000:
                raise ValueError('El texto del comunicado admite hasta 12.000 caracteres.')
            try:
                fecha = date.fromisoformat(values['fecha'])
            except ValueError as exc:
                raise ValueError('Ingresá una fecha válida.') from exc

            item = actualizacion or ConcursoActualizacion(concurso_id=concurso.id)
            archivo = request.files.get('pdf')
            if archivo and archivo.filename:
                key = minio_service.upload_document(archivo, prefix='concursos/expedientes/')
                uploaded_keys.append(key)
                item.pdf_key = key
            item.etapa = values['etapa']
            item.titulo = values['titulo']
            item.fecha = fecha
            item.descripcion = values['descripcion'] or None
            item.publicada = values['publicada']
            db.session.add(item)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            minio_service.discard_uploads(uploaded_keys)
            flash(str(exc), 'error')
            status = 422
        except Exception:
            db.session.rollback()
            minio_service.discard_uploads(uploaded_keys)
            current_app.logger.exception('No se pudo guardar el comunicado')
            flash('No se pudo guardar el comunicado. Volvé a intentar.', 'error')
            status = 503
        else:
            log_activity('CONCURSO_ACTUALIZACION', f'Concurso #{concurso.id}, comunicado #{item.id}, visible: {item.publicada}')
            flash('Se guardó el comunicado.', 'success')
            return redirect(url_for('admin.concurso_actualizaciones', concurso_id=concurso.id))

    return render_template(
        'admin/concurso_actualizaciones.html',
        concurso=concurso,
        actualizacion=actualizacion,
        actualizaciones=concurso.actualizaciones.order_by(ConcursoActualizacion.fecha.desc(), ConcursoActualizacion.id.desc()).all(),
        etapas=ConcursoActualizacion.ETAPAS,
        values=values,
    ), status


@admin_bp.route('/concursos/<int:concurso_id>/actualizaciones/<int:actualizacion_id>/pdf')
@login_required
def concurso_actualizacion_adjunto(concurso_id, actualizacion_id):
    item = ConcursoActualizacion.query.filter_by(id=actualizacion_id, concurso_id=concurso_id).first_or_404()
    if not item.pdf_key:
        abort(404)
    return minio_service.download_response(item.pdf_key, f'comunicado-{item.id}.pdf', 'application/pdf')


@admin_bp.route('/postulaciones')
@login_required
def postulaciones_admin():
    filters = _read_postulaciones_filters()
    query = _build_postulaciones_query(filters)
    postulaciones = query.order_by(Postulacion.created_at.desc()).all()
    llamados_por_area = {}
    llamados = db.session.execute(
        select(Concurso.area_convocante_id, Concurso.id, Concurso.titulo)
        .order_by(Concurso.titulo, Concurso.id)
    )
    for area_id, concurso_id, titulo in llamados:
        llamados_por_area.setdefault(area_id, []).append({'id': concurso_id, 'titulo': titulo})

    return render_template(
        'admin/postulaciones.html',
        postulaciones=postulaciones,
        llamados_por_area=llamados_por_area,
        areas=AreaConvocante.query.order_by(AreaConvocante.nombre.asc()).all(),
        tipos_contra=(
            TipoContratacion.query
            .order_by(TipoContratacion.nombre.asc())
            .all()
        ),
        **filters,
    )


@admin_bp.route('/postulaciones/export.csv')
@login_required
def postulaciones_export_csv():
    filters = _read_postulaciones_filters()
    estado_filtro = filters['estado_filtro']
    search = filters['search']

    postulaciones = (
        _build_postulaciones_query(filters)
        .order_by(Postulacion.created_at.desc())
        .all()
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'ID',
        'Estado',
        'Fecha',
        'Concurso',
        'Area',
        'Postulante',
        'Documento',
        'Email',
        'Telefono',
        'Localidad',
        'Domicilio',
        'Correo verificado',
        'Codigo seguimiento',
    ])

    for postulacion in postulaciones:
        writer.writerow([
            postulacion.id,
            postulacion.estado,
            postulacion.created_at.strftime('%d/%m/%Y %H:%M'),
            postulacion.concurso.titulo,
            (
                postulacion.concurso.area_convocante_rel.nombre
                if postulacion.concurso.area_convocante_rel
                else ''
            ),
            postulacion.nombre_completo,
            postulacion.documento,
            postulacion.email,
            postulacion.telefono,
            postulacion.localidad,
            postulacion.domicilio,
            'si' if postulacion.email_verified_at else 'no',
            postulacion.tracking_code or '',
        ])

    filename = 'postulaciones'
    if estado_filtro:
        filename += f'_{estado_filtro}'
    if (
        search
        or filters['area_convocante_id']
        or filters['concurso_id']
        or filters['tipo_contratacion_id']
        or filters['fecha_desde']
        or filters['fecha_hasta']
    ):
        filename += '_filtradas'
    filename += '.csv'

    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename={filename}'
        },
    )


@admin_bp.route('/postulaciones/<int:postulacion_id>', methods=['GET', 'POST'])
@login_required
def postulacion_detail(postulacion_id):
    postulacion = Postulacion.query.get_or_404(postulacion_id)

    if request.method == 'POST':
        nuevo_estado = request.form.get('estado')
        notas = request.form.get('notas_internas')

        estados = ['recibida', 'en_revision', 'admitida', 'rechazada']
        if nuevo_estado not in [Postulacion.ESTADO_PREINSCRIPTA, *estados] or (
            nuevo_estado != postulacion.estado and (
                nuevo_estado == Postulacion.ESTADO_PREINSCRIPTA
                or (postulacion.email_verification_uid and not postulacion.is_email_verified)
            )
        ):
            flash('La postulación web debe confirmar el correo antes de cambiar su estado.', 'error')
            return redirect(url_for('admin.postulacion_detail', postulacion_id=postulacion.id))
        postulacion.estado = nuevo_estado
        postulacion.notas_internas = notas

        db.session.commit()
        log_activity('POSTULACION_EVALUATE', f'Postulación editada para "{postulacion.nombre_completo}" - Estado: {postulacion.estado}')
        flash('Se actualizó el dictamen de admisibilidad correctamente.', 'success')
        return redirect(url_for('admin.postulacion_detail', postulacion_id=postulacion.id))

    urls = {
        tipo: [
            url_for('admin.postulacion_adjunto', postulacion_id=postulacion.id, tipo=tipo, indice=indice)
            for indice in range(len(keys))
        ]
        for tipo, keys in _postulacion_adjunto_keys(postulacion).items()
    }

    return render_template(
        'admin/postulacion_detail.html',
        postulacion=postulacion,
        cv_url=next(iter(urls['curriculum']), None),
        cedula_url=next(iter(urls['cedula']), None),
        certificados=urls['certificados'],
        constancias=urls['constancias'],
        adicionales=urls['adicionales'],
    )


def _postulacion_adjunto_keys(postulacion):
    def parse_keys(value):
        try:
            keys = json.loads(value or '[]')
        except (TypeError, ValueError):
            return []
        return [key for key in keys if isinstance(key, str) and key] if isinstance(keys, list) else []

    return {
        'curriculum': [postulacion.curriculum_key] if postulacion.curriculum_key else [],
        'cedula': [postulacion.cedula_key] if postulacion.cedula_key else [],
        'certificados': parse_keys(postulacion.certificados_keys),
        'constancias': parse_keys(postulacion.constancias_keys),
        'adicionales': parse_keys(postulacion.adicional_keys),
    }


@admin_bp.route('/postulaciones/<int:postulacion_id>/adjuntos/<tipo>/<int:indice>')
@login_required
def postulacion_adjunto(postulacion_id, tipo, indice):
    postulacion = db.get_or_404(Postulacion, postulacion_id)
    keys = _postulacion_adjunto_keys(postulacion).get(tipo, [])
    if indice >= len(keys):
        abort(404)

    key = keys[indice]
    extension = key.rsplit('.', 1)[-1].lower()
    filename = f'{tipo}-{indice + 1}'
    if extension in {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}:
        filename = f'{filename}.{extension}'

    return minio_service.download_response(key, filename)
