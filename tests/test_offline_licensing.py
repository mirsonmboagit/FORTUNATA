from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import bcrypt

from licensing.account_provisioning import (
    AccountProvisioningError,
    issue_admin_provisioning_code,
    validate_admin_provisioning_for_license,
)
from licensing.offline import (
    OfflineLicenseClient,
    OfflineLicenseIssuer,
    OfflineLicenseStore,
    generate_issuer_private_key,
    normalize_license_code,
    verify_license_code,
    verify_reactivation_code,
    verify_restoration_code,
    verify_revocation_code,
    verify_suspension_code,
)
from licensing.superadmin import (
    LocalSuperadmin,
    SuperadminError,
    add_license_duration,
    normalize_license_duration,
)
from licensing.secure_store import WindowsDPAPIProtector


class MemoryProtector:
    """Substituto determinista do DPAPI para os testes unitarios."""

    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"protected:")
        return value[len(b"protected:") :]


@pytest.mark.skipif(os.name != "nt", reason="DPAPI so esta disponivel no Windows.")
def test_windows_dpapi_protects_and_opens_the_same_value():
    protector = WindowsDPAPIProtector()
    encrypted = protector.protect(b"offline-license-check")

    assert encrypted != b"offline-license-check"
    assert protector.unprotect(encrypted) == b"offline-license-check"


def _client(
    tmp_path: Path,
    public_key: str,
    *,
    fingerprint: str = "a" * 64,
    now=None,
    request_email: str = "licencas@dono.example",
):
    return OfflineLicenseClient(
        public_key,
        credential_store=OfflineLicenseStore(tmp_path / "license.dat", protector=MemoryProtector()),
        fingerprint_provider=lambda: fingerprint,
        now_provider=now or (lambda: datetime(2026, 9, 9, tzinfo=timezone.utc)),
        request_recipient_email=request_email,
    )


def _issuer():
    return OfflineLicenseIssuer(generate_issuer_private_key())


def test_renewal_request_details_email_approval_and_expired_code_reuse(tmp_path):
    from licensing.offline import parse_license_request
    from licensing.offline_email import license_request_body

    service = LocalSuperadmin(tmp_path / "issuer.dat", protector=MemoryProtector(),
                             issuer_key_file=tmp_path / "key.py", legacy_database=tmp_path / "missing.db")
    service.bootstrap("uma-palavra-passe-muito-forte")
    now = datetime.now(timezone.utc)
    client = _client(tmp_path, service.public_key(), now=lambda: now)
    code, payload = service.issue_license(client.activation_request(), customer_ref="Loja Gaza",
                                          plan_name="Teste", duration_amount=30, duration_unit="seconds")
    assert client.activate(code).allowed
    now += timedelta(seconds=31)
    assert client.activate(code).state == "expired"
    old_request = parse_license_request(client.activation_request())
    details = dict(username="joe", contact_email="joe@example.com", customer="Loja Gaza",
                   request_type="Renovacao", plan_choice="Alterar plano", requested_plan="Diario",
                   requested_duration="10 horas", current_plan="Teste", current_expires_at=payload["expires_at"],
                   license_id=payload["license_id"])
    request = client.set_license_request_details(details)
    assert parse_license_request(request)["request_id"] == old_request["request_id"]
    body = license_request_body(request)
    for value in ("joe@example.com", "Loja Gaza", "10 horas", "Diario", payload["license_id"], "aprovacao"):
        assert value in body
    client.mark_license_request_submitted()
    client.retry_license_request()
    assert client.set_license_request_details(dict(details, requested_plan="Outro")) == request
    with pytest.raises(SuperadminError, match="aguarda aprovacao"):
        service.issue_or_get_license(request, customer_ref="Loja Gaza", plan_name="Padrao", allow_renewal=True)
    renewed, _ = service.issue_license(request, customer_ref="Loja Gaza", plan_name="Diario",
                                        duration_amount=10, duration_unit="hours", starts_at=now)
    assert client.activate(renewed).allowed


