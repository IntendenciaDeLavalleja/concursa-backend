import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import create_app
from app.admin.routes_components import auth
from app.extensions import db
from app.models.concurso import AreaConvocante, Concurso, TipoContratacion, TipoLlamado
from app.models.user import ActivityLog, AdminUser, TwoFactorCode
from app.models.violeta import BlogPost


class Settings:
    TESTING = True
    SECRET_KEY = 'test-alta-usuarios'
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    RATELIMIT_ENABLED = False


@pytest.fixture
def portal():
    app = create_app(Settings)
    with app.app_context():
        with db.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys = ON')
        db.create_all()
        super_admin = AdminUser(username='Super Admin de prueba', email='Super@EXAMPLE.ORG', is_superuser=True)
        admin = AdminUser(username='Admin de prueba', email='admin@example.org')
        db.session.add_all([super_admin, admin])
        db.session.commit()
        super_id, admin_id = super_admin.id, admin.id

    super_client = app.test_client()
    admin_client = app.test_client()
    for client, user_id in ((super_client, super_id), (admin_client, admin_id)):
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    return app, super_client, admin_client, super_id


def csrf(response):
    return re.search(rb'name="csrf_token" value="([^"]+)"', response.data)[1].decode()


def test_solo_super_admin_accede_y_crea_cuentas(portal):
    app, super_client, admin_client, _ = portal
    url = '/admin/users'
    assert app.test_client().get(url).status_code == 302
    assert b'href="/admin/users"' not in admin_client.get('/admin/').data
    assert admin_client.get(url).status_code == 403
    form = {
        'username': 'Alta bloqueada', 'email': 'alta@example.org',
        'password': 'Prueba1234', 'role': 'super_admin',
    }
    assert super_client.post(url, data=form).status_code == 400
    token = csrf(admin_client.get('/admin/concursos/nuevo'))
    assert admin_client.post(url, data={**form, 'csrf_token': token}).status_code == 403
    assert b'href="/admin/users"' in super_client.get(url).data
    with app.app_context():
        assert AdminUser.query.count() == 2


def test_catalogos_y_sus_acciones_son_exclusivos_del_super_admin(portal):
    app, super_client, admin_client, _ = portal
    opciones = (
        ('areas', 'area_convocante_id', AreaConvocante(nombre='Área existente')),
        ('tipos-vinculo', 'tipo_contratacion_id', TipoContratacion(nombre='Vínculo existente')),
        ('tipos-llamado', 'tipo_llamado_id', TipoLlamado(nombre='Clasificación existente', slug='clasificacion-existente')),
    )
    with app.app_context():
        db.session.add_all(opcion for _, _, opcion in opciones)
        db.session.commit()
        referencias = [(clave, campo, type(opcion), opcion.id, opcion.nombre) for clave, campo, opcion in opciones]

    nuevo = '/admin/concursos/nuevo'
    editor = admin_client.get(nuevo)
    assert editor.status_code == 200
    assert b'data-alta-catalogo' not in editor.data and b'alta-catalogo-dialog' not in editor.data
    assert super_client.get(nuevo).data.count(b'data-alta-catalogo') == 3
    sesion = {'csrf_token': csrf(editor)}

    for vista in ('/admin/', '/admin/concursos', '/admin/postulaciones'):
        pantalla = admin_client.get(vista)
        assert pantalla.status_code == 200
        assert 'Catálogos de concursos'.encode() not in pantalla.data
        assert b'Administrar cat' not in pantalla.data and b'Clasificaciones activas' not in pantalla.data

    for clave, campo, _, opcion_id, nombre in referencias:
        url = f'/admin/concursos/{clave}'
        assert f'>{nombre}</option>'.encode() in editor.data
        assert app.test_client().get(url).status_code == 302
        assert admin_client.get(url).status_code == 403
        assert admin_client.get(url, query_string={'edit': opcion_id}).status_code == 403
        gestion = super_client.get(url)
        assert gestion.status_code == 200 and gestion.headers['Cache-Control'] == 'private, no-store'

        alta = {**sesion, 'nombre': 'Alta bloqueada'}
        assert admin_client.post(url, data=alta, headers={'Accept': 'application/json'}).status_code == 403
        assert admin_client.post(url, data={**alta, campo: opcion_id}).status_code == 403
        assert admin_client.post(f'{url}/{opcion_id}/toggle', data=sesion).status_code == 403
        assert admin_client.post(f'{url}/{opcion_id}/eliminar', data={**sesion, 'confirmar': '1'}).status_code == 403

    datos_llamado = {
        **sesion,
        **{campo: opcion_id for _, campo, _, opcion_id, _ in referencias},
        'titulo': 'Llamado de admin común', 'cantidad_cargos': '1',
        'fecha_apertura': '2026-11-24T09:00', 'fecha_cierre': '2026-11-25T09:00',
    }
    assert admin_client.post(nuevo, data=datos_llamado).status_code == 302
    with app.app_context():
        concurso = Concurso.query.one()
        concurso_id = concurso.id
        for _, campo, modelo, opcion_id, nombre in referencias:
            opcion = modelo.query.one()
            assert (opcion.id, opcion.nombre, opcion.is_active) == (opcion_id, nombre, True)
            assert getattr(concurso, campo) == opcion_id

    edicion = admin_client.get(f'/admin/concursos/{concurso_id}/edit')
    assert edicion.status_code == 200 and b'data-alta-catalogo' not in edicion.data


