"""
API pública para el módulo de Concursos Públicos.
Endpoints: listado, detalle, filtros, estadísticas, postulaciones.
"""

import json
import re
from datetime import datetime, timedelta
from hmac import compare_digest
from email_validator import EmailNotValidError, validate_email
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    request,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import case, func, or_

from app.extensions import db, limiter
from app.models.concurso import (
    AreaConvocante,
    Concurso,
    ConcursoActualizacion,
    Postulacion,
    TipoContratacion,
    TipoLlamado,
    ahora_en_uruguay,
)
from app.services.email_service import (
    send_postulacion_email,
    send_postulacion_verification_email,
)
from app.services.concurso_documents import descargar_pdf_concurso
from app.services.minio_service import minio_service
from app.utils.logging_helper import log_activity
from app.utils.security import (
    generate_tracking_code,
    generate_verification_token,
    generate_verification_uid,
    hash_verification_token,
)

concursos_bp = Blueprint('concursos', __name__)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
DOCUMENTO_REGEX = re.compile(r'^[0-9]{8}$')
TELEFONO_REGEX = re.compile(r'^[0-9]{8,9}$')
FECHA_INPUT_REGEX = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _build_postulacion_verification_url(uid, token):
    frontend_url = current_app.config.get('FRONTEND_URL', '').rstrip('/')
    return f"{frontend_url}/postulacion/verificar#uid={uid}&token={token}"


def _generate_unique_tracking_code():
    tracking_code = generate_tracking_code()
    while Postulacion.query.filter_by(tracking_code=tracking_code).first():
        tracking_code = generate_tracking_code()
    return tracking_code


def _normalize_tracking_code(raw_tracking_code):
    return ''.join((raw_tracking_code or '').strip().upper().split())


def _tracking_code_lookup_candidates(raw_tracking_code):
    normalized_tracking_code = _normalize_tracking_code(raw_tracking_code)
    if not normalized_tracking_code:
        return []

    candidates = [normalized_tracking_code]
    ambiguous_pairs = {
        '0': 'O',
        'O': '0',
    }

    for index, character in enumerate(normalized_tracking_code):
        replacement = ambiguous_pairs.get(character)
        if replacement is None:
            continue

        candidate = (
            normalized_tracking_code[:index]
            + replacement
            + normalized_tracking_code[index + 1:]
        )
        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _normalize_email(raw_email):
    return (raw_email or '').strip().lower()


def _duplicate_postulacion_flags(concurso_id, email=None, documento=None):
    duplicate_email = False
    duplicate_documento = False

    if email:
        duplicate_email = Postulacion.query.filter(
            Postulacion.concurso_id == concurso_id,
            func.lower(Postulacion.email) == email,
        ).first() is not None

    if documento:
        duplicate_documento = Postulacion.query.filter_by(
            concurso_id=concurso_id,
            documento=documento,
        ).first() is not None

    return duplicate_email, duplicate_documento


def _duplicate_postulacion_errors(duplicate_email, duplicate_documento):
    errors = []

    if duplicate_email:
        errors.append(
            'Este correo electrónico ya fue registrado previamente en este llamado.'
        )

    if duplicate_documento:
        errors.append(
            'Esta cédula de identidad ya fue registrada previamente en este llamado.'
        )

    return errors


def _concursos_publicos():
    return Concurso.query.filter(Concurso.estado != Concurso.ESTADO_BORRADOR)


def _send_verification(postulacion, token):
    try:
        send_postulacion_verification_email(
            postulacion,
            _build_postulacion_verification_url(postulacion.email_verification_uid, token),
        )
    except Exception:
        current_app.logger.exception('No se pudo enviar el correo de verificación de postulación')
        return False
    return True


# ─── Listado de Concursos ─────────────────────────────────────────────

