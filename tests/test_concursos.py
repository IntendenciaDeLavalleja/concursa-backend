import csv
import re
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from urllib.parse import parse_qs, urlsplit

import pytest
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.admin.routes_components import catalogos_concursos as admin_catalogos
from app.admin.routes_components import concursos as admin_concursos
from app.api import concursos as api
from app.extensions import db
from app.models import concurso as models
from app.models.concurso import AreaConvocante, Concurso, ConcursoActualizacion, Postulacion, TipoContratacion, TipoLlamado
from app.models.user import ActivityLog, AdminUser
from app.services.minio_service import minio_service

PDF = b'%PDF-1.4\n% PDF sintetico de prueba\n%%EOF\n'


class StoredObject(BytesIO):
    def stream(self, size):
        while chunk := self.read(size):
            yield chunk

    def release_conn(self):
        pass


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, bucket, key, stream, length, **kwargs):
        self.objects[bucket, key] = stream.read(length)

    def get_object(self, bucket, key):
        body = self.objects[bucket, key]
        obj = StoredObject(body)
        obj.headers = {'Content-Length': str(len(body))}
        return obj

    def stat_object(self, bucket, key):
        if (bucket, key) not in self.objects:
            raise S3Error(None, 'NoSuchKey', 'Object does not exist', None, None, None)

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)


class Settings:
    TESTING = True
    SECRET_KEY = 'test-portal-concursos'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    RATELIMIT_ENABLED = False
    MINIO_BUCKET_NAME = 'concursos-test'
    FRONTEND_URL = 'https://portal.example.org'


@pytest.fixture
def portal(monkeypatch):
    app = create_app(Settings)
    clock = [datetime(2026, 11, 24, 10)]
    monkeypatch.setattr(models, 'ahora_en_uruguay', lambda: clock[0])
    monkeypatch.setattr(api, 'ahora_en_uruguay', lambda: clock[0])
    storage = MemoryStorage()
    monkeypatch.setattr(minio_service, 'client', storage)

    with app.app_context():
        with db.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys = ON')
        db.create_all()
        area = AreaConvocante(nombre='Deportes')
        tipo = TipoContratacion(nombre='Contrato de función pública')
        admin = AdminUser(username='qa', email='qa@example.org', is_superuser=True)
        db.session.add_all([area, tipo, admin])
        db.session.commit()
        admin_id, area_id, tipo_id = admin.id, area.id, tipo.id

    administrator = app.test_client()
    with administrator.session_transaction() as session:
        session['_user_id'] = str(admin_id)
        session['_fresh'] = True

    return app, administrator, app.test_client(), clock, storage, area_id, tipo_id


def admin_post(client, url, data, *, expected=302, form_url=None, headers=None):
    screen = client.get(form_url or url)
    assert screen.status_code == 200
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', screen.data)
    assert csrf is not None
    response = client.post(url, data={'csrf_token': csrf[1].decode(), **data}, headers=headers)
    assert response.status_code == expected
    return response


def datos_llamado(portal, **changes):
    _, _, _, clock, _, area, tipo = portal
    return {
        'titulo': 'Concurso de prueba',
        'area_convocante_id': area,
        'tipo_contratacion_id': tipo,
        'cantidad_cargos': 2,
        'fecha_apertura': (clock[0] - timedelta(hours=1)).isoformat(),
        'fecha_cierre': (clock[0] + timedelta(hours=1)).isoformat(),
        'estado': 'abierto',
        'postulacion_web_habilitada': 'on',
        'documentacion_requerida': '<ul><li>Constancia de prueba</li></ul>',
        **changes,
    }


def crear_llamado(portal, **changes):
    app, admin, _, _, _, _, _ = portal
    admin_post(admin, '/admin/concursos/nuevo', datos_llamado(portal, **changes))
    with app.app_context():
        concurso = db.session.scalar(select(Concurso))
        return concurso.id, concurso.slug


def datos_postulacion(concurso_id):
    return {
        'concurso_id': concurso_id,
        'nombre_completo': 'Persona de prueba',
        'documento': '12345678',
        'fecha_nacimiento': '1995-02-15',
        'email': 'aspirante@example.org',
        'telefono': '099123456',
        'domicilio': 'Calle de prueba 123',
        'localidad': 'Minas',
        'curriculum': (BytesIO(PDF), 'curriculum.pdf'),
        'cedula': (BytesIO(PDF), 'cedula.pdf'),
    }


