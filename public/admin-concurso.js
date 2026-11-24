function iniciarVerificacionSlug() {
    const titulo = document.getElementById('titulo');
    const slug = document.getElementById('slug');
    const estado = document.getElementById('slug-estado');
    let sugerirDesdeTitulo = slug.dataset.sugerirDesdeTitulo === 'true' && !slug.value;
    let temporizador;
    let verificacion;

    function mostrarEstado(mensaje = '', resultado = '') {
        const invalido = resultado === 'error';
        slug.setCustomValidity(invalido ? mensaje : '');
        slug.setAttribute('aria-invalid', String(invalido));
        slug.setAttribute('aria-describedby', invalido ? 'slug-ayuda slug-estado' : 'slug-ayuda');
        estado.dataset.estado = resultado;
        estado.textContent = mensaje;
    }

    async function verificar(valor, esSugerencia) {
        verificacion = new AbortController();
        const { signal } = verificacion;
        const url = new URL(slug.dataset.urlVerificacion, window.location.origin);
        url.searchParams.set('slug', valor);
        mostrarEstado('Verificando disponibilidad…');

        try {
            const respuesta = await fetch(url, { signal, headers: { Accept: 'application/json' } });
            if (!respuesta.ok) throw new Error();
            const resultado = await respuesta.json();
            if (signal.aborted) return;

            if (esSugerencia) slug.value = resultado.slug;
            if (resultado.disponible) {
                mostrarEstado(`Slug disponible. /concursos/${resultado.slug}`, 'disponible');
            } else {
                mostrarEstado(resultado.mensaje, 'error');
            }
        } catch {
            if (!signal.aborted) {
                mostrarEstado('No se pudo verificar ahora. La disponibilidad se comprobará al guardar.');
            }
        }
    }

    function programarVerificacion() {
        window.clearTimeout(temporizador);
        verificacion?.abort();
        mostrarEstado();
        const esSugerencia = sugerirDesdeTitulo;
        const valor = (esSugerencia ? titulo.value : slug.value).trim();
        if (valor) {
            temporizador = window.setTimeout(() => verificar(valor, esSugerencia), 400);
        }
    }

    titulo.addEventListener('input', () => {
        if (sugerirDesdeTitulo) {
            slug.value = '';
            programarVerificacion();
        }
    });
    slug.addEventListener('input', () => {
        sugerirDesdeTitulo = false;
        programarVerificacion();
    });

    if (estado.dataset.estado === 'error') {
        slug.setCustomValidity(estado.textContent);
    } else {
        programarVerificacion();
    }
}

function iniciarAltaCatalogo() {
    const dialogo = document.getElementById('alta-catalogo-dialog');
    if (typeof dialogo?.showModal !== 'function') return;

    const titulo = document.getElementById('alta-catalogo-titulo');
    const formulario = document.getElementById('alta-catalogo-form');
    const nombre = document.getElementById('alta-catalogo-nombre');
    const estado = document.getElementById('alta-catalogo-estado');
    const confirmacion = document.getElementById('alta-catalogo-confirmacion');
    const guardar = document.getElementById('alta-catalogo-guardar');
    let apertura;

    for (const enlace of document.querySelectorAll('[data-alta-catalogo]')) {
        enlace.setAttribute('aria-haspopup', 'dialog');
        enlace.addEventListener('click', (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            apertura = { selector: document.getElementById(enlace.dataset.altaCatalogo) };
            formulario.reset();
            formulario.action = enlace.href;
            nombre.maxLength = Number(enlace.dataset.maxlength);
            titulo.textContent = enlace.dataset.titulo;
            estado.textContent = '';
            confirmacion.textContent = '';
            guardar.disabled = false;
            dialogo.showModal();
        });
    }

    formulario.addEventListener('input', () => {
        estado.textContent = '';
    });
    formulario.addEventListener('submit', async (event) => {
        event.preventDefault();
        const intento = apertura;
        const sigueAbierto = () => dialogo.open && apertura === intento;
        const datos = new FormData(formulario);
        guardar.disabled = true;
        estado.textContent = '';

        try {
            const respuesta = await fetch(formulario.action, {
                method: 'POST',
                headers: { Accept: 'application/json' },
                body: datos,
            });
            const opcion = await respuesta.json();
            if (!respuesta.ok) {
                if (sigueAbierto()) estado.textContent = opcion.mensaje;
                return;
            }

            const nuevo = new Option(opcion.nombre, String(opcion.id));
            intento.selector.add(nuevo);
            if (sigueAbierto()) {
                nuevo.selected = true;
                dialogo.close();
                confirmacion.textContent = `Se agregó y seleccionó «${opcion.nombre}».`;
            }
        } catch {
            if (sigueAbierto()) {
                estado.textContent = 'No pudimos guardar la opción. Volvé a intentar.';
            }
        } finally {
            if (apertura === intento) guardar.disabled = false;
        }
    });
}

iniciarVerificacionSlug();
iniciarAltaCatalogo();