def test_superadmin_shows_owner_full_details_and_expiration(tmp_path, monkeypatch, capsys):
    from scripts.superadmin_terminal import _list_licenses

    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    monkeypatch.setattr("licensing.superadmin._now", lambda: now)
    monkeypatch.setattr("licensing.account_provisioning._now", lambda: now)
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat", protector=MemoryProtector(),
        issuer_key_file=tmp_path / "key.py", legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    client = _client(tmp_path, service.public_key(), now=lambda: now)
    code, payload = service.issue_license(
        client.activation_request(), customer_ref="Loja", plan_name="Teste",
        duration_amount=30, duration_unit="seconds",
    )
    assert client.activate(code).allowed
    admin_code, _, _ = service.issue_or_get_admin_provisioning(
        payload["license_id"], username="joao", temporary_password="Senha-temporaria-123!",
        email="joao@example.com",
    )
    _list_licenses(service)
    assert "Dono (admin): joao" in capsys.readouterr().out
    details = service.license_details(payload["license_id"])
    assert details["owner_email"] == "joao@example.com"
    assert details["license_code"] == code
    assert details["admin_provisionings"][0]["provisioning_code"] == admin_code
    assert details["license_status"] == "ativa"
    now += timedelta(seconds=31)
    assert service.list_licenses()[0]["license_status"] == "expirada"
    assert not client.validate().allowed
    state = service._require_state()
    state["licenses"][0].update(revocation_code="historico", restoration_code="recuperacao")
    service._save(state)
    assert service.list_licenses()[0]["license_status"].startswith("expirada; ")


def test_signed_offline_license_activates_without_http(tmp_path):
    issuer = _issuer()
    client = _client(tmp_path, issuer.public_key)

    request = client.activation_request()
    code, issued = issuer.issue(
        request,
        customer_ref="Loja Central",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2026, 10, 1),
    )

    assert client.validate().state == "activation_required"
    activated = client.activate(code)

    assert activated.allowed is True
    assert activated.state == "active"
    assert issued["customer_ref"] == "Loja Central"
    assert client.validate().allowed is True


def test_activation_accepts_a_complete_license_copied_with_email_line_breaks(tmp_path):
    issuer = _issuer()
    client = _client(tmp_path, issuer.public_key)
    code, _payload = issuer.issue(
        client.activation_request(),
        customer_ref="Loja Central",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2026, 10, 1),
    )
    copied_email_text = "Licenca recebida:\n" + "\n".join(code[index:index + 61] for index in range(0, len(code), 61))

    assert normalize_license_code(copied_email_text) == code
    assert client.activate(copied_email_text).allowed is True
    assert client.activate(code.rsplit(".", 1)[-1]).state == "incomplete_license"


def test_license_request_is_prepared_once_and_resets_only_after_activation(tmp_path):
    issuer = _issuer()
    client = _client(tmp_path, issuer.public_key, request_email="proprietario@example.com")

    recipient, request_code, submitted = client.pending_license_request()
    assert recipient == "proprietario@example.com"
    assert submitted is False
    assert client.mark_license_request_submitted() is True

    same_recipient, same_request, submitted = client.pending_license_request()
    assert same_recipient == recipient
    assert same_request == request_code
    assert submitted is True
    assert client.mark_license_request_submitted() is False
    assert client.retry_license_request() is True
    _recipient, retry_request, submitted = client.pending_license_request()
    assert retry_request == request_code
    assert submitted is False
    assert client.mark_license_request_submitted() is True

    code, _payload = issuer.issue(
        request_code,
        customer_ref="Loja de Pedido Unico",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2026, 10, 1),
    )
    assert client.activate(code).allowed is True
    assert client.activation_request() != request_code


def test_offline_license_is_bound_to_requesting_computer(tmp_path):
    issuer = _issuer()
    owner = _client(tmp_path / "owner", issuer.public_key, fingerprint="a" * 64)
    other = _client(tmp_path / "other", issuer.public_key, fingerprint="b" * 64)
    code, _payload = issuer.issue(
        owner.activation_request(),
        customer_ref="Loja A",
        plan_name="Anual",
        starts_at=date(2026, 1, 1),
        expires_at=date(2027, 1, 1),
    )

    assert owner.activate(code).allowed is True
    assert other.activate(code).state == "wrong_device"


