"""Estado e operacoes locais do superadmin offline.

Nao existe servidor, rota HTTP ou credencial remota neste modulo. O segredo do
emissor e guardado somente no cofre DPAPI do Windows pertencente ao dono.
"""

from __future__ import annotations

import base64
import calendar
import json
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt

from licensing.account_provisioning import (
    AccountProvisioningError,
    issue_admin_provisioning_code,
    verify_admin_provisioning_code,
)
from licensing.offline import (
    OfflineLicenseError,
    OfflineLicenseIssuer,
    OfflineLicenseStorageError,
    ProtectedJsonStore,
    generate_issuer_private_key,
    license_code_hash,
    parse_license_request,
    superadmin_state_path,
    verify_license_code,
)
from licensing.offline_email import OfflineEmailError, gmail_settings


SUPERADMIN_USERNAME = "mirson"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ISSUER_KEY_FILE = PROJECT_ROOT / "licensing" / "offline_issuer_key.py"
DEFAULT_LEGACY_DATABASE = PROJECT_ROOT / "data" / "control_plane.db"

# O UUID assinado continua a ser a identidade tecnica da licenca. Esta
# referencia curta existe apenas para o dono localizar a licenca no terminal,
# sem precisar copiar um UUID longo ou expor uma palavra-passe.
LICENSE_REFERENCE_PREFIX = "MIRSON"
_LICENSE_REFERENCE_PATTERN = re.compile(r"^MIRSON-(\d{1,8})$", re.IGNORECASE)


class SuperadminError(RuntimeError):
    """O terminal do superadmin nao pode concluir a operacao solicitada."""


@dataclass(frozen=True)
class AutomaticEmailSettings:
    """Configuracao secreta do emissor local, protegida pelo cofre DPAPI."""

    gmail_email: str
    gmail_app_password: str
    recipient_email: str
    customer_ref: str
    plan_name: str
    # ``months`` permanece para ler cofres/configuracoes antigas. Os novos
    # campos permitem prazos como 30s, 1min, 15 dias ou 2 anos.
    months: int | None
    duration_amount: int
    duration_unit: str
    auto_renewals: bool
    poll_seconds: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def _email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise SuperadminError("O e-mail e invalido.")
    return email


def _short_text(value: str, field: str, *, default: str = "") -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        text = default
    if not text or len(text) > 120:
        raise SuperadminError(f"{field} e invalido.")
    return text


def _normalize_license_reference(value: object) -> str:
    """Normaliza ``MIRSON-0001`` (ou somente ``1``) para a referencia curta.

    A referencia nao substitui ``license_id`` dentro de codigos assinados. Ela
    e um apelido local, unico e legivel para as operacoes do superadmin.
    """
    raw = str(value or "").strip()
    if raw.isdecimal():
        number = int(raw)
    else:
        match = _LICENSE_REFERENCE_PATTERN.fullmatch(raw)
        if not match:
            return ""
        number = int(match.group(1))
    if not 1 <= number <= 99_999_999:
        return ""
    return f"{LICENSE_REFERENCE_PREFIX}-{number:04d}"


def _license_reference_number(reference: str) -> int:
    normalized = _normalize_license_reference(reference)
    if not normalized:
        return 0
    return int(normalized.rsplit("-", 1)[1])


def _ensure_license_references(state: dict[str, Any]) -> bool:
    """Acrescenta referencias curtas aos cofres existentes, sem recriar nada.

    A migracao e local e conserva todos os UUIDs, codigos assinados e datas.
    Para dados corrompidos, uma referencia invalida ou duplicada recebe um
    novo numero, sem alterar a licenca a que ela aponta.
    """
    raw_records = state.get("licenses") or []
    if not isinstance(raw_records, list):
        return False

    records = [record for record in raw_records if isinstance(record, dict)]
    used: set[str] = set()
    missing: list[dict[str, Any]] = []
    highest = 0
    changed = False

    for record in records:
        original = str(record.get("license_reference") or "")
        reference = _normalize_license_reference(original)
        if not reference or reference in used:
            missing.append(record)
            continue
        if original != reference:
            record["license_reference"] = reference
            changed = True
        used.add(reference)
        highest = max(highest, _license_reference_number(reference))

    for record in missing:
        highest += 1
        reference = f"{LICENSE_REFERENCE_PREFIX}-{highest:04d}"
        while reference in used:
            highest += 1
            reference = f"{LICENSE_REFERENCE_PREFIX}-{highest:04d}"
        if str(record.get("license_reference") or "") != reference:
            record["license_reference"] = reference
            changed = True
        used.add(reference)
    return changed


def _next_license_reference(records: list[dict[str, Any]]) -> str:
    """Devolve a proxima referencia curta sem alterar registros existentes."""
    used = {
        reference
        for record in records
        if isinstance(record, dict)
        if (reference := _normalize_license_reference(record.get("license_reference")))
    }
    highest = max((_license_reference_number(reference) for reference in used), default=0)
    while True:
        highest += 1
        reference = f"{LICENSE_REFERENCE_PREFIX}-{highest:04d}"
        if reference not in used:
            return reference


def _months(value: int) -> int:
    try:
        months = int(value)
    except (TypeError, ValueError) as exc:
        raise SuperadminError("A duracao deve ser informada em meses.") from exc
    if not 1 <= months <= 120:
        raise SuperadminError("A duracao deve ficar entre 1 e 120 meses.")
    return months


def _poll_seconds(value: int) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise SuperadminError("O intervalo de verificacao e invalido.") from exc
    if not 20 <= seconds <= 3600:
        raise SuperadminError("O intervalo deve ficar entre 20 e 3600 segundos.")
    return seconds


def _provisioning_days(value: int) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise SuperadminError("A validade do codigo de conta e invalida.") from exc
    if not 1 <= days <= 30:
        raise SuperadminError("O codigo temporario deve valer entre 1 e 30 dias.")
    return days


def _temporary_account_password(value: str) -> str:
    password = str(value or "")
    if len(password) < 12:
        raise SuperadminError("A palavra-passe temporaria deve ter pelo menos 12 caracteres.")
    if not any(character.islower() for character in password):
        raise SuperadminError("A palavra-passe temporaria deve incluir uma letra minuscula.")
    if not any(character.isupper() for character in password):
        raise SuperadminError("A palavra-passe temporaria deve incluir uma letra maiuscula.")
    if not any(character.isdigit() for character in password):
        raise SuperadminError("A palavra-passe temporaria deve incluir um numero.")
    return password


_DURATION_PATTERN = re.compile(r"^\s*(\d+)\s*([^\d\s]+)?\s*$")
_DURATION_ALIASES = {
    "seconds": {"s", "sec", "secs", "seg", "segs", "segundo", "segundos", "second", "seconds"},
    "minutes": {"min", "mins", "minuto", "minutos", "minute", "minutes"},
    "hours": {"h", "hora", "horas", "hour", "hours"},
    "days": {"d", "dia", "dias", "day", "days"},
    "weeks": {"sem", "sems", "semana", "semanas", "week", "weeks"},
    "months": {"mes", "meses", "month", "months"},
    "years": {"ano", "anos", "year", "years"},
}
_DURATION_LABELS = {
    "seconds": ("segundo", "segundos"),
    "minutes": ("minuto", "minutos"),
    "hours": ("hora", "horas"),
    "days": ("dia", "dias"),
    "weeks": ("semana", "semanas"),
    "months": ("mes", "meses"),
    "years": ("ano", "anos"),
}


def _duration_token(value: object) -> str:
    """Normaliza abreviacoes em portugues/ingles sem tornar ``m`` ambiguo."""
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return text.replace(".", "")


def normalize_license_duration(value: int | str, unit: str | None = None) -> tuple[int, str]:
    """Aceita ``vitalicia``, ``30s``, ``1min``, ``15 dias`` ou quantidade + unidade.

    Valores numericos sem unidade mantem o comportamento antigo e significam
    meses. O terminal apresenta a unidade explicitamente para novos usos.
    """
    if _duration_token(unit or value) in {"vitalicia", "vitalicio", "lifetime"}:
        return 1, "lifetime"
    raw_amount = value
    raw_unit = unit
    if unit is None and isinstance(value, str):
        match = _DURATION_PATTERN.fullmatch(value)
        if not match:
            raise SuperadminError(
                "Informe o prazo como 30s, 1min, 1 dia, 7 dias, 1 mes, 1 ano ou vitalicia."
            )
        raw_amount = match.group(1)
        raw_unit = match.group(2) or "months"
    elif unit is None:
        raw_unit = "months"

    try:
        amount = int(raw_amount)
    except (TypeError, ValueError) as exc:
        raise SuperadminError("A quantidade do prazo e invalida.") from exc
    if amount < 1:
        raise SuperadminError("O prazo deve ser maior que zero.")

    token = _duration_token(raw_unit)
    resolved_unit = next(
        (canonical for canonical, aliases in _DURATION_ALIASES.items() if token in aliases),
        None,
    )
    if resolved_unit is None:
        raise SuperadminError(
            "Use segundos, minutos, horas, dias, semanas, meses ou anos como unidade do prazo."
        )
    return amount, resolved_unit


