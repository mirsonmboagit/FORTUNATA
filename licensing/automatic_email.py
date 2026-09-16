"""Emissor local que transforma pedidos recebidos por Gmail em licencas.

Nao abre porta, nao usa HTTP e nao depende de API. Ele roda somente no
computador do proprietario, consulta a caixa Gmail por IMAP e envia a licenca
assinada de volta para o endereco privado configurado. A chave privada nunca
vai para a instalacao do cliente.
"""

from __future__ import annotations

import imaplib
import hashlib
import os
import re
import socket
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr
from typing import Any, Callable

from licensing.offline import OfflineLicenseError, parse_license_request, superadmin_state_path
from licensing.offline_email import LICENSE_REQUEST_SUBJECT, SMTPSettings, send_license_email


GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
_REQUEST_PATTERN = re.compile(r"\b(SIGE-REQ1\.[A-Za-z0-9_-]{1,16384})\b")


class AutomaticEmailError(RuntimeError):
    """O emissor automatico nao conseguiu ler ou entregar uma licenca."""


@dataclass(frozen=True)
class IncomingLicenseRequest:
    message_id: bytes
    message_hash: str
    request_code: str
    sender: str


@dataclass
class AutomaticEmailReport:
    scanned: int = 0
    delivered: int = 0
    reused: int = 0
    rejected: int = 0
    failures: list[str] = field(default_factory=list)


def _decode_header(value: Any) -> str:
    chunks: list[str] = []
    for chunk, encoding in decode_header(str(value or "")):
        if isinstance(chunk, bytes):
            try:
                chunks.append(chunk.decode(encoding or "utf-8", errors="replace"))
            except LookupError:
                chunks.append(chunk.decode("utf-8", errors="replace"))
        else:
            chunks.append(str(chunk))
    return "".join(chunks).strip()


def _message_text(message) -> str:
    parts = message.walk() if message.is_multipart() else (message,)
    fragments: list[str] = []
    for part in parts:
        if part.get_content_type() != "text/plain":
            continue
        if str(part.get_content_disposition() or "").lower() == "attachment":
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            fragments.append(raw.decode(charset, errors="replace"))
        except LookupError:
            fragments.append(raw.decode("utf-8", errors="replace"))
    return "\n".join(fragments)


def parse_incoming_request(message_id: bytes, raw_message: bytes) -> IncomingLicenseRequest | None:
    """Aceita apenas a mensagem preparada pelo botao Pedir licenca."""
    try:
        message = message_from_bytes(raw_message)
    except Exception as exc:
        raise AutomaticEmailError("Uma mensagem do Gmail nao pode ser lida.") from exc
    if _decode_header(message.get("Subject")) != LICENSE_REQUEST_SUBJECT:
        return None
    match = _REQUEST_PATTERN.search(_message_text(message))
    if not match:
        raise AutomaticEmailError("O e-mail de pedido nao contem um codigo de pedido valido.")
    request_code = match.group(1)
    try:
        parse_license_request(request_code)
    except OfflineLicenseError as exc:
        raise AutomaticEmailError("O e-mail contem um pedido de licenca invalido.") from exc
    _name, sender = parseaddr(_decode_header(message.get("From")))
    return IncomingLicenseRequest(
        message_id=message_id,
        message_hash=hashlib.sha256(raw_message).hexdigest(),
        request_code=request_code,
        sender=sender.strip().lower(),
    )


def _require_ok(status: Any, action: str) -> None:
    if str(status or "").upper() != "OK":
        if action == "entrar no Gmail":
            raise AutomaticEmailError(
                "O Gmail recusou a autenticacao. Use uma palavra-passe de aplicacao nova de 16 caracteres, nao a senha normal."
            )
        raise AutomaticEmailError(f"O Gmail nao permitiu {action}.")