def test_offline_license_rejects_tampering_expiry_and_clock_rollback(tmp_path):
    issuer = _issuer()
    now = lambda: datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    client = _client(tmp_path, issuer.public_key, now=now)
    request = client.activation_request()
    code, _payload = issuer.issue(
        request,
        customer_ref="Loja B",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2026, 9, 30),
    )

    altered = code[:-1] + ("A" if code[-1] != "A" else "B")
    assert client.activate(altered).state == "invalid_license"
    assert client.activate(code).allowed is True

    rollback_client = OfflineLicenseClient(
        issuer.public_key,
        credential_store=client.credential_store,
        fingerprint_provider=lambda: "a" * 64,
        now_provider=lambda: datetime(2026, 9, 8, 10, tzinfo=timezone.utc),
    )
    assert rollback_client.validate().state == "clock_tampered"

    expired_client = _client(tmp_path / "expired", issuer.public_key)
    expired_code, _payload = issuer.issue(
        expired_client.activation_request(),
        customer_ref="Loja Expirada",
        plan_name="Mensal",
        starts_at=date(2026, 1, 1),
        expires_at=date(2026, 2, 1),
    )
    assert expired_client.activate(expired_code).state == "expired"


def test_expired_license_can_be_replaced_with_a_renewal_for_the_same_computer(tmp_path):
    issuer = _issuer()
    current_time = [datetime(2026, 9, 1, 12, tzinfo=timezone.utc)]
    client = _client(tmp_path, issuer.public_key, now=lambda: current_time[0])
    first_code, _payload = issuer.issue(
        client.activation_request(),
        customer_ref="Loja Renovada",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2026, 9, 1),
    )
    assert client.activate(first_code).allowed is True

    current_time[0] = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
    assert client.validate().state == "expired"

    renewal_code, _payload = issuer.issue(
        client.activation_request(),
        customer_ref="Loja Renovada",
        plan_name="Anual",
        starts_at=date(2026, 9, 2),
        expires_at=date(2027, 9, 9),
    )
    assert client.activate(renewal_code).allowed is True


def test_superadmin_terminal_state_uses_fixed_username_and_issues_license(tmp_path):
    key_file = tmp_path / "offline_issuer_key.py"
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=key_file,
        legacy_database=tmp_path / "missing.db",
    )

    assert service.bootstrap("uma-palavra-passe-muito-forte") is False
    assert service.authenticate("uma-palavra-passe-muito-forte") is True
    assert service.authenticate("outra-palavra-passe") is False
    assert "OFFLINE_LICENSE_PUBLIC_KEY" in key_file.read_text(encoding="utf-8")
    service.set_license_recipient_email("dono@example.com")
    assert 'OFFLINE_LICENSE_REQUEST_EMAIL = "dono@example.com"' in key_file.read_text(encoding="utf-8")
    automatic = service.configure_automatic_email(
        "a" * 16,
        plan_name="Mensal automatico",
        months=1,
        poll_seconds=60,
    )
    assert automatic["configured"] is True
    assert automatic["gmail_email"] == "dono@example.com"
    assert "gmail_app_password" not in automatic
    assert automatic["auto_renewals"] is False
    short_automatic = service.configure_automatic_email(
        "",
        plan_name="Demonstracao curta",
        duration_amount="30s",
        poll_seconds=60,
    )
    assert short_automatic["duration_label"] == "30 segundos"
    assert short_automatic["months"] is None
    assert service.automatic_email_settings().duration_unit == "seconds"

    client = _client(tmp_path / "client", service.public_key())
    request_code = client.activation_request()
    code, payload = service.issue_license(
        request_code,
        customer_ref="Cliente Local",
        plan_name="Dois meses",
        months=2,
        starts_at=date(2026, 9, 1),
    )

    assert verify_license_code(code, service.public_key())["license_id"] == payload["license_id"]
    assert client.activate(code).allowed is True
    assert service.license_code(payload["license_id"]) == code
    assert "license_code" not in service.list_licenses()[0]

    # Mesmo quando o historico visivel for reduzido, o pedido continua gasto.
    state = service._load()
    state["licenses"] = []
    service._save(state)
    with pytest.raises(SuperadminError, match="ja foi utilizado"):
        service.issue_license(
            request_code,
            customer_ref="Cliente Local",
            plan_name="Duplicada",
            months=1,
            starts_at=date(2026, 9, 1),
        )