@pytest.mark.parametrize(('rol', 'es_super'), [(None, False), ('super_admin', True)])
def test_alta_auditada_y_acceso_con_2fa(portal, monkeypatch, rol, es_super):
    app, super_client, _, super_id = portal
    url = '/admin/users'
    password = 'PruebaNueva1234'
    payload = {
        'csrf_token': csrf(super_client.get(url)),
        'username': 'Cuenta nueva',
        'email': 'Nueva@EXAMPLE.ORG',
        'password': password,
    }
    if rol is not None:
        payload['role'] = rol
    created = super_client.post(url, data=payload)
    assert created.status_code == 302 and created.location == url
    assert b'nueva@example.org' in super_client.get(url).data
    with app.app_context():
        cuenta = db.session.scalar(select(AdminUser).where(AdminUser.email == 'nueva@example.org'))
        assert cuenta.is_active and cuenta.is_superuser == es_super
        assert cuenta.password_hash != password and cuenta.check_password(password)
        entry = db.session.scalar(select(ActivityLog).where(ActivityLog.action == 'ADMIN_USER_CREATE'))
        assert entry.user_id == super_id and f'#{cuenta.id}' in entry.details
        assert password not in entry.details

    codigos = {}
    monkeypatch.setattr(auth, 'send_2fa_email', lambda email, codigo: codigos.update({email: codigo}))
    cuenta_client = app.test_client()
    login = cuenta_client.get('/admin/login')
    question = re.search(rb'(\d+) \+ (\d+)\?', login.data)
    paso1 = cuenta_client.post('/admin/login', data={
        'csrf_token': csrf(login), 'email': 'Nueva@EXAMPLE.ORG',
        'password': password, 'captcha': sum(map(int, question.groups())),
    })
    assert paso1.location == '/admin/verify-2fa'
    paso2 = cuenta_client.post(paso1.location, data={
        'csrf_token': csrf(cuenta_client.get(paso1.location)),
        'code': codigos['nueva@example.org'],
    })
    assert paso2.location == '/admin/'
    assert cuenta_client.get(url).status_code == (200 if es_super else 403)


def test_alta_valida_datos_y_rechaza_duplicados(portal):
    app, super_client, _, _ = portal
    url = '/admin/users'
    token = csrf(super_client.get(url))
    password = 'SoloLetras'
    invalid = super_client.post(url, data={
        'csrf_token': token, 'username': ' ', 'email': 'correo incorrecto',
        'password': password, 'role': 'otro_rol',
    })
    assert invalid.status_code == 422
    assert b'username-error' in invalid.data and b'email-error' in invalid.data
    assert b'password-error' in invalid.data and b'role-error' in invalid.data
    assert password.encode() not in invalid.data

    duplicate = super_client.post(url, data={
        'csrf_token': token, 'username': 'Otro usuario', 'email': 'SUPER@EXAMPLE.ORG',
        'password': 'Prueba1234', 'role': 'admin',
    })
    assert duplicate.status_code == 422
    assert b'Ya existe un usuario' in duplicate.data

    duplicate_name = super_client.post(url, data={
        'csrf_token': token, 'username': 'Super Admin de prueba', 'email': 'otro@example.org',
        'password': 'Prueba1234', 'role': 'admin',
    })
    assert duplicate_name.status_code == 422
    assert b'Ya existe un usuario con ese nombre o correo' in duplicate_name.data
    with app.app_context():
        assert AdminUser.query.count() == 2
        assert ActivityLog.query.filter_by(action='ADMIN_USER_CREATE').count() == 0


