"""Licenciamento local assinado, sem servidor HTTP nem API.

O computador do cliente cria um pedido ligado a sua identidade local. O
terminal do superadmin assina uma licenca para esse pedido e ela e entregue por
e-mail. A verificacao posterior e totalmente local: assinatura, computador,
datas e protecao contra recuo evidente do relogio.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from licensing.crypto import new_device_keypair
from licensing.device_identity import device_fingerprint, device_label
from licensing.offline_issuer_key import OFFLINE_LICENSE_PUBLIC_KEY, OFFLINE_LICENSE_REQUEST_EMAIL
from licensing.secure_store import CredentialStorageError, WindowsDPAPIProtector


UTC = timezone.utc
REQUEST_PREFIX = "SIGE-REQ1"
LICENSE_PREFIX = "SIGE-LIC1"
REVOCATION_PREFIX = "SIGE-REV1"
SUSPENSION_PREFIX = "SIGE-SUS1"
REACTIVATION_PREFIX = "SIGE-RES1"
# Opcoes do seletor; o prazo segue junto com o pedido para o emissor.
LICENSE_REQUEST_PLANS = {
    "Mensal": "1 mes",
    "Trimestral": "3 meses",
    "Semestral": "6 meses",
    "Anual": "1 ano",
    "Vitalicia": "Vitalicia",
}
RESTORATION_PREFIX = "SIGE-RST1"
PRODUCT_NAME = "SIGE-MPE"
STATE_VERSION = 1


class OfflineLicenseError(ValueError):
    """Uma solicitacao ou licenca offline nao e valida."""


class OfflineLicenseStorageError(RuntimeError):
    """O cofre DPAPI local nao pode ser utilizado com seguranca."""


@dataclass(frozen=True)
class LicenseResult:
    allowed: bool
    state: str
    message: str
    expires_at: str | None = None
    customer_id: str | None = None


ERROR_MESSAGES = {
    "activation_required": "Este computador ainda nao possui uma licenca. Envie o pedido de licenca ao superadmin.",
    "issuer_not_configured": "A chave publica do emissor de licencas ainda nao foi configurada nesta instalacao.",
    "invalid_license": "O codigo de licenca e invalido ou foi alterado.",
    "incomplete_license": "Cole o codigo completo da licenca, iniciado por SIGE-LIC1.",
    "revoked": "Esta licenca foi cancelada pelo superadmin e nao pode ser utilizada.",
    "revocation_wrong_license": "O codigo de cancelamento nao pertence a esta licenca ou computador.",
    "revocation_instead": "Este e um codigo de cancelamento. Use a opcao Aplicar cancelamento.",
    "suspended": "Esta licenca foi suspensa pelo superadmin. Importe o codigo de reativacao para voltar a utiliza-la.",
    "suspension_wrong_license": "O codigo de suspensao nao pertence a esta licenca ou computador.",
    "suspension_instead": "Este e um codigo de suspensao. Use a opcao Aplicar suspensao.",
    "reactivation_wrong_license": "O codigo de reativacao nao pertence a esta licenca ou computador.",
    "reactivation_requires_suspension": "Este codigo de reativacao nao corresponde a uma suspensao aplicada nesta licenca.",
    "reactivation_instead": "Este e um codigo de reativacao. Use a opcao Aplicar reativacao.",
    "restoration_wrong_license": "O codigo de recuperacao nao pertence a esta licenca ou computador.",
    "restoration_wrong_revocation": "O codigo de recuperacao nao corresponde ao cancelamento aplicado nesta licenca.",
    "restoration_instead": "Este e um codigo de recuperacao. Use a opcao Aplicar recuperacao.",
    "license_request_instead": "Este e o pedido de licenca, nao a licenca. Cole o codigo recebido que inicia por SIGE-LIC1.",
    "wrong_device": "Esta licenca foi emitida para outro computador.",
    "expired": "A licenca expirou. Contacte o superadmin para renovar.",
    "not_started": "A licenca ainda nao esta em vigor.",
    "clock_tampered": "A data deste computador foi recuada. Contacte o superadmin.",
    "storage_error": "A protecao local da licenca nao pode ser lida. Contacte o superadmin.",
    "request_email_not_configured": "O e-mail que recebe pedidos de licenca ainda nao foi configurado pelo superadmin.",
    "request_already_submitted": "Este computador ja enviou o seu pedido de licenca. Aguarde o codigo de ativacao.",
}


_LICENSE_CODE_PATTERN = re.compile(
    # A assinatura Ed25519 tem 64 bytes, ou 86 caracteres em base64url sem
    # preenchimento. O tamanho fixo impede que texto posterior do e-mail seja
    # absorvido quando o utilizador cola o corpo inteiro da mensagem.
    rf"{re.escape(LICENSE_PREFIX)}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{{86}}(?![A-Za-z0-9_-])"
)
_REVOCATION_CODE_PATTERN = re.compile(
    rf"{re.escape(REVOCATION_PREFIX)}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{{86}}(?![A-Za-z0-9_-])"
)
_SUSPENSION_CODE_PATTERN = re.compile(
    rf"{re.escape(SUSPENSION_PREFIX)}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{{86}}(?![A-Za-z0-9_-])"
)
_REACTIVATION_CODE_PATTERN = re.compile(
    rf"{re.escape(REACTIVATION_PREFIX)}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{{86}}(?![A-Za-z0-9_-])"
)
_RESTORATION_CODE_PATTERN = re.compile(
    rf"{re.escape(RESTORATION_PREFIX)}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{{86}}(?![A-Za-z0-9_-])"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(UTC).isoformat(timespec="seconds")


def _parse_datetime(value: object, *, end_of_day: bool = False) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.max if end_of_day else time.min)
    else:
        text = str(value or "").strip()
        if not text:
            raise OfflineLicenseError("A data da licenca e obrigatoria.")
        try:
            if len(text) == 10:
                parsed = datetime.combine(date.fromisoformat(text), time.max if end_of_day else time.min)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OfflineLicenseError("A data da licenca e invalida.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    text = str(value or "").strip()
    if not text or len(text) > 16384:
        raise OfflineLicenseError("O codigo de licenca e invalido.")
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as exc:
        raise OfflineLicenseError("O codigo de licenca e invalido.") from exc
    # Rejeita codificacoes alternativas com bits de preenchimento alterados.
    # Sem isto, pequenas mudancas no ultimo caractere poderiam decodificar para
    # os mesmos bytes e tornar a auditoria do codigo ambigua.
    if _b64encode(decoded) != text:
        raise OfflineLicenseError("O codigo de licenca e invalido.")
    return decoded


def _base64_key(value: str, *, private: bool = False) -> bytes:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception as exc:
        raise OfflineLicenseError("A chave de assinatura e invalida.") from exc
    if len(raw) != 32:
        raise OfflineLicenseError("A chave de assinatura e invalida.")
    try:
        if private:
            Ed25519PrivateKey.from_private_bytes(raw)
        else:
            Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise OfflineLicenseError("A chave de assinatura e invalida.") from exc
    return raw


def _safe_text(value: object, field: str, *, maximum: int = 160) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(character in text for character in "\r\n\x00"):
        raise OfflineLicenseError(f"{field} e invalido.")
    return text


def _fingerprint(value: object) -> str:
    fingerprint = str(value or "").strip().lower()
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        raise OfflineLicenseError("A identidade do computador e invalida.")
    return fingerprint


def _decode_payload(value: str, prefix: str, expected_parts: int) -> list[str]:
    parts = str(value or "").strip().split(".")
    if len(parts) != expected_parts or parts[0] != prefix:
        raise OfflineLicenseError("O codigo de licenca e invalido.")
    return parts


def _json_payload(encoded: str) -> dict[str, Any]:
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineLicenseError("O codigo de licenca e invalido.") from exc
    if not isinstance(payload, dict):
        raise OfflineLicenseError("O codigo de licenca e invalido.")
    return payload


def _validate_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("O pedido de licenca nao pertence a este sistema.")
    result = {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "created_at": _iso(_parse_datetime(payload.get("created_at"))),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(_base64_key(str(payload.get("device_public_key") or ""))).decode("ascii"),
    }
    details = payload.get("request_details")
    if isinstance(details, dict):
        result["request_details"] = {
            key: _safe_text(details[key], key, maximum=254)
            for key in ("username", "contact_email", "customer", "request_type", "plan_choice",
                        "requested_plan", "requested_duration", "current_plan", "current_expires_at", "license_id")
            if str(details.get(key) or "").strip()
        }
    return result


def parse_license_request(request_code: str) -> dict[str, Any]:
    """Le um pedido criado pelo programa do cliente, sem contactar a rede."""
    parts = _decode_payload(request_code, REQUEST_PREFIX, 2)
    return _validate_request_payload(_json_payload(parts[1]))


def _validate_license_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("A licenca nao pertence a este sistema.")
    starts_at = _parse_datetime(payload.get("not_before"))
    expires_at = _parse_datetime(payload.get("expires_at"), end_of_day=True)
    if expires_at <= starts_at:
        raise OfflineLicenseError("O periodo da licenca e invalido.")
    try:
        license_id = str(uuid.UUID(str(payload.get("license_id") or "")))
    except (ValueError, AttributeError) as exc:
        raise OfflineLicenseError("O identificador da licenca e invalido.") from exc
    return {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "license_id": license_id,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "customer_ref": _safe_text(payload.get("customer_ref"), "O cliente"),
        "plan_name": _safe_text(payload.get("plan_name"), "O plano", maximum=96),
        "issued_at": _iso(_parse_datetime(payload.get("issued_at"))),
        "not_before": _iso(starts_at),
        "expires_at": _iso(expires_at),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(_base64_key(str(payload.get("device_public_key") or ""))).decode("ascii"),
        "nonce": _safe_text(payload.get("nonce"), "A licenca", maximum=128),
    }


def _optional_safe_text(value: object, field: str, *, maximum: int = 160, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if len(text) > maximum or any(character in text for character in "\r\n\x00"):
        raise OfflineLicenseError(f"{field} e invalido.")
    return text


def _validate_revocation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida um cancelamento assinado sem confiar no texto recebido."""
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("O cancelamento nao pertence a este sistema.")
    try:
        revocation_id = str(uuid.UUID(str(payload.get("revocation_id") or "")))
        license_id = str(uuid.UUID(str(payload.get("license_id") or "")))
    except (ValueError, AttributeError) as exc:
        raise OfflineLicenseError("O identificador do cancelamento e invalido.") from exc
    issued_at = _parse_datetime(payload.get("issued_at"))
    effective_at = _parse_datetime(payload.get("effective_at"))
    if effective_at < issued_at - timedelta(minutes=5):
        raise OfflineLicenseError("A data de cancelamento e invalida.")
    return {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "revocation_id": revocation_id,
        "license_id": license_id,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(
            _base64_key(str(payload.get("device_public_key") or ""))
        ).decode("ascii"),
        "issued_at": _iso(issued_at),
        "effective_at": _iso(effective_at),
        "reason": _optional_safe_text(
            payload.get("reason"),
            "O motivo do cancelamento",
            maximum=180,
            default="Cancelada pelo superadmin.",
        ),
        "nonce": _safe_text(payload.get("nonce"), "O cancelamento", maximum=128),
    }