def test_superadmin_automatic_retries_reuse_the_same_signed_license(tmp_path):
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    service.set_license_recipient_email("dono@example.com")
    client = _client(tmp_path / "client", service.public_key())
    request_code = client.activation_request()

    first_code, first_payload, created = service.issue_or_get_license(
        request_code,
        customer_ref="Cliente automatico",
        plan_name="Mensal",
        months=1,
    )
    repeat_code, repeat_payload, created_again = service.issue_or_get_license(
        request_code,
        customer_ref="Outro nome nao deve gerar nova licenca",
        plan_name="Outro plano",
        months=2,
    )

    assert created is True
    assert created_again is False
    assert repeat_code == first_code
    assert repeat_payload["license_id"] == first_payload["license_id"]
    assert len(service.list_licenses()) == 1

    # Um novo pedido do mesmo computador e renovacao. O emissor automatico
    # pode exigir aprovacao comercial, mas o terminal ainda consegue renovar
    # a identidade ja existente quando o dono liberar.
    client_state = client.credential_store.load()
    client_state.pop("license_request_code", None)
    client_state.pop("license_request_submitted_at", None)
    client.credential_store.save(client_state)
    renewal_request = client.activation_request()
    with pytest.raises(SuperadminError, match="aguarda aprovacao"):
        service.issue_or_get_license(
            renewal_request,
            customer_ref="Cliente automatico",
            plan_name="Mensal",
            duration_amount="1 dia",
            allow_renewal=False,
        )
    renewal_code, renewal_payload, renewal_created = service.issue_or_get_license(
        renewal_request,
        customer_ref="Cliente automatico",
        plan_name="Mensal",
        duration_amount="1 dia",
        allow_renewal=True,
    )
    assert renewal_created is True
    assert renewal_code != first_code
    assert renewal_payload["license_id"] == first_payload["license_id"]
    assert len(service.list_licenses()) == 1


def test_superadmin_uses_a_short_stable_reference_without_replacing_uuid(tmp_path):
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    first_client = _client(tmp_path / "client-one", service.public_key(), fingerprint="1" * 64)
    second_client = _client(tmp_path / "client-two", service.public_key(), fingerprint="2" * 64)

    first_code, first = service.issue_license(
        first_client.activation_request(),
        customer_ref="Primeiro cliente",
        plan_name="Mensal",
        months=1,
        starts_at=date(2026, 9, 1),
    )
    second_code, second = service.issue_license(
        second_client.activation_request(),
        customer_ref="Segundo cliente",
        plan_name="Mensal",
        months=1,
        starts_at=date(2026, 9, 1),
    )

    assert first["license_reference"] == "MIRSON-0001"
    assert second["license_reference"] == "MIRSON-0002"
    assert service.resolve_license_identifier("MIRSON-0001") == first["license_id"]
    assert service.resolve_license_identifier("1") == first["license_id"]
    assert service.resolve_license_identifier(first["license_id"]) == first["license_id"]
    assert verify_license_code(first_code, service.public_key())["license_id"] == first["license_id"]
    assert verify_license_code(second_code, service.public_key())["license_id"] == second["license_id"]

    assert first_client.activate(first_code).allowed is True
    renewal_code, renewed = service.issue_license(
        first_client.activation_request(),
        customer_ref="Primeiro cliente",
        plan_name="Renovacao",
        duration_amount="1 dia",
        starts_at=date(2026, 9, 9),
    )
    assert renewed["license_id"] == first["license_id"]
    assert renewed["license_reference"] == "MIRSON-0001"
    assert verify_license_code(renewal_code, service.public_key())["license_id"] == first["license_id"]


def test_superadmin_adds_short_references_to_legacy_records_without_changing_license(tmp_path):
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    client = _client(tmp_path / "client", service.public_key())
    code, payload = service.issue_license(
        client.activation_request(),
        customer_ref="Cliente legado",
        plan_name="Mensal",
        months=1,
    )

    legacy_state = service._load()
    legacy_state["licenses"][0].pop("license_reference", None)
    service._save(legacy_state)

    listed = service.list_licenses()
    assert listed[0]["license_reference"] == "MIRSON-0001"
    assert service.resolve_license_identifier("1") == payload["license_id"]
    assert service.license_code(payload["license_id"]) == code
    assert verify_license_code(code, service.public_key())["license_id"] == payload["license_id"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30s", (30, "seconds")),
        ("1min", (1, "minutes")),
        ("1 hora", (1, "hours")),
        ("7 dias", (7, "days")),
        ("2 meses", (2, "months")),
        ("1 ano", (1, "years")),
        ("1 mês", (1, "months")),
    ],
)
def test_license_duration_accepts_free_portuguese_terms(raw, expected):
    assert normalize_license_duration(raw) == expected


def test_license_duration_keeps_calendar_months_and_rejects_ambiguous_units():
    start = datetime(2026, 1, 31, 10, 15, tzinfo=timezone.utc)

    assert add_license_duration(start, "1 mes") == datetime(2026, 2, 28, 10, 15, tzinfo=timezone.utc)
    with pytest.raises(SuperadminError):
        normalize_license_duration("1m")