def test_solo_super_admin_puede_editar_o_eliminar(portal):
    app, super_client, admin_client, super_id = portal
    token_admin = csrf(admin_client.get('/admin/concursos/nuevo'))
    editar = f'/admin/users/{super_id}/edit'
    eliminar = f'/admin/users/{super_id}/delete'

    for url in (editar, eliminar):
        assert app.test_client().get(url).status_code == 302
        assert admin_client.get(url).status_code == 403
        assert admin_client.post(url, data={'csrf_token': token_admin, 'confirmar': '1'}).status_code == 403

    listado = super_client.get('/admin/users')
    token_super = csrf(listado)
    assert eliminar.encode() not in listado.data
    assert super_client.get(eliminar).status_code == 403
    assert super_client.post(eliminar, data={'csrf_token': token_super, 'confirmar': '1'}).status_code == 403

    intento = super_client.post(editar, data={
        'csrf_token': token_super, 'username': 'Super Admin de prueba',
        'email': 'Super@EXAMPLE.ORG', 'role': 'admin',
    })
    assert intento.status_code == 422 and b'role-error' in intento.data
    with app.app_context():
        assert db.session.get(AdminUser, super_id).is_superuser
        assert AdminUser.query.count() == 2
        assert ActivityLog.query.count() == 0


def test_edita_usuario_y_revoca_codigos_pendientes(portal):
    app, super_client, admin_client, super_id = portal
    with app.app_context():
        usuario = AdminUser.query.filter_by(email='admin@example.org').one()
        usuario.set_password('ClaveInicial123')
        pendiente = TwoFactorCode(usuario.id, '123456')
        usado = TwoFactorCode(usuario.id, '654321')
        usado.consumed_at = datetime(2026, 11, 24, 10)
        db.session.add_all([pendiente, usado])
        db.session.commit()
        usuario_id, pendiente_id, usado_id = usuario.id, pendiente.id, usado.id
        hash_inicial = usuario.password_hash

    editar = f'/admin/users/{usuario_id}/edit'
    formulario = super_client.get(editar)
    assert formulario.status_code == 200
    assert b'Editar usuario' in formulario.data and b'value="admin@example.org"' in formulario.data
    assert hash_inicial.encode() not in formulario.data
    datos = {
        'csrf_token': csrf(formulario), 'username': 'Nombre nuevo', 'email': 'admin@example.org',
    }
    assert super_client.post(editar, data={**datos, 'csrf_token': ''}).status_code == 400
    assert super_client.post(editar, data=datos).status_code == 302
    with app.app_context():
        usuario = db.session.get(AdminUser, usuario_id)
        assert usuario.username == 'Nombre nuevo' and usuario.password_hash == hash_inicial
        assert db.session.get(TwoFactorCode, pendiente_id) is not None

    duplicado = super_client.post(editar, data={**datos, 'email': 'SUPER@EXAMPLE.ORG'})
    assert duplicado.status_code == 422 and b'email-error' in duplicado.data
    clave_invalida = 'SoloLetras'
    invalido = super_client.post(editar, data={**datos, 'password': clave_invalida})
    assert invalido.status_code == 422 and b'password-error' in invalido.data
    assert clave_invalida.encode() not in invalido.data

    nueva_clave = 'ClaveNueva123'
    aceptado = super_client.post(editar, data={
        **datos, 'email': 'Nuevo@EXAMPLE.ORG', 'password': nueva_clave, 'role': 'super_admin',
    })
    assert aceptado.status_code == 302 and aceptado.location == '/admin/users'
    assert b'Usuario actualizado.' in super_client.get(aceptado.location).data
    assert admin_client.get('/admin/users').status_code == 200
    with app.app_context():
        usuario = db.session.get(AdminUser, usuario_id)
        assert usuario.email == 'nuevo@example.org' and usuario.is_superuser
        assert usuario.password_hash != hash_inicial and usuario.check_password(nueva_clave)
        assert db.session.get(TwoFactorCode, pendiente_id) is None
        assert db.session.get(TwoFactorCode, usado_id) is not None
        entradas = ActivityLog.query.filter_by(action='ADMIN_USER_UPDATE').all()
        assert len(entradas) == 2
        assert all(entrada.user_id == super_id and nueva_clave not in entrada.details for entrada in entradas)