@concursos_bp.route('/', methods=['GET'], strict_slashes=False)
def list_concursos():
    """
    Lista concursos con paginación, búsqueda y filtros.
    Query params: search, estado, tipo_contratacion_id, tipo_llamado, area_convocante_id,
                  sort_by, sort_order, page, per_page
    """
    search = (request.args.get('search') or '').strip()
    estado = (request.args.get('estado') or '').strip()
    tipo_id = request.args.get('tipo_contratacion_id', type=int)
    tipo_llamado_slug = (request.args.get('tipo_llamado') or '').strip()
    area_id = request.args.get('area_convocante_id', type=int)
    sort_by = request.args.get('sort_by', 'fecha_apertura')
    sort_order = request.args.get('sort_order', 'desc')
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, max(1, request.args.get('per_page', 12, type=int)))

    query = _concursos_publicos()

    # Search
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Concurso.titulo.ilike(term),
                Concurso.subtitulo.ilike(term),
                Concurso.descripcion.ilike(term),
                Concurso.localidad.ilike(term),
            )
        )

    # Filter by estado
    if estado and estado in Concurso.ESTADOS:
        query = query.filter(Concurso.estado_publico == estado)

    # Filter by tipo_contratacion
    if tipo_id:
        query = query.filter(Concurso.tipo_contratacion_id == tipo_id)

    # Filter by tipo_llamado
    if tipo_llamado_slug:
        query = query.join(TipoLlamado, Concurso.tipo_llamado_id == TipoLlamado.id).filter(TipoLlamado.slug == tipo_llamado_slug)

    # Filter by area_convocante
    if area_id:
        query = query.filter(Concurso.area_convocante_id == area_id)

    # Sorting
    allowed_sort = {
        'fecha_apertura': Concurso.fecha_apertura,
        'fecha_cierre': Concurso.fecha_cierre,
        'titulo': Concurso.titulo,
    }
    sort_col = allowed_sort.get(sort_by, Concurso.fecha_apertura)
    if sort_order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'items': [c.to_list_dict() for c in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    })


# ─── Detalle de Concurso ──────────────────────────────────────────────

@concursos_bp.route('/<string:slug>', methods=['GET'])
def concurso_detail(slug):
    """Devuelve el detalle completo de un concurso por slug."""
    concurso = _concursos_publicos().filter_by(slug=slug).first_or_404()
    return jsonify(concurso.to_detail_dict())


@concursos_bp.route('/<string:slug>/documentos/<string:documento_slug>/pdf', methods=['GET'])
def concurso_document_pdf(slug, documento_slug):
    """Descarga el PDF oficial asociado a un documento de concurso, si existe."""
    concurso = _concursos_publicos().filter_by(slug=slug).first_or_404()
    return descargar_pdf_concurso(concurso, documento_slug)


@concursos_bp.route('/<string:slug>/actualizaciones/<int:actualizacion_id>/pdf')
def concurso_actualizacion_pdf(slug, actualizacion_id):
    concurso = _concursos_publicos().filter_by(slug=slug).first_or_404()
    actualizacion = concurso.actualizaciones.filter_by(id=actualizacion_id, publicada=True).first_or_404()
    if not actualizacion.pdf_key:
        abort(404)
    return minio_service.download_response(
        actualizacion.pdf_key, f'comunicado-{actualizacion.id}.pdf', 'application/pdf',
    )


# ─── Concursos Destacados ─────────────────────────────────────────────

@concursos_bp.route('/destacados', methods=['GET'])
def concursos_destacados():
    """Devuelve los concursos abiertos y próximos más recientes (máx. 6)."""
    estado = Concurso.estado_publico
    concursos = (
        _concursos_publicos()
        .filter(
            estado.in_(
                [
                    Concurso.ESTADO_ABIERTO,
                    Concurso.ESTADO_PROXIMO,
                    Concurso.ESTADO_EN_PROCESO,
                ]
            )
        )
        .order_by(
            case(
                (
                    estado.in_(
                        [
                            Concurso.ESTADO_ABIERTO,
                            Concurso.ESTADO_PROXIMO,
                        ]
                    ),
                    0,
                ),
                else_=1,
            ),
            Concurso.fecha_apertura.desc(),
        )
        .limit(6)
        .all()
    )
    return jsonify([c.to_list_dict() for c in concursos])


# ─── Estadísticas ─────────────────────────────────────────────────────