def test_superadmin_renews_same_license_id_with_a_flexible_exact_duration(tmp_path):
    current_time = [datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)]
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    client = _client(
        tmp_path / "client",
        service.public_key(),
        now=lambda: current_time[0],
    )

    first_request = client.activation_request()
    first_code, first_payload = service.issue_license(
        first_request,
        customer_ref="Cliente renovavel",
        plan_name="Demonstracao",
        duration_amount="30s",
        starts_at=current_time[0],
    )
    assert first_payload["duration_label"] == "30 segundos"
    assert first_payload["expires_at"] == "2026-09-01T12:00:30+00:00"
    assert client.activate(first_code).allowed is True

    current_time[0] = datetime(2026, 9, 1, 12, 0, 31, tzinfo=timezone.utc)
    assert client.validate().state == "expired"
    # O maior horario visto e guardado ate para uma licenca expirada; atrasar
    # a hora nao deve devolver os segundos ja consumidos.
    current_time[0] = datetime(2026, 9, 1, 12, 0, 1, tzinfo=timezone.utc)
    assert client.validate().state == "clock_tampered"

    current_time[0] = datetime(2026, 9, 1, 12, 0, 31, tzinfo=timezone.utc)
    renewal_request = client.activation_request()
    assert renewal_request != first_request
    renewal_code, renewal_payload = service.issue_license(
        renewal_request,
        customer_ref="Cliente renovavel",
        plan_name="Renovacao curta",
        duration_amount="1min",
        starts_at=current_time[0],
    )

    assert renewal_code != first_code
    assert renewal_payload["license_id"] == first_payload["license_id"]
    assert renewal_payload["request_id"] == first_payload["request_id"]
    assert renewal_payload["renewed"] is True
    assert renewal_payload["renewal_count"] == 1
    assert renewal_payload["expires_at"] == "2026-09-01T12:01:31+00:00"
    records = service.list_licenses()
    assert len(records) == 1
    assert records[0]["license_id"] == first_payload["license_id"]
    assert records[0]["duration_label"] == "1 minuto"
    assert records[0]["renewal_count"] == 1
    assert len(records[0]["request_ids"]) == 2
    assert client.activate(renewal_code).allowed is True


def test_superadmin_can_issue_one_importable_revocation_for_an_active_license(tmp_path):
    current_time = [datetime.now(timezone.utc).replace(microsecond=0)]
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    client = _client(
        tmp_path / "client",
        service.public_key(),
        now=lambda: current_time[0],
    )
    license_code, license_payload = service.issue_license(
        client.activation_request(),
        customer_ref="Cliente cancelado",
        plan_name="Mensal",
        duration_amount="30 dias",
        starts_at=current_time[0],
    )
    assert client.activate(license_code).allowed is True

    revocation_code, revocation_payload, created = service.revoke_license(
        license_payload["license_id"],
        reason="Contrato encerrado",
    )
    assert created is True
    signed = verify_revocation_code(revocation_code, service.public_key())
    assert signed["license_id"] == license_payload["license_id"]
    assert signed["reason"] == "Contrato encerrado"
    records = service.list_licenses()
    assert records[0]["revocation_status"].startswith("emitida")
    assert "revocation_code" not in records[0]

    # O cancelamento fica efetivo somente quando for importado no PC alvo.
    assert client.apply_revocation(revocation_code).state == "revoked"
    assert client.validate().state == "revoked"
    assert client.activate(license_code).state == "revoked"
    same_code, same_payload, created_again = service.revoke_license(license_payload["license_id"])
    assert created_again is False
    assert same_code == revocation_code
    assert same_payload["revocation_id"] == revocation_payload["revocation_id"]
    with pytest.raises(SuperadminError, match="cancelada"):
        service.license_code(license_payload["license_id"])
    with pytest.raises(SuperadminError, match="cancelamento emitido"):
        service.issue_license(
            client.activation_request(),
            customer_ref="Cliente cancelado",
            plan_name="Tentativa de renovar",
            duration_amount="1 dia",
            starts_at=current_time[0],
        )
    with pytest.raises(SuperadminError, match="cancelada"):
        service.issue_or_get_admin_provisioning(
            license_payload["license_id"],
            username="admin.cancelado",
            temporary_password="SenhaTemporaria!2026",
        )

    other = _client(tmp_path / "other", service.public_key(), fingerprint="b" * 64)
    assert other.apply_revocation(revocation_code).state == "revocation_wrong_license"


