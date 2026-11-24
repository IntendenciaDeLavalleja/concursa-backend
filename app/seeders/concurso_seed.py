# flake8: noqa
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

from app.extensions import db
from app.models.concurso import AreaConvocante, Concurso, Postulacion, TipoContratacion, TipoLlamado, ahora_en_uruguay


AREA_DEFINITIONS = [
    ("Dirección General de Gestión Humana y Recursos Materiales", "Gestión de personal y recursos materiales de la Intendencia."),
    ("Dirección General de Hacienda", "Gestión presupuestal, recaudación, tributos y atención al contribuyente."),
    ("Dirección General de Servicios Técnicos", "Obras, vialidad, apoyo técnico, mantenimiento y coordinación operativa."),
    ("Dirección General de Tránsito", "Control, educación vial, fiscalización y ordenamiento del tránsito."),
    ("Dirección General de Higiene", "Limpieza urbana, gestión de residuos y servicios de apoyo territorial."),
    ("Dirección General de Cultura", "Programación cultural, patrimonio, talleres y apoyo a instituciones culturales."),
    ("Dirección General de Servicios Sociales", "Programas sociales, acompañamiento territorial y articulación comunitaria."),
    ("Dirección General de Ordenamiento Urbano y Territorial", "Planificación, habilitaciones, catastro y control urbano."),
    ("Área Turismo", "Promoción turística, gestión de destinos y atención al visitante."),
    ("Área Familia y Género", "Prevención, orientación, acompañamiento y políticas de cuidados."),
    ("Área Desarrollo Agropecuario", "Asistencia técnica, sanidad animal y desarrollo productivo rural."),
    ("Área Medioambiente", "Educación ambiental, gestión de impactos y sostenibilidad."),
    ("Área Descentralización", "Coordinación con municipios, territorios y participación ciudadana."),
    ("Área Desarrollo Organizacional", "Procesos internos, modernización, recursos humanos y soporte tecnológico."),
    ("Área Promoción y Desarrollo", "Empleo, apoyo a emprendedores, inversión y promoción territorial."),
    ("Área Deporte", "Programas deportivos, coordinación de gimnasios, torneos y actividades barriales."),
    ("Área Juventud", "Programas juveniles, participación, talleres y acompañamiento a centros juveniles."),
    ("Área Prensa", "Comunicación institucional, contenido digital, cobertura y difusión pública."),
]

TYPE_DEFINITIONS = [
    ("Contrato de Función Pública", "Vinculación para tareas permanentes o de carrera administrativa según normativa vigente."),
    ("Zafral", "Contratación temporaria para períodos de alta demanda o temporada alta."),
    ("Arrendamiento de Obra", "Servicios profesionales con entregables o productos definidos por contrato."),
    ("Pasantía", "Práctica formativa para estudiantes o egresados recientes con tutoría institucional."),
    ("Beca", "Apoyo formativo para capacitación y primera experiencia laboral en áreas estratégicas."),
]

TIPO_LLAMADO_DEFINITIONS = [
    ("Interno", "Convocatorias dirigidas al personal que cumpla las condiciones de las bases."),
    ("Función Pública", "Llamados para ingreso o cobertura de cargos dentro de la estructura funcional departamental."),
    ("Zafral", "Llamados orientados a tareas temporales, de temporada o refuerzo operativo puntual."),
    ("Arrendamiento de Obra", "Llamados para contratación por obra, proyecto o entregables definidos."),
    ("Pasantía", "Llamados de carácter formativo para estudiantes o perfiles de inicio profesional."),
    ("Beca", "Llamados de apoyo formativo o inserción inicial vinculados a becas institucionales."),
]

TIPO_LLAMADO_BY_CONTRATACION = {
    'Contrato de Función Pública': 'Función Pública',
    'Zafral': 'Zafral',
    'Arrendamiento de Obra': 'Arrendamiento de Obra',
    'Pasantía': 'Pasantía',
    'Beca': 'Beca',
}