def test_inicializar_catalogos_sin_concursos_de_ejemplo(portal):
    app = portal[0]
    runner = app.test_cli_runner()
    for _ in range(2):
        response = runner.invoke(args=['init-catalogos-concursos'])
        assert response.exit_code == 0, response.exception

    with app.app_context():
        assert TipoLlamado.query.filter_by(slug='interno').count() == 1
        assert Concurso.query.count() == 0
        assert Postulacion.query.count() == 0


def test_eliminar_requiere_confirmacion_y_reasignacion_si_se_usa(portal):
    app, admin, _, _, _, _, _ = portal
    runner = app.test_cli_runner()
    response = runner.invoke(args=['init-catalogos-concursos'])
    assert response.exit_code == 0, response.exception

    with app.app_context():
        libre_id = TipoLlamado.query.filter_by(slug='interno').one().id
        usado_id = TipoLlamado.query.filter_by(slug='zafral').one().id
    concurso_id, _ = crear_llamado(portal, tipo_llamado_id=usado_id)

    catalogo = '/admin/concursos/tipos-llamado'
    eliminar_libre = f'{catalogo}/{libre_id}/eliminar'
    eliminar_usado = f'{catalogo}/{usado_id}/eliminar'
    listado = admin.get(catalogo)
    assert f'data-eliminar-url="{eliminar_libre}"'.encode() in listado.data
    assert f'data-eliminar-url="{eliminar_usado}"'.encode() in listado.data
    assert admin.get(eliminar_libre).status_code == 405
    assert admin.post(eliminar_libre, data={'confirmar': '1'}).status_code == 400

    admin_post(admin, eliminar_usado, {'confirmar': '1'}, form_url=catalogo)
    admin_post(admin, eliminar_libre, {}, form_url=catalogo)
    with app.app_context():
        assert db.session.get(TipoLlamado, libre_id) is not None

    admin_post(admin, eliminar_libre, {'confirmar': '1'}, form_url=catalogo)
    response = runner.invoke(args=['init-catalogos-concursos', '--sin-tipos-de-llamado'])
    assert response.exit_code == 0, response.exception

    with app.app_context():
        assert db.session.get(TipoLlamado, libre_id) is None
        assert db.session.get(TipoLlamado, usado_id) is not None
        assert db.session.get(Concurso, concurso_id).tipo_llamado_id == usado_id


def test_slug_publico_personalizado_y_verificacion(portal):
    _, admin, public, _, _, _, _ = portal
    verificador = '/admin/concursos/slug-disponible'
    nuevo = '/admin/concursos/nuevo'
    slug_elegido = 'Ñandú 2027'
    slug_publico = 'nandu-2027'

    assert public.get(verificador, query_string={'slug': slug_elegido}).status_code == 302
    libre = admin.get(verificador, query_string={'slug': slug_elegido})
    assert libre.json == {'slug': slug_publico, 'disponible': True, 'mensaje': None}
    assert libre.headers['Cache-Control'] == 'no-store'
    for invalido in ('***', 'Áreas', 'tipos-llamado', 'a' * 351):
        assert not admin.get(verificador, query_string={'slug': invalido}).json['disponible']
        admin_post(admin, nuevo, datos_llamado(portal, slug=invalido), expected=422)

    concurso_id, slug = crear_llamado(portal, slug=slug_elegido)
    assert slug == slug_publico
    assert public.get(f'/api/concursos/{slug}').json['id'] == concurso_id
    ocupado = admin.get(verificador, query_string={'slug': slug_elegido})
    assert not ocupado.json['disponible']
    duplicado = admin_post(admin, nuevo, datos_llamado(portal, slug=slug_elegido), expected=422)
    assert 'Este slug ya está en uso.' in duplicado.get_data(as_text=True)

    edit = f'/admin/concursos/{concurso_id}/edit'
    propio = admin.get(verificador, query_string={'slug': slug_elegido, 'concurso_id': concurso_id})
    assert propio.json['disponible']
    admin_post(admin, edit, datos_llamado(portal, titulo='Otro título'))
    assert public.get(f'/api/concursos/{slug}').json['titulo'] == 'Otro título'

    admin_post(admin, nuevo, datos_llamado(portal, titulo=slug_elegido, slug=''))
    assert public.get(f'/api/concursos/{slug}-2').status_code == 200
    admin_post(admin, edit, datos_llamado(portal, slug='Convocatoria Ñandú'))
    assert public.get('/api/concursos/convocatoria-nandu').json['id'] == concurso_id