def test_superadmin_can_restore_a_specific_definitive_revocation(tmp_path):
    current_time = [datetime.now(timezone.utc).replace(microsecond=0)]
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
    )
    service.bootstrap("Superadmin!Senha2026")
    client = _client(tmp_path / "client", service.public_key(), now=lambda: current_time[0])
    license_code, license_payload = service.issue_license(
        client.activation_request(),
        customer_ref="Loja Recuperada",
        plan_name="Mensal",
        duration_amount="30 dias",
        starts_at=current_time[0],
    )
    assert client.activate(license_code).allowed is True
    revocation_code, revocation_payload, _created = service.revoke_license(license_payload["license_id"])
    assert client.apply_revocation(revocation_code).state == "revoked"

    restoration_code, restoration_payload, created = service.restore_revoked_license(
        license_payload["license_id"],
        reason="Cancelamento de teste desfeito",
    )
    assert created is True
    signed = verify_restoration_code(restoration_code, service.public_key())
    assert signed["license_id"] == license_payload["license_id"]
    assert signed["revocation_id"] == revocation_payload["revocation_id"]
    assert signed["reason"] == "Cancelamento de teste desfeito"
    assert client.apply_restoration(restoration_code).state == "active"
    assert client.validate().allowed is True
    # Depois de recuperado, o antigo e-mail SIGE-REV1 nao pode bloquear o
    # computador outra vez; somente uma nova revogacao assinada poderia faze-lo.
    assert client.apply_revocation(revocation_code).state == "active"
    records = service.list_licenses()
    assert records[0]["license_status"].startswith("recuperacao")
    assert service.license_code(license_payload["license_id"]) == license_code

    other = _client(tmp_path / "other", service.public_key(), fingerprint="b" * 64)
    assert other.apply_restoration(restoration_code).state == "restoration_wrong_license"


def test_superadmin_can_suspend_then_reactivate_the_same_license(tmp_path):
    current_time = [datetime.now(timezone.utc).replace(microsecond=0)]
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
    )
    service.bootstrap("Superadmin!Senha2026")
    client = _client(tmp_path / "client", service.public_key(), now=lambda: current_time[0])
    license_code, license_payload = service.issue_license(
        client.activation_request(),
        customer_ref="Loja Suspensa",
        plan_name="Mensal",
        duration_amount="30 dias",
        starts_at=current_time[0],
    )
    assert client.activate(license_code).state == "active"

    suspension_code, suspension_payload, created = service.suspend_license(
        license_payload["license_id"],
        reason="Pagamento em verificacao",
    )
    assert created is True
    signed_suspension = verify_suspension_code(suspension_code, service.public_key())
    assert signed_suspension["license_id"] == license_payload["license_id"]
    assert signed_suspension["reason"] == "Pagamento em verificacao"
    assert client.apply_suspension(suspension_code).state == "suspended"
    assert client.activate(license_code).state == "suspended"
    records = service.list_licenses()
    assert records[0]["license_status"].startswith("suspensao")
    with pytest.raises(SuperadminError, match="suspensa"):
        service.license_code(license_payload["license_id"])

    reactivation_code, reactivation_payload, reactivation_created = service.reactivate_license(
        license_payload["license_id"],
        reason="Pagamento confirmado",
    )
    assert reactivation_created is True
    signed_reactivation = verify_reactivation_code(reactivation_code, service.public_key())
    assert signed_reactivation["license_id"] == license_payload["license_id"]
    assert signed_reactivation["suspension_id"] == suspension_payload["suspension_id"]
    assert signed_reactivation["reason"] == "Pagamento confirmado"
    assert client.apply_reactivation(reactivation_code).state == "active"
    assert client.validate().allowed is True
    records = service.list_licenses()
    assert records[0]["license_status"].startswith("reativacao")

    # A reativacao antiga nao pode libertar uma suspensao posterior.
    next_suspension, next_payload, _created = service.suspend_license(
        license_payload["license_id"],
        reason="Nova verificacao",
    )
    assert next_payload["suspension_id"] != suspension_payload["suspension_id"]
    assert client.apply_suspension(next_suspension).state == "suspended"
    assert client.apply_reactivation(reactivation_code).state == "reactivation_requires_suspension"

    revocation_code, _revocation_payload, _created = service.revoke_license(license_payload["license_id"])
    assert client.apply_revocation(revocation_code).state == "revoked"
    with pytest.raises(SuperadminError, match="cancelada definitivamente"):
        service.reactivate_license(license_payload["license_id"])