def license_duration_label(amount: int, unit: str) -> str:
    quantity, canonical_unit = normalize_license_duration(amount, unit)
    if canonical_unit == "lifetime":
        return "Vitalicia"
    singular, plural = _DURATION_LABELS[canonical_unit]
    return f"{quantity} {singular if quantity == 1 else plural}"


def _add_months_datetime(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + int(months)
    year, month = value.year + month_index // 12, month_index % 12 + 1
    if not 1 <= year <= 9999:
        raise SuperadminError("O prazo escolhido ultrapassa a data maxima suportada.")
    return value.replace(
        year=year,
        month=month,
        day=min(value.day, calendar.monthrange(year, month)[1]),
    )


def add_license_duration(value: datetime | date, amount: int | str, unit: str | None = None) -> datetime:
    """Soma um prazo exato, preservando hora e fuso para licencas curtas."""
    quantity, canonical_unit = normalize_license_duration(amount, unit)
    if canonical_unit == "lifetime":
        # Valor reservado e assinado, compativel com os cofres existentes.
        return datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    if isinstance(value, datetime):
        start = value
    else:
        start = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start = start.astimezone(timezone.utc).replace(microsecond=0)
    try:
        if canonical_unit == "seconds":
            result = start + timedelta(seconds=quantity)
        elif canonical_unit == "minutes":
            result = start + timedelta(minutes=quantity)
        elif canonical_unit == "hours":
            result = start + timedelta(hours=quantity)
        elif canonical_unit == "days":
            result = start + timedelta(days=quantity)
        elif canonical_unit == "weeks":
            result = start + timedelta(weeks=quantity)
        elif canonical_unit == "months":
            result = _add_months_datetime(start, quantity)
        else:
            result = _add_months_datetime(start, quantity * 12)
    except (OverflowError, ValueError) as exc:
        raise SuperadminError("O prazo escolhido ultrapassa a data maxima suportada.") from exc
    if result <= start:
        raise SuperadminError("O prazo escolhido e invalido.")
    return result


def add_months(value: date, months: int) -> date:
    """Soma meses do calendario, preservando o ultimo dia quando necessario."""
    try:
        quantity = int(months)
    except (TypeError, ValueError) as exc:
        raise SuperadminError("A duracao deve ser informada em meses.") from exc
    if not 1 <= quantity <= 120:
        raise SuperadminError("A duracao deve ficar entre 1 e 120 meses.")
    month_index = value.month - 1 + quantity
    year, month = value.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _record_request_ids(record: dict[str, Any]) -> set[str]:
    """Todos os pedidos que pertencem a uma unica licenca logica."""
    values = {str(record.get("request_id") or "").strip()}
    request_ids = record.get("request_ids") or []
    if isinstance(request_ids, list):
        values.update(str(item or "").strip() for item in request_ids)
    return {value for value in values if value}


def _same_device_record(
    record: dict[str, Any],
    request: dict[str, Any],
    public_key: str,
) -> bool:
    """Confirma a identidade do PC inclusive para cofres antigos.

    Os primeiros cofres guardavam apenas a fingerprint. Quando for preciso
    renovar um desses registos, lemos a chave publica do codigo assinado uma
    vez e gravamos tambem a chave do dispositivo. Isso evita transformar uma
    renovacao numa segunda licenca e nao reduz a ligacao ao computador.
    """
    if str(record.get("fingerprint") or "").strip().lower() != str(request.get("fingerprint") or "").lower():
        return False
    device_key = str(record.get("device_public_key") or "").strip()
    if not device_key:
        code = str(record.get("license_code") or "")
        if not code:
            return False
        try:
            device_key = str(verify_license_code(code, public_key).get("device_public_key") or "")
        except OfflineLicenseError:
            return False
        if not device_key:
            return False
        record["device_public_key"] = device_key
    return device_key == str(request.get("device_public_key") or "")


def _license_has_revocation(record: dict[str, Any]) -> bool:
    """Indica que um SIGE-REV1 foi emitido para a licenca."""
    return bool(str(record.get("revocation_id") or "").strip() or str(record.get("revocation_code") or "").strip())


def _license_has_restoration(record: dict[str, Any]) -> bool:
    """Indica a correcao excepcional de um cancelamento emitida pelo dono."""
    return bool(str(record.get("restoration_id") or "").strip() or str(record.get("restoration_code") or "").strip())


def _license_is_revoked(record: dict[str, Any]) -> bool:
    """Indica cancelamento ainda sem um SIGE-RST1 de recuperacao emitido."""
    return _license_has_revocation(record) and not _license_has_restoration(record)


def _license_has_suspension(record: dict[str, Any]) -> bool:
    """Indica que o dono emitiu pelo menos uma suspensao para a licenca."""
    return bool(str(record.get("suspension_id") or "").strip() or str(record.get("suspension_code") or "").strip())


def _license_is_suspended(record: dict[str, Any]) -> bool:
    """Suspensao ainda sem uma reativacao emitida pelo dono.

    Numa operacao offline nao existe confirmacao automatica de que o cliente
    importou SIGE-RES1. Quando o superadmin ja emitiu a reativacao, ele pode
    voltar a gerir a licenca; o PC continua bloqueado ate importar o codigo.
    """
    return _license_has_suspension(record) and not bool(
        str(record.get("reactivation_id") or "").strip()
        or str(record.get("reactivation_code") or "").strip()
    )


class LocalSuperadmin:
    """Superadmin unico, local e protegido por DPAPI + bcrypt."""

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        protector=None,
        issuer_key_file: str | Path | None = None,
        legacy_database: str | Path | None = None,
    ):
        self._state_store = ProtectedJsonStore(state_path or superadmin_state_path(), protector=protector)
        self._issuer_key_file = Path(issuer_key_file) if issuer_key_file else DEFAULT_ISSUER_KEY_FILE
        self._legacy_database = Path(legacy_database) if legacy_database else DEFAULT_LEGACY_DATABASE

    def _load(self) -> dict[str, Any] | None:
        try:
            return self._state_store.load()
        except OfflineLicenseStorageError as exc:
            raise SuperadminError(str(exc)) from exc

    def _save(self, state: dict[str, Any]) -> None:
        try:
            self._state_store.save(state)
        except OfflineLicenseStorageError as exc:
            raise SuperadminError(str(exc)) from exc

    def initialized(self) -> bool:
        return self._load() is not None

    @staticmethod
    def _password_hash(password: str) -> str:
        value = str(password or "")
        if len(value) < 16:
            raise SuperadminError("A palavra-passe do superadmin deve ter pelo menos 16 caracteres.")
        return base64.b64encode(bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt())).decode("ascii")

    def _legacy_password_hash(self) -> str | None:
        """Migra apenas o hash ja criado localmente, nunca uma senha em texto."""
        if not self._legacy_database.exists():
            return None
        try:
            with sqlite3.connect(self._legacy_database) as connection:
                row = connection.execute(
                    "SELECT password_hash FROM accounts WHERE username = ? AND role = 'superadmin' LIMIT 1",
                    (SUPERADMIN_USERNAME,),
                ).fetchone()
        except sqlite3.Error:
            return None
        if not row or not row[0]:
            return None
        raw = bytes(row[0])
        try:
            # bcrypt valida o formato durante uma comparacao com texto vazio.
            bcrypt.checkpw(b"", raw)
        except ValueError:
            return None
        return base64.b64encode(raw).decode("ascii")

    def bootstrap(self, password: str | None = None) -> bool:
        """Cria o cofre; devolve True quando reutilizou o hash local existente."""
        if self.initialized():
            raise SuperadminError("O superadmin local ja foi configurado.")
        password_hash = self._legacy_password_hash()
        migrated = bool(password_hash)
        if not password_hash:
            if password is None:
                raise SuperadminError("Defina a palavra-passe inicial no terminal protegido.")
            password_hash = self._password_hash(password)
        issuer_private_key = generate_issuer_private_key()
        state = {
            "username": SUPERADMIN_USERNAME,
            "password_hash": password_hash,
            "issuer_private_key": issuer_private_key,
            "license_recipient_email": "",
            "licenses": [],
            # O historico visivel pode ser limitado, mas esta lista nao: cada
            # pedido precisa continuar bloqueado mesmo depois de muitos anos.
            "used_request_ids": [],
            # Registo de contas admin autorizadas para cada instalacao. Os
            # codigos ficam no cofre DPAPI para reenvio; a palavra-passe fica
            # apenas como hash bcrypt dentro do codigo assinado.
            "admin_provisionings": [],
            # Hashes das mensagens ja entregues pelo emissor. Assim, abrir um
            # pedido no Gmail nao bloqueia o processamento, mas a mesma
            # mensagem tampouco volta a disparar e-mails a cada consulta.
            "automatic_email_delivered_message_hashes": [],
            "automatic_email": {},
            "created_at": _iso(),
            "updated_at": _iso(),
        }
        self._save(state)
        self.configure_desktop_public_key()
        return migrated

    def authenticate(self, password: str) -> bool:
        state = self._load()
        if not state or str(state.get("username") or "").lower() != SUPERADMIN_USERNAME:
            return False
        try:
            password_hash = base64.b64decode(str(state.get("password_hash") or ""), validate=True)
            return bcrypt.checkpw(str(password or "").encode("utf-8"), password_hash)
        except (ValueError, TypeError):
            return False

    def _require_state(self) -> dict[str, Any]:
        state = self._load()
        if not state:
            raise SuperadminError("O superadmin local ainda nao foi configurado.")
        if str(state.get("username") or "").lower() != SUPERADMIN_USERNAME:
            raise SuperadminError("O cofre do superadmin e invalido.")
        # Cofres emitidos antes da referencia curta continuam validos. A
        # migracao so adiciona o apelido local; nunca toca no UUID assinado,
        # em codigos emitidos ou nas datas da licenca.
        if _ensure_license_references(state):
            state["updated_at"] = _iso()
            self._save(state)
        return state

    def issuer(self) -> OfflineLicenseIssuer:
        state = self._require_state()
        try:
            return OfflineLicenseIssuer(str(state.get("issuer_private_key") or ""))
        except OfflineLicenseError as exc:
            raise SuperadminError("A chave privada local do superadmin esta invalida.") from exc

    def public_key(self) -> str:
        return self.issuer().public_key

    def configure_desktop_public_key(self) -> Path:
        """Coloca somente a chave publica no codigo que sera empacotado."""
        public_key = self.public_key()
        content = (
            '"""Chave publica do emissor de licencas offline.\n\n'
            "Gerada pelo terminal local do superadmin. A chave privada fica apenas\n"
            "no cofre DPAPI do computador do dono.\n"
            '"""\n\n'
            f'OFFLINE_LICENSE_PUBLIC_KEY = "{public_key}"\n\n'
            "# Endereco publico que recebe pedidos de licenca dos clientes.\n"
            f"OFFLINE_LICENSE_REQUEST_EMAIL = {json.dumps(self.license_recipient_email())}\n"
        )
        try:
            self._issuer_key_file.parent.mkdir(parents=True, exist_ok=True)
            self._issuer_key_file.write_text(content, encoding="utf-8")
            cache_directory = self._issuer_key_file.parent / "__pycache__"
            for cached_file in cache_directory.glob("offline_issuer_key.*.pyc"):
                try:
                    cached_file.unlink(missing_ok=True)
                except OSError:
                    # A configuracao ja foi gravada; o Python ainda compara a
                    # origem na proxima abertura, portanto nao a invalide por
                    # causa de um cache temporariamente bloqueado.
                    pass
        except OSError as exc:
            raise SuperadminError("Nao foi possivel preparar a chave publica para o programa desktop.") from exc
        return self._issuer_key_file

    def license_recipient_email(self) -> str:
        state = self._require_state()
        return str(state.get("license_recipient_email") or "")

    def set_license_recipient_email(self, email: str) -> str:
        state = self._require_state()
        recipient = _email(email)
        previous_recipient = str(state.get("license_recipient_email") or "").strip().lower()
        state["license_recipient_email"] = recipient
        if previous_recipient and previous_recipient != recipient:
            # O emissor le a mesma caixa que recebe as licencas. Ao trocar o
            # endereco, exige uma nova palavra-passe de aplicacao para evitar
            # que o processo continue ligado ao Gmail anterior.
            state["automatic_email"] = {}
        state["updated_at"] = _iso()
        self._save(state)
        self.configure_desktop_public_key()
        return recipient

    def configure_automatic_email(
        self,
        gmail_app_password: str,
        *,
        customer_ref: str = "Cliente por e-mail",
        plan_name: str = "Mensal",
        months: int | None = 1,
        duration_amount: int | str | None = None,
        duration_unit: str | None = None,
        auto_renewals: bool = False,
        poll_seconds: int = 60,
    ) -> dict[str, Any]:
        """Guarda uma unica configuracao para o emissor automatico local.

        A mesma conta Gmail recebe o pedido e recebe a licenca assinada. A
        palavra-passe de aplicacao fica dentro do cofre DPAPI, jamais no
        computador do cliente nem em ficheiros de configuracao distribuidos.
        """
        state = self._require_state()
        recipient = _email(str(state.get("license_recipient_email") or ""))
        existing = state.get("automatic_email") or {}
        requested_password = str(gmail_app_password or "")
        if not requested_password and isinstance(existing, dict):
            requested_password = str(existing.get("gmail_app_password") or "")
        try:
            gmail = gmail_settings(recipient, requested_password)
        except OfflineEmailError as exc:
            raise SuperadminError(str(exc)) from exc
        # ``months`` continua aceito para que o cofre e os atalhos antigos
        # funcionem. A configuracao nova sempre guarda quantidade + unidade.
        if duration_amount is None:
            amount, unit = normalize_license_duration(months if months is not None else 1, "months")
        else:
            amount, unit = normalize_license_duration(duration_amount, duration_unit)
        automatic = {
            "gmail_email": gmail.from_email,
            "gmail_app_password": gmail.password,
            "customer_ref": _short_text(customer_ref, "A referencia padrao do cliente", default="Cliente por e-mail"),
            "plan_name": _short_text(plan_name, "O nome do plano", default="Mensal"),
            # Chave antiga, mantida somente quando a unidade e meses para
            # facilitar a leitura de cofres ja existentes.
            "months": amount if unit == "months" else None,
            "duration_amount": amount,
            "duration_unit": unit,
            # Por seguranca comercial, a renovacao requer decisao do dono
            # salvo se ele habilitar expressamente este comportamento.
            "auto_renewals": bool(auto_renewals),
            "poll_seconds": _poll_seconds(poll_seconds),
        }
        state["automatic_email"] = automatic
        state["updated_at"] = _iso()
        self._save(state)
        return self.automatic_email_status()

    def disable_automatic_email(self) -> None:
        state = self._require_state()
        state["automatic_email"] = {}
        state["updated_at"] = _iso()
        self._save(state)

    def automatic_email_settings(self) -> AutomaticEmailSettings:
        """Le a configuracao secreta do emissor, apenas no computador dono."""
        state = self._require_state()
        automatic = state.get("automatic_email") or {}
        if not isinstance(automatic, dict):
            raise SuperadminError("A configuracao do emissor automatico e invalida.")
        recipient = _email(str(state.get("license_recipient_email") or ""))
        try:
            gmail = gmail_settings(
                str(automatic.get("gmail_email") or recipient),
                str(automatic.get("gmail_app_password") or ""),
            )
        except OfflineEmailError as exc:
            raise SuperadminError("Configure o emissor automatico com a palavra-passe de aplicacao do Gmail.") from exc
        if gmail.from_email != recipient:
            raise SuperadminError("O Gmail automatico deve ser o mesmo e-mail que recebe as licencas.")
        if automatic.get("duration_amount") is None:
            # Migracao transparente de configuracoes antigas, que so tinham
            # ``months``. Nenhum segredo nem licenca precisa ser recriado.
            amount, unit = normalize_license_duration(automatic.get("months", 1), "months")
        else:
            amount, unit = normalize_license_duration(
                automatic.get("duration_amount"),
                automatic.get("duration_unit"),
            )
        return AutomaticEmailSettings(
            gmail_email=gmail.from_email,
            gmail_app_password=gmail.password,
            recipient_email=recipient,
            customer_ref=_short_text(automatic.get("customer_ref"), "A referencia padrao do cliente", default="Cliente por e-mail"),
            plan_name=_short_text(automatic.get("plan_name"), "O nome do plano", default="Mensal"),
            months=amount if unit == "months" else None,
            duration_amount=amount,
            duration_unit=unit,
            # Cofres antigos nao tinham esta chave: por padrao, nunca se
            # renovam licencas alugadas sem aprovacao do superadmin.
            auto_renewals=automatic.get("auto_renewals") is True,
            poll_seconds=_poll_seconds(automatic.get("poll_seconds", 60)),
        )

    def automatic_email_status(self) -> dict[str, Any]:
        """Estado consultavel no terminal sem revelar a senha Gmail."""
        try:
            settings = self.automatic_email_settings()
        except SuperadminError:
            return {"configured": False}
        return {
            "configured": True,
            "gmail_email": settings.gmail_email,
            "recipient_email": settings.recipient_email,
            "customer_ref": settings.customer_ref,
            "plan_name": settings.plan_name,
            "months": settings.months,
            "duration_amount": settings.duration_amount,
            "duration_unit": settings.duration_unit,
            "duration_label": license_duration_label(settings.duration_amount, settings.duration_unit),
            "auto_renewals": settings.auto_renewals,
            "poll_seconds": settings.poll_seconds,
        }

    @staticmethod
    def _automatic_delivery_hashes(state: dict[str, Any]) -> set[str]:
        """Extrai hashes de entrega sem confiar em dados corrompidos."""
        values = state.get("automatic_email_delivered_message_hashes") or []
        if not isinstance(values, list):
            return set()
        return {
            value
            for item in values
            if len(value := str(item or "").lower()) == 64
            and all(character in "0123456789abcdef" for character in value)
        }

    @staticmethod
    def _automatic_delivery_hash(message_hash: str) -> str:
        value = str(message_hash or "").lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise SuperadminError("O identificador da mensagem de licenca e invalido.")
        return value

    def automatic_email_message_was_delivered(self, message_hash: str) -> bool:
        """Indica se esta mensagem Gmail ja teve a licenca entregue."""
        value = self._automatic_delivery_hash(message_hash)
        return value in self._automatic_delivery_hashes(self._require_state())

    def mark_automatic_email_message_delivered(self, message_hash: str) -> None:
        """Regista uma entrega concluida para nao reenviar a mesma mensagem.

        O registo so e feito depois de o Gmail aceitar o envio. Se ele falhar,
        a mesma mensagem continua apta a ser tentada novamente com a mesma
        licenca assinada. Um novo e-mail de reenvio usa outro hash e recebe o
        mesmo codigo, nunca uma segunda licenca.
        """
        value = self._automatic_delivery_hash(message_hash)
        state = self._require_state()
        delivered_hashes = self._automatic_delivery_hashes(state)
        if value in delivered_hashes:
            return
        delivered_hashes.add(value)
        state["automatic_email_delivered_message_hashes"] = sorted(delivered_hashes)
        state["updated_at"] = _iso()
        self._save(state)

    def issue_license(
        self,
        request_code: str,
        *,
        customer_ref: str,
        plan_name: str,
        months: int | None = 1,
        duration_amount: int | str | None = None,
        duration_unit: str | None = None,
        starts_at: date | datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Emite a primeira licenca ou renova a mesma licenca do PC.

        Um pedido novo vindo do mesmo computador nao cria um segundo cliente
        nem outro ``license_id``. O codigo assinado muda porque o periodo muda,
        mas a identidade da licenca e o pedido original permanecem estaveis.
        """
        if duration_amount is None:
            amount, unit = normalize_license_duration(months if months is not None else 1, "months")
        else:
            amount, unit = normalize_license_duration(duration_amount, duration_unit)
        starts = starts_at or _now()
        expires = add_license_duration(starts, amount, unit)
        try:
            request = parse_license_request(request_code)
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        state = self._require_state()
        raw_records = state.get("licenses") or []
        records = [record for record in raw_records if isinstance(record, dict)] if isinstance(raw_records, list) else []
        if any(
            _license_is_revoked(record)
            and str(record.get("fingerprint") or "").strip().lower() == request["fingerprint"]
            for record in records
        ):
            raise SuperadminError(
                "Este computador possui uma licenca com cancelamento emitido. "
                "Nao e permitido emitir ou renovar enquanto ela estiver cancelada."
            )
        if any(
            _license_is_suspended(record)
            and str(record.get("fingerprint") or "").strip().lower() == request["fingerprint"]
            for record in records
        ):
            raise SuperadminError(
                "Este computador possui uma licenca suspensa. Emita e entregue o codigo de reativacao antes de renovar."
            )
        used_request_ids = {
            str(request_id or "")
            for request_id in state.get("used_request_ids") or []
        }
        # Tambem considera registos criados antes da lista dedicada existir.
        for record in records:
            used_request_ids.update(_record_request_ids(record))
        if request["request_id"] in used_request_ids:
            raise SuperadminError("Este pedido de licenca ja foi utilizado e nao pode gerar outra licenca.")

        public_key = self.public_key()
        existing = next(
            (
                record
                for record in reversed(records)
                if _same_device_record(record, request, public_key)
            ),
            None,
        )
        stable_request_id = None
        stable_license_id = None
        if existing is not None:
            if _license_is_revoked(existing):
                raise SuperadminError("Esta licenca foi cancelada e nao pode ser renovada.")
            if _license_is_suspended(existing):
                raise SuperadminError("Esta licenca esta suspensa e nao pode ser renovada antes da reativacao.")
            stable_request_id = str(existing.get("request_id") or "").strip()
            stable_license_id = str(existing.get("license_id") or "").strip()
            if not stable_request_id or not stable_license_id:
                raise SuperadminError("A licenca existente deste computador esta incompleta e nao pode ser renovada.")
        try:
            code, payload = self.issuer().issue(
                request_code,
                customer_ref=customer_ref,
                plan_name=plan_name,
                starts_at=starts,
                expires_at=expires,
                license_id=stable_license_id,
                stable_request_id=stable_request_id,
            )
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        used_request_ids.add(request["request_id"])
        if existing is None:
            record = {
                "license_id": payload["license_id"],
                "license_reference": _next_license_reference(records),
                "request_id": payload["request_id"],
                "request_ids": [request["request_id"]],
                "latest_request_id": request["request_id"],
                "customer_ref": payload["customer_ref"],
                "plan_name": payload["plan_name"],
                "fingerprint": payload["fingerprint"],
                "device_public_key": payload["device_public_key"],
                "issued_at": payload["issued_at"],
                "first_issued_at": payload["issued_at"],
                "last_renewed_at": None,
                "not_before": payload["not_before"],
                "expires_at": payload["expires_at"],
                "duration_amount": amount,
                "duration_unit": unit,
                "renewal_count": 0,
                "code_hash": license_code_hash(code),
                # O cofre inteiro e DPAPI; manter o codigo permite reenviar a
                # mesma licenca sem fabricar uma segunda autorizacao.
                "license_code": code,
            }
            records.append(record)
            renewed = False
            renewal_count = 0
        else:
            request_ids = _record_request_ids(existing)
            request_ids.add(request["request_id"])
            try:
                previous_renewals = max(0, int(existing.get("renewal_count") or 0))
            except (TypeError, ValueError):
                previous_renewals = 0
            existing.update(
                {
                    "license_id": payload["license_id"],
                    # O pedido original tambem fica estavel para os codigos
                    # SIGE-ADM1 ja emitidos para esta instalacao.
                    "request_id": payload["request_id"],
                    "request_ids": sorted(request_ids),
                    "latest_request_id": request["request_id"],
                    "customer_ref": payload["customer_ref"],
                    "plan_name": payload["plan_name"],
                    "fingerprint": payload["fingerprint"],
                    "device_public_key": payload["device_public_key"],
                    "issued_at": payload["issued_at"],
                    "first_issued_at": existing.get("first_issued_at") or existing.get("issued_at") or payload["issued_at"],
                    "last_renewed_at": payload["issued_at"],
                    "not_before": payload["not_before"],
                    "expires_at": payload["expires_at"],
                    "duration_amount": amount,
                    "duration_unit": unit,
                    "renewal_count": previous_renewals + 1,
                    "code_hash": license_code_hash(code),
                    "license_code": code,
                }
            )
            renewed = True
            renewal_count = previous_renewals + 1
        # Nao se limita a tabela a 1000 entradas: ela e a fonte local que
        # preserva a identidade de cada licenca durante toda a vida do produto.
        state["licenses"] = records
        state["used_request_ids"] = sorted(value for value in used_request_ids if value)
        state["updated_at"] = _iso()
        self._save(state)
        payload["duration_amount"] = amount
        payload["duration_unit"] = unit
        payload["duration_label"] = license_duration_label(amount, unit)
        payload["license_reference"] = str(
            (record if existing is None else existing).get("license_reference") or ""
        )
        payload["renewed"] = renewed
        payload["renewal_count"] = renewal_count
        return code, payload

    def issue_or_get_license(
        self,
        request_code: str,
        *,
        customer_ref: str,
        plan_name: str,
        months: int | None = 1,
        duration_amount: int | str | None = None,
        duration_unit: str | None = None,
        allow_renewal: bool = True,
    ) -> tuple[str, dict[str, Any], bool]:
        """Emite/renova ou devolve o codigo do mesmo pedido.

        O emissor automatico pode repetir o envio se o Gmail falhar depois de
        assinar. Reenviar o mesmo codigo e seguro; assinar outro para o mesmo
        pedido nao e. Um pedido novo do mesmo computador e uma renovacao: o
        codigo muda, mas o ``license_id`` e o pedido original nao.
        """
        try:
            request = parse_license_request(request_code)
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        state = self._require_state()
        raw_records = state.get("licenses") or []
        records = [record for record in raw_records if isinstance(record, dict)] if isinstance(raw_records, list) else []
        for record in reversed(records):
            if not isinstance(record, dict) or request["request_id"] not in _record_request_ids(record):
                continue
            if _license_is_revoked(record):
                raise SuperadminError("Esta licenca foi cancelada e nao pode ser reenviada ou renovada.")
            if _license_is_suspended(record):
                raise SuperadminError("Esta licenca esta suspensa. Emita a reativacao antes de reenviar ou renovar.")
            code = str(record.get("license_code") or "")
            if not code:
                raise SuperadminError("A licenca deste pedido foi encontrada, mas o codigo protegido nao esta disponivel.")
            try:
                amount, unit = normalize_license_duration(
                    record.get("duration_amount", record.get("months", 1)),
                    record.get("duration_unit", "months"),
                )
            except SuperadminError:
                amount, unit = 1, "months"
            return (
                code,
                {
                    "license_id": record.get("license_id"),
                    "license_reference": record.get("license_reference"),
                    "request_id": record.get("request_id"),
                    "customer_ref": record.get("customer_ref"),
                    "plan_name": record.get("plan_name"),
                    "issued_at": record.get("issued_at"),
                    "not_before": record.get("not_before"),
                    "expires_at": record.get("expires_at"),
                    "duration_amount": amount,
                    "duration_unit": unit,
                    "duration_label": license_duration_label(amount, unit),
                    "renewed": bool(record.get("renewal_count")),
                    "renewal_count": int(record.get("renewal_count") or 0),
                },
                False,
            )
        if any(
            _license_is_revoked(record)
            and str(record.get("fingerprint") or "").strip().lower() == request["fingerprint"]
            for record in records
        ):
            raise SuperadminError("Este computador possui uma licenca cancelada e nao pode receber nova emissao.")
        if any(
            _license_is_suspended(record)
            and str(record.get("fingerprint") or "").strip().lower() == request["fingerprint"]
            for record in records
        ):
            raise SuperadminError("Este computador possui uma licenca suspensa e aguarda reativacao do superadmin.")
        if request.get("request_details"):
            raise SuperadminError(
                "Pedido com escolha de plano aguarda aprovacao do superadmin. "
                "Consulte os detalhes no e-mail e use a opcao 2 do terminal."
            )
        if not allow_renewal:
            public_key = self.public_key()
            if any(_same_device_record(record, request, public_key) for record in records):
                raise SuperadminError(
                    "A renovacao desta licenca aguarda aprovacao do superadmin. "
                    "No terminal, use a opcao 2 e escolha o novo prazo."
                )
        code, payload = self.issue_license(
            request_code,
            customer_ref=customer_ref,
            plan_name=plan_name,
            months=months,
            duration_amount=duration_amount,
            duration_unit=duration_unit,
        )
        return code, payload, True

    def list_licenses(self) -> list[dict[str, Any]]:
        state = self._require_state()
        owners = {}
        for admin in state.get("admin_provisionings") or []:
            if isinstance(admin, dict) and admin.get("status") != "replaced":
                owners[str(admin.get("license_id") or "")] = admin
        records = []
        for record in reversed(list(state.get("licenses") or [])):
            if not isinstance(record, dict):
                continue
            safe_record = dict(record)
            owner = owners.get(str(record.get("license_id") or ""), {})
            safe_record["owner_username"] = owner.get("username") or record.get("owner_username") or ""
            safe_record["owner_email"] = owner.get("email") or record.get("owner_email") or ""
            safe_record.pop("license_code", None)
            safe_record.pop("code_hash", None)
            safe_record.pop("revocation_code", None)
            safe_record.pop("revocation_code_hash", None)
            safe_record.pop("suspension_code", None)
            safe_record.pop("suspension_code_hash", None)
            safe_record.pop("reactivation_code", None)
            safe_record.pop("reactivation_code_hash", None)
            safe_record.pop("restoration_code", None)
            safe_record.pop("restoration_code_hash", None)
            if _license_has_revocation(record):
                if _license_has_restoration(record):
                    restoration_status = (
                        "recuperacao enviada; aguarda importacao no computador"
                        if str(record.get("restoration_status") or "") == "sent"
                        else "recuperacao emitida; aguarda importacao no computador"
                    )
                    safe_record["revocation_status"] = "cancelamento revertido pelo superadmin; " + restoration_status
                    safe_record["restoration_status"] = restoration_status
                    safe_record["license_status"] = restoration_status
                else:
                    safe_record["revocation_status"] = (
                        "enviada; aguarda importacao no computador"
                        if str(record.get("revocation_status") or "") == "sent"
                        else "emitida; aguarda importacao no computador"
                    )
                    safe_record["license_status"] = "cancelada definitivamente; " + safe_record["revocation_status"]
            elif _license_has_suspension(record):
                safe_record["revocation_status"] = "nao cancelada"
                if str(record.get("reactivation_code") or ""):
                    reactivation_status = (
                        "reativacao enviada; aguarda importacao no computador"
                        if str(record.get("reactivation_status") or "") == "sent"
                        else "reativacao emitida; aguarda importacao no computador"
                    )
                    safe_record["suspension_status"] = reactivation_status
                    safe_record["license_status"] = reactivation_status
                else:
                    suspension_status = (
                        "suspensao enviada; aguarda importacao no computador"
                        if str(record.get("suspension_status") or "") == "sent"
                        else "suspensao emitida; aguarda importacao no computador"
                    )
                    safe_record["suspension_status"] = suspension_status
                    safe_record["license_status"] = suspension_status
            else:
                safe_record["revocation_status"] = "nao cancelada"
                safe_record["suspension_status"] = "nao suspensa"
                safe_record["license_status"] = "ativa"
            try:
                expires = datetime.fromisoformat(str(record.get("expires_at") or "").replace("Z", "+00:00"))
                safe_record["validity_status"] = "expirada" if expires.astimezone(timezone.utc) < _now() else "dentro do prazo"
            except (TypeError, ValueError):
                safe_record["validity_status"] = "validade desconhecida"
            if safe_record["validity_status"] != "dentro do prazo":
                control_status = safe_record["license_status"]
                safe_record["license_status"] = safe_record["validity_status"]
                if control_status != "ativa":
                    safe_record["license_status"] += "; " + control_status
            try:
                amount, unit = normalize_license_duration(
                    safe_record.get("duration_amount", safe_record.get("months", 1)),
                    safe_record.get("duration_unit", "months"),
                )
                safe_record["duration_amount"] = amount
                safe_record["duration_unit"] = unit
                safe_record["duration_label"] = license_duration_label(amount, unit)
            except SuperadminError:
                safe_record["duration_label"] = "prazo desconhecido"
            records.append(safe_record)
        return records

    def license_details(self, license_id: str) -> dict[str, Any]:
        """Registo completo para consulta no terminal autenticado do superadmin."""
        selected = self.resolve_license_identifier(license_id)
        state = self._require_state()
        record = next(dict(item) for item in state.get("licenses") or []
                      if isinstance(item, dict) and item.get("license_id") == selected)
        summary = next(item for item in self.list_licenses() if item["license_id"] == selected)
        record.update(summary)
        record["admin_provisionings"] = [dict(item) for item in state.get("admin_provisionings") or []
                                         if isinstance(item, dict) and item.get("license_id") == selected]
        return record

    def resolve_license_identifier(self, value: str) -> str:
        """Resolve uma referencia curta do terminal para o UUID interno.

        Aceita ``MIRSON-0001``, somente ``1`` ou o UUID legado exato. O UUID
        continua sendo usado internamente e dentro dos codigos assinados.
        """
        raw = str(value or "").strip()
        if not raw:
            raise SuperadminError("Informe a referencia da licenca, por exemplo MIRSON-0001.")
        reference = _normalize_license_reference(raw)
        state = self._require_state()
        matches = []
        for record in state.get("licenses") or []:
            if not isinstance(record, dict):
                continue
            internal_id = str(record.get("license_id") or "").strip()
            local_reference = _normalize_license_reference(record.get("license_reference"))
            if raw.casefold() == internal_id.casefold() or (reference and reference == local_reference):
                matches.append(internal_id)
        if len(matches) == 1 and matches[0]:
            return matches[0]
        if len(matches) > 1:
            raise SuperadminError("A referencia da licenca e ambigua no cofre local.")
        raise SuperadminError("A referencia da licenca nao foi encontrada. Use a opcao 3 para consultar a lista.")

    def license_code(self, license_id: str) -> str:
        state = self._require_state()
        for record in state.get("licenses") or []:
            if str(record.get("license_id") or "") == str(license_id or ""):
                if _license_is_revoked(record):
                    raise SuperadminError("Esta licenca foi cancelada. Reenvie o codigo de cancelamento, nao a licenca.")
                if _license_is_suspended(record):
                    raise SuperadminError("Esta licenca esta suspensa. Reenvie o codigo de suspensao ou emita a reativacao.")
                code = str(record.get("license_code") or "")
                if code:
                    return code
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def revoke_license(
        self,
        license_id: str,
        *,
        reason: str = "",
        effective_at: date | datetime | None = None,
    ) -> tuple[str, dict[str, Any], bool]:
        """Emite uma unica revogacao assinada para a licenca escolhida.

        O cofre registra ``emitida`` ou ``enviada``; sem servidor ele nunca
        afirma que o computador do cliente ja importou o cancelamento.
        """
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        records = list(state.get("licenses") or [])
        record = next(
            (item for item in records if isinstance(item, dict) and str(item.get("license_id") or "") == selected_id),
            None,
        )
        if record is None:
            raise SuperadminError("Escolha uma licenca emitida por este superadmin.")
        existing_code = str(record.get("revocation_code") or "")
        if _license_is_revoked(record):
            if not existing_code:
                raise SuperadminError("O cancelamento desta licenca foi marcado, mas o codigo protegido nao esta disponivel.")
            return (
                existing_code,
                {
                    "revocation_id": record.get("revocation_id"),
                    "license_id": record.get("license_id"),
                    "customer_ref": record.get("customer_ref"),
                    "reason": record.get("revocation_reason") or "Cancelada pelo superadmin.",
                    "issued_at": record.get("revocation_issued_at"),
                    "effective_at": record.get("revocation_effective_at"),
                    "status": record.get("revocation_status") or "issued",
                },
                False,
            )
        license_code = str(record.get("license_code") or "")
        if not license_code:
            raise SuperadminError("O codigo protegido desta licenca nao esta disponivel para criar o cancelamento.")
        try:
            code, payload = self.issuer().issue_revocation(
                license_code,
                reason=reason,
                effective_at=effective_at,
            )
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        # Um novo cancelamento deve prevalecer sobre uma recuperacao anterior.
        # O novo revocation_id tambem impede que o SIGE-RST1 antigo o reverta.
        for key in (
            "restoration_id",
            "restoration_status",
            "restoration_reason",
            "restoration_issued_at",
            "restoration_effective_at",
            "restoration_code",
            "restoration_code_hash",
            "restoration_sent_at",
        ):
            record.pop(key, None)
        record.update(
            {
                "revocation_id": payload["revocation_id"],
                "revocation_status": "issued",
                "revocation_reason": payload["reason"],
                "revocation_issued_at": payload["issued_at"],
                "revocation_effective_at": payload["effective_at"],
                "revocation_code": code,
                "revocation_code_hash": license_code_hash(code),
            }
        )
        state["licenses"] = records
        state["updated_at"] = _iso()
        self._save(state)
        payload["customer_ref"] = record.get("customer_ref")
        payload["status"] = "issued"
        return code, payload, True

    def mark_license_revocation_sent(self, license_id: str) -> None:
        """Regista somente que o Gmail aceitou o envio do mesmo codigo."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != selected_id:
                continue
            if not _license_is_revoked(record):
                raise SuperadminError("Esta licenca ainda nao possui um cancelamento emitido.")
            record["revocation_status"] = "sent"
            record["revocation_sent_at"] = _iso()
            state["updated_at"] = _iso()
            self._save(state)
            return
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def license_revocation_code(self, license_id: str) -> str:
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != str(license_id or ""):
                continue
            if not _license_is_revoked(record):
                raise SuperadminError("Este cancelamento ja possui uma recuperacao emitida; reenvie o codigo de recuperacao.")
            code = str(record.get("revocation_code") or "")
            if code:
                return code
            raise SuperadminError("Esta licenca ainda nao possui um codigo de cancelamento.")
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def restore_revoked_license(
        self,
        license_id: str,
        *,
        reason: str = "",
        effective_at: date | datetime | None = None,
    ) -> tuple[str, dict[str, Any], bool]:
        """Emite uma recuperacao excepcional para um cancelamento SIGE-REV1.

        A operacao nao apaga a auditoria do cancelamento. Ela cria um
        SIGE-RST1 vinculado ao revocation_id, que o computador precisa importar
        antes de o acesso poder voltar a funcionar.
        """
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        records = list(state.get("licenses") or [])
        record = next(
            (item for item in records if isinstance(item, dict) and str(item.get("license_id") or "") == selected_id),
            None,
        )
        if record is None:
            raise SuperadminError("Escolha uma licenca emitida por este superadmin.")
        if not _license_has_revocation(record):
            raise SuperadminError("Esta licenca nao possui um cancelamento que possa ser recuperado.")
        existing_code = str(record.get("restoration_code") or "")
        if existing_code:
            return (
                existing_code,
                {
                    "restoration_id": record.get("restoration_id"),
                    "revocation_id": record.get("revocation_id"),
                    "license_id": record.get("license_id"),
                    "customer_ref": record.get("customer_ref"),
                    "reason": record.get("restoration_reason") or "Cancelamento revertido pelo superadmin.",
                    "issued_at": record.get("restoration_issued_at"),
                    "effective_at": record.get("restoration_effective_at"),
                    "status": record.get("restoration_status") or "issued",
                },
                False,
            )
        license_code = str(record.get("license_code") or "")
        revocation_code = str(record.get("revocation_code") or "")
        if not license_code or not revocation_code:
            raise SuperadminError("Os codigos protegidos desta licenca nao estao disponiveis para criar a recuperacao.")
        try:
            code, payload = self.issuer().issue_restoration(
                license_code,
                revocation_code,
                reason=reason,
                effective_at=effective_at,
            )
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        record.update(
            {
                "restoration_id": payload["restoration_id"],
                "restoration_status": "issued",
                "restoration_reason": payload["reason"],
                "restoration_issued_at": payload["issued_at"],
                "restoration_effective_at": payload["effective_at"],
                "restoration_code": code,
                "restoration_code_hash": license_code_hash(code),
            }
        )
        state["licenses"] = records
        state["updated_at"] = _iso()
        self._save(state)
        payload["customer_ref"] = record.get("customer_ref")
        payload["status"] = "issued"
        return code, payload, True

    def mark_license_restoration_sent(self, license_id: str) -> None:
        """Regista que o Gmail aceitou o envio da recuperacao excepcional."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != selected_id:
                continue
            if not str(record.get("restoration_code") or ""):
                raise SuperadminError("Esta licenca ainda nao possui um codigo de recuperacao.")
            record["restoration_status"] = "sent"
            record["restoration_sent_at"] = _iso()
            state["updated_at"] = _iso()
            self._save(state)
            return
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def license_restoration_code(self, license_id: str) -> str:
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != str(license_id or ""):
                continue
            code = str(record.get("restoration_code") or "")
            if code:
                return code
            raise SuperadminError("Esta licenca ainda nao possui um codigo de recuperacao.")
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def suspend_license(
        self,
        license_id: str,
        *,
        reason: str = "",
        effective_at: date | datetime | None = None,
    ) -> tuple[str, dict[str, Any], bool]:
        """Emite uma suspensao reversivel para a licenca escolhida."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        records = list(state.get("licenses") or [])
        record = next(
            (item for item in records if isinstance(item, dict) and str(item.get("license_id") or "") == selected_id),
            None,
        )
        if record is None:
            raise SuperadminError("Escolha uma licenca emitida por este superadmin.")
        if _license_is_revoked(record):
            raise SuperadminError("Esta licenca foi cancelada definitivamente e nao pode ser suspensa ou reativada.")
        existing_code = str(record.get("suspension_code") or "")
        if _license_is_suspended(record):
            if not existing_code:
                raise SuperadminError("A suspensao desta licenca foi marcada, mas o codigo protegido nao esta disponivel.")
            return (
                existing_code,
                {
                    "suspension_id": record.get("suspension_id"),
                    "license_id": record.get("license_id"),
                    "customer_ref": record.get("customer_ref"),
                    "reason": record.get("suspension_reason") or "Suspensa pelo superadmin.",
                    "issued_at": record.get("suspension_issued_at"),
                    "effective_at": record.get("suspension_effective_at"),
                    "status": record.get("suspension_status") or "issued",
                },
                False,
            )
        license_code = str(record.get("license_code") or "")
        if not license_code:
            raise SuperadminError("O codigo protegido desta licenca nao esta disponivel para criar a suspensao.")
        try:
            code, payload = self.issuer().issue_suspension(
                license_code,
                reason=reason,
                effective_at=effective_at,
            )
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        # Uma nova suspensao substitui a anterior ja reativada. O antigo
        # SIGE-RES1 deixa de corresponder ao novo suspension_id no cliente.
        for key in (
            "reactivation_id",
            "reactivation_status",
            "reactivation_reason",
            "reactivation_issued_at",
            "reactivation_effective_at",
            "reactivation_code",
            "reactivation_code_hash",
            "reactivation_sent_at",
        ):
            record.pop(key, None)
        record.update(
            {
                "suspension_id": payload["suspension_id"],
                "suspension_status": "issued",
                "suspension_reason": payload["reason"],
                "suspension_issued_at": payload["issued_at"],
                "suspension_effective_at": payload["effective_at"],
                "suspension_code": code,
                "suspension_code_hash": license_code_hash(code),
            }
        )
        state["licenses"] = records
        state["updated_at"] = _iso()
        self._save(state)
        payload["customer_ref"] = record.get("customer_ref")
        payload["status"] = "issued"
        return code, payload, True

    def mark_license_suspension_sent(self, license_id: str) -> None:
        """Regista que o Gmail aceitou o envio da suspensao atual."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != selected_id:
                continue
            if not _license_is_suspended(record):
                raise SuperadminError("Esta licenca nao possui uma suspensao pendente de reativacao.")
            record["suspension_status"] = "sent"
            record["suspension_sent_at"] = _iso()
            state["updated_at"] = _iso()
            self._save(state)
            return
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def license_suspension_code(self, license_id: str) -> str:
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != str(license_id or ""):
                continue
            if not _license_is_suspended(record):
                raise SuperadminError("Esta licenca nao possui uma suspensao pendente.")
            code = str(record.get("suspension_code") or "")
            if code:
                return code
            raise SuperadminError("O codigo de suspensao desta licenca nao esta disponivel.")
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def reactivate_license(
        self,
        license_id: str,
        *,
        reason: str = "",
        effective_at: date | datetime | None = None,
    ) -> tuple[str, dict[str, Any], bool]:
        """Emite um SIGE-RES1 que remove somente a suspensao atual."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        records = list(state.get("licenses") or [])
        record = next(
            (item for item in records if isinstance(item, dict) and str(item.get("license_id") or "") == selected_id),
            None,
        )
        if record is None:
            raise SuperadminError("Escolha uma licenca emitida por este superadmin.")
        if _license_is_revoked(record):
            raise SuperadminError("Esta licenca foi cancelada definitivamente e nao pode ser reativada.")
        suspension_code = str(record.get("suspension_code") or "")
        if not _license_has_suspension(record) or not suspension_code:
            raise SuperadminError("Esta licenca nao possui uma suspensao que possa ser reativada.")
        existing_code = str(record.get("reactivation_code") or "")
        if existing_code:
            return (
                existing_code,
                {
                    "reactivation_id": record.get("reactivation_id"),
                    "suspension_id": record.get("suspension_id"),
                    "license_id": record.get("license_id"),
                    "customer_ref": record.get("customer_ref"),
                    "reason": record.get("reactivation_reason") or "Reativada pelo superadmin.",
                    "issued_at": record.get("reactivation_issued_at"),
                    "effective_at": record.get("reactivation_effective_at"),
                    "status": record.get("reactivation_status") or "issued",
                },
                False,
            )
        license_code = str(record.get("license_code") or "")
        if not license_code:
            raise SuperadminError("O codigo protegido desta licenca nao esta disponivel para criar a reativacao.")
        try:
            code, payload = self.issuer().issue_reactivation(
                license_code,
                suspension_code,
                reason=reason,
                effective_at=effective_at,
            )
        except OfflineLicenseError as exc:
            raise SuperadminError(str(exc)) from exc
        record.update(
            {
                "reactivation_id": payload["reactivation_id"],
                "reactivation_status": "issued",
                "reactivation_reason": payload["reason"],
                "reactivation_issued_at": payload["issued_at"],
                "reactivation_effective_at": payload["effective_at"],
                "reactivation_code": code,
                "reactivation_code_hash": license_code_hash(code),
            }
        )
        state["licenses"] = records
        state["updated_at"] = _iso()
        self._save(state)
        payload["customer_ref"] = record.get("customer_ref")
        payload["status"] = "issued"
        return code, payload, True

    def mark_license_reactivation_sent(self, license_id: str) -> None:
        """Regista que o Gmail aceitou o envio do SIGE-RES1 atual."""
        selected_id = str(license_id or "").strip()
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != selected_id:
                continue
            if not str(record.get("reactivation_code") or ""):
                raise SuperadminError("Esta licenca ainda nao possui um codigo de reativacao.")
            record["reactivation_status"] = "sent"
            record["reactivation_sent_at"] = _iso()
            state["updated_at"] = _iso()
            self._save(state)
            return
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def license_reactivation_code(self, license_id: str) -> str:
        state = self._require_state()
        for record in state.get("licenses") or []:
            if not isinstance(record, dict) or str(record.get("license_id") or "") != str(license_id or ""):
                continue
            code = str(record.get("reactivation_code") or "")
            if code:
                return code
            raise SuperadminError("Esta licenca ainda nao possui um codigo de reativacao.")
        raise SuperadminError("A licenca solicitada nao foi encontrada no cofre local.")

    def issue_or_get_admin_provisioning(
        self,
        license_id: str,
        *,
        username: str,
        temporary_password: str,
        email: str | None = None,
        valid_days: int = 7,
    ) -> tuple[str, dict[str, Any], bool]:
        """Cria o unico codigo temporario da conta admin de uma licenca.

        A conta ainda nao e criada no computador do cliente nesta etapa: o
        codigo assinado e que permite a criacao local, depois de a licenca ser
        ativada. Um segundo pedido para a mesma licenca devolve exatamente o
        mesmo codigo, sem guardar a palavra-passe em texto.
        """
        selected_license_id = str(license_id or "").strip()
        state = self._require_state()
        license_record = next(
            (
                record
                for record in state.get("licenses") or []
                if isinstance(record, dict) and str(record.get("license_id") or "") == selected_license_id
            ),
            None,
        )
        if license_record is None:
            raise SuperadminError("Escolha uma licenca emitida por este superadmin.")
        if _license_is_revoked(license_record):
            raise SuperadminError("Esta licenca foi cancelada; nao e permitido criar ou reenviar a conta admin.")
        if _license_is_suspended(license_record):
            raise SuperadminError("Esta licenca esta suspensa; reative-a antes de criar ou reenviar a conta admin.")
        existing_records = list(state.get("admin_provisionings") or [])
        for record in existing_records:
            if str(record.get("status") or "active") == "replaced":
                continue
            if str(record.get("license_id") or "") != selected_license_id:
                continue
            code = str(record.get("provisioning_code") or "")
            if not code:
                raise SuperadminError("A conta desta licenca foi encontrada, mas o codigo protegido nao esta disponivel.")
            safe_payload = {
                key: record.get(key)
                for key in (
                    "provisioning_id",
                    "license_id",
                    "request_id",
                    "username",
                    "email",
                    "customer_ref",
                    "issued_at",
                    "expires_at",
                )
            }
            return code, safe_payload, False

        license_code = str(license_record.get("license_code") or "")
        if not license_code:
            raise SuperadminError("O codigo protegido desta licenca nao esta disponivel.")
        try:
            license_expires_at = datetime.fromisoformat(
                str(license_record.get("expires_at") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise SuperadminError("A validade da licenca escolhida e invalida.") from exc
        if license_expires_at < _now():
            raise SuperadminError("Esta licenca expirou. Renove-a antes de preparar a conta admin.")

        password = _temporary_account_password(temporary_password)
        days = _provisioning_days(valid_days)
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        try:
            code, payload = issue_admin_provisioning_code(
                str(state.get("issuer_private_key") or ""),
                license_code,
                username=username,
                password_hash=password_hash,
                email=email,
                expires_at=_now().date() + timedelta(days=days),
            )
        except AccountProvisioningError as exc:
            raise SuperadminError(str(exc)) from exc

        existing_records.append(
            {
                "provisioning_id": payload["provisioning_id"],
                "license_id": payload["license_id"],
                "request_id": payload["request_id"],
                "username": payload["username"],
                "email": payload["email"],
                "customer_ref": license_record.get("customer_ref"),
                "issued_at": payload["issued_at"],
                "expires_at": payload["expires_at"],
                "status": "active",
                "provisioning_code": code,
                "code_hash": license_code_hash(code),
            }
        )
        # O codigo assinado nao precisa do nome comercial do cliente, mas o
        # terminal/e-mail precisa dele para apresentar o registo com clareza.
        payload["customer_ref"] = license_record.get("customer_ref")
        state["admin_provisionings"] = existing_records[-1000:]
        state["updated_at"] = _iso()
        self._save(state)
        return code, payload, True

    def renew_expired_admin_provisioning(
        self,
        provisioning_id: str,
        *,
        temporary_password: str,
        valid_days: int = 7,
    ) -> tuple[str, dict[str, Any]]:
        """Substitui um codigo SIGE-ADM1 somente depois de ele expirar.

        O codigo anterior continua no historico com estado ``replaced``. Isso
        preserva auditoria e garante que nunca ha dois codigos validos para a
        mesma conta ao mesmo tempo.
        """
        selected_id = str(provisioning_id or "").strip()
        state = self._require_state()
        records = list(state.get("admin_provisionings") or [])
        record = next(
            (item for item in records if str(item.get("provisioning_id") or "") == selected_id),
            None,
        )
        if record is None:
            raise SuperadminError("A conta admin escolhida nao foi encontrada.")
        if str(record.get("status") or "active") == "replaced":
            raise SuperadminError("Este codigo ja foi substituido; escolha o registo mais recente.")
        old_code = str(record.get("provisioning_code") or "")
        try:
            signed_payload = verify_admin_provisioning_code(old_code, self.public_key())
            expires_at = datetime.fromisoformat(
                str(signed_payload.get("expires_at") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (AccountProvisioningError, TypeError, ValueError) as exc:
            raise SuperadminError("O codigo existente esta invalido e nao pode ser substituido.") from exc
        if expires_at >= _now():
            raise SuperadminError("O codigo atual ainda esta valido. Reenvie-o em vez de criar outro.")

        license_record = next(
            (
                item
                for item in state.get("licenses") or []
                if str(item.get("license_id") or "") == str(record.get("license_id") or "")
            ),
            None,
        )
        if license_record is None:
            raise SuperadminError("A licenca associada a esta conta nao foi encontrada.")
        if _license_is_revoked(license_record):
            raise SuperadminError("A licenca associada a esta conta foi cancelada.")
        if _license_is_suspended(license_record):
            raise SuperadminError("A licenca associada a esta conta esta suspensa.")
        license_code = str(license_record.get("license_code") or "")
        if not license_code:
            raise SuperadminError("O codigo protegido da licenca nao esta disponivel.")
        try:
            license_expires_at = datetime.fromisoformat(
                str(license_record.get("expires_at") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise SuperadminError("A validade da licenca associada e invalida.") from exc
        if license_expires_at < _now():
            raise SuperadminError("A licenca desta conta expirou. Renove a licenca antes de criar outro codigo.")

        password = _temporary_account_password(temporary_password)
        days = _provisioning_days(valid_days)
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        try:
            code, payload = issue_admin_provisioning_code(
                str(state.get("issuer_private_key") or ""),
                license_code,
                username=str(record.get("username") or ""),
                password_hash=password_hash,
                email=record.get("email"),
                expires_at=_now().date() + timedelta(days=days),
            )
        except AccountProvisioningError as exc:
            raise SuperadminError(str(exc)) from exc

        record["status"] = "replaced"
        record["replaced_at"] = _iso()
        record["replaced_by"] = payload["provisioning_id"]
        payload["customer_ref"] = license_record.get("customer_ref")
        records.append(
            {
                "provisioning_id": payload["provisioning_id"],
                "license_id": payload["license_id"],
                "request_id": payload["request_id"],
                "username": payload["username"],
                "email": payload["email"],
                "customer_ref": license_record.get("customer_ref"),
                "issued_at": payload["issued_at"],
                "expires_at": payload["expires_at"],
                "status": "active",
                "provisioning_code": code,
                "code_hash": license_code_hash(code),
            }
        )
        state["admin_provisionings"] = records[-1000:]
        state["updated_at"] = _iso()
        self._save(state)
        return code, payload

    def list_admin_provisionings(self) -> list[dict[str, Any]]:
        """Tabela segura de contas admin emitidas pelo proprietario.

        ``code_status`` descreve apenas a validade do codigo armazenado. Sem
        servidor, o terminal nao finge saber se o comprador ja o importou.
        """
        state = self._require_state()
        records: list[dict[str, Any]] = []
        for record in reversed(list(state.get("admin_provisionings") or [])):
            safe_record = dict(record)
            safe_record.pop("provisioning_code", None)
            safe_record.pop("code_hash", None)
            if str(safe_record.get("status") or "active") == "replaced":
                safe_record["code_status"] = "substituido"
                records.append(safe_record)
                continue
            try:
                expires_at = datetime.fromisoformat(
                    str(safe_record.get("expires_at") or "").replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                safe_record["code_status"] = "expirado" if expires_at < _now() else "valido"
            except (TypeError, ValueError):
                safe_record["code_status"] = "desconhecido"
            records.append(safe_record)
        return records

    def admin_provisioning_code(self, provisioning_id: str) -> str:
        state = self._require_state()
        for record in state.get("admin_provisionings") or []:
            if str(record.get("provisioning_id") or "") == str(provisioning_id or ""):
                license_record = next(
                    (
                        item
                        for item in state.get("licenses") or []
                        if isinstance(item, dict)
                        and str(item.get("license_id") or "") == str(record.get("license_id") or "")
                    ),
                    None,
                )
                if license_record is not None and _license_is_revoked(license_record):
                    raise SuperadminError("A licenca desta conta admin foi cancelada; o codigo nao pode ser reenviado.")
                if license_record is not None and _license_is_suspended(license_record):
                    raise SuperadminError("A licenca desta conta admin esta suspensa; reative-a antes de reenviar o codigo.")
                code = str(record.get("provisioning_code") or "")
                if code:
                    return code
        raise SuperadminError("A conta admin solicitada nao foi encontrada no cofre local.")