def test_slug_ocupado_al_guardar_retrotrae_adjuntos(portal, monkeypatch):
    app, admin, _, _, storage, _, _ = portal
    _, slug = crear_llamado(portal)
    verificar_uso = admin_concursos._slug_en_uso
    controles = iter((False, True))

    def slug_en_uso(candidato, concurso_id=None):
        return next(controles) and verificar_uso(candidato, concurso_id)

    monkeypatch.setattr(admin_concursos, '_slug_en_uso', slug_en_uso)
    result = admin_post(
        admin, '/admin/concursos/nuevo',
        datos_llamado(portal, slug=slug, bases_concurso_pdf=(BytesIO(PDF), 'bases.pdf')),
        expected=422,
    )
    assert 'Este slug ya está en uso.' in result.get_data(as_text=True)
    assert not storage.objects
    with app.app_context():
        assert Concurso.query.count() == 1


@pytest.mark.parametrize(('clave', 'campo', 'api_catalogo'), [
    ('areas', 'area_convocante_id', 'areas'),
    ('tipos-vinculo', 'tipo_contratacion_id', 'tipos-contratacion'),
    ('tipos-llamado', 'tipo_llamado_id', 'tipos-llamado'),
])
def test_gestion_catalogo_y_opciones_de_llamados(portal, clave, campo, api_catalogo):
    app, admin, public, _, _, _, _ = portal
    admin_url = f'/admin/concursos/{clave}'
    public_url = f'/api/concursos/{api_catalogo}'
    nuevo = '/admin/concursos/nuevo'
    headers = {'Accept': 'application/json'}

    assert public.get(admin_url).status_code == 302
    assert admin.post(admin_url, data={'nombre': 'Artes'}, headers=headers).status_code == 400
    alta = admin_post(admin, admin_url, {'nombre': 'Artes'}, expected=201, form_url=nuevo, headers=headers)
    opcion_id = alta.json['id']
    assert alta.json in public.get(public_url).json
    assert public.get(public_url).headers['Cache-Control'] == 'no-store'
    assert b'>Artes</option>' in admin.get(nuevo).data
    admin_post(admin, admin_url, {'nombre': ' artes '}, expected=422, headers=headers)

    concurso_id, slug = crear_llamado(portal, **{campo: opcion_id})
    edit_url = f'/admin/concursos/{concurso_id}/edit'
    admin_post(admin, admin_url, {campo: opcion_id, 'nombre': 'Artes y cultura', 'descripcion': 'Cultura local'})
    detalle = public.get(f'/api/concursos/{slug}').json[campo.removesuffix('_id')]
    assert detalle['nombre'] == 'Artes y cultura'
    if clave == 'tipos-llamado':
        assert detalle['slug'] == 'artes'
        filtrado = public.get('/api/concursos', query_string={'tipo_llamado': detalle['slug']})
        assert filtrado.json['total'] == 1

    admin_post(admin, f'{admin_url}/{opcion_id}/toggle', {}, form_url=admin_url)
    assert all(opcion['id'] != opcion_id for opcion in public.get(public_url).json)
    editor_nuevo = admin.get(nuevo).data
    assert b'>Artes y cultura</option>' not in editor_nuevo
    assert b'>Artes y cultura (inactivo)</option>' not in editor_nuevo
    assert b'Artes y cultura (inactivo)' in admin.get(edit_url).data
    admin_post(admin, nuevo, datos_llamado(portal, **{campo: opcion_id}), expected=422)
    admin_post(admin, edit_url, datos_llamado(portal, **{campo: opcion_id}))

    borrar = f'{admin_url}/{opcion_id}/eliminar'
    assert f'data-eliminar-url="{borrar}"'.encode() in admin.get(admin_url).data
    admin_post(admin, borrar, {'confirmar': '1'}, form_url=admin_url)
    assert public.get(f'/api/concursos/{slug}').json[campo.removesuffix('_id')]['id'] == opcion_id

    libre = admin_post(admin, admin_url, {'nombre': 'Opción libre'}, expected=201, headers=headers).json
    borrar_libre = f"{admin_url}/{libre['id']}/eliminar"
    assert f'data-eliminar-url="{borrar_libre}"'.encode() in admin.get(admin_url).data
    admin_post(admin, borrar_libre, {'confirmar': '1'}, form_url=admin_url)
    assert all(opcion['id'] != libre['id'] for opcion in public.get(public_url).json)

    destino = admin_post(admin, admin_url, {'nombre': 'Opción de reemplazo'}, expected=201, headers=headers).json
    with app.app_context():
        postulacion = Postulacion(
            concurso_id=concurso_id, nombre_completo='Persona de prueba', documento='12345678',
            fecha_nacimiento=date(1995, 2, 15), email='persona@example.org', telefono='099123456',
            domicilio='Domicilio de prueba', localidad='Minas',
        )
        db.session.add(postulacion)
        db.session.commit()
        postulacion_id = postulacion.id

    for reemplazo_invalido in (opcion_id, destino['id'] + 1):
        admin_post(admin, borrar, {'confirmar': '1', 'reemplazo': reemplazo_invalido}, form_url=admin_url)
        assert public.get(f'/api/concursos/{slug}').json[campo.removesuffix('_id')]['id'] == opcion_id

    admin_post(admin, borrar, {'confirmar': '1', 'reemplazo': destino['id']}, form_url=admin_url)
    resultado = public.get(f'/api/concursos/{slug}').json
    assert resultado['id'] == concurso_id
    assert resultado[campo.removesuffix('_id')] == destino
    assert f'data-eliminar-url="{borrar}"'.encode() not in admin.get(admin_url).data
    with app.app_context():
        assert db.session.get(Postulacion, postulacion_id).concurso_id == concurso_id
        auditoria = db.session.scalars(select(ActivityLog).order_by(ActivityLog.id.desc())).first()
        assert auditoria.action.endswith('_DELETE')
        assert 'Llamados reasignados a «Opción de reemplazo»' in auditoria.details


