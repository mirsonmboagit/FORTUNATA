"""Avisos de seguranca enviados ao proprietario sem expor segredos.

Nao ha servidor neste modo de funcionamento. Por isso o aviso e enviado pela
configuracao SMTP da propria instalacao, da mesma forma que a recuperacao de
palavra-passe. Uma falha de e-mail nunca pode desfazer uma alteracao de senha
ja concluida; o evento continua registado na auditoria local.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from threading import Thread


_EVENT_LABELS = {
    "ADMIN_CREATED": "Uma conta administradora foi criada",
    "PASSWORD_CHANGED": "A palavra-passe de uma conta foi alterada",
    "ACCOUNT_BLOCKED": "Uma conta foi bloqueada",
    "ACCOUNT_UNBLOCKED": "Uma conta foi desbloqueada",
}


def _recipient() -> str:
    """Lê apenas o endereço público distribuído com o cliente."""
    try:
        from licensing.offline_issuer_key import OFFLINE_LICENSE_REQUEST_EMAIL

        return str(OFFLINE_LICENSE_REQUEST_EMAIL or "").strip()
    except Exception:
        return ""


def notify_superadmin_account_event(username: str, event: str) -> bool:
    """Tenta avisar o proprietário; nunca inclui senha, hash ou código.

    Retorna ``True`` quando o aviso foi colocado para envio. A função é
    deliberadamente de melhor esforço: a conta já foi gravada com segurança
    antes deste passo e não deve ser alterada por uma indisponibilidade de
    rede/e-mail. O SMTP executa numa thread daemon para que uma rede lenta
    nunca atrase o login, a alteração de senha ou os testes locais.
    """
    recipient = _recipient()
    label = _EVENT_LABELS.get(str(event or "").strip())
    safe_username = str(username or "").strip()
    if not recipient or not label or not safe_username:
        return False

    computer = str(os.environ.get("COMPUTERNAME") or "computador local").strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        "Alerta de seguranca do MIRSON MBOA.\n\n"
        f"Evento: {label}.\n"
        f"Utilizador: {safe_username}\n"
        f"Computador: {computer}\n"
        f"Data: {timestamp}\n\n"
        "Nenhuma palavra-passe, hash ou codigo foi incluido neste aviso. "
        "Se nao reconhece a acao, contacte o comprador e reveja o registo local.\n"
    )
    def deliver() -> None:
        try:
            from utils.business.email_service import send_system_email

            send_system_email(recipient, "MIRSON MBOA - alerta de seguranca", body)
        except Exception:
            # O evento principal ja foi guardado no banco. Nao retemos senha
            # ou fila em ficheiro local apenas por causa de uma falha SMTP.
            return

    try:
        Thread(target=deliver, name="sige-security-email", daemon=True).start()
    except Exception:
        return False
    return True