def _validate_suspension_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida uma suspensao temporaria assinada pelo superadmin."""
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("A suspensao nao pertence a este sistema.")
    try:
        suspension_id = str(uuid.UUID(str(payload.get("suspension_id") or "")))
        license_id = str(uuid.UUID(str(payload.get("license_id") or "")))
    except (ValueError, AttributeError) as exc:
        raise OfflineLicenseError("O identificador da suspensao e invalido.") from exc
    issued_at = _parse_datetime(payload.get("issued_at"))
    effective_at = _parse_datetime(payload.get("effective_at"))
    if effective_at < issued_at - timedelta(minutes=5):
        raise OfflineLicenseError("A data de suspensao e invalida.")
    return {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "suspension_id": suspension_id,
        "license_id": license_id,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(
            _base64_key(str(payload.get("device_public_key") or ""))
        ).decode("ascii"),
        "issued_at": _iso(issued_at),
        "effective_at": _iso(effective_at),
        "reason": _optional_safe_text(
            payload.get("reason"),
            "O motivo da suspensao",
            maximum=180,
            default="Suspensa pelo superadmin.",
        ),
        "nonce": _safe_text(payload.get("nonce"), "A suspensao", maximum=128),
    }


def _validate_reactivation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida uma reativacao ligada a uma suspensao especifica."""
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("A reativacao nao pertence a este sistema.")
    try:
        reactivation_id = str(uuid.UUID(str(payload.get("reactivation_id") or "")))
        suspension_id = str(uuid.UUID(str(payload.get("suspension_id") or "")))
        license_id = str(uuid.UUID(str(payload.get("license_id") or "")))
    except (ValueError, AttributeError) as exc:
        raise OfflineLicenseError("O identificador da reativacao e invalido.") from exc
    issued_at = _parse_datetime(payload.get("issued_at"))
    effective_at = _parse_datetime(payload.get("effective_at"))
    if effective_at < issued_at - timedelta(minutes=5):
        raise OfflineLicenseError("A data de reativacao e invalida.")
    return {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "reactivation_id": reactivation_id,
        "suspension_id": suspension_id,
        "license_id": license_id,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(
            _base64_key(str(payload.get("device_public_key") or ""))
        ).decode("ascii"),
        "issued_at": _iso(issued_at),
        "effective_at": _iso(effective_at),
        "reason": _optional_safe_text(
            payload.get("reason"),
            "O motivo da reativacao",
            maximum=180,
            default="Reativada pelo superadmin.",
        ),
        "nonce": _safe_text(payload.get("nonce"), "A reativacao", maximum=128),
    }