def test_superadmin_remembers_successful_automatic_delivery(tmp_path):
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    message_hash = "a" * 64

    assert service.automatic_email_message_was_delivered(message_hash) is False
    service.mark_automatic_email_message_delivered(message_hash)
    assert service.automatic_email_message_was_delivered(message_hash) is True


def test_signed_admin_code_is_bound_to_the_active_license_and_device(tmp_path):
    private_key = generate_issuer_private_key()
    issuer = OfflineLicenseIssuer(private_key)
    client = _client(tmp_path, issuer.public_key)
    license_code, _license_payload = issuer.issue(
        client.activation_request(),
        customer_ref="Conta segura",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2027, 9, 1),
    )
    assert client.activate(license_code).allowed is True
    password_hash = bcrypt.hashpw(b"SenhaTemporaria!2026", bcrypt.gensalt()).decode("ascii")

    provisioning_code, payload = issue_admin_provisioning_code(
        private_key,
        license_code,
        username="admin.loja",
        password_hash=password_hash,
        email="admin@example.com",
        expires_at=date.today() + timedelta(days=30),
    )
    active_license = client.credential_store.load()["license_code"]
    validated = validate_admin_provisioning_for_license(
        provisioning_code,
        issuer.public_key,
        active_license,
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    assert validated["provisioning_id"] == payload["provisioning_id"]
    assert validated["username"] == "admin.loja"
    assert validated["password_hash"] == password_hash

    other = _client(tmp_path / "other", issuer.public_key, fingerprint="b" * 64)
    other_license, _other_payload = issuer.issue(
        other.activation_request(),
        customer_ref="Outro computador",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2027, 9, 1),
    )
    assert other.activate(other_license).allowed is True
    with pytest.raises(AccountProvisioningError, match="outro computador ou licenca"):
        validate_admin_provisioning_for_license(
            provisioning_code,
            issuer.public_key,
            other.credential_store.load()["license_code"],
            now=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )


def test_admin_code_expires_before_it_can_create_an_account(tmp_path):
    private_key = generate_issuer_private_key()
    issuer = OfflineLicenseIssuer(private_key)
    client = _client(tmp_path, issuer.public_key)
    license_code, _payload = issuer.issue(
        client.activation_request(),
        customer_ref="Conta expirada",
        plan_name="Mensal",
        starts_at=date(2026, 9, 1),
        expires_at=date(2027, 9, 1),
    )
    assert client.activate(license_code).allowed is True
    expires_at = datetime.now(timezone.utc).date() + timedelta(days=1)
    provisioning_code, _provisioning = issue_admin_provisioning_code(
        private_key,
        license_code,
        username="admin.loja",
        password_hash=bcrypt.hashpw(b"SenhaTemporaria!2026", bcrypt.gensalt()).decode("ascii"),
        expires_at=expires_at,
    )

    with pytest.raises(AccountProvisioningError, match="expirou"):
        validate_admin_provisioning_for_license(
            provisioning_code,
            issuer.public_key,
            client.credential_store.load()["license_code"],
            now=datetime.now(timezone.utc) + timedelta(days=2),
        )