def test_eliminar_clasificacion_es_atomico_y_permite_dejar_llamado_sin_clasificar(portal, monkeypatch):
    app, admin, public, _, _, _, _ = portal
    with app.app_context():
        clasificacion = TipoLlamado(nombre='Clasificación a eliminar', slug='clasificacion-a-eliminar')
        db.session.add(clasificacion)
        db.session.commit()
        opcion_id = clasificacion.id

    concurso_id, slug = crear_llamado(portal, tipo_llamado_id=opcion_id)
    catalogo = '/admin/concursos/tipos-llamado'
    borrar = f'{catalogo}/{opcion_id}/eliminar'
    datos = {'confirmar': '1', 'reemplazo': 'sin-clasificacion'}

    def fallo_auditoria(*args, **kwargs):
        raise IntegrityError(None, None, RuntimeError('fallo de prueba al registrar auditoría'))

    with monkeypatch.context() as cambios:
        cambios.setattr(admin_catalogos, 'log_activity', fallo_auditoria)
        admin_post(admin, borrar, datos, form_url=catalogo)
    with app.app_context():
        assert db.session.get(TipoLlamado, opcion_id) is not None
        assert db.session.get(Concurso, concurso_id).tipo_llamado_id == opcion_id

    admin_post(admin, borrar, datos, form_url=catalogo)
    assert public.get(f'/api/concursos/{slug}').json['tipo_llamado'] is None
    with app.app_context():
        assert db.session.get(TipoLlamado, opcion_id) is None


