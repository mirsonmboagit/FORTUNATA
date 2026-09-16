"""Provisionamento offline e assinado da conta admin do comprador.

O emissor fica somente no computador do proprietario. A instalacao do cliente
recebe um codigo assinado, confere-o com a chave publica ja distribuida e so
depois grava o hash da palavra-passe temporaria na sua base local. Nao existe
servidor, API ou palavra-passe reversivel neste fluxo.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from licensing.offline import OfflineLicenseError, verify_license_code


UTC = timezone.utc
PRODUCT_NAME = "SIGE-MPE"
PROVISIONING_VERSION = 1
ADMIN_PROVISIONING_PREFIX = "SIGE-ADM1"
_USERNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,47}\Z")


class AccountProvisioningError(ValueError):
    """O codigo assinado de conta nao pode ser utilizado."""


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
            raise AccountProvisioningError("A data do codigo de conta e obrigatoria.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AccountProvisioningError("A data do codigo de conta e invalida.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: object) -> bytes:
    text = str(value or "").strip()
    if not text or len(text) > 16384:
        raise AccountProvisioningError("O codigo de conta e invalido.")
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except Exception as exc:
        raise AccountProvisioningError("O codigo de conta e invalido.") from exc
    if _b64encode(decoded) != text:
        raise AccountProvisioningError("O codigo de conta e invalido.")
    return decoded


def _key(value: str, *, private: bool = False) -> bytes:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception as exc:
        raise AccountProvisioningError("A chave do emissor e invalida.") from exc
    if len(raw) != 32:
        raise AccountProvisioningError("A chave do emissor e invalida.")
    try:
        if private:
            Ed25519PrivateKey.from_private_bytes(raw)
        else:
            Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise AccountProvisioningError("A chave do emissor e invalida.") from exc
    return raw


def _safe_text(value: object, field: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(character in text for character in "\r\n\x00"):
        raise AccountProvisioningError(f"{field} e invalido.")
    return text


def _username(value: object) -> str:
    username = _safe_text(value, "O utilizador", maximum=48)
    if not _USERNAME_RE.fullmatch(username):
        raise AccountProvisioningError(
            "O utilizador deve ter 3 a 48 caracteres: letras, numeros, ponto, hifen ou sublinhado."
        )
    return username


def _optional_email(value: object) -> str | None:
    email = str(value or "").strip().lower()
    if not email:
        return None
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise AccountProvisioningError("O e-mail da conta e invalido.")
    return email


def _password_hash(value: object) -> str:
    hashed = _safe_text(value, "O hash da palavra-passe", maximum=200)
    # Hashes bcrypt sao sempre textos ASCII iniciados por $2a$, $2b$ ou $2y$.
    if len(hashed) != 60 or not hashed.startswith("$2"):
        raise AccountProvisioningError("O hash da palavra-passe temporaria e invalido.")
    return hashed


def _uuid(value: object, field: str) -> str:
    try:
        return str(uuid.UUID(str(value or "")))
    except (ValueError, AttributeError) as exc:
        raise AccountProvisioningError(f"{field} e invalido.") from exc


def _fingerprint(value: object) -> str:
    fingerprint = str(value or "").strip().lower()
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        raise AccountProvisioningError("A identidade do computador e invalida.")
    return fingerprint


def _public_device_key(value: object) -> str:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception as exc:
        raise AccountProvisioningError("A chave do computador e invalida.") from exc
    if len(raw) != 32:
        raise AccountProvisioningError("A chave do computador e invalida.")
    return base64.b64encode(raw).decode("ascii")


def _decode_code(value: object) -> tuple[dict[str, Any], bytes]:
    parts = str(value or "").strip().split(".")
    if len(parts) != 3 or parts[0] != ADMIN_PROVISIONING_PREFIX:
        raise AccountProvisioningError("O codigo de conta e invalido.")
    try:
        payload = json.loads(_b64decode(parts[1]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccountProvisioningError("O codigo de conta e invalido.") from exc
    if not isinstance(payload, dict):
        raise AccountProvisioningError("O codigo de conta e invalido.")
    return payload, _b64decode(parts[2])


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("version") != PROVISIONING_VERSION or payload.get("product") != PRODUCT_NAME:
        raise AccountProvisioningError("O codigo de conta nao pertence a este sistema.")
    issued_at = _parse_datetime(payload.get("issued_at"))
    expires_at = _parse_datetime(payload.get("expires_at"), end_of_day=True)
    if expires_at <= issued_at:
        raise AccountProvisioningError("O periodo do codigo de conta e invalido.")
    return {
        "version": PROVISIONING_VERSION,
        "product": PRODUCT_NAME,
        "provisioning_id": _uuid(payload.get("provisioning_id"), "O identificador de provisionamento"),
        "license_id": _uuid(payload.get("license_id"), "O identificador da licenca"),
        "request_id": _safe_text(payload.get("request_id"), "O pedido", maximum=96),
        "fingerprint": _fingerprint(payload.get("fingerprint")),
        "device_public_key": _public_device_key(payload.get("device_public_key")),
        "username": _username(payload.get("username")),
        "email": _optional_email(payload.get("email")),
        "password_hash": _password_hash(payload.get("password_hash")),
        "must_change_password": bool(payload.get("must_change_password")),
        "issued_at": _iso(issued_at),
        "expires_at": _iso(expires_at),
        "nonce": _safe_text(payload.get("nonce"), "O codigo de conta", maximum=128),
    }


def issue_admin_provisioning_code(
    issuer_private_key: str,
    license_code: str,
    *,
    username: str,
    password_hash: str,
    email: str | None = None,
    expires_at: date | datetime | str,
) -> tuple[str, dict[str, Any]]:
    """Cria um codigo de conta admin ligado a uma licenca ja emitida."""
    private = Ed25519PrivateKey.from_private_bytes(_key(issuer_private_key, private=True))
    public_key = base64.b64encode(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    try:
        license_payload = verify_license_code(license_code, public_key)
    except OfflineLicenseError as exc:
        raise AccountProvisioningError("A licenca escolhida para criar a conta e invalida.") from exc

    expiry = _parse_datetime(expires_at, end_of_day=True)
    issued_at = _now()
    if expiry <= issued_at:
        raise AccountProvisioningError("O codigo temporario deve expirar no futuro.")
    payload = {
        "version": PROVISIONING_VERSION,
        "product": PRODUCT_NAME,
        "provisioning_id": str(uuid.uuid4()),
        "license_id": license_payload["license_id"],
        "request_id": license_payload["request_id"],
        "fingerprint": license_payload["fingerprint"],
        "device_public_key": license_payload["device_public_key"],
        "username": _username(username),
        "email": _optional_email(email),
        "password_hash": _password_hash(password_hash),
        "must_change_password": True,
        "issued_at": _iso(issued_at),
        "expires_at": _iso(expiry),
        "nonce": secrets.token_urlsafe(18),
    }
    validated = _validate_payload(payload)
    signature = private.sign(_canonical_json(payload))
    code = f"{ADMIN_PROVISIONING_PREFIX}.{_b64encode(_canonical_json(payload))}.{_b64encode(signature)}"
    return code, validated


def verify_admin_provisioning_code(code: str, public_key: str) -> dict[str, Any]:
    """Confirma que o codigo veio do superadmin que assinou a licenca."""
    payload, signature = _decode_code(code)
    try:
        Ed25519PublicKey.from_public_bytes(_key(public_key)).verify(signature, _canonical_json(payload))
    except AccountProvisioningError:
        raise
    except Exception as exc:
        raise AccountProvisioningError("A assinatura do codigo de conta nao e valida.") from exc
    return _validate_payload(payload)


def validate_admin_provisioning_for_license(
    code: str,
    public_key: str,
    active_license_code: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Garante que o codigo temporario pertence a esta licenca/computador."""
    payload = verify_admin_provisioning_code(code, public_key)
    try:
        license_payload = verify_license_code(active_license_code, public_key)
    except OfflineLicenseError as exc:
        raise AccountProvisioningError("A licenca ativa deste computador e invalida.") from exc
    current = (now or _now()).astimezone(UTC)
    if current > _parse_datetime(payload["expires_at"], end_of_day=True):
        raise AccountProvisioningError("O codigo temporario de conta expirou. Peca outro ao superadmin.")
    for field in ("license_id", "request_id", "fingerprint", "device_public_key"):
        if payload[field] != license_payload[field]:
            raise AccountProvisioningError("O codigo de conta pertence a outro computador ou licenca.")
    return payload