def test_superadmin_issues_one_safe_admin_code_for_each_license(tmp_path):
    service = LocalSuperadmin(
        tmp_path / "superadmin.dat",
        protector=MemoryProtector(),
        issuer_key_file=tmp_path / "offline_issuer_key.py",
        legacy_database=tmp_path / "missing.db",
    )
    service.bootstrap("uma-palavra-passe-muito-forte")
    client = _client(
        tmp_path / "client",
        service.public_key(),
        now=lambda: datetime.now(timezone.utc),
    )
    license_code, license_payload = service.issue_license(
        client.activation_request(),
        customer_ref="Cliente de conta",
        plan_name="Mensal",
        months=1,
        starts_at=date.today() - timedelta(days=1),
    )
    assert client.activate(license_code).allowed is True

    code, payload, created = service.issue_or_get_admin_provisioning(
        license_payload["license_id"],
        username="admin.cliente",
        temporary_password="SenhaTemporaria!2026",
        email="admin@example.com",
        valid_days=7,
    )
    same_code, same_payload, created_again = service.issue_or_get_admin_provisioning(
        license_payload["license_id"],
        username="nome-nao-deve-alterar",
        temporary_password="OutraSenha!2026",
        valid_days=7,
    )

    assert created is True
    assert created_again is False
    assert same_code == code
    assert same_payload["provisioning_id"] == payload["provisioning_id"]
    safe_row = service.list_admin_provisionings()[0]
    assert safe_row["username"] == "admin.cliente"
    assert "provisioning_code" not in safe_row
    assert "password" not in safe_row
    validated = validate_admin_provisioning_for_license(
        code,
        service.public_key(),
        client.credential_store.load()["license_code"],
    )
    assert bcrypt.checkpw(b"SenhaTemporaria!2026", validated["password_hash"].encode("ascii"))

    # Uma renovacao conserva license_id e request_id, portanto o codigo admin
    # ja emitido continua ligado a esta mesma instalacao.
    renewal_code, renewal_payload = service.issue_license(
        client.activation_request(),
        customer_ref="Cliente de conta",
        plan_name="Renovacao",
        duration_amount="7 dias",
        starts_at=date.today() - timedelta(days=1),
    )
    assert renewal_payload["license_id"] == license_payload["license_id"]
    assert client.activate(renewal_code).allowed is True
    renewed_admin = validate_admin_provisioning_for_license(
        code,
        service.public_key(),
        client.credential_store.load()["license_code"],
    )
    assert renewed_admin["provisioning_id"] == payload["provisioning_id"]


@pytest.mark.parametrize("duration", ["vitalicia", "vital\u00edcia", "lifetime"])
def test_lifetime_license_remains_active_and_signed(tmp_path, duration):
    service = LocalSuperadmin(tmp_path / "issuer.dat", protector=MemoryProtector(),
                             issuer_key_file=tmp_path / "key.py", legacy_database=tmp_path / "missing.db")
    service.bootstrap("uma-palavra-passe-muito-forte")
    now = datetime.now(timezone.utc)
    client = _client(tmp_path, service.public_key(), now=lambda: now)
    code, payload = service.issue_license(client.activation_request(), customer_ref="Loja",
                                          plan_name="Vitalicia", duration_amount=duration)
    assert payload["duration_label"] == "Vitalicia"
    assert verify_license_code(code, service.public_key())["expires_at"] == payload["expires_at"]
    assert client.activate(code).allowed
    now = datetime(2199, 1, 1, tzinfo=timezone.utc)
    result = client.validate()
    assert result.allowed
    assert "vitalicia" in result.message


def test_renewal_request_reuses_signed_license_without_form(tmp_path):
    from licensing.offline import parse_license_request
    issuer = _issuer()
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    client = _client(tmp_path, issuer.public_key, now=lambda: now)
    code, payload = issuer.issue(client.activation_request(), customer_ref="Loja Gaza",
                                 plan_name="Mensal", starts_at=now,
                                 expires_at=now + timedelta(days=30))
    assert client.activate(code).allowed
    now += timedelta(days=31)
    assert client.validate().state == "expired"
    request_code = client.prepare_license_request()
    details = parse_license_request(request_code)["request_details"]
    assert details["customer"] == "Loja Gaza"
    assert details["requested_plan"] == "Mensal"
    assert details["requested_duration"] == "Manter prazo anterior"
    assert details["request_type"] == "Renovacao"
    assert details["license_id"] == payload["license_id"]
    assert client.prepare_license_request(username="different") == request_code
    client.mark_license_request_submitted()
    client.retry_license_request()
    assert client.prepare_license_request() == request_code


def test_first_license_request_needs_no_customer_form(tmp_path):
    from licensing.offline import parse_license_request
    client = _client(tmp_path, _issuer().public_key)
    details = parse_license_request(client.prepare_license_request())["request_details"]
    assert details == {"request_type": "Primeira ativacao"}


@pytest.mark.parametrize("plan,duration", [
    ("Mensal", "1 mes"), ("Trimestral", "3 meses"),
    ("Semestral", "6 meses"), ("Anual", "1 ano"), ("Vitalicia", "Vitalicia"),
])
def test_request_includes_selected_plan_and_duration(tmp_path, plan, duration):
    from licensing.offline import parse_license_request
    client = _client(tmp_path, _issuer().public_key)
    code = client.prepare_license_request(plan=plan)
    details = parse_license_request(code)["request_details"]
    assert details["requested_plan"] == plan
    assert details["requested_duration"] == duration
    assert client.prepare_license_request(plan="Mensal") == code