def _validate_restoration_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida uma recuperacao excepcional de um cancelamento especifico."""
    if payload.get("version") != STATE_VERSION or payload.get("product") != PRODUCT_NAME:
        raise OfflineLicenseError("A recuperacao nao pertence a este sistema.")
    try:
        restoration_id = str(uuid.UUID(str(payload.get("restoration_id") or "")))
        revocation_id = str(uuid.UUID(str(payload.get("revocation_id") or "")))
        license_id = str(uuid.UUID(str(payload.get("license_id") or "")))
    except (ValueError, AttributeError) as exc:
        raise OfflineLicenseError("O identificador da recuperacao e invalido.") from exc
    issued_at = _parse_datetime(payload.get("issued_at"))
    effective_at = _parse_datetime(payload.get("effective_at"))
    if effective_at < issued_at - timedelta(minutes=5):
        raise OfflineLicenseError("A data de recuperacao e invalida.")
    return {
        "version": STATE_VERSION,
        "product": PRODUCT_NAME,
        "restoration_id": restoration_id,
        "revocation_id": revocation_id,
        "license_id": license_id,
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": base64.b64encode(
            _base64_key(str(payload.get("device_public_key") or ""))
        ).decode("ascii"),
        "issued_at": _iso(issued_at),
        "effective_at": _iso(effective_at),
        "reason": _optional_safe_text(
            payload.get("reason"),
            "O motivo da recuperacao",
            maximum=180,
            default="Cancelamento revertido pelo superadmin.",
        ),
        "nonce": _safe_text(payload.get("nonce"), "A recuperacao", maximum=128),
    }


def verify_license_code(license_code: str, public_key: str) -> dict[str, Any]:
    """Confirma a assinatura Ed25519 antes de confiar em qualquer campo."""
    parts = _decode_payload(license_code, LICENSE_PREFIX, 3)
    payload = _json_payload(parts[1])
    try:
        signature = _b64decode(parts[2])
        Ed25519PublicKey.from_public_bytes(_base64_key(public_key)).verify(signature, _canonical_json(payload))
    except OfflineLicenseError:
        raise
    except Exception as exc:
        raise OfflineLicenseError("A assinatura da licenca nao e valida.") from exc
    return _validate_license_payload(payload)


def verify_revocation_code(revocation_code: str, public_key: str) -> dict[str, Any]:
    """Confirma que o cancelamento foi assinado pelo mesmo superadmin."""
    parts = _decode_payload(revocation_code, REVOCATION_PREFIX, 3)
    payload = _json_payload(parts[1])
    try:
        signature = _b64decode(parts[2])
        Ed25519PublicKey.from_public_bytes(_base64_key(public_key)).verify(signature, _canonical_json(payload))
    except OfflineLicenseError:
        raise
    except Exception as exc:
        raise OfflineLicenseError("A assinatura do cancelamento nao e valida.") from exc
    return _validate_revocation_payload(payload)


def verify_suspension_code(suspension_code: str, public_key: str) -> dict[str, Any]:
    """Confirma uma suspensao assinada pelo mesmo superadmin."""
    parts = _decode_payload(suspension_code, SUSPENSION_PREFIX, 3)
    payload = _json_payload(parts[1])
    try:
        signature = _b64decode(parts[2])
        Ed25519PublicKey.from_public_bytes(_base64_key(public_key)).verify(signature, _canonical_json(payload))
    except OfflineLicenseError:
        raise
    except Exception as exc:
        raise OfflineLicenseError("A assinatura da suspensao nao e valida.") from exc
    return _validate_suspension_payload(payload)


def verify_reactivation_code(reactivation_code: str, public_key: str) -> dict[str, Any]:
    """Confirma uma reativacao assinada e ligada a uma suspensao."""
    parts = _decode_payload(reactivation_code, REACTIVATION_PREFIX, 3)
    payload = _json_payload(parts[1])
    try:
        signature = _b64decode(parts[2])
        Ed25519PublicKey.from_public_bytes(_base64_key(public_key)).verify(signature, _canonical_json(payload))
    except OfflineLicenseError:
        raise
    except Exception as exc:
        raise OfflineLicenseError("A assinatura da reativacao nao e valida.") from exc
    return _validate_reactivation_payload(payload)


def verify_restoration_code(restoration_code: str, public_key: str) -> dict[str, Any]:
    """Confirma a recuperacao assinada de um cancelamento especifico."""
    parts = _decode_payload(restoration_code, RESTORATION_PREFIX, 3)
    payload = _json_payload(parts[1])
    try:
        signature = _b64decode(parts[2])
        Ed25519PublicKey.from_public_bytes(_base64_key(public_key)).verify(signature, _canonical_json(payload))
    except OfflineLicenseError:
        raise
    except Exception as exc:
        raise OfflineLicenseError("A assinatura da recuperacao nao e valida.") from exc
    return _validate_restoration_payload(payload)


def normalize_license_code(value: object) -> str:
    """Extrai uma licenca completa de texto copiado de um e-mail.

    Alguns clientes de e-mail inserem quebras de linha visuais em codigos
    longos. Os componentes base64url de uma licenca nunca possuem espacos,
    portanto remover apenas espacos e quebras nao muda o codigo assinado.
    """
    text = str(value or "")
    compact = "".join(text.split())
    match = _LICENSE_CODE_PATTERN.search(compact)
    return match.group(0) if match else compact


def normalize_revocation_code(value: object) -> str:
    """Extrai um SIGE-REV1 completo mesmo quando o e-mail o quebra em linhas."""
    text = "".join(str(value or "").split())
    match = _REVOCATION_CODE_PATTERN.search(text)
    return match.group(0) if match else text


def normalize_suspension_code(value: object) -> str:
    """Extrai um SIGE-SUS1 completo mesmo quando o e-mail o quebra em linhas."""
    text = "".join(str(value or "").split())
    match = _SUSPENSION_CODE_PATTERN.search(text)
    return match.group(0) if match else text


def normalize_reactivation_code(value: object) -> str:
    """Extrai um SIGE-RES1 completo mesmo quando o e-mail o quebra em linhas."""
    text = "".join(str(value or "").split())
    match = _REACTIVATION_CODE_PATTERN.search(text)
    return match.group(0) if match else text


def normalize_restoration_code(value: object) -> str:
    """Extrai um SIGE-RST1 completo mesmo quando o e-mail o quebra em linhas."""
    text = "".join(str(value or "").split())
    match = _RESTORATION_CODE_PATTERN.search(text)
    return match.group(0) if match else text


def generate_issuer_private_key() -> str:
    """Gera uma chave de emissor; o chamador deve protege-la com DPAPI."""
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


class OfflineLicenseIssuer:
    """Emite codigos assinados localmente pelo superadmin."""

    def __init__(self, private_key: str):
        self._private = Ed25519PrivateKey.from_private_bytes(_base64_key(private_key, private=True))

    @property
    def public_key(self) -> str:
        raw = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def issue(
        self,
        request_code: str,
        *,
        customer_ref: str,
        plan_name: str,
        starts_at: str | date | datetime,
        expires_at: str | date | datetime,
        license_id: str | None = None,
        stable_request_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assina uma ativacao ou renovacao para a mesma instalacao.

        Nas renovacoes, ``license_id`` e ``stable_request_id`` sao mantidos.
        Assim o codigo muda porque a validade muda, mas a identidade logica da
        licenca continua unica para o mesmo computador.
        """
        request = parse_license_request(request_code)
        starts = _parse_datetime(starts_at)
        expires = _parse_datetime(expires_at, end_of_day=True)
        if expires <= starts:
            raise OfflineLicenseError("A data de expiracao deve ser posterior ao inicio.")
        if license_id is None:
            resolved_license_id = str(uuid.uuid4())
        else:
            try:
                resolved_license_id = str(uuid.UUID(str(license_id)))
            except (ValueError, AttributeError) as exc:
                raise OfflineLicenseError("O identificador da licenca e invalido.") from exc
        request_id = (
            _safe_text(stable_request_id, "O pedido", maximum=96)
            if stable_request_id is not None
            else request["request_id"]
        )
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "license_id": resolved_license_id,
            "request_id": request_id,
            "customer_ref": _safe_text(customer_ref, "O cliente"),
            "plan_name": _safe_text(plan_name, "O plano", maximum=96),
            "issued_at": _iso(),
            "not_before": _iso(starts),
            "expires_at": _iso(expires),
            "fingerprint": request["fingerprint"],
            "device_public_key": request["device_public_key"],
            "nonce": secrets.token_urlsafe(18),
        }
        signature = self._private.sign(_canonical_json(payload))
        code = f"{LICENSE_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
        return code, _validate_license_payload(payload)

    def issue_revocation(
        self,
        license_code: str,
        *,
        reason: str = "",
        effective_at: str | date | datetime | None = None,
        revocation_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assina o cancelamento de uma licenca ja emitida.

        O codigo resultante continua ligado a mesma licenca e dispositivo. Ele
        nao apaga dados do cliente: quando importado, bloqueia o login local.
        """
        license_payload = verify_license_code(license_code, self.public_key)
        issued_at = _now()
        effective = _parse_datetime(effective_at or issued_at)
        if effective < issued_at - timedelta(minutes=5):
            raise OfflineLicenseError("A data de cancelamento nao pode estar no passado.")
        if revocation_id is None:
            resolved_revocation_id = str(uuid.uuid4())
        else:
            try:
                resolved_revocation_id = str(uuid.UUID(str(revocation_id)))
            except (ValueError, AttributeError) as exc:
                raise OfflineLicenseError("O identificador do cancelamento e invalido.") from exc
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "revocation_id": resolved_revocation_id,
            "license_id": license_payload["license_id"],
            "request_id": license_payload["request_id"],
            "fingerprint": license_payload["fingerprint"],
            "device_public_key": license_payload["device_public_key"],
            "issued_at": _iso(issued_at),
            "effective_at": _iso(effective),
            "reason": _optional_safe_text(
                reason,
                "O motivo do cancelamento",
                maximum=180,
                default="Cancelada pelo superadmin.",
            ),
            "nonce": secrets.token_urlsafe(18),
        }
        signature = self._private.sign(_canonical_json(payload))
        code = f"{REVOCATION_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
        return code, _validate_revocation_payload(payload)

    def issue_suspension(
        self,
        license_code: str,
        *,
        reason: str = "",
        effective_at: str | date | datetime | None = None,
        suspension_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assina uma suspensao temporaria para a licenca e PC indicados."""
        license_payload = verify_license_code(license_code, self.public_key)
        issued_at = _now()
        effective = _parse_datetime(effective_at or issued_at)
        if effective < issued_at - timedelta(minutes=5):
            raise OfflineLicenseError("A data de suspensao nao pode estar no passado.")
        if suspension_id is None:
            resolved_suspension_id = str(uuid.uuid4())
        else:
            try:
                resolved_suspension_id = str(uuid.UUID(str(suspension_id)))
            except (ValueError, AttributeError) as exc:
                raise OfflineLicenseError("O identificador da suspensao e invalido.") from exc
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "suspension_id": resolved_suspension_id,
            "license_id": license_payload["license_id"],
            "request_id": license_payload["request_id"],
            "fingerprint": license_payload["fingerprint"],
            "device_public_key": license_payload["device_public_key"],
            "issued_at": _iso(issued_at),
            "effective_at": _iso(effective),
            "reason": _optional_safe_text(
                reason,
                "O motivo da suspensao",
                maximum=180,
                default="Suspensa pelo superadmin.",
            ),
            "nonce": secrets.token_urlsafe(18),
        }
        signature = self._private.sign(_canonical_json(payload))
        code = f"{SUSPENSION_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
        return code, _validate_suspension_payload(payload)

    def issue_reactivation(
        self,
        license_code: str,
        suspension_code: str,
        *,
        reason: str = "",
        effective_at: str | date | datetime | None = None,
        reactivation_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assina a reativacao da suspensao especifica desta licenca.

        O codigo nunca aceita apenas o ``license_id``: ele tambem precisa do
        ``suspension_id`` previamente emitido. Assim, uma reativacao antiga
        nao pode desbloquear uma suspensao nova da mesma instalacao.
        """
        license_payload = verify_license_code(license_code, self.public_key)
        suspension_payload = verify_suspension_code(suspension_code, self.public_key)
        identity_fields = ("license_id", "request_id", "fingerprint", "device_public_key")
        if any(
            str(suspension_payload.get(field) or "") != str(license_payload.get(field) or "")
            for field in identity_fields
        ):
            raise OfflineLicenseError("A suspensao nao pertence a esta licenca.")
        issued_at = _now()
        effective = _parse_datetime(effective_at or issued_at)
        if effective < issued_at - timedelta(minutes=5):
            raise OfflineLicenseError("A data de reativacao nao pode estar no passado.")
        if reactivation_id is None:
            resolved_reactivation_id = str(uuid.uuid4())
        else:
            try:
                resolved_reactivation_id = str(uuid.UUID(str(reactivation_id)))
            except (ValueError, AttributeError) as exc:
                raise OfflineLicenseError("O identificador da reativacao e invalido.") from exc
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "reactivation_id": resolved_reactivation_id,
            "suspension_id": suspension_payload["suspension_id"],
            "license_id": license_payload["license_id"],
            "request_id": license_payload["request_id"],
            "fingerprint": license_payload["fingerprint"],
            "device_public_key": license_payload["device_public_key"],
            "issued_at": _iso(issued_at),
            "effective_at": _iso(effective),
            "reason": _optional_safe_text(
                reason,
                "O motivo da reativacao",
                maximum=180,
                default="Reativada pelo superadmin.",
            ),
            "nonce": secrets.token_urlsafe(18),
        }
        signature = self._private.sign(_canonical_json(payload))
        code = f"{REACTIVATION_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
        return code, _validate_reactivation_payload(payload)

    def issue_restoration(
        self,
        license_code: str,
        revocation_code: str,
        *,
        reason: str = "",
        effective_at: str | date | datetime | None = None,
        restoration_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Assina a correcao excepcional de um SIGE-REV1 previamente emitido.

        O codigo permanece ligado ao cancelamento por ``revocation_id``. Um
        SIGE-RST1 nao pode libertar uma nova revogacao criada posteriormente.
        """
        license_payload = verify_license_code(license_code, self.public_key)
        revocation_payload = verify_revocation_code(revocation_code, self.public_key)
        identity_fields = ("license_id", "request_id", "fingerprint", "device_public_key")
        if any(
            str(revocation_payload.get(field) or "") != str(license_payload.get(field) or "")
            for field in identity_fields
        ):
            raise OfflineLicenseError("O cancelamento nao pertence a esta licenca.")
        issued_at = _now()
        effective = _parse_datetime(effective_at or issued_at)
        if effective < issued_at - timedelta(minutes=5):
            raise OfflineLicenseError("A data de recuperacao nao pode estar no passado.")
        if restoration_id is None:
            resolved_restoration_id = str(uuid.uuid4())
        else:
            try:
                resolved_restoration_id = str(uuid.UUID(str(restoration_id)))
            except (ValueError, AttributeError) as exc:
                raise OfflineLicenseError("O identificador da recuperacao e invalido.") from exc
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "restoration_id": resolved_restoration_id,
            "revocation_id": revocation_payload["revocation_id"],
            "license_id": license_payload["license_id"],
            "request_id": license_payload["request_id"],
            "fingerprint": license_payload["fingerprint"],
            "device_public_key": license_payload["device_public_key"],
            "issued_at": _iso(issued_at),
            "effective_at": _iso(effective),
            "reason": _optional_safe_text(
                reason,
                "O motivo da recuperacao",
                maximum=180,
                default="Cancelamento revertido pelo superadmin.",
            ),
            "nonce": secrets.token_urlsafe(18),
        }
        signature = self._private.sign(_canonical_json(payload))
        code = f"{RESTORATION_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
        return code, _validate_restoration_payload(payload)