ROLE_TEMPLATES = {
    "administrativo": {
        "perfil": "Persona organizada, con criterio para el manejo de expedientes, atención al público y trabajo bajo procedimientos.",
        "tareas": [
            "atención presencial y telefónica a usuarios internos y externos",
            "ingreso, control y archivo de documentación",
            "confección de planillas, notas y reportes de gestión",
            "apoyo en derivación de trámites y seguimiento de expedientes",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "enseñanza media completa o equivalente",
            "manejo básico de herramientas informáticas",
            "buena conducta funcional y no estar inhabilitado para el cargo",
        ],
        "requisitos_valorados": [
            "estudios en administración, contabilidad o afines",
            "experiencia previa en organismos públicos o atención al contribuyente",
            "manejo de sistemas de gestión documental",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "constancia de domicilio", "certificado de antecedentes judiciales"],
    },
    "contable": {
        "perfil": "Perfil metódico, con formación administrativa o contable y capacidad para trabajar con documentación presupuestal.",
        "tareas": [
            "registro de comprobantes, imputaciones y conciliaciones básicas",
            "control de rendiciones y apoyo en liquidaciones",
            "seguimiento de expedientes contables y cuadros de ejecución",
            "asistencia al equipo de recaudación y tesorería",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "bachillerato completo o estudios técnicos afines",
            "no contar con observaciones graves en antecedentes funcionales",
            "disponibilidad horaria para tareas de cierre mensual",
        ],
        "requisitos_valorados": [
            "formación terciaria en administración, contabilidad o economía",
            "manejo de Excel y sistemas de gestión financiera",
            "experiencia en gestión presupuestal pública",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "certificados de cursos", "certificado de antecedentes judiciales"],
    },
    "tecnico": {
        "perfil": "Profesional o técnico con capacidad para diagnosticar, planificar y ejecutar tareas de apoyo especializado con criterio operativo.",
        "tareas": [
            "inspección, relevamiento y elaboración de informes técnicos",
            "coordinación con cuadrillas, proveedores o equipos de campo",
            "apoyo a la planificación de obras, intervenciones o programas",
            "seguimiento de indicadores y cumplimiento de cronogramas",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "título habilitante o formación técnica en el área correspondiente",
            "experiencia mínima comprobable cuando el cargo lo requiera",
            "disponibilidad para trasladarse dentro del departamento",
        ],
        "requisitos_valorados": [
            "experiencia en administración pública o consultoría técnica",
            "manejo de SIG, CAD, planillas o software especializado",
            "conocimiento de normativa departamental y nacional aplicable",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "título habilitante", "escolaridad", "constancia de experiencia laboral"],
    },
    "profesional": {
        "perfil": "Profesional con capacidad de análisis, redacción técnica y trabajo interdisciplinario en el marco de políticas departamentales.",
        "tareas": [
            "elaboración de informes, dictámenes o proyectos de intervención",
            "asesoramiento a direcciones y equipos territoriales",
            "revisión de normativa, expedientes y documentación técnica",
            "participación en mesas de trabajo y coordinación interinstitucional",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "título universitario habilitante según el perfil del cargo",
            "documentación que acredite experiencia profesional cuando sea requerida",
            "disponibilidad para tareas presenciales y salidas a territorio",
        ],
        "requisitos_valorados": [
            "posgrados, cursos de actualización o experiencia en gestión pública",
            "producción de informes, proyectos y trabajo con equipos multidisciplinarios",
            "manejo de herramientas de redacción y presentación institucional",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "título habilitante", "escolaridad", "certificado de antecedentes judiciales", "constancia de experiencia laboral"],
    },
    "social": {
        "perfil": "Persona con sensibilidad social, buena capacidad de escucha y criterio para intervenir en contextos comunitarios complejos.",
        "tareas": [
            "acompañamiento a familias, referentes comunitarios y equipos territoriales",
            "registro de intervenciones, derivaciones y seguimiento de casos",
            "participación en jornadas, talleres y acciones de prevención",
            "coordinación con centros educativos, salud y redes comunitarias",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "formación terciaria o universitaria afín al área social según el cargo",
            "certificación de antecedentes judiciales y buena conducta funcional",
            "capacidad de trabajo en territorio y articulación interinstitucional",
        ],
        "requisitos_valorados": [
            "experiencia en abordaje comunitario, niñez, adolescencia o género",
            "manejo de herramientas de registro y redacción de informes",
            "formación en perspectiva de derechos y trabajo social",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "certificado de antecedentes judiciales", "constancia de experiencia laboral"],
    },
    "cultural": {
        "perfil": "Perfil creativo y organizado, con capacidad para diseñar, coordinar y sostener propuestas culturales o educativas en el territorio.",
        "tareas": [
            "planificación de talleres, actividades abiertas y muestras",
            "coordinación con colectivos, docentes y espacios culturales",
            "registro de asistencia, evaluación y comunicación de actividades",
            "producción de contenidos y apoyo logístico a eventos",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "escolaridad acorde al perfil o experiencia demostrable equivalente",
            "disponibilidad para trabajar en horarios vespertinos o de fin de semana",
            "presentación de propuesta de trabajo cuando el llamado lo requiera",
        ],
        "requisitos_valorados": [
            "experiencia en gestión cultural, educación no formal o animación socioeducativa",
            "manejo de herramientas digitales para difusión y registro",
            "formación en artes, comunicación o pedagogía",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "propuesta de trabajo", "constancia de experiencia laboral"],
    },
    "territorial": {
        "perfil": "Persona con capacidad de articulación local, seguimiento de demandas barriales y trabajo directo con referentes comunitarios.",
        "tareas": [
            "relevamiento de demandas territoriales y seguimiento de compromisos",
            "coordinación con municipios, comisiones vecinales y servicios departamentales",
            "organización de instancias de cercanía y participación ciudadana",
            "apoyo a operativos itinerantes y jornadas en localidades del interior",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "experiencia en trabajo territorial o gestión comunitaria",
            "disponibilidad para desplazarse por el departamento",
            "capacidad de redacción y seguimiento de expedientes o reportes",
        ],
        "requisitos_valorados": [
            "manejo de herramientas de georreferenciación o registros territoriales",
            "formación en participación ciudadana, desarrollo local o afines",
            "experiencia en coordinación de actores públicos y sociales",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "constancia de domicilio", "escolaridad", "constancia de experiencia laboral"],
    },
    "operativo": {
        "perfil": "Perfil práctico, con disposición para tareas físicas, manejo responsable de equipos y cumplimiento estricto de instrucciones operativas.",
        "tareas": [
            "apoyo en cuadrillas, carga y descarga de materiales o herramientas",
            "limpieza, orden y mantenimiento básico de espacios públicos",
            "operación de equipos livianos o semipesados según habilitación",
            "cumplimiento de protocolos de seguridad e higiene laboral",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "carné de salud vigente",
            "aptitud física para tareas operativas",
            "libreta de conducir cuando la tarea lo requiera",
        ],
        "requisitos_valorados": [
            "experiencia en mantenimiento, obra o servicios generales",
            "conocimiento de uso de maquinaria o herramientas manuales",
            "residencia cercana a la zona de trabajo",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "carné de salud vigente", "libreta de conducir", "certificado de antecedentes judiciales"],
    },
    "zafral": {
        "perfil": "Perfil operativo y flexible, orientado a tareas de temporada con foco en atención al público y mantenimiento del servicio.",
        "tareas": [
            "atención de espacios turísticos o recreativos durante la temporada",
            "limpieza, mantenimiento y control básico de instalaciones",
            "apoyo en cobro, orientación al visitante y control de ingreso",
            "cumplimiento de horarios rotativos y trabajo en fines de semana",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "carné de salud vigente",
            "disponibilidad horaria estacional completa",
            "buena presencia y trato adecuado con el público",
        ],
        "requisitos_valorados": [
            "experiencia en atención al visitante, higiene o mantenimiento",
            "conocimiento de la zona turística o balnearia",
            "libreta de conducir o certificaciones complementarias",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "carné de salud vigente", "certificado de antecedentes judiciales"],
    },
    "pasantia": {
        "perfil": "Estudiante o recién egresado con interés en aprender procesos internos, aportar apoyo operativo y desarrollarse en entorno institucional.",
        "tareas": [
            "apoyo en carga de datos, digitalización y archivo",
            "colaboración en tareas de comunicación, soporte o administración",
            "participación en actividades de seguimiento con tutoría",
            "elaboración de reportes simples y asistencia a equipos técnicos",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "constancia de estudiante regular o egreso reciente según el perfil",
            "disponibilidad para cumplir horario parcial",
            "no haber participado en otra pasantía incompatible con la convocatoria",
        ],
        "requisitos_valorados": [
            "manejo de herramientas ofimáticas y colaboración digital",
            "interés por la gestión pública y el servicio a la ciudadanía",
            "trayectoria académica acorde al área solicitada",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "constancia de estudiante", "carta de motivación"],
    },
    "beca": {
        "perfil": "Joven en formación con potencial para integrarse a tareas de aprendizaje asistido y acompañamiento técnico dentro del organismo.",
        "tareas": [
            "apoyo a equipos internos bajo supervisión",
            "colaboración en tareas de archivo, relevamiento o comunicación",
            "participación en instancias de capacitación y seguimiento",
            "producción de insumos básicos para el equipo asignado",
        ],
        "requisitos_excluyentes": [
            "cédula de identidad vigente",
            "constancia de inscripción o escolaridad actualizada",
            "disponibilidad horaria compatible con la carga académica",
            "cumplir con las condiciones definidas en las bases de la beca",
        ],
        "requisitos_valorados": [
            "interés por la gestión pública y la mejora de procesos",
            "manejo de ofimática, sistemas web o herramientas de soporte",
            "participación previa en proyectos estudiantiles o comunitarios",
        ],
        "documentos": ["cédula de identidad", "currículum vitae", "escolaridad", "carta de motivación", "formulario firmado"],
    },
}


