"""
Modelos de datos para el sistema de Concursos Públicos.
Incluye: AreaConvocante, TipoContratacion, Concurso, Postulacion.
"""

from datetime import UTC, datetime, timedelta
import json
import re
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case
from sqlalchemy.ext.hybrid import hybrid_property

from app.extensions import db


CONCURSO_TIMEZONE = ZoneInfo('America/Montevideo')


def ahora_en_uruguay():
    return datetime.now(CONCURSO_TIMEZONE).replace(tzinfo=None)


def fecha_concurso_iso(value):
    return value.replace(tzinfo=CONCURSO_TIMEZONE).isoformat() if value else None


class AreaConvocante(db.Model):
    __tablename__ = 'areas_convocantes'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False, unique=True)
    descripcion = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    concursos = db.relationship('Concurso', backref='area_convocante_rel', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'descripcion': self.descripcion,
        }

    def __repr__(self):
        return f'<AreaConvocante {self.nombre}>'


class TipoContratacion(db.Model):
    __tablename__ = 'tipos_contratacion'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)
    descripcion = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    concursos = db.relationship('Concurso', backref='tipo_contratacion_rel', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'descripcion': self.descripcion,
        }

    def __repr__(self):
        return f'<TipoContratacion {self.nombre}>'


class TipoLlamado(db.Model):
    __tablename__ = 'tipos_llamado'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)
    slug = db.Column(db.String(180), nullable=False, unique=True, index=True)
    descripcion = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    concursos = db.relationship('Concurso', backref='tipo_llamado_rel', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'slug': self.slug,
            'descripcion': self.descripcion,
        }

    @staticmethod
    def generate_slug(nombre):
        return Concurso.generate_slug(nombre)

    def __repr__(self):
        return f'<TipoLlamado {self.nombre}>'


