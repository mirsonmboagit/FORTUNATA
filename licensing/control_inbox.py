"""Aplica automaticamente as acoes de licenca recebidas por e-mail.

O superadmin envia um codigo assinado (SIGE-REV1/SUS1/RES1/RST1) para o
e-mail desta instalacao. Este modulo consulta essa caixa por IMAP e aplica
o codigo sozinho, sem qualquer acao do admin.

A assinatura do codigo e a fronteira de seguranca: nao confiamos no
remetente nem no assunto da mensagem.
"""

from __future__ import annotations

import hashlib
import imaplib
import os
import re
import ssl
from dataclasses import dataclass, field
from email import message_from_bytes
from typing import Any, Callable

from licensing.offline import LICENSE_PREFIX, OfflineLicenseClient

CONTROL_PREFIXES = (LICENSE_PREFIX, "SIGE-REV1", "SIGE-SUS1", "SIGE-RES1", "SIGE-RST1")
_CONTROL_PATTERN = re.compile(
    r"\b(SIGE-(?:LIC1|REV1|SUS1|RES1|RST1)\.[A-Za-z0-9_-]{1,16384})\b"
)


class ControlInboxError(RuntimeError):
    """A caixa de controlo nao pode ser lida ou aplicada."""


@dataclass(frozen=True)
class ControlInboxSettings:
    imap_host: str
    imap_port: int
    username: str
    password: str

    @property
    def configured(self) -> bool:
        return bool(self.imap_host and self.username and self.password)


@dataclass
class ControlInboxReport:
    scanned: int = 0
    applied: int = 0
    ignored: int = 0
    failures: list[str] = field(default_factory=list)


def _imap_host(smtp_host: str) -> str:
    host = str(smtp_host or "").strip().lower()
    if not host:
        return ""
    if "gmail" in host:
        return "imap.gmail.com"
    if host.startswith("smtp."):
        return "imap." + host[len("smtp.") :]
    return host


def control_inbox_settings() -> ControlInboxSettings:
    """Le a conta de e-mail desta instalacao, reutilizando o SMTP existente."""
    return ControlInboxSettings(
        imap_host=_imap_host(os.getenv("SMTP_HOST") or ""),
        imap_port=993,
        username=str(os.getenv("SMTP_USERNAME") or "").strip(),
        password="".join(str(os.getenv("SMTP_PASSWORD") or "").split()),
    )


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


def extract_control_code(raw_message: bytes) -> str:
    """Devolve o primeiro codigo de controlo assinado da mensagem."""
    try:
        message = message_from_bytes(raw_message)
    except Exception as exc:
        raise ControlInboxError("Uma mensagem de controlo nao pode ser lida.") from exc
    match = _CONTROL_PATTERN.search(_message_text(message))
    return match.group(1) if match else ""


def _apply_control_code(client: OfflineLicenseClient, code: str):
    if code.startswith(f"{LICENSE_PREFIX}."):
        return client.activate(code)
    if code.startswith("SIGE-REV1."):
        return client.apply_revocation(code)
    if code.startswith("SIGE-SUS1."):
        return client.apply_suspension(code)
    if code.startswith("SIGE-RES1."):
        return client.apply_reactivation(code)
    if code.startswith("SIGE-RST1."):
        return client.apply_restoration(code)
    return None


def _raw_message(fetch_data: Any) -> bytes:
    for item in fetch_data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    raise ControlInboxError("O servidor devolveu uma mensagem de controlo vazia.")


def _require_ok(status: Any, action: str) -> None:
    if str(status or "").upper() != "OK":
        raise ControlInboxError(f"O servidor de e-mail nao permitiu {action}.")


def _mark_seen(mailbox, message_id: bytes) -> None:
    try:
        mailbox.store(message_id, "+FLAGS", "\\Seen")
    except Exception:
        pass


def poll_control_inbox(
    client: OfflineLicenseClient,
    *,
    settings: ControlInboxSettings | None = None,
    imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
) -> ControlInboxReport:
    """Le a caixa e aplica os codigos de controlo encontrados.

    A aplicacao e idempotente. Inclui a primeira licenca e renovacoes, para
    que o administrador nunca precise copiar codigos do e-mail. Uma falha
    temporaria mantem a mensagem para a proxima consulta; um codigo de outro
    computador e marcado como visto.
    """
    report = ControlInboxReport()
    active = settings or control_inbox_settings()
    if not active.configured:
        return report

    mailbox = None
    try:
        try:
            mailbox = imap_factory(active.imap_host, active.imap_port)
            _require_ok(mailbox.login(active.username, active.password)[0], "entrar no e-mail")
            _require_ok(mailbox.select("INBOX")[0], "abrir a caixa de entrada")
            message_ids: list[bytes] = []
            for prefix in CONTROL_PREFIXES:
                # Processamos apenas mensagens ainda nao consumidas. Sem este
                # filtro, o mesmo e-mail assinado seria reaplicado a cada
                # ciclo e uma sessao valida seria devolvida continuamente ao
                # login, mesmo sem uma nova decisao do superadmin.
                status, result = mailbox.search(None, "UNSEEN", "TEXT", prefix)
                if str(status or "").upper() != "OK":
                    continue
                for message_id in (result[0] if result else b"").split():
                    if message_id not in message_ids:
                        message_ids.append(message_id)
            for message_id in message_ids:
                status, fetched = mailbox.fetch(message_id, "(RFC822)")
                if str(status or "").upper() != "OK":
                    continue
                try:
                    code = extract_control_code(_raw_message(fetched))
                except ControlInboxError as exc:
                    _mark_seen(mailbox, message_id)
                    report.failures.append(str(exc))
                    continue
                if not code:
                    continue
                report.scanned += 1
                try:
                    result = _apply_control_code(client, code)
                except Exception as exc:
                    report.failures.append(f"Acao de licenca pendente: {exc}")
                    continue
                state = str(getattr(result, "state", "") or "")
                if state == "storage_error":
                    report.failures.append("Nao foi possivel guardar a acao de licenca.")
                    continue
                _mark_seen(mailbox, message_id)
                if getattr(result, "allowed", False) or state in {"revoked", "suspended", "active"}:
                    report.applied += 1
                else:
                    report.ignored += 1
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
            raise ControlInboxError(
                "Nao foi possivel ligar a caixa de e-mail de licenca."
            ) from exc
    finally:
        if mailbox is not None:
            for closer in ("close", "logout"):
                try:
                    getattr(mailbox, closer)()
                except Exception:
                    pass
    return report


def control_message_hash(raw_message: bytes) -> str:
    return hashlib.sha256(raw_message).hexdigest()