CONCURSO_BLUEPRINTS = [
    {"titulo": "Auxiliar Administrativo para Recaudación", "area": "Dirección General de Hacienda", "tipo": "Contrato de Función Pública", "template": "administrativo", "estado": "abierto", "localidad": "Minas", "dependencia": "Departamento de Recaudación y Atención al Contribuyente", "vacantes": 3, "remuneracion": "UYU 46.200 nominales mensuales", "admite_web": True, "bases": "bases_auxiliar_recaudacion_2026.pdf", "normativa": "Resolución IDL 148/2026", "email": "concursos.hacienda@idl.gub.uy", "telefono": "(044) 2345 210", "contacto": "Mesa de Entrada de Hacienda, planta baja del Palacio Municipal", "resumen": "Cobertura de vacantes para apoyo administrativo y atención de trámites tributarios en la capital departamental.", "publicacion_days": -3, "apertura_days": -12, "cierre_days": 18, "resolucion_days": 35, "postulaciones": 3},
    {"titulo": "Administrativo Contable para Tesorería", "area": "Dirección General de Hacienda", "tipo": "Contrato de Función Pública", "template": "contable", "estado": "abierto", "localidad": "Minas", "dependencia": "Departamento de Tesorería y Control Presupuestal", "vacantes": 2, "remuneracion": "Según escala vigente de la Intendencia", "admite_web": True, "bases": "bases_administrativo_contable_2026.pdf", "normativa": "Resolución IDL 149/2026", "email": "tesoreria.concursos@idl.gub.uy", "telefono": "(044) 2345 211", "contacto": "Departamento de Tesorería, Palacio Municipal", "resumen": "Llamado para reforzar el equipo contable y administrativo en la gestión de ingresos y rendiciones.", "publicacion_days": -4, "apertura_days": -16, "cierre_days": 20, "resolucion_days": 40, "postulaciones": 4},
    {"titulo": "Inspector de Tránsito de Campo", "area": "Dirección General de Tránsito", "tipo": "Contrato de Función Pública", "template": "operativo", "estado": "en_proceso", "localidad": "José Pedro Varela", "dependencia": "Operativo Regional de Fiscalización", "vacantes": 4, "remuneracion": "UYU 41.800 nominales mensuales + compensación por turno", "admite_web": False, "bases": "bases_inspector_transito_campo_2025.pdf", "normativa": "Resolución IDL 118/2025", "email": "transito.concursos@idl.gub.uy", "telefono": "(4464) 2280", "contacto": "Base operativa de Tránsito en José Pedro Varela", "resumen": "Proceso de selección para reforzar fiscalización vial y operativos móviles en rutas y accesos departamentales.", "publicacion_days": -42, "apertura_days": -38, "cierre_days": -4, "resolucion_days": 14, "postulaciones": 5},
    {"titulo": "Operario de Higiene Urbana", "area": "Dirección General de Higiene", "tipo": "Zafral", "template": "operativo", "estado": "abierto", "localidad": "Minas", "dependencia": "Cuadrilla de Barrido y Recolección", "vacantes": 8, "remuneracion": "UYU 39.500 nominales mensuales por temporada", "admite_web": True, "bases": "bases_operario_higiene_urbana_2026.pdf", "normativa": "Resolución IDL 151/2026", "email": "higiene.concursos@idl.gub.uy", "telefono": "(044) 2345 215", "contacto": "Centro de Operaciones de Higiene, barrio San Francisco", "resumen": "Convocatoria zafral para reforzar tareas de limpieza urbana, recolección y apoyo a operativos especiales.", "publicacion_days": -2, "apertura_days": -9, "cierre_days": 22, "resolucion_days": 37, "postulaciones": 2},
    {"titulo": "Arquitecto Asesor en Ordenamiento Urbano y Territorial", "area": "Dirección General de Ordenamiento Urbano y Territorial", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "archivado", "localidad": "Minas", "dependencia": "Unidad de Habilitaciones y Proyectos Urbanos", "vacantes": 1, "remuneracion": "A definir por entregables y certificación de hitos", "admite_web": False, "bases": "bases_arq_asesor_ordenamiento_2025.pdf", "normativa": "Resolución IDL 072/2025", "email": "ordenamiento.urbano@idl.gub.uy", "telefono": "(044) 2345 227", "contacto": "Dirección General de Ordenamiento Urbano y Territorial", "resumen": "Asesoramiento técnico para revisión de expedientes, criterios de implantación y compatibilidad territorial.", "publicacion_days": -210, "apertura_days": -188, "cierre_days": -148, "resolucion_days": -120, "postulaciones": 3},
    {"titulo": "Ingeniero Civil para Supervisión de Obras", "area": "Dirección General de Servicios Técnicos", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "proximo", "localidad": "Solís de Mataojo", "dependencia": "Unidad de Vialidad y Obras Menores", "vacantes": 1, "remuneracion": "Según alcance del contrato y certificación mensual", "admite_web": True, "bases": "bases_ingeniero_civil_supervision_obras_2026.pdf", "normativa": "Resolución IDL 161/2026", "email": "obras.tecnicas@idl.gub.uy", "telefono": "(4440) 2155", "contacto": "Base de Servicios Técnicos en Solís de Mataojo", "resumen": "Llamado previo para contratación técnica orientada a supervisión, cómputos y seguimiento de obras menores.", "publicacion_days": -1, "apertura_days": 12, "cierre_days": 42, "resolucion_days": 68, "postulaciones": 0},
    {"titulo": "Abogado Asesor para Desarrollo Organizacional", "area": "Área Desarrollo Organizacional", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "finalizado", "localidad": "Minas", "dependencia": "Unidad de Asesoramiento Jurídico y Procesos", "vacantes": 1, "remuneracion": "UYU 72.000 mensuales según certificación de entregables", "admite_web": False, "bases": "bases_abogado_asesor_organizacion_2025.pdf", "normativa": "Resolución IDL 093/2025", "email": "desarrollo.organizacional@idl.gub.uy", "telefono": "(044) 2345 219", "contacto": "Área Desarrollo Organizacional, segundo piso del Palacio Municipal", "resumen": "Selección para apoyo jurídico-técnico en mejora de procesos, contratos y redacción de actos administrativos.", "publicacion_days": -155, "apertura_days": -142, "cierre_days": -110, "resolucion_days": -82, "postulaciones": 4},
    {"titulo": "Veterinario de Campo para Sanidad Animal", "area": "Área Desarrollo Agropecuario", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "en_proceso", "localidad": "Mariscala", "dependencia": "Programa de Sanidad Animal y Productividad Rural", "vacantes": 2, "remuneracion": "A definir por visitas, informes y jornadas de campo", "admite_web": True, "bases": "bases_veterinario_campo_sanidad_2026.pdf", "normativa": "Resolución IDL 158/2026", "email": "agropecuario@idl.gub.uy", "telefono": "(4455) 2177", "contacto": "Oficina del Área Desarrollo Agropecuario en Mariscala", "resumen": "Contratación técnica para relevamientos sanitarios, articulación con productores y apoyo a campañas departamentales.", "publicacion_days": -31, "apertura_days": -29, "cierre_days": -2, "resolucion_days": 19, "postulaciones": 3},
    {"titulo": "Especialista en Gestión Ambiental", "area": "Área Medioambiente", "tipo": "Contrato de Función Pública", "template": "profesional", "estado": "abierto", "localidad": "Arequita", "dependencia": "Unidad de Gestión de Residuos y Educación Ambiental", "vacantes": 1, "remuneracion": "UYU 58.300 nominales mensuales", "admite_web": True, "bases": "bases_especialista_gestion_ambiental_2026.pdf", "normativa": "Resolución IDL 162/2026", "email": "medioambiente.concursos@idl.gub.uy", "telefono": "(044) 2345 233", "contacto": "Base de Área Medioambiente en Arequita", "resumen": "Llamado para fortalecer planificación ambiental, educación ciudadana y seguimiento de acciones de sostenibilidad.", "publicacion_days": -5, "apertura_days": -14, "cierre_days": 16, "resolucion_days": 31, "postulaciones": 5},
    {"titulo": "Técnico Social para Acompañamiento Territorial", "area": "Dirección General de Servicios Sociales", "tipo": "Contrato de Función Pública", "template": "social", "estado": "abierto", "localidad": "José Batlle y Ordóñez", "dependencia": "Equipo de Abordaje Territorial", "vacantes": 2, "remuneracion": "UYU 49.800 nominales mensuales", "admite_web": True, "bases": "bases_tecnico_social_acompanamiento_territorial_2026.pdf", "normativa": "Resolución IDL 163/2026", "email": "servicios.sociales@idl.gub.uy", "telefono": "(4454) 2060", "contacto": "Centro de Servicios Sociales en José Batlle y Ordóñez", "resumen": "Convocatoria para integrar equipos territoriales con tareas de seguimiento, orientación y articulación comunitaria.", "publicacion_days": -2, "apertura_days": -10, "cierre_days": 20, "resolucion_days": 38, "postulaciones": 4},
    {"titulo": "Gestor Cultural para Circuitos Barriales", "area": "Dirección General de Cultura", "tipo": "Contrato de Función Pública", "template": "cultural", "estado": "finalizado", "localidad": "Minas", "dependencia": "Programa de Cultura Comunitaria", "vacantes": 1, "remuneracion": "UYU 45.500 nominales mensuales", "admite_web": False, "bases": "bases_gestor_cultural_circuitos_barriales_2025.pdf", "normativa": "Resolución IDL 089/2025", "email": "cultura.concursos@idl.gub.uy", "telefono": "(044) 2345 240", "contacto": "Dirección General de Cultura, Casa de la Cultura", "resumen": "Proceso ya concluido para coordinación de talleres, circuitos barriales y apoyo a espacios culturales del departamento.", "publicacion_days": -198, "apertura_days": -184, "cierre_days": -150, "resolucion_days": -122, "postulaciones": 6},
    {"titulo": "Coordinador Territorial para Municipios del Este", "area": "Área Descentralización", "tipo": "Contrato de Función Pública", "template": "territorial", "estado": "archivado", "localidad": "Villa Serrana", "dependencia": "Mesa de Trabajo con Municipios del Este", "vacantes": 1, "remuneracion": "Según escala vigente y responsabilidad territorial", "admite_web": False, "bases": "bases_coordinador_territorial_municipios_este_2025.pdf", "normativa": "Resolución IDL 077/2025", "email": "descentralizacion@idl.gub.uy", "telefono": "(044) 2345 244", "contacto": "Área Descentralización, coordinación itinerante", "resumen": "Concurso archivado de un proceso territorial orientado a coordinación con municipios y articulación barrial.", "publicacion_days": -260, "apertura_days": -235, "cierre_days": -198, "resolucion_days": -165, "postulaciones": 2},
    {"titulo": "Técnico en Turismo para Información al Visitante", "area": "Área Turismo", "tipo": "Contrato de Función Pública", "template": "tecnico", "estado": "abierto", "localidad": "Minas", "dependencia": "Centro de Información Turística Departamental", "vacantes": 2, "remuneracion": "UYU 43.900 nominales mensuales", "admite_web": True, "bases": "bases_tecnico_turismo_informacion_visitante_2026.pdf", "normativa": "Resolución IDL 164/2026", "email": "turismo@idl.gub.uy", "telefono": "(044) 2345 251", "contacto": "Centro de Información Turística, terminal de Minas", "resumen": "Selección para apoyo al visitante, relevamiento de servicios y difusión del circuito turístico departamental.", "publicacion_days": -4, "apertura_days": -11, "cierre_days": 19, "resolucion_days": 34, "postulaciones": 5},
    {"titulo": "Auxiliar de Comunicación y Prensa", "area": "Área Prensa", "tipo": "Pasantía", "template": "pasantia", "estado": "suspendido", "localidad": "Minas", "dependencia": "Equipo de Contenidos Digitales y Prensa", "vacantes": 2, "remuneracion": "Beca estímulo UYU 18.000 mensuales", "admite_web": False, "bases": "bases_auxiliar_prensa_2026.pdf", "normativa": "Resolución IDL 166/2026", "email": "prensa@idl.gub.uy", "telefono": "(044) 2345 260", "contacto": "Área Prensa, Palacio Municipal", "resumen": "Llamado suspendido temporalmente por revisión de bases y ajuste de cronograma de selección.", "publicacion_days": -18, "apertura_days": 6, "cierre_days": 28, "resolucion_days": 45, "postulaciones": 0},
    {"titulo": "Tallerista de Juventud para Expresión Creativa", "area": "Área Juventud", "tipo": "Contrato de Función Pública", "template": "cultural", "estado": "finalizado", "localidad": "Minas", "dependencia": "Programa de Centros Juveniles", "vacantes": 1, "remuneracion": "UYU 32.400 nominales mensuales", "admite_web": False, "bases": "bases_tallerista_juventud_expresion_creativa_2025.pdf", "normativa": "Resolución IDL 094/2025", "email": "juventud@idl.gub.uy", "telefono": "(044) 2345 266", "contacto": "Área Juventud, Centro Cultural Eduardo Fabini", "resumen": "Concurso cerrado para facilitación de talleres y acompañamiento de experiencias artísticas con jóvenes del departamento.", "publicacion_days": -176, "apertura_days": -162, "cierre_days": -130, "resolucion_days": -103, "postulaciones": 5},
    {"titulo": "Operario Zafral de Campings y Balnearios", "area": "Área Turismo", "tipo": "Zafral", "template": "zafral", "estado": "proximo", "localidad": "Villa Serrana", "dependencia": "Gestión de Campings y Áreas Recreativas", "vacantes": 12, "remuneracion": "UYU 37.200 nominales mensuales por temporada", "admite_web": True, "bases": "bases_operario_campings_balnearios_2026.pdf", "normativa": "Resolución IDL 170/2026", "email": "turismo.temporada@idl.gub.uy", "telefono": "(044) 2345 273", "contacto": "Operativo Turístico de Villa Serrana", "resumen": "Convocatoria anticipada para temporada, con foco en atención al público, mantenimiento y orden de espacios recreativos.", "publicacion_days": -1, "apertura_days": 15, "cierre_days": 45, "resolucion_days": 72, "postulaciones": 0},
    {"titulo": "Peón Zafral de Cuadrilla para Mantenimiento", "area": "Dirección General de Servicios Técnicos", "tipo": "Zafral", "template": "operativo", "estado": "abierto", "localidad": "Solís de Mataojo", "dependencia": "Cuadrilla de Mantenimiento de Caminos Vecinales", "vacantes": 10, "remuneracion": "UYU 36.800 nominales mensuales por campaña", "admite_web": True, "bases": "bases_peon_zafral_cuadrilla_mantenimiento_2026.pdf", "normativa": "Resolución IDL 171/2026", "email": "servicios.tecnicos@idl.gub.uy", "telefono": "(4440) 2160", "contacto": "Base vial de Solís de Mataojo", "resumen": "Llamado zafral para tareas operativas de apoyo a mantenimiento vial y trabajos de campo en distintas zonas del departamento.", "publicacion_days": -6, "apertura_days": -13, "cierre_days": 21, "resolucion_days": 39, "postulaciones": 3},
    {"titulo": "Pasante para Apoyo Administrativo y Gestión Documental", "area": "Área Desarrollo Organizacional", "tipo": "Pasantía", "template": "pasantia", "estado": "proximo", "localidad": "Minas", "dependencia": "Mesa de Procesos y Archivo Central", "vacantes": 3, "remuneracion": "Beca estímulo UYU 21.500 mensuales", "admite_web": True, "bases": "bases_pasantia_apoyo_administrativo_gestion_documental_2026.pdf", "normativa": "Resolución IDL 172/2026", "email": "desarrollo.organizacional@idl.gub.uy", "telefono": "(044) 2345 220", "contacto": "Área Desarrollo Organizacional, Palacio Municipal", "resumen": "Pasantía orientada al apoyo documental, archivo, carga de datos y mejora de procesos internos.", "publicacion_days": -1, "apertura_days": 10, "cierre_days": 34, "resolucion_days": 57, "postulaciones": 0},
    {"titulo": "Pasante de Apoyo Tecnológico para Sistemas Internos", "area": "Área Desarrollo Organizacional", "tipo": "Pasantía", "template": "pasantia", "estado": "en_proceso", "localidad": "Minas", "dependencia": "Mesa de Soporte y Modernización", "vacantes": 2, "remuneracion": "Beca estímulo UYU 22.000 mensuales", "admite_web": True, "bases": "bases_pasantia_apoyo_tecnologico_2025.pdf", "normativa": "Resolución IDL 139/2025", "email": "soporte@idl.gub.uy", "telefono": "(044) 2345 221", "contacto": "Mesa de Modernización y Soporte", "resumen": "Convocatoria para apoyo a tareas tecnológicas, digitalización y asistencia básica a equipos internos.", "publicacion_days": -45, "apertura_days": -41, "cierre_days": -3, "resolucion_days": 16, "postulaciones": 4},
    {"titulo": "Administrativo para Servicios Sociales en Interior", "area": "Dirección General de Servicios Sociales", "tipo": "Contrato de Función Pública", "template": "administrativo", "estado": "finalizado", "localidad": "Mariscala", "dependencia": "Oficina Territorial de Atención Social", "vacantes": 2, "remuneracion": "UYU 45.900 nominales mensuales", "admite_web": False, "bases": "bases_administrativo_servicios_sociales_interior_2025.pdf", "normativa": "Resolución IDL 098/2025", "email": "servicios.sociales@idl.gub.uy", "telefono": "(4455) 2190", "contacto": "Oficina Territorial en Mariscala", "resumen": "Concurso finalizado para cobertura de apoyo administrativo en oficinas descentralizadas de atención social.", "publicacion_days": -180, "apertura_days": -170, "cierre_days": -136, "resolucion_days": -104, "postulaciones": 4},
    {"titulo": "Coordinador de Promoción y Desarrollo", "area": "Área Promoción y Desarrollo", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "suspendido", "localidad": "Minas", "dependencia": "Unidad de Empleo y Emprendimientos", "vacantes": 1, "remuneracion": "A definir según plan de trabajo y metas de gestión", "admite_web": False, "bases": "bases_coordinador_promocion_desarrollo_2026.pdf", "normativa": "Resolución IDL 167/2026", "email": "promocion.desarrollo@idl.gub.uy", "telefono": "(044) 2345 229", "contacto": "Área Promoción y Desarrollo, segundo piso", "resumen": "Proceso suspendido mientras se ajustan los alcances del perfil y las metas de la contratación.", "publicacion_days": -20, "apertura_days": 5, "cierre_days": 33, "resolucion_days": 51, "postulaciones": 0},
    {"titulo": "Docente Tallerista para Deporte Comunitario", "area": "Área Deporte", "tipo": "Beca", "template": "cultural", "estado": "archivado", "localidad": "José Pedro Varela", "dependencia": "Programa Deporte Barrial y Escuelas Deportivas", "vacantes": 2, "remuneracion": "Beca estímulo UYU 19.000 mensuales", "admite_web": False, "bases": "bases_tallerista_deporte_comunitario_2025.pdf", "normativa": "Resolución IDL 080/2025", "email": "deporte@idl.gub.uy", "telefono": "(4464) 2295", "contacto": "Área Deporte, gimnasio municipal de José Pedro Varela", "resumen": "Llamado archivado para sostener talleres, apoyo pedagógico y actividades barriales con enfoque recreativo.", "publicacion_days": -244, "apertura_days": -228, "cierre_days": -191, "resolucion_days": -160, "postulaciones": 2},
    {"titulo": "Técnico en Prevención y Salud Ambiental", "area": "Área Medioambiente", "tipo": "Contrato de Función Pública", "template": "tecnico", "estado": "abierto", "localidad": "Minas", "dependencia": "Unidad de Control y Educación Ambiental", "vacantes": 1, "remuneracion": "UYU 52.700 nominales mensuales", "admite_web": True, "bases": "bases_tecnico_prevencion_salud_ambiental_2026.pdf", "normativa": "Resolución IDL 173/2026", "email": "medioambiente@idl.gub.uy", "telefono": "(044) 2345 234", "contacto": "Área Medioambiente, Palacio Municipal", "resumen": "Convocatoria para tareas de inspección, prevención y educación ambiental en áreas urbanas y rurales.", "publicacion_days": -3, "apertura_days": -8, "cierre_days": 24, "resolucion_days": 41, "postulaciones": 4},
    {"titulo": "Auxiliar de Prensa para Producción Multimedia", "area": "Área Prensa", "tipo": "Pasantía", "template": "pasantia", "estado": "en_proceso", "localidad": "Minas", "dependencia": "Unidad de Comunicación Digital", "vacantes": 2, "remuneracion": "Beca estímulo UYU 20.500 mensuales", "admite_web": True, "bases": "bases_auxiliar_prensa_multimedia_2025.pdf", "normativa": "Resolución IDL 141/2025", "email": "prensa@idl.gub.uy", "telefono": "(044) 2345 261", "contacto": "Área Prensa, Palacio Municipal", "resumen": "Proceso en curso para apoyo multimedia, edición simple, difusión digital y cobertura institucional.", "publicacion_days": -39, "apertura_days": -33, "cierre_days": -1, "resolucion_days": 12, "postulaciones": 4},
    {"titulo": "Operario de Apoyo para Feria y Logística", "area": "Área Promoción y Desarrollo", "tipo": "Zafral", "template": "operativo", "estado": "finalizado", "localidad": "Minas", "dependencia": "Unidad de Ferias y Eventos Productivos", "vacantes": 6, "remuneracion": "UYU 38.600 nominales mensuales por temporada", "admite_web": False, "bases": "bases_operario_feria_logistica_2025.pdf", "normativa": "Resolución IDL 101/2025", "email": "promocion.desarrollo@idl.gub.uy", "telefono": "(044) 2345 230", "contacto": "Área Promoción y Desarrollo, Mercado Municipal", "resumen": "Convocatoria cerrada para apoyo operativo en ferias, armado logístico y atención de eventos departamentales.", "publicacion_days": -170, "apertura_days": -160, "cierre_days": -124, "resolucion_days": -95, "postulaciones": 5},
    {"titulo": "Arquitecto/a para Inspección de Habilitaciones", "area": "Dirección General de Ordenamiento Urbano y Territorial", "tipo": "Arrendamiento de Obra", "template": "profesional", "estado": "abierto", "localidad": "Minas", "dependencia": "Unidad de Habilitaciones y Contralor Edilicio", "vacantes": 1, "remuneracion": "A definir según visitas técnicas y entregables", "admite_web": True, "bases": "bases_arquitecto_inspeccion_habilitaciones_2026.pdf", "normativa": "Resolución IDL 174/2026", "email": "ordenamiento.urbano@idl.gub.uy", "telefono": "(044) 2345 228", "contacto": "Oficina de Habilitaciones, Palacio Municipal", "resumen": "Llamado para apoyo profesional en inspecciones, relevamientos y seguimiento de habilitaciones edilicias.", "publicacion_days": -4, "apertura_days": -10, "cierre_days": 17, "resolucion_days": 36, "postulaciones": 3},
    {"titulo": "Beca de Apoyo para Diseño y Analítica de Datos", "area": "Área Desarrollo Organizacional", "tipo": "Beca", "template": "beca", "estado": "proximo", "localidad": "Minas", "dependencia": "Equipo de Transformación Digital", "vacantes": 2, "remuneracion": "Beca estímulo UYU 23.000 mensuales", "admite_web": True, "bases": "bases_beca_diseno_analitica_datos_2026.pdf", "normativa": "Resolución IDL 175/2026", "email": "modernizacion@idl.gub.uy", "telefono": "(044) 2345 222", "contacto": "Área Desarrollo Organizacional, sector modernización", "resumen": "Beca orientada a tareas de apoyo en visualización de datos, documentación y mejora de procesos internos.", "publicacion_days": -1, "apertura_days": 8, "cierre_days": 32, "resolucion_days": 55, "postulaciones": 0},
    {"titulo": "Técnico en Género y Cuidados", "area": "Área Familia y Género", "tipo": "Contrato de Función Pública", "template": "social", "estado": "archivado", "localidad": "Minas", "dependencia": "Programa de Cuidados y Prevención", "vacantes": 1, "remuneracion": "UYU 51.200 nominales mensuales", "admite_web": False, "bases": "bases_tecnico_genero_cuidados_2025.pdf", "normativa": "Resolución IDL 088/2025", "email": "familia.genero@idl.gub.uy", "telefono": "(044) 2345 239", "contacto": "Área Familia y Género, Casa de la Mujer", "resumen": "Proceso archivado para fortalecer intervenciones territoriales y articulación con redes de cuidados.", "publicacion_days": -220, "apertura_days": -205, "cierre_days": -171, "resolucion_days": -142, "postulaciones": 4},
    {"titulo": "Inspector de Tránsito para Control en Accesos", "area": "Dirección General de Tránsito", "tipo": "Contrato de Función Pública", "template": "operativo", "estado": "abierto", "localidad": "Villa Serrana", "dependencia": "Operativo de Control de Accesos y Rutas", "vacantes": 3, "remuneracion": "UYU 42.900 nominales mensuales + compensación por nocturnidad", "admite_web": True, "bases": "bases_inspector_transito_accesos_2026.pdf", "normativa": "Resolución IDL 176/2026", "email": "transito.concursos@idl.gub.uy", "telefono": "(044) 2345 246", "contacto": "Base vial de Villa Serrana", "resumen": "Refuerzo para operativos de control, fiscalización y asistencia en accesos estratégicos del departamento.", "publicacion_days": -2, "apertura_days": -9, "cierre_days": 23, "resolucion_days": 40, "postulaciones": 2},
    {"titulo": "Operario de Apoyo para Caminería Rural", "area": "Dirección General de Servicios Técnicos", "tipo": "Zafral", "template": "operativo", "estado": "en_proceso", "localidad": "José Batlle y Ordóñez", "dependencia": "Cuadrilla de Caminería Rural", "vacantes": 9, "remuneracion": "UYU 37.900 nominales mensuales por campaña", "admite_web": True, "bases": "bases_operario_caminaria_rural_2025.pdf", "normativa": "Resolución IDL 143/2025", "email": "servicios.tecnicos@idl.gub.uy", "telefono": "(4454) 2033", "contacto": "Base vial de José Batlle y Ordóñez", "resumen": "Selección para reforzar cuadrillas de caminería rural y tareas de mantenimiento territorial.", "publicacion_days": -34, "apertura_days": -30, "cierre_days": -6, "resolucion_days": 15, "postulaciones": 5},
    {"titulo": "Tallerista Deportivo para Iniciación Motriz", "area": "Área Deporte", "tipo": "Beca", "template": "cultural", "estado": "archivado", "localidad": "Arequita", "dependencia": "Programa Deporte y Comunidad", "vacantes": 2, "remuneracion": "Beca estímulo UYU 18.500 mensuales", "admite_web": False, "bases": "bases_tallerista_deportivo_iniciacion_motriz_2025.pdf", "normativa": "Resolución IDL 086/2025", "email": "deporte@idl.gub.uy", "telefono": "(044) 2345 268", "contacto": "Área Deporte, complejo deportivo municipal", "resumen": "Llamado archivado para talleristas con experiencia en infancia, recreación y promoción de actividad física.", "publicacion_days": -240, "apertura_days": -224, "cierre_days": -188, "resolucion_days": -156, "postulaciones": 3},
    {"titulo": "Beca de Apoyo en Archivo y Atención Interna", "area": "Área Desarrollo Organizacional", "tipo": "Beca", "template": "beca", "estado": "abierto", "localidad": "Minas", "dependencia": "Archivo Central y Gestión Documental", "vacantes": 2, "remuneracion": "Beca estímulo UYU 19.500 mensuales", "admite_web": True, "bases": "bases_beca_apoyo_archivo_atencion_interna_2026.pdf", "normativa": "Resolución IDL 177/2026", "email": "desarrollo.organizacional@idl.gub.uy", "telefono": "(044) 2345 220", "contacto": "Área Desarrollo Organizacional, Palacio Municipal", "resumen": "Convocatoria para apoyo interno en archivo, atención básica y actualización de legajos documentales.", "publicacion_days": -3, "apertura_days": -11, "cierre_days": 14, "resolucion_days": 29, "postulaciones": 3},
]


