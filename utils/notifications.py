import os
import smtplib
import ssl
from email.message import EmailMessage


def get_smtp_settings():
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "465")),
        "username": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "email_from": os.getenv("EMAIL_FROM", os.getenv("SMTP_USERNAME", "")),
        "use_ssl": os.getenv("SMTP_USE_SSL", "true").lower() in {"true", "1", "yes"},
    }


def is_smtp_configured():
    settings = get_smtp_settings()
    return bool(settings["host"] and settings["username"] and settings["password"] and settings["email_from"])


def send_email_notification(to_email, subject, body):
    settings = get_smtp_settings()
    if not is_smtp_configured():
        return False, "SMTP settings are not configured"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["email_from"]
    message["To"] = to_email
    message.set_content(body)

    try:
        if settings["use_ssl"]:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings["host"], settings["port"], context=context) as server:
                server.login(settings["username"], settings["password"])
                server.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], settings["port"]) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(settings["username"], settings["password"])
                server.send_message(message)

        return True, "Email sent"
    except Exception as exc:
        return False, str(exc)
