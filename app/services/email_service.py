import smtplib
import ssl
from threading import Thread

from flask import current_app, render_template
from flask_mail import Connection, Message

class BoundedMailConnection(Connection):
    def configure_host(self):
        context = ssl.create_default_context()
        options = {'timeout': 8}
        if self.mail.use_ssl:
            host = smtplib.SMTP_SSL(self.mail.server, self.mail.port, context=context, **options)
        else:
            host = smtplib.SMTP(self.mail.server, self.mail.port, **options)
        try:
            if self.mail.use_tls:
                host.starttls(context=context)
            if self.mail.username and self.mail.password:
                host.login(self.mail.username, self.mail.password)
        except Exception:
            host.close()
            raise
        return host


def send_async_email(app, msg):
    with app.app_context():
        try:
            with BoundedMailConnection(current_app.extensions['mail']) as connection:
                connection.send(msg)
        except Exception:
            current_app.logger.exception('Error al enviar correo electrónico')


def send_email(subject, recipients, text_body, html_body, attachments=None, *, synchronous=False):
    msg = Message(subject, recipients=recipients)
    msg.body = text_body
    msg.html = html_body

    if attachments:
        for att in attachments:
            msg.attach(att['filename'], att['content_type'], att['data'])

    if synchronous:
        with BoundedMailConnection(current_app.extensions['mail']) as connection:
            connection.send(msg)
    else:
        Thread(
            target=send_async_email,
            args=(current_app._get_current_object(), msg),
        ).start()


def send_postulacion_verification_email(postulacion, verification_url):
    """Envía el correo para confirmar la preinscripción."""
    subject = 'Confirmá tu preinscripción - Lavalleja Concursa'

    html_body = render_template(
        'emails/postulacion_preinscripcion.html',
        postulacion=postulacion,
        verification_url=verification_url,
    )

    text_body = (
        f"Hola {postulacion.nombre_completo}. "
        'Recibimos tu preinscripción. Para finalizarla debés '
        'confirmar tu correo '
        f'entrando al siguiente enlace: {verification_url}'
    )

    send_email(
        subject=subject,
        recipients=[postulacion.email],
        text_body=text_body,
        html_body=html_body,
        synchronous=True,
    )


def send_postulacion_email(postulacion):
    """Envía confirmación final de postulación con su código de seguimiento."""
    subject = 'Inscripción confirmada - Lavalleja Concursa'

    html_body = render_template(
        'emails/postulacion_recibida.html',
        postulacion=postulacion,
    )

    text_body = (
        f"Tu inscripción quedó confirmada con éxito. "
        f"Tu código de seguimiento es: {postulacion.tracking_code}."
    )

    send_email(
        subject=subject,
        recipients=[postulacion.email],
        text_body=text_body,
        html_body=html_body,
        synchronous=True,
    )


def send_2fa_email(to_email, code):
    subject = "[Lavalleja Concursa] Código de verificación de acceso"

    html_body = render_template('emails/2fa_code.html', code=code)

    send_email(
        subject=subject,
        recipients=[to_email],
        text_body=(
            'Tu código de verificación para el panel de administración '
            f'de Lavalleja Concursa: {code}. Expira en 10 minutos.'
        ),
        html_body=html_body,
        synchronous=True,
    )


def send_contact_confirmation_email(to_email: str, msg):
    """Envía un email de confirmación por el formulario de contacto."""
    subject = "Tu mensaje fue recibido - Lavalleja Concursa"

    html_body = render_template('emails/contact_confirmation.html', msg=msg)

    send_email(
        subject=subject,
        recipients=[to_email],
        text_body=(
            "Gracias por escribirnos. Tu mensaje fue recibido y "
            "nos comunicaremos contigo en el horario que indicaste. "
            "Si es una emergencia, por favor comunicate al 911 o al "
            "servicio de emergencias local."
        ),
        html_body=html_body,
    )