POSTULATION_BLUEPRINTS = [
    {"nombre": "Mariana Sosa", "documento": "4.129.875-2", "fecha_nacimiento": "1995-04-12", "email": "mariana.sosa@example.com", "telefono": "099 222 410", "domicilio": "Av. Gral. Lavalleja 842, Minas", "localidad": "Minas", "estado": "recibida", "observaciones": "Adjunta constancia de domicilio y experiencia en caja."},
    {"nombre": "Diego Pereira", "documento": "4.393.118-4", "fecha_nacimiento": "1991-09-08", "email": "diego.pereira@example.com", "telefono": "098 771 304", "domicilio": "25 de Mayo 223, Minas", "localidad": "Minas", "estado": "en_revision", "observaciones": "Solicita considerar experiencia en mesa de entrada."},
    {"nombre": "Sofía Bentancur", "documento": "4.517.009-1", "fecha_nacimiento": "1998-01-24", "email": "sofia.bentancur@example.com", "telefono": "099 812 773", "domicilio": "Barrio La Coronilla, Minas", "localidad": "Minas", "estado": "admitida", "observaciones": "Cumple con carné de salud y disponibilidad horaria."},
    {"nombre": "Nicolás Machado", "documento": "4.082.776-9", "fecha_nacimiento": "1989-11-03", "email": "nicolas.machado@example.com", "telefono": "091 442 118", "domicilio": "Ruta 8 km 185, José Pedro Varela", "localidad": "José Pedro Varela", "estado": "rechazada", "observaciones": "No acreditó libreta requerida en el plazo establecido."},
    {"nombre": "Lucía Cabrera", "documento": "4.211.663-7", "fecha_nacimiento": "1994-06-19", "email": "lucia.cabrera@example.com", "telefono": "098 663 901", "domicilio": "Miguelete 311, José Batlle y Ordóñez", "localidad": "José Batlle y Ordóñez", "estado": "recibida", "observaciones": "Presenta formación en trabajo social y experiencia territorial."},
    {"nombre": "Andrés Ríos", "documento": "4.331.902-5", "fecha_nacimiento": "1987-08-15", "email": "andres.rios@example.com", "telefono": "099 102 551", "domicilio": "Camino a Arequita s/n, Minas", "localidad": "Minas", "estado": "admitida", "observaciones": "Adjunta plan de trabajo para educación ambiental en centros educativos."},
    {"nombre": "Valentina Núñez", "documento": "4.498.104-0", "fecha_nacimiento": "1990-03-27", "email": "valentina.nunez@example.com", "telefono": "091 880 410", "domicilio": "Ruta 8, km 164, Mariscala", "localidad": "Mariscala", "estado": "en_revision", "observaciones": "Acredita experiencia en campañas sanitarias bovinas."},
    {"nombre": "Martín Pacheco", "documento": "4.266.330-2", "fecha_nacimiento": "1993-12-02", "email": "martin.pacheco@example.com", "telefono": "097 314 880", "domicilio": "Treinta y Tres 1180, Minas", "localidad": "Minas", "estado": "admitida", "observaciones": "Propone calendario de talleres barriales y mediación cultural."},
    {"nombre": "Camila Ferreira", "documento": "4.367.552-6", "fecha_nacimiento": "2000-10-09", "email": "camila.ferreira@example.com", "telefono": "092 555 820", "domicilio": "Piria 907, Minas", "localidad": "Minas", "estado": "recibida", "observaciones": "Adjunta portafolio digital y manejo básico de edición."},
    {"nombre": "Ezequiel Viera", "documento": "5.028.441-3", "fecha_nacimiento": "2002-05-21", "email": "ezequiel.viera@example.com", "telefono": "095 880 240", "domicilio": "Los Olivos 44, Minas", "localidad": "Minas", "estado": "recibida", "observaciones": "Estudiante de informática con disponibilidad parcial."},
    {"nombre": "Paula Acosta", "documento": "4.186.710-8", "fecha_nacimiento": "1992-07-14", "email": "paula.acosta@example.com", "telefono": "099 730 441", "domicilio": "Centro, Mariscala", "localidad": "Mariscala", "estado": "admitida", "observaciones": "Cuenta con experiencia en oficina territorial y archivo."},
    {"nombre": "Bruno Silveira", "documento": "4.590.221-1", "fecha_nacimiento": "1997-02-05", "email": "bruno.silveira@example.com", "telefono": "091 620 050", "domicilio": "Villa Serrana, Ruta 60", "localidad": "Villa Serrana", "estado": "recibida", "observaciones": "Postulación anticipada para temporada alta."},
]