def test_filtrar_postulaciones_por_llamado_del_area(portal):
    app, admin, _, clock, _, area_id, tipo_id = portal
    with app.app_context():
        otra_area = AreaConvocante(nombre='Turismo')
        db.session.add(otra_area)
        db.session.flush()
        llamados = []
        for index, area in enumerate((area_id, area_id, otra_area.id), start=1):
            llamado = Concurso(
                titulo=f'Llamado {index}', slug=f'llamado-{index}',
                area_convocante_id=area, tipo_contratacion_id=tipo_id,
                fecha_apertura=clock[0], fecha_cierre=clock[0] + timedelta(days=1),
            )
            db.session.add(Postulacion(
                concurso=llamado, nombre_completo=f'Aspirante {index}',
                documento=f'{index:08d}', fecha_nacimiento=date(1995, 2, 15),
                email=f'aspirante-{index}@example.org', telefono='099123456',
                domicilio='Domicilio de prueba', localidad='Minas',
            ))
            llamados.append(llamado)
        db.session.commit()
        primero_id, _, otro_id = [llamado.id for llamado in llamados]

    url = '/admin/postulaciones'
    sin_area = admin.get(url, query_string={'concurso_id': primero_id})
    selector = re.search(rb'<select id="concurso_id"([^>]*)>', sin_area.data)
    assert selector[1].rstrip().endswith(b' disabled')
    assert b'Aspirante 3' in sin_area.data

    filtros = {'area_convocante_id': area_id, 'concurso_id': primero_id}
    filtrado = admin.get(url, query_string=filtros)
    options = re.search(rb'<select id="concurso_id"[^>]*>(.*?)</select>', filtrado.data, re.S)[1]
    assert f'value="{primero_id}" selected'.encode() in options
    assert b'Llamado 2' in options and b'Llamado 3' not in options
    assert b'Aspirante 1' in filtrado.data
    assert b'Aspirante 2' not in filtrado.data and b'Aspirante 3' not in filtrado.data
    assert f'concurso_id={primero_id}'.encode() in filtrado.data

    csv_url = url + '/export.csv'
    exportado = admin.get(csv_url, query_string=filtros)
    rows = list(csv.DictReader(StringIO(exportado.get_data(as_text=True))))
    assert [row['Postulante'] for row in rows] == ['Aspirante 1']

    filtros['concurso_id'] = otro_id
    exportado = admin.get(csv_url, query_string=filtros)
    assert list(csv.DictReader(StringIO(exportado.get_data(as_text=True)))) == []


def test_plazo_y_estado_publico(portal, monkeypatch):
    app, admin, public, clock, storage, _, _ = portal
    monkeypatch.setattr(api, 'send_postulacion_verification_email', lambda *_: None)
    concurso_id, slug = crear_llamado(portal)
    date = clock[0]
    apertura = date - timedelta(hours=1)
    cierre = date + timedelta(hours=1)
    url = f'/api/concursos/{slug}'
    postulaciones = '/api/concursos/postulaciones'

    clock[0] = apertura - timedelta(seconds=1)
    response = public.get(url)
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json['estado'] == 'proximo'
    assert response.json['documentos'] == []
    assert response.json['ms_hasta_cambio_estado'] == 1_000
    assert public.get('/api/concursos?estado=abierto').json['total'] == 0
    assert public.get('/api/concursos?estado=proximo').json['items'][0]['ms_hasta_cambio_estado'] == 1_000
    assert b'1 pr\xc3\xb3ximos &middot; 0 finalizados' in admin.get('/admin/').data
    assert public.post(postulaciones, data=datos_postulacion(concurso_id)).status_code == 422
    assert not storage.objects

    clock[0] = apertura
    detail = public.get(url).json
    assert detail['estado'] == 'abierto'
    assert detail['fecha_cierre'].endswith('-03:00')
    assert detail['ms_hasta_cambio_estado'] == 7_200_000
    assert detail['documentos'][-1]['kind'] == 'postulacion'
    assert public.get('/api/concursos?estado=abierto').json['total'] == 1
    assert public.post(postulaciones, data=datos_postulacion(concurso_id)).status_code == 201
    assert len(storage.objects) == 2

    clock[0] = cierre - timedelta(seconds=1)
    assert public.get(url).json['ms_hasta_cambio_estado'] == 1_000
    clock[0] = cierre
    detail = public.get(url).json
    assert detail['estado'] == 'en_proceso' and detail['ms_hasta_cambio_estado'] is None
    assert detail['documentos'] == []
    stats = public.get('/api/concursos/estadisticas').json
    assert stats['abiertos'] == 0 and stats['en_proceso'] == 1
    assert b'0 abiertos &middot; 1 en proceso' in admin.get('/admin/').data
    assert b'Estado actual <strong class="text-white">En proceso</strong>' in admin.get(f'/admin/concursos/{concurso_id}/edit').data
    assert b'No disponible' in admin.get('/admin/concursos?estado=en_proceso').data
    assert public.post(postulaciones, data=datos_postulacion(concurso_id)).status_code == 422
    assert len(storage.objects) == 2
    with app.app_context():
        assert db.session.get(Concurso, concurso_id).estado == Concurso.ESTADO_ABIERTO