class Concurso(db.Model):
    __tablename__ = 'concursos'

    SLUG_MAX_LENGTH = 350
    ESTADO_ABIERTO = 'abierto'
    ESTADO_EN_PROCESO = 'en_proceso'
    ESTADO_FINALIZADO = 'finalizado'
    ESTADO_ARCHIVADO = 'archivado'
    ESTADO_SUSPENDIDO = 'suspendido'
    ESTADO_PROXIMO = 'proximo'
    ESTADO_BORRADOR = 'borrador'

    ESTADOS = [
        ESTADO_ABIERTO, ESTADO_EN_PROCESO, ESTADO_FINALIZADO,
        ESTADO_ARCHIVADO, ESTADO_SUSPENDIDO, ESTADO_PROXIMO,
    ]
    ESTADOS_ADMIN = [ESTADO_BORRADOR, *ESTADOS]

    DOCUMENT_KIND_PAGE = 'page'
    DOCUMENT_KIND_EXTERNAL = 'external'
    DOCUMENT_KIND_POSTULACION = 'postulacion'
    DOCUMENT_DEFINITIONS = [
        {
            'id': 'bases-concurso',
            'nombre': 'Bases del Concurso',
            'tipo': 'bases',
            'field': 'bases_concurso_html',
        },
        {
            'id': 'bases-llamado',
            'nombre': 'Bases del llamado',
            'tipo': 'bases',
            'field': 'bases_llamado_html',
        },
        {
            'id': 'anexo-declaracion-jurada',
            'nombre': 'Resolución',
            'tipo': 'anexo',
            'field': 'anexo_declaracion_jurada_html',
        },
    ]

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(300), nullable=False)
    subtitulo = db.Column(db.String(500), nullable=True)
    slug = db.Column(db.String(SLUG_MAX_LENGTH), nullable=False, unique=True, index=True)
    estado = db.Column(db.String(20), nullable=False, default=ESTADO_PROXIMO)

    area_convocante_id = db.Column(
        db.Integer, db.ForeignKey('areas_convocantes.id'), nullable=False, index=True
    )
    tipo_contratacion_id = db.Column(
        db.Integer, db.ForeignKey('tipos_contratacion.id'), nullable=False, index=True
    )
    tipo_llamado_id = db.Column(
        db.Integer, db.ForeignKey('tipos_llamado.id'), nullable=True, index=True
    )

    cantidad_cargos = db.Column(db.Integer, nullable=False, default=1)
    remuneracion = db.Column(db.String(200), nullable=True)
    localidad = db.Column(db.String(200), nullable=True)
    dependencia = db.Column(db.String(300), nullable=True)

    fecha_apertura = db.Column(db.DateTime, nullable=False)
    fecha_cierre = db.Column(db.DateTime, nullable=False)
    fecha_resolucion_estimada = db.Column(db.DateTime, nullable=True)

    descripcion = db.Column(db.Text, nullable=False, default='')
    requisitos_excluyentes = db.Column(db.Text, nullable=True)
    requisitos_valorados = db.Column(db.Text, nullable=True)
    perfil_buscado = db.Column(db.Text, nullable=True)
    tareas_funciones = db.Column(db.Text, nullable=True)
    documentacion_requerida = db.Column(db.Text, nullable=True)
    forma_postulacion = db.Column(db.Text, nullable=True)
    contacto_consulta = db.Column(db.String(500), nullable=True)
    normativa = db.Column(db.Text, nullable=True)
    bases_url = db.Column(db.String(800), nullable=True)
    bases_concurso_html = db.Column(db.Text, nullable=True)
    bases_llamado_html = db.Column(db.Text, nullable=True)
    anexo_declaracion_jurada_html = db.Column(db.Text, nullable=True)

    # JSON-stored timeline: [{"fecha": "...", "titulo": "...", "descripcion": "...", "completado": bool}]
    timeline_json = db.Column(db.Text, nullable=True)
    # JSON-stored documents: [{"id": N, "nombre": "...", "url": "...", "tipo": "..."}]
    documentos_json = db.Column(db.Text, nullable=True)

    requiere_18_anos = db.Column(db.Boolean, default=True, nullable=False, server_default=db.text('1'))

    author_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('AdminUser', backref=db.backref('concursos', lazy='dynamic'))
    postulaciones = db.relationship('Postulacion', backref='concurso', lazy='dynamic')
    actualizaciones = db.relationship('ConcursoActualizacion', back_populates='concurso', lazy='dynamic')

    def _estado_y_proximo_cambio(self, ahora):
        if self.estado != self.ESTADO_ABIERTO:
            return self.estado, None
        if ahora < self.fecha_apertura:
            return self.ESTADO_PROXIMO, self.fecha_apertura
        if ahora < self.fecha_cierre:
            return self.ESTADO_ABIERTO, self.fecha_cierre
        return self.ESTADO_EN_PROCESO, None

    @hybrid_property
    def estado_publico(self):
        estado, _ = self._estado_y_proximo_cambio(ahora_en_uruguay())
        return estado

    @estado_publico.expression
    def estado_publico(cls):
        now = ahora_en_uruguay()
        abierto = cls.estado == cls.ESTADO_ABIERTO
        return case(
            (and_(abierto, cls.fecha_apertura > now), cls.ESTADO_PROXIMO),
            (and_(abierto, cls.fecha_cierre <= now), cls.ESTADO_EN_PROCESO),
            else_=cls.estado,
        )

    def _estado_para_api(self):
        ahora = ahora_en_uruguay()
        estado, proximo_cambio = self._estado_y_proximo_cambio(ahora)
        ms_hasta_cambio = None
        if proximo_cambio is not None:
            cambio_utc = proximo_cambio.replace(tzinfo=CONCURSO_TIMEZONE).astimezone(UTC)
            ahora_utc = ahora.replace(tzinfo=CONCURSO_TIMEZONE).astimezone(UTC)
            ms_hasta_cambio = ceil((cambio_utc - ahora_utc) / timedelta(milliseconds=1))
        return {'estado': estado, 'ms_hasta_cambio_estado': ms_hasta_cambio}

    def to_list_dict(self):
        return {
            'id': self.id,
            'titulo': self.titulo,
            'subtitulo': self.subtitulo,
            'slug': self.slug,
            **self._estado_para_api(),
            'area_convocante': self.area_convocante_rel.nombre if self.area_convocante_rel else '',
            'tipo_contratacion': self.tipo_contratacion_rel.nombre if self.tipo_contratacion_rel else '',
            'tipo_llamado': self.tipo_llamado_rel.nombre if self.tipo_llamado_rel else '',
            'tipo_llamado_slug': self.tipo_llamado_rel.slug if self.tipo_llamado_rel else None,
            'cantidad_cargos': self.cantidad_cargos,
            'remuneracion': self.remuneracion,
            'localidad': self.localidad,
            'fecha_apertura': fecha_concurso_iso(self.fecha_apertura),
            'fecha_cierre': fecha_concurso_iso(self.fecha_cierre),
        }

    def _legacy_documents(self):
        try:
            if self.documentos_json:
                documents = json.loads(self.documentos_json)
                if isinstance(documents, list):
                    return documents
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def document_contents(self):
        contents = {}
        for definition in self.DOCUMENT_DEFINITIONS:
            value = (getattr(self, definition['field']) or '').strip()
            if value:
                contents[definition['id']] = value
        return contents

    def postulacion_web_habilitada(self):
        for document in self._legacy_documents():
            if not isinstance(document, dict):
                continue

            tipo = str(document.get('tipo') or '').strip().lower()
            nombre = str(document.get('nombre') or '').strip().lower()
            if tipo == 'formulario' or 'formulario' in nombre:
                return True

        return False

    def document_download_source(self, document_id):
        sources = {}

        if self.bases_url:
            sources['bases-concurso'] = self.bases_url

        for document in self._legacy_documents():
            if not isinstance(document, dict):
                continue

            source_url = str(document.get('url') or '').strip()
            if not source_url:
                continue

            tipo = str(document.get('tipo') or '').strip().lower()
            nombre = str(document.get('nombre') or '').strip().lower()

            if tipo == 'bases' and 'llamado' in nombre:
                sources['bases-llamado'] = source_url
            elif tipo == 'anexo' or 'anexo' in nombre:
                sources['anexo-declaracion-jurada'] = source_url

        return sources.get(document_id)

    def public_documents(self, *, estado=None):
        contents = self.document_contents()
        documents = []

        for definition in self.DOCUMENT_DEFINITIONS:
            document_id = definition['id']
            source = self.document_download_source(document_id)
            has_page = document_id in contents
            if not source and not has_page:
                continue

            download_url = source
            if source and (has_page or source.startswith('minio:')):
                download_url = f'/api/concursos/{self.slug}/documentos/{document_id}/pdf'

            documents.append({
                'id': document_id,
                'nombre': definition['nombre'],
                'tipo': definition['tipo'],
                'kind': self.DOCUMENT_KIND_PAGE if has_page else self.DOCUMENT_KIND_EXTERNAL,
                'slug': document_id if has_page else None,
                'url': None if has_page else download_url,
                'download_url': download_url,
            })

        if estado is None:
            estado = self.estado_publico
        if estado == self.ESTADO_ABIERTO and self.postulacion_web_habilitada():
            documents.append({
                'id': 'formulario-postulacion',
                'nombre': 'Formulario web de postulación',
                'tipo': 'formulario',
                'kind': self.DOCUMENT_KIND_POSTULACION,
                'slug': 'formulario-postulacion',
                'url': None,
                'download_url': None,
            })

        return documents

    def to_detail_dict(self):
        timeline = None
        try:
            if self.timeline_json:
                timeline = json.loads(self.timeline_json)
        except (json.JSONDecodeError, TypeError):
            pass

        programacion = self._estado_para_api()
        documents = self.public_documents(estado=programacion['estado'])
        return {
            'id': self.id,
            'titulo': self.titulo,
            'subtitulo': self.subtitulo,
            'slug': self.slug,
            **programacion,
            'area_convocante': self.area_convocante_rel.to_dict() if self.area_convocante_rel else None,
            'tipo_contratacion': self.tipo_contratacion_rel.to_dict() if self.tipo_contratacion_rel else None,
            'tipo_llamado': self.tipo_llamado_rel.to_dict() if self.tipo_llamado_rel else None,
            'cantidad_cargos': self.cantidad_cargos,
            'remuneracion': self.remuneracion,
            'localidad': self.localidad,
            'fecha_apertura': fecha_concurso_iso(self.fecha_apertura),
            'fecha_cierre': fecha_concurso_iso(self.fecha_cierre),
            'fecha_resolucion_estimada': fecha_concurso_iso(self.fecha_resolucion_estimada),
            'requiere_18_anos': self.requiere_18_anos,
            'descripcion': self.descripcion,
            'requisitos_excluyentes': self.requisitos_excluyentes,
            'requisitos_valorados': self.requisitos_valorados,
            'perfil_buscado': self.perfil_buscado,
            'tareas_funciones': self.tareas_funciones,
            'documentacion_requerida': self.documentacion_requerida,
            'forma_postulacion': self.forma_postulacion,
            'contacto_consulta': self.contacto_consulta,
            'normativa': self.normativa,
            'bases_url': next((doc['download_url'] for doc in documents if doc['id'] == 'bases-concurso'), None),
            'documentos_contenido': self.document_contents(),
            'postulacion_web_habilitada': self.postulacion_web_habilitada(),
            'timeline': timeline,
            'documentos': documents,
            'actualizaciones': [
                actualizacion.to_public_dict(self.slug)
                for actualizacion in self.actualizaciones.filter_by(publicada=True)
                .order_by(ConcursoActualizacion.fecha.desc(), ConcursoActualizacion.id.desc())
            ],
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @staticmethod
    def generate_slug(titulo):
        slug = titulo.lower().strip()
        slug = re.sub(r'[áàäâ]', 'a', slug)
        slug = re.sub(r'[éèëê]', 'e', slug)
        slug = re.sub(r'[íìïî]', 'i', slug)
        slug = re.sub(r'[óòöô]', 'o', slug)
        slug = re.sub(r'[úùüû]', 'u', slug)
        slug = re.sub(r'[ñ]', 'n', slug)
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug

    def __repr__(self):
        return f'<Concurso {self.slug} [{self.estado}]>'


class ConcursoActualizacion(db.Model):
    __tablename__ = 'concurso_actualizaciones'

    ETAPAS = {
        'convocatoria': 'Convocatoria y bases',
        'inscripcion': 'Inscripciones',
        'admision': 'Admisibilidad',
        'evaluacion': 'Evaluación de méritos y antecedentes',
        'entrevista': 'Entrevistas',
        'resultado_provisorio': 'Resultados provisorios',
        'observaciones': 'Observaciones',
        'homologacion': 'Resultado definitivo y homologación',
        'destinos': 'Elección de destinos',
        'otro': 'Otro comunicado',
    }

    id = db.Column(db.Integer, primary_key=True)
    concurso_id = db.Column(db.Integer, db.ForeignKey('concursos.id', ondelete='CASCADE'), nullable=False, index=True)
    etapa = db.Column(db.String(32), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    pdf_key = db.Column(db.String(500), nullable=True)
    publicada = db.Column(db.Boolean, nullable=False, default=False)

    concurso = db.relationship('Concurso', back_populates='actualizaciones')

    def to_public_dict(self, concurso_slug):
        return {
            'id': self.id,
            'etapa': self.ETAPAS[self.etapa],
            'titulo': self.titulo,
            'fecha': self.fecha.isoformat(),
            'descripcion': self.descripcion,
            'pdf_url': f'/api/concursos/{concurso_slug}/actualizaciones/{self.id}/pdf' if self.pdf_key else None,
        }


class Postulacion(db.Model):
    __tablename__ = 'postulaciones'
    __table_args__ = (
        db.UniqueConstraint(
            'concurso_id',
            'documento',
            name='uq_postulaciones_concurso_documento',
        ),
        db.UniqueConstraint(
            'concurso_id',
            'email',
            name='uq_postulaciones_concurso_email',
        ),
    )

    ESTADO_PREINSCRIPTA = 'preinscripta'
    ESTADO_RECIBIDA = 'recibida'
    ESTADO_EN_REVISION = 'en_revision'
    ESTADO_ADMITIDA = 'admitida'
    ESTADO_RECHAZADA = 'rechazada'

    EMAIL_VERIFICATION_WINDOW_HOURS = 24

    id = db.Column(db.Integer, primary_key=True)
    concurso_id = db.Column(db.Integer, db.ForeignKey('concursos.id'), nullable=False, index=True)

    nombre_completo = db.Column(db.String(200), nullable=False)
    documento = db.Column(db.String(20), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30), nullable=False)
    domicilio = db.Column(db.String(300), nullable=False)
    localidad = db.Column(db.String(100), nullable=False)
    observaciones = db.Column(db.Text, nullable=True)

    # File paths (stored in MinIO or filesystem)
    curriculum_key = db.Column(db.String(500), nullable=True)
    cedula_key = db.Column(db.String(500), nullable=True)
    certificados_keys = db.Column(db.Text, nullable=True)  # JSON array
    constancias_keys = db.Column(db.Text, nullable=True)   # JSON array
    adicional_keys = db.Column(db.Text, nullable=True)      # JSON array

    estado = db.Column(db.String(20), nullable=False, default=ESTADO_PREINSCRIPTA)
    notas_internas = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tracking_code = db.Column(db.String(50), nullable=True, unique=True, index=True)
    email_verification_uid = db.Column(db.String(80), nullable=True, unique=True, index=True)
    email_verification_token_hash = db.Column(db.String(64), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    def verification_expires_at(self):
        if not self.email_verification_sent_at:
            return None
        return self.email_verification_sent_at + timedelta(hours=self.EMAIL_VERIFICATION_WINDOW_HOURS)

    def is_verification_expired(self):
        expires_at = self.verification_expires_at()
        return expires_at is not None and datetime.utcnow() > expires_at

    def start_email_verification(self, uid, token_hash):
        self.email_verification_uid = uid
        self.email_verification_token_hash = token_hash
        self.email_verification_sent_at = datetime.utcnow()
        self.email_verified_at = None
        self.tracking_code = None
        self.estado = self.ESTADO_PREINSCRIPTA

    def complete_email_verification(self, tracking_code):
        self.email_verified_at = datetime.utcnow()
        self.tracking_code = tracking_code
        self.estado = self.ESTADO_RECIBIDA

    def to_dict(self):
        return {
            'id': self.id,
            'concurso_id': self.concurso_id,
            'nombre_completo': self.nombre_completo,
            'documento': self.documento,
            'email': self.email,
            'estado': self.estado,
            'tracking_code': self.tracking_code,
            'email_verified': self.is_email_verified,
            'created_at': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<Postulacion {self.id} - {self.nombre_completo}>'