def _clean(text):
    return " ".join(str(text).split())


def _html_paragraphs(*parts):
    return "".join(f"<p>{_clean(part)}</p>" for part in parts if part)


def _html_list(items):
    return "<ul>" + "".join(f"<li>{_clean(item)}</li>" for item in items if item) + "</ul>"


def _dt_from(now, days=0, hour=9, minute=0):
    target = now + timedelta(days=days)
    return target.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _currency_text(remuneracion):
    return remuneracion if remuneracion else "A definir según bases"


def _ensure_lookup(model, rows):
    existing = {}
    for nombre, descripcion in rows:
        attributes = {'nombre': nombre, 'descripcion': descripcion}
        match = model.nombre == nombre
        if model is TipoLlamado:
            attributes['slug'] = model.generate_slug(nombre)
            match = db.or_(match, model.slug == attributes['slug'])
        row = model.query.filter(match).first()
        if row is None:
            row = model(**attributes)
            db.session.add(row)
        elif descripcion and not row.descripcion:
            row.descripcion = descripcion
        existing[nombre] = row
    return existing


def _state_dates(now, estado, apertura_days, cierre_days, resolucion_days, publication_days):
    fecha_publicacion = _dt_from(now, publication_days)
    fecha_apertura = _dt_from(now, apertura_days)
    fecha_cierre = _dt_from(now, cierre_days)
    fecha_resolucion = _dt_from(now, resolucion_days) if resolucion_days is not None else None

    if estado == Concurso.ESTADO_ABIERTO and fecha_apertura > fecha_cierre:
        fecha_cierre = fecha_apertura + timedelta(days=20)
    if estado == Concurso.ESTADO_PROXIMO and fecha_apertura <= now:
        fecha_apertura = _dt_from(now, 10)
    if estado in {Concurso.ESTADO_FINALIZADO, Concurso.ESTADO_ARCHIVADO} and fecha_resolucion and fecha_resolucion < fecha_cierre:
        fecha_resolucion = fecha_cierre + timedelta(days=12)
    return fecha_publicacion, fecha_apertura, fecha_cierre, fecha_resolucion