def test_plazo_respeta_proximo_y_suspendido_configurados(portal):
    _, admin, public, clock, _, _, _ = portal
    concurso_id, slug = crear_llamado(portal, estado='proximo')
    clock[0] += timedelta(hours=2)
    detail_url = f'/api/concursos/{slug}'
    detail = public.get(detail_url).json
    assert detail['estado'] == 'proximo' and detail['ms_hasta_cambio_estado'] is None

    admin_post(admin, f'/admin/concursos/{concurso_id}/edit', datos_llamado(portal, estado='suspendido'))
    detail = public.get(detail_url).json
    assert detail['estado'] == 'suspendido' and detail['ms_hasta_cambio_estado'] is None
    assert public.post('/api/concursos/postulaciones', data=datos_postulacion(concurso_id)).status_code == 422


def test_recuperar_correo_y_confirmar_sin_duplicados(portal, monkeypatch):
    app, _, public, _, storage, _, _ = portal
    concurso_id, _ = crear_llamado(portal)
    creation = '/api/concursos/postulaciones'
    verification = f'{creation}/verificar-email'
    resend = f'{creation}/reenviar-confirmacion'

    missing_file = datos_postulacion(concurso_id)
    del missing_file['cedula']
    assert public.post(creation, data=missing_file).status_code == 422
    invalid_file = datos_postulacion(concurso_id)
    invalid_file['cedula'] = (BytesIO(b'archivo no permitido'), 'cedula.txt')
    assert public.post(creation, data=invalid_file).status_code == 422
    assert storage.objects == {}

    def unavailable(*_):
        raise OSError('SMTP simulado sin conexión')

    monkeypatch.setattr(api, 'send_postulacion_verification_email', unavailable)
    response = public.post(creation, data=datos_postulacion(concurso_id))
    assert response.status_code == 201
    assert not response.json['verification_email_sent']
    assert public.post(creation, data=datos_postulacion(concurso_id)).status_code == 409
    assert len(storage.objects) == 2
    identidad = {'concurso_id': concurso_id, 'email': 'aspirante@example.org', 'documento': '12345678'}
    assert public.post(resend, data=identidad).status_code == 503

    links = []
    monkeypatch.setattr(api, 'send_postulacion_verification_email', lambda _, link: links.append(link))
    monkeypatch.setattr(api, 'send_postulacion_email', lambda _: None)
    assert public.post(resend, data=identidad).status_code == 200
    params = {key: value[0] for key, value in parse_qs(urlsplit(links[-1]).fragment).items()}
    assert public.get(verification, query_string=params).status_code == 405
    with app.app_context():
        postulacion = db.session.scalar(select(Postulacion))
        assert postulacion.estado == 'preinscripta'
        postulacion.email_verification_sent_at -= timedelta(hours=25)
        db.session.commit()

    assert public.post(verification, data=params).status_code == 410
    assert public.post(resend, data=identidad).status_code == 200
    nuevo_enlace = {key: value[0] for key, value in parse_qs(urlsplit(links[-1]).fragment).items()}
    assert public.post(verification, data=params).status_code == 400
    confirmed = public.post(verification, data=nuevo_enlace)
    assert confirmed.status_code == 200
    code = confirmed.json['tracking_code']
    assert confirmed.json['completion_email_sent']
    assert public.post(verification, data=nuevo_enlace).json['tracking_code'] == code
    assert public.post(verification, data={**nuevo_enlace, 'token': 'incorrecto'}).status_code == 400
    assert public.get(f'{creation}/seguimiento/{code}').json['estado_raw'] == 'recibida'


