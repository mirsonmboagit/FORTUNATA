"""Envio de mensagens transacionais de autenticacao por SMTP."""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from utils.config.paths import ENV_FILE


_EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


class EmailServiceError(RuntimeError):
    """Erro base do servico de e-mail."""


class EmailServiceNotConfigured(EmailServiceError):
    """O SMTP ainda nao foi configurado no ambiente."""


class EmailDeliveryError(EmailServiceError):
    """O servidor SMTP nao conseguiu entregar a mensagem."""


def save_smtp_settings(
    username,
    password,
    from_email=None,
    host="smtp.gmail.com",
    port=587,
    from_name="SIGE MPE",
    use_tls=True,
    use_ssl=False,
):
    """Guarda a conta SMTP da instalacao local sem expor a senha na UI."""
    username = normalize_email(username)
    from_email = normalize_email(from_email or username)
    host = str(host or "").strip()
    password = str(password or "").strip()
    if not host or not is_valid_email(username) or not is_valid_email(from_email):
        raise EmailServiceNotConfigured("Informe um servidor e e-mails SMTP validos.")
    if not password:
        raise EmailServiceNotConfigured("Informe a senha de aplicacao do SMTP.")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise EmailServiceNotConfigured("A porta SMTP deve ser numerica.") from exc
    if not 1 <= port <= 65535:
        raise EmailServiceNotConfigured("A porta SMTP esta fora do intervalo permitido.")
    if bool(use_tls) and bool(use_ssl):
        raise EmailServiceNotConfigured("Escolha TLS ou SSL, nao os dois.")

    path = Path(ENV_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values = {
        "SMTP_HOST": host,
        "SMTP_PORT": str(port),
        "SMTP_USERNAME": username,
        "SMTP_PASSWORD": password,
        "SMTP_FROM_EMAIL": from_email,
        "SMTP_FROM_NAME": str(from_name or "SIGE MPE").replace("\r", " ").replace("\n", " ").strip(),
        "SMTP_USE_TLS": "true" if use_tls else "false",
        "SMTP_USE_SSL": "true" if use_ssl else "false",
    }
    seen = set()
    output = []
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    for key, value in values.items():
        os.environ[key] = value
    return {"ok": True, "host": host, "from_email": from_email}


def normalize_email(value):
    """Normaliza um endereco para armazenamento e comparacao."""
    return str(value or "").strip().lower()


def is_valid_email(value):
    """Faz uma validacao sintatica basica, sem consultar o provedor."""
    email = normalize_email(value)
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return False
    local = email.rsplit("@", 1)[0]
    return bool(
        len(local) <= 64
        and not local.startswith(".")
        and not local.endswith(".")
        and ".." not in local
    )


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "sim", "on"}


def _smtp_settings():
    host = str(os.getenv("SMTP_HOST") or "").strip()
    username = str(os.getenv("SMTP_USERNAME") or "").strip()
    password = str(os.getenv("SMTP_PASSWORD") or "")
    from_email = normalize_email(os.getenv("SMTP_FROM_EMAIL"))
    from_name = (
        str(os.getenv("SMTP_FROM_NAME") or "Loja")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
        or "Loja"
    )
    use_ssl = _env_bool("SMTP_USE_SSL", False)
    use_tls = _env_bool("SMTP_USE_TLS", not use_ssl)

    if not host or not from_email:
        raise EmailServiceNotConfigured(
            "Configure SMTP_HOST e SMTP_FROM_EMAIL para ativar o envio de e-mails."
        )
    if not is_valid_email(from_email):
        raise EmailServiceNotConfigured("SMTP_FROM_EMAIL nao contem um endereco valido.")
    if use_ssl and use_tls:
        raise EmailServiceNotConfigured(
            "SMTP_USE_SSL e SMTP_USE_TLS nao podem estar ativos ao mesmo tempo."
        )
    if username and not password:
        raise EmailServiceNotConfigured(
            "SMTP_PASSWORD e obrigatorio quando SMTP_USERNAME esta configurado."
        )

    raw_port = str(os.getenv("SMTP_PORT") or ("465" if use_ssl else "587")).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise EmailServiceNotConfigured("SMTP_PORT deve ser um numero valido.") from exc
    if not 1 <= port <= 65535:
        raise EmailServiceNotConfigured("SMTP_PORT esta fora do intervalo permitido.")

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "from_name": from_name,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
    }


def _send_message(recipient, subject, body):
    recipient = normalize_email(recipient)
    if not is_valid_email(recipient):
        raise EmailDeliveryError("O destinatario nao contem um endereco de e-mail valido.")

    settings = _smtp_settings()
    message = EmailMessage()
    message["From"] = formataddr((settings["from_name"], settings["from_email"]))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()
    try:
        if settings["use_ssl"]:
            with smtplib.SMTP_SSL(
                settings["host"], settings["port"], timeout=15, context=context
            ) as smtp:
                if settings["username"]:
                    smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], settings["port"], timeout=15) as smtp:
                smtp.ehlo()
                if settings["use_tls"]:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if settings["username"]:
                    smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
    except EmailServiceError:
        raise
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Nao foi possivel enviar o e-mail pelo servidor SMTP.") from exc
    return True


def send_email_verification_code(email, username, code):
    """Envia o codigo que confirma o e-mail cadastrado."""
    body = (
        f"Ola, {str(username or '').strip() or 'utilizador'}.\n\n"
        f"O seu codigo de verificacao e: {code}\n\n"
        "O codigo expira em 10 minutos e so pode ser utilizado uma vez. "
        "Se nao solicitou esta verificacao, ignore esta mensagem.\n"
    )
    return _send_message(email, "Confirme o seu e-mail", body)


def send_password_reset_code(email, username, code):
    """Envia o codigo de uso unico para redefinir a senha."""
    body = (
        f"Ola, {str(username or '').strip() or 'utilizador'}.\n\n"
        f"O seu codigo para redefinir a senha e: {code}\n\n"
        "O codigo expira em 10 minutos e so pode ser utilizado uma vez. "
        "Se nao solicitou a alteracao, ignore esta mensagem.\n"
    )
    return _send_message(email, "Codigo para redefinir a senha", body)


def send_password_changed_notice(email, username):
    """Avisa o titular depois de a senha ser alterada."""
    body = (
        f"Ola, {str(username or '').strip() or 'utilizador'}.\n\n"
        "A senha da sua conta foi alterada com sucesso.\n"
        "Se nao realizou esta alteracao, contacte imediatamente o administrador.\n"
    )
    return _send_message(email, "A sua senha foi alterada", body)