def _timeline_for(estado, apertura, cierre, resolucion, publication):
    events = [
        {"fecha": publication.date().isoformat(), "titulo": "Publicación de bases", "descripcion": "Se publica el llamado con sus bases y cronograma preliminar.", "completado": publication <= datetime.utcnow()},
        {"fecha": apertura.date().isoformat(), "titulo": "Apertura de postulaciones", "descripcion": "Se habilita o habilitará la recepción de postulaciones.", "completado": apertura <= datetime.utcnow() or estado in {Concurso.ESTADO_ABIERTO, Concurso.ESTADO_EN_PROCESO, Concurso.ESTADO_FINALIZADO, Concurso.ESTADO_ARCHIVADO, Concurso.ESTADO_SUSPENDIDO}},
        {"fecha": cierre.date().isoformat(), "titulo": "Cierre de postulaciones", "descripcion": "Finaliza el período para presentar documentación.", "completado": cierre <= datetime.utcnow() or estado in {Concurso.ESTADO_FINALIZADO, Concurso.ESTADO_ARCHIVADO}},
    ]
    if resolucion:
        events.append({"fecha": resolucion.date().isoformat(), "titulo": "Resolución / resultados", "descripcion": "Publicación de resultados o resolución administrativa.", "completado": resolucion <= datetime.utcnow() or estado in {Concurso.ESTADO_FINALIZADO, Concurso.ESTADO_ARCHIVADO}})
    if estado == Concurso.ESTADO_SUSPENDIDO:
        events.append({"fecha": datetime.utcnow().date().isoformat(), "titulo": "Suspensión del proceso", "descripcion": "El llamado queda en pausa hasta nuevo aviso.", "completado": True})
    return events


