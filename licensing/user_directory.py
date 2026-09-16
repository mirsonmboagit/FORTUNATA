"""Consulta somente de leitura das contas da instalacao pelo superadmin."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from licensing.offline import OfflineLicenseClient, OfflineLicenseStore, OfflineLicenseError, OfflineLicenseStorageError, verify_license_code
from licensing.superadmin import SuperadminError
from utils.config.app_config import get_database_path


def local_user_directory(service, *, database_path=None, license_store=None):
    path = Path(database_path or get_database_path()).resolve()
    if not path.is_file():
        raise SuperadminError(f"Base de dados local nao encontrada: {path}")
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            users = [dict(row) for row in connection.execute("SELECT * FROM users ORDER BY role, username")]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            receipts = ([dict(row) for row in connection.execute("SELECT provisioning_id, username FROM admin_provisioning_receipts")]
                        if "admin_provisioning_receipts" in tables else [])
    except sqlite3.Error as exc:
        raise SuperadminError(f"Nao foi possivel consultar os utilizadores: {exc}") from exc

    licenses = {row["license_id"]: row for row in service.list_licenses()}
    provisions = {row["provisioning_id"]: row for row in service.list_admin_provisionings()}
    imported = {}
    for receipt in receipts:
        provision = provisions.get(receipt["provisioning_id"])
        if provision and provision.get("username") == receipt["username"]:
            imported[receipt["username"]] = provision["license_id"]

    installation = {"status": "sem licenca instalada"}
    try:
        store = license_store or OfflineLicenseStore()
        state = store.load()
        if state.get("license_code"):
            payload = verify_license_code(state["license_code"], service.public_key())
            # Consulta sem validate(): validate grava last_seen_at no cofre.
            client = OfflineLicenseClient(service.public_key(), credential_store=store)
            client._payload_for_current_device(state["license_code"], state)
            now = datetime.now(timezone.utc)
            status = "expirada" if datetime.fromisoformat(payload["expires_at"]) < now else "ativa"
            if datetime.fromisoformat(payload["not_before"]) > now:
                status = "ainda nao iniciada"
            control = client._applied_revocation_result(state, payload, now) or client._applied_suspension_result(state, payload, now)
            if control:
                status = control.state
            installation = {"license_id": payload["license_id"], "expires_at": payload["expires_at"],
                            "reference": licenses.get(payload["license_id"], {}).get("license_reference") or payload["license_id"],
                            "status": status}
    except (OfflineLicenseError, OfflineLicenseStorageError) as exc:
        installation = {"status": f"nao verificavel: {exc}"}

    for user in users:
        stored = user.pop("password", "") or ""
        stored = stored.decode("utf-8", errors="backslashreplace") if isinstance(stored, bytes) else str(stored)
        user["password_storage"] = "hash bcrypt; original irrecuperavel" if stored.startswith(("$2a$", "$2b$", "$2y$")) else "formato legado; consultar detalhes"
        user["stored_password_value"] = stored
        owner = user["username"] if user.get("role") == "admin" else user.get("data_owner")
        owner_license = imported.get(owner)
        user["owner_license"] = licenses.get(owner_license) if owner_license else None
        user["license_link"] = "importacao confirmada" if owner_license else "sem vinculo individual confirmado"
        user["installation_license"] = dict(installation)
    return {"database_path": str(path), "users": users, "installation_license": installation}