@concursos_bp.route('/estadisticas', methods=['GET'])
def estadisticas():
    """Devuelve contadores de concursos por estado."""
    estado = Concurso.estado_publico
    counts = (
        _concursos_publicos().with_entities(estado, func.count(Concurso.id))
        .group_by(estado)
        .all()
    )
    stats = {estado: 0 for estado in Concurso.ESTADOS}
    for estado, count in counts:
        if estado in stats:
            stats[estado] = count

    postulaciones = (
        db.session.query(func.count(Postulacion.id))
        .join(Concurso)
        .filter(Concurso.estado != Concurso.ESTADO_BORRADOR)
        .scalar() or 0
    )

    return jsonify({
        'abiertos': stats.get('abierto', 0),
        'en_proceso': stats.get('en_proceso', 0),
        'finalizados': stats.get('finalizado', 0),
        'archivados': stats.get('archivado', 0),
        'postulaciones_en_curso': postulaciones,
    })


# ─── Áreas Convocantes ────────────────────────────────────────────────

@concursos_bp.route('/areas', methods=['GET'])
def list_areas():
    """Devuelve las áreas convocantes activas."""
    areas = AreaConvocante.query.filter_by(is_active=True).order_by(AreaConvocante.nombre).all()
    return jsonify([a.to_dict() for a in areas])


# ─── Tipos de Contratación ────────────────────────────────────────────

@concursos_bp.route('/tipos-contratacion', methods=['GET'])
def list_tipos():
    """Devuelve los tipos de contratación activos."""
    tipos = TipoContratacion.query.filter_by(is_active=True).order_by(TipoContratacion.nombre).all()
    return jsonify([t.to_dict() for t in tipos])


@concursos_bp.route('/tipos-llamado', methods=['GET'])
def list_tipos_llamado():
    """Devuelve los tipos de llamado activos."""
    tipos = TipoLlamado.query.filter_by(is_active=True).order_by(TipoLlamado.nombre).all()
    return jsonify([t.to_dict() for t in tipos])


# ─── Postulación ──────────────────────────────────────────────────────