def _documentos_json(blueprint):
    docs = [
        {"id": 1, "nombre": "Bases del llamado", "url": f"/public/bases/{blueprint['bases']}", "tipo": "bases"},
        {"id": 2, "nombre": "Resolución", "url": f"/public/bases/{blueprint['bases'].replace('.pdf', '_anexo_dj.pdf')}", "tipo": "anexo"},
    ]
    if blueprint["admite_web"]:
        docs.append({"id": 3, "nombre": "Formulario web de postulación", "url": "/concursos/postular", "tipo": "formulario"})
    return json.dumps(docs, ensure_ascii=False)


def _build_texts(blueprint):
    template = ROLE_TEMPLATES[blueprint["template"]]
    area = blueprint["area"]
    localidad = blueprint["localidad"]
    titulo = blueprint["titulo"]
    resumen = blueprint["resumen"]
    descripcion = _html_paragraphs(
        f"La Intendencia Departamental de Lavalleja convoca a {titulo.lower()} para la {area.lower()} con desempeño en {localidad}.",
        resumen,
        f"La tarea se desarrollará en coordinación con {area}, con foco en servicio público, trazabilidad administrativa y cumplimiento de bases.",
    )
    return {
        "resumen": resumen,
        "descripcion": descripcion,
        "perfil": template["perfil"],
        "tareas": _html_list(template["tareas"]),
        "requisitos_excluyentes": _html_list(template["requisitos_excluyentes"]),
        "requisitos_valorados": _html_list(template["requisitos_valorados"]),
        "documentacion": _html_list(template["documentos"]),
        "bases_concurso": _html_paragraphs(
            f"Las bases del concurso para {titulo.lower()} establecen el alcance del llamado, el cronograma previsto y las condiciones generales de participación.",
            f"El proceso corresponde a {area.lower()} y el área convocante responsable actuará en {localidad}.",
            f"Antes de postularte, revisá cuidadosamente la normativa aplicable, la documentación requerida y los criterios de evaluación publicados para este llamado.",
        ),
        "bases_llamado": _html_list([
            f"Cargo o función convocada: {titulo}",
            f"Área convocante: {area}",
            f"Localidad de referencia: {localidad}",
            f"Cantidad de vacantes previstas: {blueprint['vacantes']}",
            f"Modalidad de contratación: {blueprint['tipo']}",
            f"Remuneración de referencia: {blueprint['remuneracion']}",
        ]),
        "anexo_declaracion_jurada": _html_paragraphs(
            f"La resolución correspondiente a {titulo.lower()} establece la decisión administrativa aplicable al llamado y formaliza sus actuaciones principales.",
            f"El acto se dicta en el marco de {area.lower()} y sirve como respaldo documental del proceso convocado para {localidad}.",
            "Su publicación permite consultar el contenido oficial del acto administrativo y los alcances definidos para el concurso.",
        ),
        "forma_postulacion": (
            "Postulación exclusivamente web a través del formulario institucional." if blueprint["admite_web"] else
            "No admite postulación web. La presentación se realiza según lo indicado en las bases y en la oficina de referencia."
        ),
    }