@pytest.mark.parametrize(('campo_pdf', 'documento_id'), [
    ('bases_concurso_pdf', 'bases-concurso'),
    ('bases_llamado_pdf', 'bases-llamado'),
    ('anexo_pdf', 'anexo-declaracion-jurada'),
])
def test_detalle_verifica_el_pdf_de_cada_documento(portal, campo_pdf, documento_id):
    _, _, public, _, storage, _, _ = portal
    _, slug = crear_llamado(
        portal,
        bases_concurso_html='<p>Bases del concurso</p>',
        bases_llamado_html='<p>Bases del llamado</p>',
        anexo_declaracion_jurada_html='<p>Resolución</p>',
        **{campo_pdf: (BytesIO(PDF), 'oficial.pdf')},
    )
    url = f'/api/concursos/{slug}'
    pdf_url = f'{url}/documentos/{documento_id}/pdf'
    documents = public.get(url).json['documentos']
    assert {doc['id'] for doc in documents if doc['kind'] == 'page'} == {
        'bases-concurso', 'bases-llamado', 'anexo-declaracion-jurada',
    }
    assert {doc['id']: doc['download_url'] for doc in documents if doc['download_url']} == {
        documento_id: pdf_url,
    }
    assert public.get(pdf_url).data == PDF

    bucket, key = next(iter(storage.objects))
    storage.remove_object(bucket, key)
    documents = public.get(url).json['documentos']
    assert all(doc['download_url'] is None for doc in documents)
    assert documents[-1]['kind'] == 'postulacion'


def test_detalle_verifica_pdf_estatico(portal, tmp_path):
    app, _, public, _, _, _, _ = portal
    concurso_id, slug = crear_llamado(portal, postulacion_web_habilitada='')
    app.static_folder = tmp_path
    pdf = tmp_path / 'bases.pdf'
    pdf.write_bytes(PDF)
    source = '/public/bases.pdf'
    with app.app_context():
        db.session.get(Concurso, concurso_id).bases_url = source
        db.session.commit()

    url = f'/api/concursos/{slug}'
    documents = public.get(url).json['documentos']
    assert len(documents) == 1
    assert documents[0]['download_url'] == source
    assert public.get(source).data == PDF

    pdf.unlink()
    detail = public.get(url).json
    assert detail['documentos'] == []
    assert detail['bases_url'] is None


def test_borrador_publicacion_y_adjuntos_por_etapa(portal):
    app, admin, public, _, _, _, _ = portal
    concurso_id, slug = crear_llamado(
        portal, estado='borrador', bases_llamado_pdf=(BytesIO(PDF), 'bases.pdf'),
    )
    url = f'/api/concursos/{slug}'
    assert public.get(url).status_code == 404
    assert public.get(f'{url}/documentos/bases-llamado/pdf').status_code == 404
    assert public.get('/api/concursos').json['total'] == 0

    admin_url = f'/admin/concursos/{concurso_id}'
    assert admin.get(f'{admin_url}/documentos/bases-llamado/pdf').data == PDF
    admin_post(admin, f'{admin_url}/actualizaciones', {
        'etapa': 'homologacion', 'titulo': 'Resolución de la etapa',
        'descripcion': 'Comunicado de prueba', 'fecha': '2026-11-24',
        'publicada': 'on', 'pdf': (BytesIO(PDF), 'resolucion.pdf'),
    })
    with app.app_context():
        update_id = db.session.scalar(select(ConcursoActualizacion.id))
    assert public.get(f'{url}/actualizaciones/{update_id}/pdf').status_code == 404
    assert admin.get(f'{admin_url}/actualizaciones/{update_id}/pdf').data == PDF

    admin_post(admin, f'{admin_url}/edit', datos_llamado(portal))
    detail = public.get(url).json
    assert detail['documentacion_requerida'] == '<ul><li>Constancia de prueba</li></ul>'
    assert detail['actualizaciones'][0]['titulo'] == 'Resolución de la etapa'
    assert public.get(detail['actualizaciones'][0]['pdf_url']).data == PDF
    assert public.get(f'{url}/documentos/bases-llamado/pdf').data == PDF

    admin_post(admin, f'{admin_url}/edit', datos_llamado(
        portal, bases_llamado_pdf=(BytesIO(b'invalido'), 'bases.pdf'),
    ), expected=422)
    assert public.get(f'{url}/documentos/bases-llamado/pdf').data == PDF

    form = datos_llamado(portal)
    del form['postulacion_web_habilitada']
    admin_post(admin, f'{admin_url}/edit', form)
    assert not public.get(url).json['postulacion_web_habilitada']

    admin_post(admin, f'{admin_url}/actualizaciones/{update_id}', {
        'etapa': 'homologacion', 'titulo': 'Resolución de la etapa',
        'descripcion': 'Comunicado de prueba', 'fecha': '2026-11-24',
    })
    assert public.get(url).json['actualizaciones'] == []
    assert public.get(f'{url}/actualizaciones/{update_id}/pdf').status_code == 404