@concursos_bp.route('/postulaciones', methods=['POST'])
@limiter.limit("5 per minute")
def crear_postulacion():
    """
    Recibe una postulación con datos personales y archivos.
    Content-Type: multipart/form-data
    """
    # Validate concurso
    concurso_id = request.form.get('concurso_id', type=int)
    if not concurso_id:
        return jsonify({'message': 'Concurso no especificado.'}), 400

    concurso = db.session.get(Concurso, concurso_id)
    if not concurso or concurso.estado == Concurso.ESTADO_BORRADOR:
        return jsonify({'message': 'Concurso no encontrado.'}), 404

    if concurso.estado_publico != Concurso.ESTADO_ABIERTO:
        return jsonify({
            'message': 'Este concurso no está abierto para postulaciones.'
        }), 422

    if not concurso.postulacion_web_habilitada():
        return jsonify({
            'message': (
                'La postulación web no está habilitada para este concurso.'
            )
        }), 422

    # Validate required fields
    nombre = (request.form.get('nombre_completo') or '').strip()
    documento = (request.form.get('documento') or '').strip()
    fecha_nac_str = (request.form.get('fecha_nacimiento') or '').strip()
    email = _normalize_email(request.form.get('email'))
    telefono = (request.form.get('telefono') or '').strip()
    domicilio = (request.form.get('domicilio') or '').strip()
    localidad = (request.form.get('localidad') or '').strip()
    observaciones = (request.form.get('observaciones') or '').strip() or None

    errors = []
    if not nombre or len(nombre) < 3:
        errors.append('Nombre completo es requerido (mín. 3 caracteres).')
    if not documento:
        errors.append('La cédula es requerida.')
    elif not DOCUMENTO_REGEX.fullmatch(documento):
        errors.append(
            'La cédula debe tener 8 dígitos, incluyendo el dígito final, '
            'sin puntos ni guiones.'
        )
    if not fecha_nac_str:
        errors.append('Fecha de nacimiento es requerida.')
    elif not FECHA_INPUT_REGEX.fullmatch(fecha_nac_str):
        errors.append('Fecha de nacimiento inválida.')
    try:
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        errors.append('Ingresá una dirección de correo válida.')
    if not telefono:
        errors.append('Teléfono es requerido.')
    elif not TELEFONO_REGEX.fullmatch(telefono):
        errors.append('El teléfono debe contener solo números y hasta 9 dígitos.')
    if not domicilio:
        errors.append('Domicilio es requerido.')
    if not localidad:
        errors.append('Localidad es requerida.')
    for value, limit, label in (
        (nombre, 200, 'El nombre completo'), (email, 120, 'El correo'),
        (domicilio, 300, 'El domicilio'), (localidad, 100, 'La localidad'),
        (observaciones or '', 1000, 'El texto de observaciones'),
    ):
        if len(value) > limit:
            errors.append(f'{label} admite hasta {limit} caracteres.')

    for field, label in (('curriculum', 'currículum'), ('cedula', 'archivo de cédula')):
        if not request.files.get(field):
            errors.append(f'Adjuntá el {label}.')

    if errors:
        return jsonify({'message': 'Datos inválidos.', 'errors': errors}), 422

    duplicate_email, duplicate_documento = _duplicate_postulacion_flags(
        concurso_id,
        email=email,
        documento=documento,
    )
    duplicate_errors = _duplicate_postulacion_errors(
        duplicate_email,
        duplicate_documento,
    )
    if duplicate_errors:
        return jsonify({
            'message': 'Ya existe una postulación para este llamado. Si está pendiente, podés reenviar la confirmación.',
            'errors': duplicate_errors,
            'duplicate_email': duplicate_email,
            'duplicate_documento': duplicate_documento,
        }), 409

    # Parse date
    try:
        fecha_nacimiento = datetime.strptime(fecha_nac_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Formato de fecha inválido.'}), 422

    today = ahora_en_uruguay().date()
    if fecha_nacimiento > today:
        return jsonify({'message': 'La fecha de nacimiento no puede estar en el futuro.'}), 422

    if concurso.requiere_18_anos:
        age = today.year - fecha_nacimiento.year - (
            (today.month, today.day)
            < (fecha_nacimiento.month, fecha_nacimiento.day)
        )
        if age < 18:
            return jsonify({
                'message': (
                    'Debés tener al menos 18 años para postularte '
                    'a este concurso.'
                )
            }), 422

    uploaded_keys = []

    def save_file(file, field_name):
        if not _allowed_file(file.filename):
            raise ValueError(
                f'El archivo de {field_name} tiene un formato no permitido.'
            )
        key = minio_service.upload_application_file(
            file,
            prefix=f'postulaciones/{concurso_id}/',
            allowed_extensions=ALLOWED_EXTENSIONS,
            max_size=MAX_FILE_SIZE,
        )
        uploaded_keys.append(key)
        return key

    def save_files(field_name):
        keys = [save_file(file, field_name) for file in request.files.getlist(field_name) if file and file.filename]
        return json.dumps(keys) if keys else None

    try:
        curriculum_key = save_file(request.files['curriculum'], 'currículum')
        cedula_key = save_file(request.files['cedula'], 'cédula')
        certificados_keys = save_files('certificados')
        constancias_keys = save_files('constancias')
        adicional_keys = save_files('adicional')
    except ValueError as exc:
        minio_service.discard_uploads(uploaded_keys)
        return jsonify({'message': str(exc)}), 422
    except Exception:
        minio_service.discard_uploads(uploaded_keys)
        current_app.logger.exception(
            'Error subiendo adjuntos de postulación a MinIO'
        )
        return jsonify({
            'message': (
                'No se pudieron guardar los archivos adjuntos. '
                'Intentá nuevamente.'
            )
        }), 503

    verification_token = generate_verification_token()

    postulacion = Postulacion(
        concurso_id=concurso_id,
        nombre_completo=nombre,
        documento=documento,
        fecha_nacimiento=fecha_nacimiento,
        email=email,
        telefono=telefono,
        domicilio=domicilio,
        localidad=localidad,
        observaciones=observaciones,
        curriculum_key=curriculum_key,
        cedula_key=cedula_key,
        certificados_keys=certificados_keys,
        constancias_keys=constancias_keys,
        adicional_keys=adicional_keys,
    )
    postulacion.start_email_verification(
        generate_verification_uid(),
        hash_verification_token(verification_token),
    )

    db.session.add(postulacion)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        minio_service.discard_uploads(uploaded_keys)
        duplicate_email, duplicate_documento = _duplicate_postulacion_flags(
            concurso_id,
            email=email,
            documento=documento,
        )
        duplicate_errors = _duplicate_postulacion_errors(
            duplicate_email,
            duplicate_documento,
        ) or [
            'Ya existe una postulación registrada para este llamado.'
        ]
        return jsonify({
            'message': 'Ya existe una postulación para este llamado. Si está pendiente, podés reenviar la confirmación.',
            'errors': duplicate_errors,
            'duplicate_email': duplicate_email,
            'duplicate_documento': duplicate_documento,
        }), 409

    except SQLAlchemyError:
        db.session.rollback()
        minio_service.discard_uploads(uploaded_keys)
        current_app.logger.exception('No se pudo registrar la preinscripción')
        return jsonify({'message': 'No pudimos guardar la preinscripción. Volvé a intentar.'}), 503

    email_sent = _send_verification(postulacion, verification_token)

    log_activity(
        'POSTULACION_PREINSCRIPCION_CREADA',
        f'Preinscripción #{postulacion.id} al concurso #{concurso.id}',
    )

    return jsonify({
        'message': 'Preinscripción registrada.',
        'id': postulacion.id,
        'email': postulacion.email,
        'verification_required': True,
        'verification_email_sent': email_sent,
    }), 201


@concursos_bp.route('/postulaciones/verificar-duplicado', methods=['GET', 'POST'])
@limiter.limit("20/minute")
def verificar_postulacion_duplicada():
    values = request.form if request.method == 'POST' else request.args
    concurso_id = values.get('concurso_id', type=int)
    email = _normalize_email(values.get('email'))
    documento = (values.get('documento') or '').strip()

    if not concurso_id:
        return jsonify({'message': 'Concurso no especificado.'}), 400

    if not email and not documento:
        return jsonify({
            'message': 'Debés indicar un correo o una cédula para verificar.'
        }), 400

    _concursos_publicos().filter_by(id=concurso_id).first_or_404()
    duplicate_email, duplicate_documento = _duplicate_postulacion_flags(
        concurso_id,
        email=email,
        documento=documento,
    )

    return jsonify({
        'duplicate_email': duplicate_email,
        'duplicate_documento': duplicate_documento,
        'errors': _duplicate_postulacion_errors(
            duplicate_email,
            duplicate_documento,
        ),
    }), 200


@concursos_bp.route('/postulaciones/reenviar-confirmacion', methods=['POST'])
@limiter.limit("5/minute")
def reenviar_confirmacion_postulacion():
    concurso_id = request.form.get('concurso_id', type=int)
    email = _normalize_email(request.form.get('email'))
    documento = (request.form.get('documento') or '').strip()
    if not concurso_id or not DOCUMENTO_REGEX.fullmatch(documento):
        return jsonify({'message': 'Ingresá el concurso y la cédula con 8 dígitos.'}), 422
    try:
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return jsonify({'message': 'Ingresá una dirección de correo válida.'}), 422

    concurso = _concursos_publicos().filter_by(id=concurso_id).first_or_404()
    message = 'Si hay una preinscripción pendiente dentro del plazo de confirmación, recibirás un nuevo enlace.'
    if ahora_en_uruguay() >= concurso.fecha_cierre + timedelta(hours=Postulacion.EMAIL_VERIFICATION_WINDOW_HOURS):
        return jsonify({'message': message}), 200

    postulacion = Postulacion.query.filter(
        Postulacion.concurso_id == concurso.id,
        Postulacion.documento == documento,
        func.lower(Postulacion.email) == email,
        Postulacion.email_verified_at.is_(None),
        Postulacion.email_verification_uid.is_not(None),
        Postulacion.estado == Postulacion.ESTADO_PREINSCRIPTA,
    ).with_for_update().first()

    if postulacion:
        token = generate_verification_token()
        postulacion.start_email_verification(postulacion.email_verification_uid, hash_verification_token(token))
        db.session.flush()
        if not _send_verification(postulacion, token):
            db.session.rollback()
            return jsonify({'message': 'El servicio de correo no está disponible. Volvé a intentar en unos minutos.'}), 503
        db.session.commit()

    return jsonify({'message': message}), 200


@concursos_bp.route('/postulaciones/verificar-email', methods=['POST'])
@limiter.limit("10/minute")
def verificar_email_postulacion():
    uid = (request.form.get('uid') or '').strip()
    token = (request.form.get('token') or '').strip()

    if not uid or len(uid) > 80 or not token or len(token) > 80:
        return jsonify({
            'message': 'El enlace de verificación es inválido.'
        }), 400

    postulacion = Postulacion.query.filter_by(email_verification_uid=uid).with_for_update().first()
    if not postulacion or not compare_digest(
        postulacion.email_verification_token_hash or '',
        hash_verification_token(token),
    ):
        return jsonify({
            'message': 'El enlace ya no es válido. Usá el último correo que recibiste.',
        }), 400

    if postulacion.is_email_verified:
        return jsonify({
            'message': 'La inscripción ya había sido confirmada.',
            'tracking_code': postulacion.tracking_code,
            'already_verified': True,
            'concurso_titulo': postulacion.concurso.titulo,
            'completion_email_sent': False,
        }), 200

    if postulacion.is_verification_expired():
        return jsonify({
            'message': (
                'El enlace de verificación expiró. '
                'Podés solicitar otro desde la ficha del concurso.'
            ),
            'concurso_slug': postulacion.concurso.slug,
        }), 410

    tracking_code = _generate_unique_tracking_code()
    postulacion.complete_email_verification(tracking_code)
    db.session.commit()

    email_sent = True
    try:
        send_postulacion_email(postulacion)
    except Exception:
        email_sent = False
        current_app.logger.exception(
            'No se pudo enviar el mail final de inscripción'
        )

    log_activity(
        'POSTULACION_EMAIL_CONFIRMADO',
        f'Inscripción #{postulacion.id} confirmada',
    )

    return jsonify({
        'message': 'Inscripción confirmada con éxito.',
        'tracking_code': postulacion.tracking_code,
        'concurso_titulo': postulacion.concurso.titulo,
        'already_verified': False,
        'completion_email_sent': email_sent,
    }), 200


@concursos_bp.after_request
def _no_cache_respuestas_dinamicas(response):
    if request.path.startswith('/api/concursos/postulaciones') or request.endpoint in {
        'api.concursos.list_concursos',
        'api.concursos.concurso_detail',
        'api.concursos.concursos_destacados',
        'api.concursos.estadisticas',
        'api.concursos.list_areas',
        'api.concursos.list_tipos',
        'api.concursos.list_tipos_llamado',
    }:
        response.headers['Cache-Control'] = 'no-store'
    return response


@concursos_bp.route('/postulaciones/seguimiento/<tracking_code>', methods=['GET'])
@limiter.limit("5/minute")
def get_postulacion_status(tracking_code):
    """
    Obtiene el estado de una postulación mediante su código de seguimiento.
    """
    lookup_candidates = _tracking_code_lookup_candidates(tracking_code)

    if not lookup_candidates:
        return jsonify({
            'message': 'Código de seguimiento no encontrado.'
        }), 404

    postulaciones = Postulacion.query.filter(
        Postulacion.tracking_code.in_(lookup_candidates)
    ).all()

    postulacion = None
    postulaciones_por_codigo = {
        item.tracking_code: item for item in postulaciones
    }

    for candidate in lookup_candidates:
        postulacion = postulaciones_por_codigo.get(candidate)
        if postulacion is not None:
            break

    if not postulacion:
        return jsonify({
            'message': 'Código de seguimiento no encontrado.'
        }), 404

    estado_verbose = {
        'preinscripta': 'Preinscripción pendiente de confirmación',
        'recibida': 'Recibida',
        'en_revision': 'En revisión',
        'admitida': 'Admitida',
        'rechazada': 'Rechazada'
    }.get(postulacion.estado, postulacion.estado.capitalize())

    return jsonify({
        'id': postulacion.id,
        'tracking_code': postulacion.tracking_code,
        'concurso_slug': postulacion.concurso.slug,
        'concurso_titulo': postulacion.concurso.titulo,
        'fecha': postulacion.created_at.strftime('%d/%m/%Y'),
        'documento': f"{postulacion.documento[:3]}***{postulacion.documento[-3:]}" if len(postulacion.documento) > 6 else postulacion.documento,
        'estado': estado_verbose,
        'estado_raw': postulacion.estado
    })