def _gmail_connection_message(error: BaseException) -> str:
    """Traduz falhas Gmail sem imprimir resposta bruta nem dados sensiveis."""
    detail = str(error).casefold()
    if isinstance(error, imaplib.IMAP4.abort):
        return "A ligacao IMAP com o Gmail foi interrompida. Verifique Internet, data/hora e tente novamente."
    if isinstance(error, imaplib.IMAP4.error):
        if "application-specific password" in detail:
            return (
                "O Gmail exige uma palavra-passe de aplicacao. No superadmin, escolha 5 e informe uma nova "
                "palavra-passe Gmail de 16 caracteres; nao use a senha normal."
            )
        if any(token in detail for token in ("authenticationfailed", "invalid credentials", "username and password", "web login required")):
            return (
                "O Gmail recusou a autenticacao. Confirme o mesmo Gmail configurado e uma palavra-passe de "
                "aplicacao valida de 16 caracteres."
            )
        if any(token in detail for token in ("imap disabled", "imap is disabled", "not enabled")):
            return "O acesso IMAP esta desativado nessa conta Gmail. Ative o IMAP e tente novamente."
        if any(token in detail for token in ("too many", "rate limit", "rate-limited")):
            return "O Gmail limitou temporariamente os acessos. Aguarde alguns minutos e tente novamente."
    if isinstance(error, (socket.gaierror, TimeoutError, ConnectionRefusedError, ssl.SSLError, OSError)):
        return "Nao foi possivel alcancar imap.gmail.com na porta 993. Verifique Internet, firewall e data/hora."
    return "Nao foi possivel ligar ao Gmail do emissor automatico."


def _raw_message(fetch_data: Any) -> bytes:
    for item in fetch_data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    raise AutomaticEmailError("O Gmail devolveu uma mensagem de pedido vazia.")


def _mark_seen(mailbox, message_id: bytes) -> None:
    status, _data = mailbox.store(message_id, "+FLAGS", "\\Seen")
    _require_ok(status, "marcar o pedido como concluido")


