# Lavalleja Concursa · Backend

API de concursos y postulaciones y panel de administración en `/admin`. El contenedor ejecuta las migraciones de MariaDB y arranca Gunicorn en el puerto interno **5000**.

## Coolify

| Ajuste | Valor |
| --- | --- |
| Repositorio | `IntendenciaDeLavalleja/concursa-backend` |
| Rama | `main` |
| Build Pack | Dockerfile |
| Base Directory | `/` |
| Dockerfile Location | `/Dockerfile` |
| Puerto interno | `5000` |
| Health Check | `GET /health` |
| Dominio | Subdominio HTTPS del backend |

Configurá las variables en **Environment Variables** con alcance **Runtime**. Usá [el ejemplo](.env.example) para ver las claves. Las credenciales deben quedar en las variables de Coolify. Para valores que contienen signos de dólar, activá **Literal**.

- Conservá `SECRET_KEY` entre despliegues para mantener las sesiones. `WTF_CSRF_SECRET_KEY` es opcional.
- En `FRONTEND_URL` poné el origen HTTPS del frontend, como `https://concursa.example.org`. Se usa para los enlaces de confirmación y como origen permitido por CORS. Si definís `CORS_ORIGINS`, indicá la lista completa de orígenes permitidos separados por comas, incluido el del frontend.
- Para MariaDB usá `DATABASE_URL` o `DATABASE_URI`. Si ambas están definidas, tiene prioridad `DATABASE_URL`. Codificá los caracteres especiales de usuario y contraseña si los incluís en la URL. También podés definir `MARIADB_HOST`, `MARIADB_USER`, `MARIADB_PASSWORD` y `MARIADB_DATABASE`. Usá una base persistente accesible desde la red de la aplicación.
- Cargá los valores `MAIL_*` del SMTP institucional. Activá solo uno de `MAIL_USE_TLS` y `MAIL_USE_SSL` según el proveedor. El remitente indicado en `MAIL_DEFAULT_SENDER` tiene que estar autorizado.
- Configurá las credenciales, el endpoint y el bucket de MinIO. El backend verifica el almacenamiento al iniciar. La cuenta de servicio necesita acceso al bucket y a su política.
- Configurá `REDIS_URL` para compartir límites de uso y caché entre los procesos de Gunicorn. También se admiten `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` y `REDIS_PASSWORD`.
- Los valores del contenedor asumen HTTPS y un proxy directo de Coolify. `SESSION_COOKIE_SECURE=True` protege la sesión del panel y `PROXY_FIX_X_FOR=1` toma la IP a través de ese proxy. Ajustá el conteo si hay otra capa de proxy de confianza.

El frontend usa la URL de este backend en `VITE_BACKEND_URL`. El acceso administrativo se hace en `https://API_DOMINIO/admin/` usando el subdominio del backend. [Repositorio del frontend](https://github.com/IntendenciaDeLavalleja/concursa-frontend)

En una instalación nueva podés crear el primer super administrador desde la terminal de la aplicación. El comando pide la contraseña de manera interactiva.

```sh
flask --app 'app:create_app()' create-admin USUARIO CORREO --super-admin
```

Si reutilizás una base existente, conservá su revisión de Alembic y respaldá la base y el bucket antes del primer despliegue.

## Desarrollo

Usá Python 3.12. Flask lee `.env` desde el entorno local. Para HTTP directo usá `SESSION_COOKIE_SECURE=False` y `PROXY_FIX_X_FOR=0`.

```sh
python -m pip install -r requirements.txt
flask --app wsgi db upgrade
flask --app wsgi run
```

```sh
python -m pytest -q
```
