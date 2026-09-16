"""Verificacao local da assinatura do emissor e prova do dispositivo."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def device_proof_message(device_id: str, fingerprint: str, timestamp: int) -> bytes:
    return canonical_json(
        {
            "device_id": str(device_id),
            "fingerprint": str(fingerprint),
            "purpose": "sige-mpe-license-validation-v1",
            "timestamp": int(timestamp),
        }
    )


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception as exc:
        raise ValueError("Chave codificada de forma invalida.") from exc
    if len(raw) != 32:
        raise ValueError("Tamanho de chave invalido.")
    return raw


def new_device_keypair() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    raw_private = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw_private).decode("ascii"), base64.b64encode(raw_public).decode("ascii")


def sign_device_proof(private_key: str, device_id: str, fingerprint: str) -> tuple[int, str]:
    timestamp = int(time.time())
    try:
        private = Ed25519PrivateKey.from_private_bytes(_decode_key(private_key))
        signature = private.sign(device_proof_message(device_id, fingerprint, timestamp))
    except Exception as exc:
        raise ValueError("Chave privada do dispositivo invalida.") from exc
    return timestamp, base64.b64encode(signature).decode("ascii")


def verify_issuer_proof(public_key: str, validation: dict[str, Any], proof: dict[str, Any]) -> bool:
    if str(proof.get("algorithm") or "") != "Ed25519":
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(_decode_key(public_key))
        signature = base64.b64decode(str(proof.get("signature") or ""), validate=True)
        public.verify(signature, canonical_json(validation))
        return True
    except Exception:
        return False
