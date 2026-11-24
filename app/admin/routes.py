"""
Rutas principales del panel de administración de Lavalleja Concursa.
"""
from flask import render_template
from flask_login import current_user, login_required
from sqlalchemy import func
from app.models.concurso import Concurso, Postulacion, TipoLlamado
from . import admin_bp

# ─── Módulos de rutas ──────────────────────────────────────────────────────────
from .routes_components import auth        # noqa: F401
from .routes_components import audit       # noqa: F401
from .routes_components import catalogos_concursos  # noqa: F401
from .routes_components import concursos  # noqa: F401
from .routes_components import users       # noqa: F401


@admin_bp.route('/')
@login_required
def dashboard():
    # Estadísticas para el dashboard de concursos
    estado_actual = Concurso.estado_publico
    estados = dict(
        Concurso.query.with_entities(estado_actual, func.count(Concurso.id)).group_by(estado_actual).all()
    )

    total_postulaciones = Postulacion.query.count()
    postulaciones_preinscriptas = Postulacion.query.filter_by(estado=Postulacion.ESTADO_PREINSCRIPTA).count()
    postulaciones_recibidas = Postulacion.query.filter_by(estado=Postulacion.ESTADO_RECIBIDA).count()
    postulaciones_revision = Postulacion.query.filter_by(estado=Postulacion.ESTADO_EN_REVISION).count()
    postulaciones_admitidas = Postulacion.query.filter_by(estado=Postulacion.ESTADO_ADMITIDA).count()

    total_tipos_llamado = (
        TipoLlamado.query.filter_by(is_active=True).count() if current_user.is_superuser else None
    )

    # Postulaciones recientes
    recent_postulaciones = (
        Postulacion.query
        .order_by(Postulacion.created_at.desc())
        .limit(5).all()
    )

    # Concursos recientes
    recent_concursos = (
        Concurso.query
        .order_by(Concurso.created_at.desc())
        .limit(5).all()
    )

    return render_template(
        'admin/dashboard.html',
        total_concursos=sum(estados.values()),
        abiertos=estados.get(Concurso.ESTADO_ABIERTO, 0),
        en_proceso=estados.get(Concurso.ESTADO_EN_PROCESO, 0),
        finalizados=estados.get(Concurso.ESTADO_FINALIZADO, 0),
        proximos=estados.get(Concurso.ESTADO_PROXIMO, 0),
        total_postulaciones=total_postulaciones,
        postulaciones_preinscriptas=postulaciones_preinscriptas,
        postulaciones_recibidas=postulaciones_recibidas,
        postulaciones_revision=postulaciones_revision,
        postulaciones_admitidas=postulaciones_admitidas,
        total_tipos_llamado=total_tipos_llamado,
        recent_postulaciones=recent_postulaciones,
        recent_concursos=recent_concursos,
    )