def test_eliminar_usuario_con_confirmacion_preserva_registros(portal):
    app, super_client, admin_client, super_id = portal
    with app.app_context():
        usuario = AdminUser.query.filter_by(email='admin@example.org').one()
        usuario.is_superuser = True
        area = AreaConvocante(nombre='Deportes')
        vinculo = TipoContratacion(nombre='Contrato de prueba')
        db.session.add_all([area, vinculo])
        db.session.flush()
        apertura = datetime(2026, 11, 24, 10)
        llamado = Concurso(
            titulo='Llamado de prueba', slug='llamado-de-prueba', author=usuario,
            area_convocante_id=area.id, tipo_contratacion_id=vinculo.id,
            fecha_apertura=apertura, fecha_cierre=apertura + timedelta(days=1),
        )
        articulo = BlogPost(title='Artículo de prueba', slug='articulo-de-prueba', author=usuario)
        historial = ActivityLog(owner=usuario, username=usuario.username, action='ADMIN_LOGIN_2FA_SUCCESS')
        codigo = TwoFactorCode(usuario.id, '123456')
        db.session.add_all([llamado, articulo, historial, codigo])
        db.session.commit()
        usuario_id, llamado_id, articulo_id, historial_id, codigo_id = (
            usuario.id, llamado.id, articulo.id, historial.id, codigo.id,
        )

    eliminar = f'/admin/users/{usuario_id}/delete'
    listado = super_client.get('/admin/users')
    assert b'aria-label="Eliminar a Admin de prueba"' in listado.data
    assert b'id="eliminar-usuario-dialog"' in listado.data
    assert admin_client.get('/admin/').status_code == 200
    aviso = super_client.get(eliminar)
    assert aviso.status_code == 200
    assert b'<strong>Admin de prueba</strong>' in aviso.data
    assert b'Esta acci\xc3\xb3n es permanente.' in aviso.data
    token = csrf(aviso)
    assert super_client.post(eliminar, data={'confirmar': '1'}).status_code == 400
    assert super_client.post(eliminar, data={'csrf_token': token}).status_code == 400
    with app.app_context():
        assert db.session.get(AdminUser, usuario_id) is not None

    respuesta = super_client.post(eliminar, data={'csrf_token': token, 'confirmar': '1'})
    assert respuesta.status_code == 302 and respuesta.location == '/admin/users'
    actualizado = super_client.get(respuesta.location)
    assert b'Se elimin\xc3\xb3 el usuario' in actualizado.data and eliminar.encode() not in actualizado.data
    assert admin_client.get('/admin/').status_code == 302
    assert super_client.post(eliminar, data={'csrf_token': token, 'confirmar': '1'}).status_code == 404
    with app.app_context():
        assert db.session.get(AdminUser, usuario_id) is None
        assert db.session.get(TwoFactorCode, codigo_id) is None
        assert db.session.get(Concurso, llamado_id).author_id is None
        assert db.session.get(BlogPost, articulo_id).author_id is None
        entrada_previa = db.session.get(ActivityLog, historial_id)
        assert entrada_previa.username == 'Admin de prueba' and entrada_previa.user_id is None
        entrada_baja = ActivityLog.query.filter_by(action='ADMIN_USER_DELETE').one()
        assert entrada_baja.user_id == super_id and f'#{usuario_id} (Admin de prueba)' in entrada_baja.details
