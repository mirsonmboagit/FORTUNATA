"""Mensagens de licenciamento offline enviadas pelo computador do dono."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr


LICENSE_REQUEST_SUBJECT = "MIRSON MBOA - Pedido de licenca"


class OfflineEmailError(RuntimeError):
    """O envio local por e-mail nao foi concluido."""


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str = "SIGE MPE Licencas"
    use_tls: bool = True
    use_ssl: bool = False


def _email(value: str, field: str) -> str:
    address = str(value or "").strip().lower()
    if not address or len(address) > 254 or "@" not in address or address.startswith("@") or address.endswith("@"):
        raise OfflineEmailError(f"{field} e invalido.")
    return address


def gmail_settings(sender_email: str, app_password: str) -> SMTPSettings:
    """Configuracao padrao do Gmail com STARTTLS, sem guardar a senha."""
    sender = _email(sender_email, "O e-mail Gmail")
    password = "".join(str(app_password or "").split())
    if len(password) < 16:
        raise OfflineEmailError("A palavra-passe de aplicacao do Gmail parece incompleta.")
    return SMTPSettings(
        host="smtp.gmail.com",
        port=587,
        username=sender,
        password=password,
        from_email=sender,
        use_tls=True,
        use_ssl=False,
    )


def license_request_body(request_code: str) -> str:
    """Corpo padrao do pedido; o codigo nao e mostrado na interface do cliente."""
    code = str(request_code or "").strip()
    if not code.startswith("SIGE-REQ1.") or len(code) > 16384:
        raise OfflineEmailError("O pedido de licenca e invalido.")
    from licensing.offline import parse_license_request, OfflineLicenseError
    try:
        request = parse_license_request(code)
    except OfflineLicenseError as exc:
        raise OfflineEmailError("O pedido de licenca e invalido.") from exc
    details = request.get("request_details") or {}
    def field(key):
        return " ".join(str(details.get(key) or "Nao informado").splitlines())
    return (
        "Ola,\n\n"
        "PEDIDO DE LICENCA / RENOVACAO\n\n"
        f"Tipo de pedido: {field('request_type')}\n"
        f"Utilizador solicitante (admin): {field('username')}\n"
        f"E-mail de contacto do solicitante: {field('contact_email')}\n"
        f"Cliente / estabelecimento: {field('customer')}\n"
        f"Licenca atual: {field('license_id')}\n"
        f"Plano atual: {field('current_plan')}\n"
        f"Expiracao atual: {field('current_expires_at')}\n\n"
        f"Escolha do cliente: {field('plan_choice')}\n"
        f"Plano pretendido: {field('requested_plan')}\n"
        f"Prazo pretendido: {field('requested_duration')}\n\n"
        f"Data do pedido (UTC): {request['created_at']}\n"
        f"Identificador do pedido: {request['request_id']}\n"
        f"Identificador do computador: {request['fingerprint']}\n\n"
        "Os dados do solicitante sao declarados no pedido; nao representam uma sessao autenticada.\n"
        "O plano e o prazo pedidos dependem da aprovacao do superadmin.\n"
        "Para manter o plano, confirme o prazo anterior no registo da licenca.\n\n"
        "Pedido unico de licenca:\n"
        f"{code}\n\n"
        "Este codigo e somente o pedido. NAO o cole na tela de ativacao; "
        "aguarde o segundo e-mail, cujo codigo comeca por SIGE-LIC1.\n\n"
        "O emissor local do superadmin pode criar a licenca correspondente.\n"
        "Um codigo expirado nao renova a validade ao ser introduzido novamente.\n"
    )


def _expiry_label(value: object) -> str:
    """Mantem a hora visivel para licencas de segundos/minutos."""
    raw = str(value or "").strip()
    if raw == "9999-12-31T23:59:59+00:00":
        return "Vitalicia (sem expiracao)"
    if "T" not in raw:
        return raw
    visible = raw.replace("T", " ")[:19]
    return f"{visible} UTC" if raw.endswith("+00:00") or raw.endswith("Z") else visible


def send_license_email(
    settings: SMTPSettings,
    recipient: str,
    license_code: str,
    *,
    customer_ref: str,
    plan_name: str,
    expires_at: str,
) -> None:
    """Envia o codigo assinado ao e-mail privado configurado pelo dono."""
    destination = _email(recipient, "O e-mail destinatario")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois ao mesmo tempo.")
    message = EmailMessage()
    message["Subject"] = f"Licenca SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "Foi emitida uma licenca offline do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Plano: {plan_name}\n"
        f"Valida ate: {_expiry_label(expires_at)}\n\n"
        "No computador autorizado, abra a tela de ativacao e cole o codigo completo abaixo, "
        "desde SIGE-LIC1. ate ao ultimo caractere. Se o Gmail o separar visualmente em linhas, "
        "pode copiar todas as linhas ou abrir o ficheiro .txt em anexo. "
        "Nao encaminhe este codigo: ele funciona apenas no computador que gerou o pedido.\n\n"
        f"{license_code}\n"
    )
    message.add_attachment(
        f"{license_code}\n",
        subtype="plain",
        filename="licenca-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar a licenca por e-mail. Verifique o Gmail e tente novamente.") from exc


def send_license_revocation_email(
    settings: SMTPSettings,
    recipient: str,
    revocation_code: str,
    *,
    customer_ref: str,
    reason: str,
    effective_at: str,
) -> None:
    """Envia o cancelamento assinado, sem prometer revogacao remota."""
    destination = _email(recipient, "O e-mail destinatario")
    code = str(revocation_code or "").strip()
    if not code.startswith("SIGE-REV1.") or len(code) > 16384:
        raise OfflineEmailError("O codigo de cancelamento da licenca e invalido.")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois ao mesmo tempo.")
    message = EmailMessage()
    message["Subject"] = f"Cancelamento de licenca SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "Foi emitido um cancelamento de licenca offline do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Efeito a partir de: {_expiry_label(effective_at)}\n"
        f"Motivo: {str(reason or 'Cancelada pelo superadmin.')}\n\n"
        "No computador autorizado, abra o controlo de licenca na tela de login e escolha "
        "APLICAR CANCELAMENTO. Cole o codigo completo SIGE-REV1 abaixo. Depois de importado, "
        "o acesso desse computador fica bloqueado. Este e-mail nao apaga dados da loja.\n\n"
        f"{code}\n"
    )
    message.add_attachment(
        f"{code}\n",
        subtype="plain",
        filename="cancelamento-licenca-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar o cancelamento por e-mail. Verifique o Gmail e tente novamente.") from exc


def send_license_suspension_email(
    settings: SMTPSettings,
    recipient: str,
    suspension_code: str,
    *,
    customer_ref: str,
    reason: str,
    effective_at: str,
) -> None:
    """Entrega uma suspensao reversivel para o computador autorizado."""
    destination = _email(recipient, "O e-mail destinatario")
    code = str(suspension_code or "").strip()
    if not code.startswith("SIGE-SUS1.") or len(code) > 16384:
        raise OfflineEmailError("O codigo de suspensao da licenca e invalido.")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois ao mesmo tempo.")
    message = EmailMessage()
    message["Subject"] = f"Suspensao de licenca SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "Foi emitida uma suspensao reversivel de licenca offline do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Efeito a partir de: {_expiry_label(effective_at)}\n"
        f"Motivo: {str(reason or 'Suspensa pelo superadmin.')}\n\n"
        "No computador autorizado, abra o controlo de licenca na tela de login e escolha "
        "APLICAR CODIGO DE SUSPENSAO. Cole o codigo completo SIGE-SUS1 abaixo. "
        "Depois de importado, o acesso fica bloqueado, mas podera ser reativado somente "
        "por um novo codigo assinado do superadmin. Este e-mail nao apaga dados da loja.\n\n"
        f"{code}\n"
    )
    message.add_attachment(
        f"{code}\n",
        subtype="plain",
        filename="suspensao-licenca-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar a suspensao por e-mail. Verifique o Gmail e tente novamente.") from exc


def send_license_reactivation_email(
    settings: SMTPSettings,
    recipient: str,
    reactivation_code: str,
    *,
    customer_ref: str,
    reason: str,
    effective_at: str,
) -> None:
    """Entrega a reativacao da suspensao atual, sem anular cancelamentos."""
    destination = _email(recipient, "O e-mail destinatario")
    code = str(reactivation_code or "").strip()
    if not code.startswith("SIGE-RES1.") or len(code) > 16384:
        raise OfflineEmailError("O codigo de reativacao da licenca e invalido.")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois ao mesmo tempo.")
    message = EmailMessage()
    message["Subject"] = f"Reativacao de licenca SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "Foi emitida uma reativacao para uma suspensao de licenca offline do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Efeito a partir de: {_expiry_label(effective_at)}\n"
        f"Motivo: {str(reason or 'Reativada pelo superadmin.')}\n\n"
        "No computador autorizado, abra o controlo de licenca na tela de login e escolha "
        "APLICAR CODIGO DE REATIVACAO. Cole o codigo completo SIGE-RES1 abaixo. "
        "A reativacao so remove a suspensao correspondente; ela nao consegue anular "
        "um cancelamento definitivo e a licenca continua sujeita ao prazo contratado.\n\n"
        f"{code}\n"
    )
    message.add_attachment(
        f"{code}\n",
        subtype="plain",
        filename="reativacao-licenca-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar a reativacao por e-mail. Verifique o Gmail e tente novamente.") from exc


def send_license_restoration_email(
    settings: SMTPSettings,
    recipient: str,
    restoration_code: str,
    *,
    customer_ref: str,
    reason: str,
    effective_at: str,
) -> None:
    """Entrega a recuperacao excepcional de um cancelamento definitivo."""
    destination = _email(recipient, "O e-mail destinatario")
    code = str(restoration_code or "").strip()
    if not code.startswith("SIGE-RST1.") or len(code) > 16384:
        raise OfflineEmailError("O codigo de recuperacao da licenca e invalido.")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois ao mesmo tempo.")
    message = EmailMessage()
    message["Subject"] = f"Recuperacao de cancelamento SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "O superadmin reverteu excepcionalmente um cancelamento de licenca offline do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Efeito a partir de: {_expiry_label(effective_at)}\n"
        f"Motivo: {str(reason or 'Cancelamento revertido pelo superadmin.')}\n\n"
        "No computador autorizado, abra a tela de login e escolha APLICAR CODIGO DE RECUPERACAO. "
        "Cole o codigo completo SIGE-RST1 abaixo. Este codigo apenas reverte o cancelamento "
        "indicado; a licenca continua sujeita ao prazo contratado e a uma nova decisao do superadmin.\n\n"
        f"{code}\n"
    )
    message.add_attachment(
        f"{code}\n",
        subtype="plain",
        filename="recuperacao-cancelamento-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar a recuperacao por e-mail. Verifique o Gmail e tente novamente.") from exc


def send_admin_provisioning_email(
    settings: SMTPSettings,
    recipient: str,
    provisioning_code: str,
    *,
    username: str,
    expires_at: str,
    customer_ref: str = "Cliente",
) -> None:
    """Entrega ao proprietario o codigo temporario da conta admin.

    A palavra-passe temporaria nao acompanha este e-mail: ela e conhecida
    somente por quem a definiu no terminal e deve ser entregue ao comprador
    por um canal seguro. O codigo contem apenas o hash bcrypt dessa senha.
    """
    destination = _email(recipient, "O e-mail destinatario")
    code = str(provisioning_code or "").strip()
    if not code.startswith("SIGE-ADM1.") or len(code) > 16384:
        raise OfflineEmailError("O codigo temporario da conta e invalido.")
    if settings.use_tls and settings.use_ssl:
        raise OfflineEmailError("Use TLS ou SSL, mas nao os dois.")
    message = EmailMessage()
    message["Subject"] = f"Conta admin SIGE MPE - {customer_ref}"
    message["From"] = formataddr((settings.from_name, _email(settings.from_email, "O e-mail remetente")))
    message["To"] = destination
    message.set_content(
        "Foi preparada uma conta admin temporaria para uma instalacao do SIGE MPE.\n\n"
        f"Cliente: {customer_ref}\n"
        f"Utilizador admin: {username}\n"
        f"Codigo valido ate: {str(expires_at)[:10]}\n\n"
        "No computador autorizado e ja licenciado, abra o login e cole o codigo completo "
        "SIGE-ADM1 abaixo para criar a conta. Entregue a palavra-passe temporaria por um "
        "canal separado e seguro; ela deve ser alterada no primeiro acesso.\n\n"
        f"{code}\n"
    )
    message.add_attachment(
        f"{code}\n",
        subtype="plain",
        filename="conta-admin-sige-mpe.txt",
    )
    context = ssl.create_default_context()
    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=context) as smtp:
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as smtp:
                smtp.ehlo()
                if settings.use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(settings.username, settings.password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OfflineEmailError("Nao foi possivel enviar o codigo da conta admin por e-mail.") from exc