def offline_data_root() -> Path:
    override = str(os.environ.get("SIGEMPE_OFFLINE_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return Path(local_app_data).expanduser().resolve() / "MIRSON-MBOA"
    return Path.home().resolve() / ".mirson-mboa"


def desktop_license_state_path() -> Path:
    return offline_data_root() / "licensing" / "offline-license.dat"


def superadmin_state_path() -> Path:
    return offline_data_root() / "superadmin" / "state.dat"


class ProtectedJsonStore:
    """Pequeno cofre JSON com DPAPI e escrita atomica."""

    def __init__(self, path: str | Path, protector=None):
        self.path = Path(path)
        self.protector = protector or WindowsDPAPIProtector()

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            encrypted = base64.b64decode(self.path.read_bytes(), validate=True)
            clear = self.protector.unprotect(encrypted)
            value = json.loads(clear.decode("utf-8"))
        except CredentialStorageError as exc:
            raise OfflineLicenseStorageError("O cofre pertence a outro utilizador ou computador.") from exc
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OfflineLicenseStorageError("O cofre local esta corrompido.") from exc
        if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
            raise OfflineLicenseStorageError("O cofre local e invalido.")
        return value

    def save(self, value: dict[str, Any]) -> None:
        if not isinstance(value, dict):
            raise OfflineLicenseStorageError("Os dados locais sao invalidos.")
        payload = dict(value)
        payload["version"] = STATE_VERSION
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            clear = _canonical_json(payload)
            encrypted = self.protector.protect(clear)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(base64.b64encode(encrypted))
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except CredentialStorageError as exc:
            raise OfflineLicenseStorageError("Nao foi possivel proteger os dados locais.") from exc
        except OSError as exc:
            raise OfflineLicenseStorageError("Nao foi possivel guardar os dados locais.") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class OfflineLicenseStore:
    """Estado da instalacao protegido para o utilizador Windows atual."""

    def __init__(self, path: str | Path | None = None, protector=None):
        self._store = ProtectedJsonStore(path or desktop_license_state_path(), protector=protector)

    def load(self) -> dict[str, Any]:
        return self._store.load() or {"version": STATE_VERSION}

    def save(self, value: dict[str, Any]) -> None:
        self._store.save(value)

    def ensure_device_identity(self) -> dict[str, Any]:
        state = self.load()
        private_key = str(state.get("device_private_key") or "")
        public_key = str(state.get("device_public_key") or "")
        try:
            _base64_key(private_key, private=True)
            _base64_key(public_key)
        except OfflineLicenseError:
            private_key, public_key = new_device_keypair()
            state["device_private_key"] = private_key
            state["device_public_key"] = public_key
            self.save(state)
        return state


class OfflineLicenseClient:
    """Valida uma licenca local, sem abrir conexoes de rede."""

    def __init__(
        self,
        public_key: str | None = None,
        *,
        credential_store: OfflineLicenseStore | None = None,
        fingerprint_provider: Callable[[], str] = device_fingerprint,
        now_provider: Callable[[], datetime] = _now,
        request_recipient_email: str | None = None,
    ):
        self.public_key = str(public_key if public_key is not None else OFFLINE_LICENSE_PUBLIC_KEY).strip()
        self.credential_store = credential_store or OfflineLicenseStore()
        self._fingerprint_provider = fingerprint_provider
        self._now_provider = now_provider
        self.request_recipient_email = str(
            request_recipient_email
            if request_recipient_email is not None
            else OFFLINE_LICENSE_REQUEST_EMAIL
        ).strip().lower()

    @classmethod
    def from_runtime(cls) -> "OfflineLicenseClient":
        return cls()

    @staticmethod
    def _result(state: str, *, expires_at: str | None = None, customer_id: str | None = None) -> LicenseResult:
        return LicenseResult(False, state, ERROR_MESSAGES.get(state, "A licenca nao pode ser validada."), expires_at, customer_id)

    def activation_request(self) -> str:
        """Cria ou reutiliza o pedido pendente ligado a este computador."""
        state = self.credential_store.ensure_device_identity()
        fingerprint = _fingerprint(self._fingerprint_provider())
        existing = str(state.get("license_request_code") or "")
        if existing:
            try:
                request = parse_license_request(existing)
                if (
                    request["fingerprint"] == fingerprint
                    and request["device_public_key"] == str(state.get("device_public_key") or "")
                ):
                    return existing
            except OfflineLicenseError:
                pass
        payload = {
            "version": STATE_VERSION,
            "product": PRODUCT_NAME,
            "request_id": secrets.token_urlsafe(18),
            "created_at": _iso(self._now_provider()),
            "fingerprint": fingerprint,
            "device_public_key": str(state["device_public_key"]),
            "device_label": device_label(fingerprint),
        }
        request_code = f"{REQUEST_PREFIX}.{_b64encode(_canonical_json(payload))}"
        state["license_request_code"] = request_code
        state.pop("license_request_submitted_at", None)
        self.credential_store.save(state)
        return request_code

    def pending_license_request(self) -> tuple[str, str, bool]:
        """Devolve o pedido unico e o e-mail publico definido pelo superadmin."""
        recipient = self.request_recipient_email
        if not recipient or "@" not in recipient:
            raise OfflineLicenseError("request_email_not_configured")
        request_code = self.activation_request()
        state = self.credential_store.load()
        return recipient, request_code, bool(state.get("license_request_submitted_at"))

    def prepare_license_request(self, *, username: str = "", plan: str = "") -> str:
        """Preenche o pedido com a licenca assinada, preservando os reenvios."""
        code = self.activation_request()
        request = parse_license_request(code)
        if request.get("request_details"):
            return code
        state = self.credential_store.load()
        current = {}
        if state.get("license_code"):
            current = self._payload_for_current_device(state["license_code"], state)
        details = {"username": str(username or "").strip(),
                   "request_type": "Renovacao" if current else "Primeira ativacao"}
        if current:
            details.update(
                customer=current["customer_ref"],
                requested_plan=current["plan_name"],
                requested_duration="Manter prazo anterior",
                plan_choice="Manter plano atual",
                current_plan=current["plan_name"],
                current_expires_at=current["expires_at"],
                license_id=current["license_id"],
            )
        if plan:
            if plan not in LICENSE_REQUEST_PLANS:
                raise OfflineLicenseError("Selecione um plano valido.")
            details.update(requested_plan=plan,
                           requested_duration=LICENSE_REQUEST_PLANS[plan],
                           plan_choice="Alterar plano" if current else "Escolher plano")
        return self.set_license_request_details(details)

    def set_license_request_details(self, details: dict[str, Any]) -> str:
        """Guarda os dados do pedido sem alterar a sua identidade nos reenvios."""
        code = self.activation_request()
        state = self.credential_store.load()
        payload = parse_license_request(code)
        if state.get("license_request_submitted_at") or payload.get("request_details"):
            return code
        payload["request_details"] = details
        payload = _validate_request_payload(payload)
        code = f"{REQUEST_PREFIX}.{_b64encode(_canonical_json(payload))}"
        state["license_request_code"] = code
        self.credential_store.save(state)
        return code

    def mark_license_request_submitted(self) -> bool:
        """Regista a unica abertura do pedido antes de o cliente enviar o e-mail."""
        _recipient, _request_code, already_submitted = self.pending_license_request()
        if already_submitted:
            return False
        state = self.credential_store.load()
        state["license_request_submitted_at"] = _iso(self._now_provider())
        self.credential_store.save(state)
        return True

    def retry_license_request(self) -> bool:
        """Liberta apenas o reenvio do mesmo pedido, nunca cria outro pedido.

        Serve para quando o e-mail falha ou o cliente precisa reenviar. O
        request_id, a identidade do dispositivo e a eventual licenca ja
        assinada permanecem iguais; assim, o superadmin so pode devolver a
        mesma licenca em vez de fabricar uma segunda autorizacao.
        """
        self.activation_request()
        state = self.credential_store.load()
        if not state.get("license_request_submitted_at"):
            return False
        state.pop("license_request_submitted_at", None)
        self.credential_store.save(state)
        return True

    def _payload_for_current_device(self, license_code: str, state: dict[str, Any]) -> dict[str, Any]:
        payload = verify_license_code(license_code, self.public_key)
        if payload["fingerprint"] != _fingerprint(self._fingerprint_provider()):
            raise OfflineLicenseError("wrong_device")
        if payload["device_public_key"] != str(state.get("device_public_key") or ""):
            raise OfflineLicenseError("wrong_device")
        return payload

    @staticmethod
    def _control_matches_license(control: object, license_payload: dict[str, Any]) -> bool:
        """Compara somente os campos que ligam um controlo a uma licenca."""
        if not isinstance(control, dict):
            return False
        return all(
            str(control.get(field) or "") == str(license_payload.get(field) or "")
            for field in ("license_id", "request_id", "fingerprint", "device_public_key")
        )

    @classmethod
    def _revocation_matches_license(cls, revocation: object, license_payload: dict[str, Any]) -> bool:
        return cls._control_matches_license(revocation, license_payload)

    @classmethod
    def _suspension_matches_license(cls, suspension: object, license_payload: dict[str, Any]) -> bool:
        return cls._control_matches_license(suspension, license_payload)

    @classmethod
    def _restoration_matches_revocation(
        cls,
        restoration: object,
        revocation: object,
        license_payload: dict[str, Any],
    ) -> bool:
        if not cls._control_matches_license(restoration, license_payload):
            return False
        if not isinstance(restoration, dict) or not isinstance(revocation, dict):
            return False
        return str(restoration.get("revocation_id") or "") == str(revocation.get("revocation_id") or "")

    def _applied_revocation_result(
        self,
        state: dict[str, Any],
        license_payload: dict[str, Any],
        now: datetime,
    ) -> LicenseResult | None:
        revocation = state.get("license_revocation")
        if not self._revocation_matches_license(revocation, license_payload):
            return None
        restoration = state.get("license_restoration")
        if self._restoration_matches_revocation(restoration, revocation, license_payload):
            try:
                restored_at = _parse_datetime(
                    state.get("license_restoration_applied_effective_at")
                    or restoration.get("effective_at")
                )
            except (OfflineLicenseError, AttributeError):
                # Um recibo corrompido jamais pode tornar uma revogacao mais
                # permissiva; mantenha o bloqueio seguro.
                return self._result("storage_error")
            if now >= restored_at:
                return None
        try:
            # A assinatura conserva a data definida pelo superadmin, mas uma
            # vez que o codigo chega a este PC e e importado manualmente, o
            # cancelamento e imediato. Isto tambem evita que segundos de
            # diferenca entre os relogios do dono e do cliente o atrasem.
            effective_at = _parse_datetime(
                state.get("license_revocation_applied_effective_at")
                or revocation.get("effective_at")
            )
        except (OfflineLicenseError, AttributeError):
            # Um cofre alterado nao deve tornar a licenca mais permissiva.
            return self._result("storage_error")
        if now >= effective_at:
            return self._result(
                "revoked",
                expires_at=license_payload.get("expires_at"),
                customer_id=license_payload.get("license_id"),
            )
        return None

    def _applied_suspension_result(
        self,
        state: dict[str, Any],
        license_payload: dict[str, Any],
        now: datetime,
    ) -> LicenseResult | None:
        suspension = state.get("license_suspension")
        if not self._suspension_matches_license(suspension, license_payload):
            return None
        try:
            # Tal como no cancelamento, depois de o codigo assinado ser
            # importado neste computador a suspensao torna-se imediata, sem
            # depender de diferencas pequenas entre relogios.
            effective_at = _parse_datetime(
                state.get("license_suspension_applied_effective_at")
                or suspension.get("effective_at")
            )
        except (OfflineLicenseError, AttributeError):
            return self._result("storage_error")
        if now >= effective_at:
            return self._result(
                "suspended",
                expires_at=license_payload.get("expires_at"),
                customer_id=license_payload.get("license_id"),
            )
        return None

    def validate(self) -> LicenseResult:
        try:
            state = self.credential_store.load()
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        license_code = str(state.get("license_code") or "")
        if not license_code:
            return self._result("activation_required")
        if not self.public_key:
            return self._result("issuer_not_configured")
        try:
            payload = self._payload_for_current_device(license_code, state)
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")

        now = self._now_provider().astimezone(UTC)
        revocation_result = self._applied_revocation_result(state, payload, now)
        if revocation_result is not None:
            return revocation_result
        suspension_result = self._applied_suspension_result(state, payload, now)
        if suspension_result is not None:
            return suspension_result
        try:
            last_seen = _parse_datetime(state.get("last_seen_at")) if state.get("last_seen_at") else None
        except OfflineLicenseError:
            return self._result("storage_error")
        # Para prazos de segundos ou minutos, uma tolerancia de cinco minutos
        # permitiria expirar e voltar atras no relogio. O maior horario visto
        # fica protegido no cofre local antes mesmo de devolver "expirada".
        if last_seen and now < last_seen:
            return self._result("clock_tampered", expires_at=payload["expires_at"], customer_id=payload["license_id"])
        if last_seen is None or now > last_seen:
            state["last_seen_at"] = _iso(now)
            try:
                self.credential_store.save(state)
            except OfflineLicenseStorageError:
                return self._result("storage_error")
        starts_at = _parse_datetime(payload["not_before"])
        expires_at = _parse_datetime(payload["expires_at"], end_of_day=True)
        if now < starts_at:
            return self._result("not_started", expires_at=payload["expires_at"], customer_id=payload["license_id"])
        if payload["expires_at"] == "9999-12-31T23:59:59+00:00":
            return LicenseResult(True, "active", "Licenca vitalicia ativa.", payload["expires_at"], payload["license_id"])
        if now > expires_at:
            return self._result("expired", expires_at=payload["expires_at"], customer_id=payload["license_id"])
        expires_label = payload["expires_at"].replace("T", " ").replace("+00:00", " UTC")
        return LicenseResult(True, "active", f"Licenca ativa ate {expires_label}.", payload["expires_at"], payload["license_id"])

    def apply_revocation(self, revocation_code: str) -> LicenseResult:
        """Importa um cancelamento assinado no computador a que ele pertence.

        Nao comunica com a Internet. O codigo deve ser entregue ao computador
        alvo e importado por alguem com acesso fisico a ele.
        """
        if not self.public_key:
            return self._result("issuer_not_configured")
        code = normalize_revocation_code(revocation_code)
        if code.startswith(f"{LICENSE_PREFIX}."):
            return self._result("incomplete_license")
        if code.startswith(f"{RESTORATION_PREFIX}."):
            return self._result("restoration_instead")
        if code and not code.startswith(f"{REVOCATION_PREFIX}."):
            return self._result("incomplete_license")
        try:
            state = self.credential_store.ensure_device_identity()
            payload = verify_revocation_code(code, self.public_key)
            if payload["fingerprint"] != _fingerprint(self._fingerprint_provider()):
                return self._result("revocation_wrong_license")
            if payload["device_public_key"] != str(state.get("device_public_key") or ""):
                return self._result("revocation_wrong_license")
            active_code = str(state.get("license_code") or "")
            if active_code:
                active_payload = self._payload_for_current_device(active_code, state)
                if not self._revocation_matches_license(payload, active_payload):
                    return self._result("revocation_wrong_license")
                if self._restoration_matches_revocation(
                    state.get("license_restoration"),
                    payload,
                    active_payload,
                ):
                    # Um SIGE-RST1 importado antes deste antigo SIGE-REV1
                    # impede que o e-mail de cancelamento seja usado depois
                    # para bloquear novamente a mesma licenca.
                    return self.validate()
            existing = state.get("license_revocation")
            if isinstance(existing, dict) and existing.get("license_id") not in {None, payload["license_id"]}:
                return self._result("revocation_wrong_license")
            state["license_revocation"] = payload
            applied_at = _iso(self._now_provider())
            state["license_revocation_applied_at"] = applied_at
            state["license_revocation_applied_effective_at"] = applied_at
            self.credential_store.save(state)
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")
        return self.validate()

    def apply_restoration(self, restoration_code: str) -> LicenseResult:
        """Importa a recuperacao assinada de um cancelamento SIGE-REV1.

        Ela tambem deixa um recibo local quando o cancelamento ainda nao foi
        importado. Assim, um e-mail SIGE-REV1 antigo nao pode ser aplicado
        depois para desfazer a decisao mais recente do superadmin.
        """
        if not self.public_key:
            return self._result("issuer_not_configured")
        code = normalize_restoration_code(restoration_code)
        if code.startswith(f"{REVOCATION_PREFIX}."):
            return self._result("revocation_instead")
        if code.startswith(f"{SUSPENSION_PREFIX}."):
            return self._result("suspension_instead")
        if code.startswith(f"{REACTIVATION_PREFIX}."):
            return self._result("reactivation_instead")
        if code.startswith(f"{LICENSE_PREFIX}.") or (code and not code.startswith(f"{RESTORATION_PREFIX}.")):
            return self._result("incomplete_license")
        try:
            state = self.credential_store.ensure_device_identity()
            payload = verify_restoration_code(code, self.public_key)
            if payload["fingerprint"] != _fingerprint(self._fingerprint_provider()):
                return self._result("restoration_wrong_license")
            if payload["device_public_key"] != str(state.get("device_public_key") or ""):
                return self._result("restoration_wrong_license")
            active_code = str(state.get("license_code") or "")
            if not active_code:
                return self._result("activation_required")
            active_payload = self._payload_for_current_device(active_code, state)
            if not self._control_matches_license(payload, active_payload):
                return self._result("restoration_wrong_license")
            revocation = state.get("license_revocation")
            if isinstance(revocation, dict):
                if not self._revocation_matches_license(revocation, active_payload):
                    return self._result("restoration_wrong_revocation")
                if str(revocation.get("revocation_id") or "") != str(payload.get("revocation_id") or ""):
                    return self._result("restoration_wrong_revocation")
            state["license_restoration"] = payload
            applied_at = _iso(self._now_provider())
            state["license_restoration_applied_at"] = applied_at
            state["license_restoration_applied_effective_at"] = applied_at
            self.credential_store.save(state)
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")
        return self.validate()

    def apply_suspension(self, suspension_code: str) -> LicenseResult:
        """Importa uma suspensao temporaria assinada para este computador."""
        if not self.public_key:
            return self._result("issuer_not_configured")
        code = normalize_suspension_code(suspension_code)
        if code.startswith(f"{REVOCATION_PREFIX}."):
            return self._result("revocation_instead")
        if code.startswith(f"{REACTIVATION_PREFIX}."):
            return self._result("reactivation_instead")
        if code.startswith(f"{RESTORATION_PREFIX}."):
            return self._result("restoration_instead")
        if code.startswith(f"{LICENSE_PREFIX}.") or (code and not code.startswith(f"{SUSPENSION_PREFIX}.")):
            return self._result("incomplete_license")
        try:
            state = self.credential_store.ensure_device_identity()
            payload = verify_suspension_code(code, self.public_key)
            if payload["fingerprint"] != _fingerprint(self._fingerprint_provider()):
                return self._result("suspension_wrong_license")
            if payload["device_public_key"] != str(state.get("device_public_key") or ""):
                return self._result("suspension_wrong_license")
            active_code = str(state.get("license_code") or "")
            if not active_code:
                return self._result("activation_required")
            active_payload = self._payload_for_current_device(active_code, state)
            if not self._suspension_matches_license(payload, active_payload):
                return self._result("suspension_wrong_license")
            now = self._now_provider().astimezone(UTC)
            if self._applied_revocation_result(state, active_payload, now) is not None:
                return self._result(
                    "revoked",
                    expires_at=active_payload.get("expires_at"),
                    customer_id=active_payload.get("license_id"),
                )
            existing = state.get("license_suspension")
            if isinstance(existing, dict) and existing.get("license_id") not in {None, payload["license_id"]}:
                return self._result("suspension_wrong_license")
            state["license_suspension"] = payload
            applied_at = _iso(self._now_provider())
            state["license_suspension_applied_at"] = applied_at
            state["license_suspension_applied_effective_at"] = applied_at
            # Uma suspensao nova invalida qualquer recibo de uma reativacao
            # anterior para que ele nunca seja reutilizado indevidamente.
            state.pop("license_reactivation", None)
            state.pop("license_reactivation_applied_at", None)
            self.credential_store.save(state)
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")
        return self.validate()

    def apply_reactivation(self, reactivation_code: str) -> LicenseResult:
        """Remove apenas a suspensao correspondente a um codigo SIGE-RES1."""
        if not self.public_key:
            return self._result("issuer_not_configured")
        code = normalize_reactivation_code(reactivation_code)
        if code.startswith(f"{REVOCATION_PREFIX}."):
            return self._result("revocation_instead")
        if code.startswith(f"{SUSPENSION_PREFIX}."):
            return self._result("suspension_instead")
        if code.startswith(f"{RESTORATION_PREFIX}."):
            return self._result("restoration_instead")
        if code.startswith(f"{LICENSE_PREFIX}.") or (code and not code.startswith(f"{REACTIVATION_PREFIX}.")):
            return self._result("incomplete_license")
        try:
            state = self.credential_store.ensure_device_identity()
            payload = verify_reactivation_code(code, self.public_key)
            if payload["fingerprint"] != _fingerprint(self._fingerprint_provider()):
                return self._result("reactivation_wrong_license")
            if payload["device_public_key"] != str(state.get("device_public_key") or ""):
                return self._result("reactivation_wrong_license")
            active_code = str(state.get("license_code") or "")
            if not active_code:
                return self._result("activation_required")
            active_payload = self._payload_for_current_device(active_code, state)
            if not self._control_matches_license(payload, active_payload):
                return self._result("reactivation_wrong_license")
            now = self._now_provider().astimezone(UTC)
            revocation_result = self._applied_revocation_result(state, active_payload, now)
            if revocation_result is not None:
                return revocation_result
            suspension = state.get("license_suspension")
            if (
                not self._suspension_matches_license(suspension, active_payload)
                or str(suspension.get("suspension_id") or "") != str(payload.get("suspension_id") or "")
            ):
                return self._result("reactivation_requires_suspension")
            state["license_reactivation"] = payload
            state["license_reactivation_applied_at"] = _iso(self._now_provider())
            state.pop("license_suspension", None)
            state.pop("license_suspension_applied_at", None)
            state.pop("license_suspension_applied_effective_at", None)
            self.credential_store.save(state)
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")
        return self.validate()

    def activate(self, license_code: str) -> LicenseResult:
        if not self.public_key:
            return self._result("issuer_not_configured")
        code = normalize_license_code(license_code)
        if code.startswith(f"{REQUEST_PREFIX}."):
            return self._result("license_request_instead")
        if code.startswith(f"{REVOCATION_PREFIX}."):
            return self._result("revocation_instead")
        if code.startswith(f"{SUSPENSION_PREFIX}."):
            return self._result("suspension_instead")
        if code.startswith(f"{REACTIVATION_PREFIX}."):
            return self._result("reactivation_instead")
        if code.startswith(f"{RESTORATION_PREFIX}."):
            return self._result("restoration_instead")
        if code and not code.startswith(f"{LICENSE_PREFIX}."):
            return self._result("incomplete_license")
        try:
            state = self.credential_store.ensure_device_identity()
            payload = self._payload_for_current_device(code, state)
            now = self._now_provider().astimezone(UTC)
            revocation_result = self._applied_revocation_result(state, payload, now)
            if revocation_result is not None:
                return revocation_result
            suspension_result = self._applied_suspension_result(state, payload, now)
            if suspension_result is not None:
                return suspension_result
            previous_seen = _parse_datetime(state.get("last_seen_at")) if state.get("last_seen_at") else None
            if previous_seen and now < previous_seen:
                return self._result("clock_tampered")
            state["license_code"] = code
            state["last_seen_at"] = _iso(now)
            state.pop("license_request_code", None)
            state.pop("license_request_submitted_at", None)
            self.credential_store.save(state)
        except OfflineLicenseStorageError:
            return self._result("storage_error")
        except OfflineLicenseError as error:
            return self._result(str(error) if str(error) in ERROR_MESSAGES else "invalid_license")
        return self.validate()


def license_code_hash(license_code: str) -> str:
    """Identificador nao reversivel adequado para o historico local."""
    return hashlib.sha256(str(license_code or "").encode("utf-8")).hexdigest()