def poll_unread_requests(
    *,
    gmail_email: str,
    gmail_app_password: str,
    smtp_settings: SMTPSettings,
    recipient_email: str,
    issue_or_get: Callable[[str, str], tuple[str, dict[str, Any], bool]],
    was_delivered: Callable[[str], bool] | None = None,
    mark_delivered: Callable[[str], None] | None = None,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    send_license: Callable[..., None] = send_license_email,
) -> AutomaticEmailReport:
    """Processa uma vez os pedidos de licenca da caixa Gmail configurada.

    Somente mensagens com o assunto exato do aplicativo sao lidas. Tambem sao
    encontrados pedidos que o proprietario ja abriu no Gmail: abrir um e-mail
    nunca deve impedir a ativacao do cliente. O cofre local marca entregas
    concluidas para que uma mensagem antiga nao envie a mesma licenca em cada
    consulta.

    Uma falha de emissao ou envio nao marca a entrega; a tentativa seguinte
    reutiliza exatamente a mesma licenca assinada, sem fabricar outra.
    """
    report = AutomaticEmailReport()
    mailbox = None
    try:
        try:
            mailbox = imap_factory(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
            _require_ok(mailbox.login(gmail_email, gmail_app_password)[0], "entrar no Gmail")
            _require_ok(mailbox.select("INBOX")[0], "abrir a caixa de entrada")
            # A busca e limitada ao assunto reservado. Nao percorremos toda a
            # caixa de entrada e nao dependemos de a mensagem continuar como
            # nao lida depois de o proprietario a consultar no Gmail.
            status, result = mailbox.search(None, f'HEADER Subject "{LICENSE_REQUEST_SUBJECT}"')
            _require_ok(status, "procurar pedidos de licenca")
            message_ids = (result[0] if result else b"").split()
            for message_id in message_ids:
                status, fetched = mailbox.fetch(message_id, "(RFC822)")
                _require_ok(status, "ler um pedido de licenca")
                try:
                    request = parse_incoming_request(message_id, _raw_message(fetched))
                except AutomaticEmailError as exc:
                    # E-mail com o assunto reservado, mas sem pedido valido:
                    # marca-o para nao bloquear a fila para sempre.
                    _mark_seen(mailbox, message_id)
                    report.rejected += 1
                    report.failures.append(str(exc))
                    continue
                if request is None:
                    continue
                report.scanned += 1
                try:
                    if was_delivered is not None and was_delivered(request.message_hash):
                        # Uma copia/reenvio posterior do mesmo pedido nao
                        # precisa criar nem voltar a enviar a mesma licenca.
                        _mark_seen(mailbox, message_id)
                        continue
                    license_code, payload, created = issue_or_get(request.request_code, request.sender)
                    send_license(
                        smtp_settings,
                        recipient_email,
                        license_code,
                        customer_ref=str(payload.get("customer_ref") or "Cliente por e-mail"),
                        plan_name=str(payload.get("plan_name") or "Mensal"),
                        expires_at=str(payload.get("expires_at") or ""),
                    )
                    if mark_delivered is not None:
                        mark_delivered(request.message_hash)
                    _mark_seen(mailbox, message_id)
                    report.delivered += 1
                    if not created:
                        report.reused += 1
                except Exception as exc:
                    # Mantem como nao lido. Uma tentativa posterior nao cria
                    # uma segunda licenca porque issue_or_get devolve a mesma.
                    report.failures.append(f"Pedido pendente: {exc}")
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
            raise AutomaticEmailError(_gmail_connection_message(exc)) from exc
    finally:
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:
                pass
            try:
                mailbox.logout()
            except Exception:
                pass
    return report


def poll_superadmin_once(service, *, imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL) -> AutomaticEmailReport:
    """Adaptador entre o cofre DPAPI do superadmin e a caixa Gmail."""
    settings = service.automatic_email_settings()
    smtp_settings = SMTPSettings(
        host="smtp.gmail.com",
        port=587,
        username=settings.gmail_email,
        password=settings.gmail_app_password,
        from_email=settings.gmail_email,
        use_tls=True,
        use_ssl=False,
    )

    def issue_or_get(request_code: str, sender: str):
        customer_ref = settings.customer_ref
        if customer_ref.casefold() == "cliente por e-mail" and sender:
            customer_ref = sender[:120]
        return service.issue_or_get_license(
            request_code,
            customer_ref=customer_ref,
            plan_name=settings.plan_name,
            duration_amount=settings.duration_amount,
            duration_unit=settings.duration_unit,
            allow_renewal=settings.auto_renewals,
        )

    return poll_unread_requests(
        gmail_email=settings.gmail_email,
        gmail_app_password=settings.gmail_app_password,
        smtp_settings=smtp_settings,
        recipient_email=settings.recipient_email,
        issue_or_get=issue_or_get,
        was_delivered=service.automatic_email_message_was_delivered,
        mark_delivered=service.mark_automatic_email_message_delivered,
        imap_factory=imap_factory,
    )


@contextmanager
def _exclusive_emitter_lock():
    """Impede duas janelas locais de emitirem o mesmo pedido ao mesmo tempo."""
    if os.name != "nt":
        yield
        return
    import msvcrt

    lock_path = superadmin_state_path().with_suffix(".emitter.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise AutomaticEmailError("O emissor automatico ja esta ativo neste computador.") from exc
        try:
            yield
        finally:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def run_superadmin_emitter(service, *, stop_requested: Callable[[], bool] | None = None) -> None:
    """Mantem o emissor local ativo ate Ctrl+C ou pedido externo de paragem."""
    should_stop = stop_requested or (lambda: False)
    with _exclusive_emitter_lock():
        while not should_stop():
            settings = service.automatic_email_settings()
            try:
                report = poll_superadmin_once(service)
                if report.delivered or report.rejected or report.failures:
                    print(
                        f"Emissor: {report.delivered} entregue(s), {report.reused} reenvio(s), "
                        f"{report.rejected} rejeitado(s)."
                    )
                    for failure in report.failures:
                        print(f"  - {failure}")
            except AutomaticEmailError as error:
                # Falhas temporarias de Internet/Gmail nao devem obrigar o
                # proprietario a iniciar o emissor de novo.
                print(f"Emissor: {error} Nova tentativa em breve.")
            for _ in range(settings.poll_seconds):
                if should_stop():
                    return
                time.sleep(1)