def _build_concurso(blueprint, area_obj, tipo_obj, tipo_llamado_obj, now):
    publication, apertura, cierre, resolucion = _state_dates(
        now,
        blueprint["estado"],
        blueprint["apertura_days"],
        blueprint["cierre_days"],
        blueprint["resolucion_days"],
        blueprint["publicacion_days"],
    )
    texts = _build_texts(blueprint)
    slug = Concurso.generate_slug(blueprint["titulo"])
    return Concurso(
        titulo=blueprint["titulo"],
        subtitulo=blueprint["resumen"],
        slug=slug,
        estado=blueprint["estado"],
        area_convocante_id=area_obj.id,
        tipo_contratacion_id=tipo_obj.id,
        tipo_llamado_id=tipo_llamado_obj.id if tipo_llamado_obj else None,
        cantidad_cargos=blueprint["vacantes"],
        remuneracion=_currency_text(blueprint["remuneracion"]),
        localidad=blueprint["localidad"],
        dependencia=blueprint["area"],
        fecha_apertura=apertura,
        fecha_cierre=cierre,
        fecha_resolucion_estimada=resolucion,
        descripcion=texts["descripcion"],
        requisitos_excluyentes=texts["requisitos_excluyentes"],
        requisitos_valorados=texts["requisitos_valorados"],
        perfil_buscado=texts["perfil"],
        tareas_funciones=texts["tareas"],
        documentacion_requerida=texts["documentacion"],
        forma_postulacion=texts["forma_postulacion"],
        contacto_consulta=blueprint["contacto"],
        normativa=blueprint["normativa"],
        bases_url=f"/public/bases/{blueprint['bases']}",
        bases_concurso_html=texts["bases_concurso"],
        bases_llamado_html=texts["bases_llamado"],
        anexo_declaracion_jurada_html=texts["anexo_declaracion_jurada"],
        timeline_json=json.dumps(_timeline_for(blueprint["estado"], apertura, cierre, resolucion, publication), ensure_ascii=False),
        documentos_json=_documentos_json(blueprint),
        created_at=publication,
        updated_at=resolucion or publication,
    )


def _build_postulacion(concurso, blueprint, index):
    template = POSTULATION_BLUEPRINTS[(index + concurso.id) % len(POSTULATION_BLUEPRINTS)]
    created_at = concurso.created_at + timedelta(days=1 + index)
    return Postulacion(
        concurso_id=concurso.id,
        nombre_completo=template["nombre"],
        documento=template["documento"],
        fecha_nacimiento=datetime.strptime(template["fecha_nacimiento"], "%Y-%m-%d").date(),
        email=template["email"],
        telefono=template["telefono"],
        domicilio=template["domicilio"],
        localidad=template["localidad"],
        observaciones=template["observaciones"],
        curriculum_key=f"seed/{concurso.slug}/{template['documento']}/cv.pdf",
        cedula_key=f"seed/{concurso.slug}/{template['documento']}/ci.pdf",
        certificados_keys=json.dumps([f"seed/{concurso.slug}/{template['documento']}/certificado-1.pdf"], ensure_ascii=False),
        constancias_keys=json.dumps([f"seed/{concurso.slug}/{template['documento']}/constancia-1.pdf"], ensure_ascii=False),
        adicional_keys=json.dumps([f"seed/{concurso.slug}/{template['documento']}/anexo-motivacion.pdf"], ensure_ascii=False),
        estado=template["estado"],
        notas_internas="Postulación de ejemplo generada por seed para demos y testing.",
        created_at=created_at,
        updated_at=created_at,
    )


def preparar_catalogos_concursos(*, incluir_tipos_llamado=True):
    areas = _ensure_lookup(AreaConvocante, AREA_DEFINITIONS)
    tipos = _ensure_lookup(TipoContratacion, TYPE_DEFINITIONS)
    tipos_llamado = (
        _ensure_lookup(TipoLlamado, TIPO_LLAMADO_DEFINITIONS)
        if incluir_tipos_llamado else {}
    )
    return areas, tipos, tipos_llamado


def seed_concursos(reset=False):
    now = ahora_en_uruguay().replace(minute=0, second=0, microsecond=0)
    areas, tipos, tipos_llamado = preparar_catalogos_concursos()

    seed_slugs = [Concurso.generate_slug(item["titulo"]) for item in CONCURSO_BLUEPRINTS]

    if reset:
        postulaciones = Postulacion.query.join(Concurso).filter(Concurso.slug.in_(seed_slugs)).all()
        for postulacion in postulaciones:
            db.session.delete(postulacion)
        concursos_existentes = Concurso.query.filter(Concurso.slug.in_(seed_slugs)).all()
        for concurso in concursos_existentes:
            db.session.delete(concurso)
        db.session.flush()

    existing_slugs = {slug for (slug,) in db.session.query(Concurso.slug).filter(Concurso.slug.in_(seed_slugs)).all()}

    concursos_creados = []
    for blueprint in CONCURSO_BLUEPRINTS:
        slug = Concurso.generate_slug(blueprint["titulo"])
        if slug in existing_slugs and not reset:
            continue
        tipo_llamado_nombre = TIPO_LLAMADO_BY_CONTRATACION.get(blueprint['tipo'])
        concurso = _build_concurso(
            blueprint,
            areas[blueprint["area"]],
            tipos[blueprint["tipo"]],
            tipos_llamado.get(tipo_llamado_nombre),
            now,
        )
        db.session.add(concurso)
        db.session.flush()
        concursos_creados.append((concurso, blueprint))

    postulaciones_creadas = 0
    for concurso, blueprint in concursos_creados:
        if concurso.estado not in {Concurso.ESTADO_ABIERTO, Concurso.ESTADO_EN_PROCESO, Concurso.ESTADO_FINALIZADO}:
            continue
        limite = blueprint.get("postulaciones", 0)
        if limite <= 0:
            continue
        for idx in range(min(limite, len(POSTULATION_BLUEPRINTS))):
            postulacion = _build_postulacion(concurso, blueprint, idx)
            if postulacion is None:
                continue
            db.session.add(postulacion)
            postulaciones_creadas += 1

    db.session.commit()

    state_counter = Counter(concurso.estado for concurso, _ in concursos_creados)
    type_counter = Counter(concurso.tipo_contratacion_rel.nombre for concurso, _ in concursos_creados)
    called_type_counter = Counter((concurso.tipo_llamado_rel.nombre if concurso.tipo_llamado_rel else 'Sin tipo') for concurso, _ in concursos_creados)

    return {
        "concursos_creados": len(concursos_creados),
        "postulaciones_creadas": postulaciones_creadas,
        "por_estado": dict(sorted(state_counter.items())),
        "por_tipo": dict(sorted(type_counter.items())),
        "por_tipo_llamado": dict(sorted(called_type_counter.items())),
    }
