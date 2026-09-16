"""Terminal local do superadmin para licencas offline do SIGE MPE."""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from licensing.offline_email import (
    OfflineEmailError,
    SMTPSettings,
    gmail_settings,
    send_admin_provisioning_email,
    send_license_email,
    send_license_reactivation_email,
    send_license_restoration_email,
    send_license_revocation_email,
    send_license_suspension_email,
)
from licensing.superadmin import (
    LocalSuperadmin,
    SUPERADMIN_USERNAME,
    SuperadminError,
    license_duration_label,
    normalize_license_duration,
)


def _expiry_label(value: object) -> str:
    """Mostra hora quando o prazo e curto, sem esconder segundos."""
    raw = str(value or "").strip()
    if raw == "9999-12-31T23:59:59+00:00":
        return "Vitalicia (sem expiracao)"
    if not raw:
        return "-"
    if "T" not in raw:
        return raw
    visible = raw.replace("T", " ")[:19]
    return f"{visible} UTC" if raw.endswith("+00:00") or raw.endswith("Z") else visible


def _license_reference(record: dict) -> str:
    """Referencia curta usada para selecionar a licenca no CMD."""
    return str(record.get("license_reference") or record.get("license_id") or "-")


def _license_record(service: LocalSuperadmin, internal_id: str) -> dict:
    return next(
        record
        for record in service.list_licenses()
        if str(record.get("license_id") or "") == str(internal_id or "")
    )


def _read_license_identifier(service: LocalSuperadmin, prompt: str) -> str:
    """Aceita MIRSON-0001, apenas 1, ou o UUID antigo por compatibilidade."""
    selected = input(prompt).strip()
    return service.resolve_license_identifier(selected)


def _confirm_license_identifier(service: LocalSuperadmin, internal_id: str, reference: str) -> bool:
    confirmation = input(
        f"Para confirmar, digite novamente a referencia {reference}: "
    ).strip()
    try:
        return service.resolve_license_identifier(confirmation) == internal_id
    except SuperadminError:
        return False


def _clear_terminal() -> None:
    """Redesenha o painel sem deixar o historico do menu ocupar a janela."""
    os.system("cls" if os.name == "nt" else "clear")


def _back_to_menu() -> None:
    input("\nPrima Enter para voltar ao painel... ")


def _new_password() -> str:
    while True:
        password = getpass.getpass("Crie a palavra-passe do superadmin: ")
        confirmation = getpass.getpass("Repita a palavra-passe: ")
        if password != confirmation:
            print("As palavras-passe nao coincidem.")
        elif len(password) < 16:
            print("Use pelo menos 16 caracteres.")
        else:
            return password


def _authenticate(service: LocalSuperadmin) -> bool:
    for _attempt in range(3):
        password = getpass.getpass(f"Palavra-passe de {SUPERADMIN_USERNAME}: ")
        if service.authenticate(password):
            return True
        print("Credenciais invalidas.")
    return False


def _smtp_send(service: LocalSuperadmin, license_code: str, payload: dict) -> None:
    recipient = service.license_recipient_email()
    if not recipient:
        raise SuperadminError("Defina primeiro o e-mail privado que recebera as licencas.")
    sender = input(f"Gmail remetente [{recipient}]: ").strip() or recipient
    app_password = getpass.getpass("Cole a palavra-passe de aplicacao do Gmail: ")
    settings = gmail_settings(sender, app_password)
    send_license_email(
        settings,
        recipient,
        license_code,
        customer_ref=payload["customer_ref"],
        plan_name=payload["plan_name"],
        expires_at=payload["expires_at"],
    )


def _smtp_send_revocation(service: LocalSuperadmin, revocation_code: str, payload: dict) -> None:
    recipient = service.license_recipient_email()
    if not recipient:
        raise SuperadminError("Defina primeiro o e-mail privado que recebera os cancelamentos.")
    sender = input(f"Gmail remetente [{recipient}]: ").strip() or recipient
    app_password = getpass.getpass("Cole a palavra-passe de aplicacao do Gmail: ")
    settings = gmail_settings(sender, app_password)
    send_license_revocation_email(
        settings,
        recipient,
        revocation_code,
        customer_ref=str(payload.get("customer_ref") or "Cliente"),
        reason=str(payload.get("reason") or "Cancelada pelo superadmin."),
        effective_at=str(payload.get("effective_at") or ""),
    )


def _smtp_send_suspension(service: LocalSuperadmin, suspension_code: str, payload: dict) -> None:
    recipient = service.license_recipient_email()
    if not recipient:
        raise SuperadminError("Defina primeiro o e-mail privado que recebera as suspensoes.")
    sender = input(f"Gmail remetente [{recipient}]: ").strip() or recipient
    app_password = getpass.getpass("Cole a palavra-passe de aplicacao do Gmail: ")
    settings = gmail_settings(sender, app_password)
    send_license_suspension_email(
        settings,
        recipient,
        suspension_code,
        customer_ref=str(payload.get("customer_ref") or "Cliente"),
        reason=str(payload.get("reason") or "Suspensa pelo superadmin."),
        effective_at=str(payload.get("effective_at") or ""),
    )


def _smtp_send_reactivation(service: LocalSuperadmin, reactivation_code: str, payload: dict) -> None:
    recipient = service.license_recipient_email()
    if not recipient:
        raise SuperadminError("Defina primeiro o e-mail privado que recebera as reativacoes.")
    sender = input(f"Gmail remetente [{recipient}]: ").strip() or recipient
    app_password = getpass.getpass("Cole a palavra-passe de aplicacao do Gmail: ")
    settings = gmail_settings(sender, app_password)
    send_license_reactivation_email(
        settings,
        recipient,
        reactivation_code,
        customer_ref=str(payload.get("customer_ref") or "Cliente"),
        reason=str(payload.get("reason") or "Reativada pelo superadmin."),
        effective_at=str(payload.get("effective_at") or ""),
    )


def _smtp_send_restoration(service: LocalSuperadmin, restoration_code: str, payload: dict) -> None:
    recipient = service.license_recipient_email()
    if not recipient:
        raise SuperadminError("Defina primeiro o e-mail privado que recebera as recuperacoes.")
    sender = input(f"Gmail remetente [{recipient}]: ").strip() or recipient
    app_password = getpass.getpass("Cole a palavra-passe de aplicacao do Gmail: ")
    settings = gmail_settings(sender, app_password)
    send_license_restoration_email(
        settings,
        recipient,
        restoration_code,
        customer_ref=str(payload.get("customer_ref") or "Cliente"),
        reason=str(payload.get("reason") or "Cancelamento revertido pelo superadmin."),
        effective_at=str(payload.get("effective_at") or ""),
    )


def _configure_recipient(service: LocalSuperadmin) -> None:
    current = service.license_recipient_email()
    prompt = f"E-mail privado que recebera as licencas [{current}]: " if current else "E-mail privado que recebera as licencas: "
    email = input(prompt).strip() or current
    if not email:
        print("Nenhum e-mail foi alterado.")
        return
    print(f"E-mail privado configurado: {service.set_license_recipient_email(email)}")


def _configure_automatic_email(service: LocalSuperadmin) -> None:
    if not service.license_recipient_email():
        print("Defina primeiro o e-mail privado na opcao 1.")
        return
    current = service.automatic_email_status()
    if current.get("configured"):
        print(f"Gmail automatico: {current['gmail_email']}")
        print(f"Plano padrao: {current['plan_name']} ({current.get('duration_label', '1 mes')})")
        print(f"Renovacoes automaticas: {'sim' if current.get('auto_renewals') else 'nao (recomendado)'}")
        print("Deixe a palavra-passe de aplicacao vazia para manter a ja protegida no cofre local.")
    else:
        print("Use a palavra-passe de aplicacao Gmail. Ela fica protegida pelo Windows neste computador.")
    plan_name = input(f"Plano automatico [{current.get('plan_name', 'Mensal')}]: ").strip() or current.get("plan_name", "Mensal")
    current_duration = str(current.get("duration_label") or f"{current.get('months') or 1} meses")
    duration_text = input(
        f"Prazo automatico [{current_duration}] (ex.: 30s, 1min, 1 dia, 2 meses, 1 ano, vitalicia): "
    ).strip() or current_duration
    renewal_default = "S" if current.get("auto_renewals") else "N"
    renewal_answer = input(
        f"Permitir renovacoes automaticas sem aprovacao no terminal? [s/N] ({renewal_default}): "
    ).strip().casefold()
    if not renewal_answer:
        auto_renewals = bool(current.get("auto_renewals"))
    elif renewal_answer in {"s", "sim", "y", "yes"}:
        auto_renewals = True
    elif renewal_answer in {"n", "nao", "não", "no"}:
        auto_renewals = False
    else:
        print("Resposta invalida. Use S para sim ou N para nao.")
        return
    poll_seconds = input(f"Verificar novos pedidos a cada segundos [{current.get('poll_seconds', 60)}]: ").strip() or str(current.get("poll_seconds", 60))
    customer_ref = input(f"Referencia padrao do cliente [{current.get('customer_ref', 'Cliente por e-mail')}]: ").strip() or current.get("customer_ref", "Cliente por e-mail")
    password = getpass.getpass("Palavra-passe de aplicacao Gmail: ")
    try:
        duration_amount, duration_unit = normalize_license_duration(duration_text)
        status = service.configure_automatic_email(
            password,
            customer_ref=customer_ref,
            plan_name=plan_name,
            duration_amount=duration_amount,
            duration_unit=duration_unit,
            auto_renewals=auto_renewals,
            poll_seconds=int(poll_seconds),
        )
    except (SuperadminError, ValueError) as error:
        print(f"O emissor automatico nao foi configurado: {error}")
        return
    print(
        "Emissor automatico configurado para "
        f"{status['recipient_email']}. Plano: {status['plan_name']} ({status['duration_label']}). "
        f"Renovacoes automaticas: {'sim' if status['auto_renewals'] else 'nao'}."
    )
    start_now = input("Iniciar o emissor automatico agora? [S/n]: ").strip().lower()
    if start_now not in {"n", "nao", "não"}:
        _start_automatic_emitter()


def _start_automatic_emitter() -> None:
    script = PROJECT_ROOT / "scripts" / "emissor_licencas_automatico.py"
    try:
        subprocess.Popen([sys.executable, str(script)], cwd=str(PROJECT_ROOT), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    except OSError as error:
        print(f"Nao foi possivel iniciar o emissor automatico: {error}")
        return
    print("O emissor automatico foi aberto numa nova janela. Deixe-a aberta para processar pedidos.")


def _issue_license(service: LocalSuperadmin) -> None:
    request_code = input("Cole o pedido de licenca do computador do cliente: ").strip()
    from licensing.offline import parse_license_request, OfflineLicenseError
    try:
        request = parse_license_request(request_code)
    except OfflineLicenseError as error:
        print(f"Pedido invalido: {error}")
        return
    details = request.get("request_details") or {}
    current = next((row for row in service.list_licenses()
                    if row.get("fingerprint") == request["fingerprint"]
                    and row.get("device_public_key") == request["device_public_key"]), {})
    default_plan = "Mensal"
    default_duration = "1 mes"
    if details:
        print("DADOS DECLARADOS PELO SOLICITANTE (confirme antes de emitir)")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        if details.get("plan_choice") == "Manter plano atual" and current:
            default_plan = current.get("plan_name") or default_plan
            default_duration = current.get("duration_label") or default_duration
        else:
            default_plan = details.get("requested_plan") or default_plan
            requested_duration = details.get("requested_duration")
            if requested_duration and requested_duration != "Manter prazo anterior":
                default_duration = requested_duration
    default_customer = current.get("customer_ref") or details.get("customer") or ""
    customer_ref = input(f"Nome ou referencia do cliente [{default_customer}]: ").strip() or default_customer
    plan_name = input(f"Nome do plano [{default_plan}]: ").strip() or default_plan
    duration_text = input(
        f"Prazo da licenca [{default_duration}] (ex.: 30s, 10h, 7 dias, 2 meses, 1 ano, vitalicia): "
    ).strip() or default_duration
    try:
        duration_amount, duration_unit = normalize_license_duration(duration_text)
        license_code, payload = service.issue_license(
            request_code,
            customer_ref=customer_ref,
            plan_name=plan_name,
            duration_amount=duration_amount,
            duration_unit=duration_unit,
        )
    except (SuperadminError, ValueError) as error:
        print(f"A licenca nao foi emitida: {error}")
        return
    try:
        _smtp_send(service, license_code, payload)
    except OfflineEmailError as error:
        print(f"A licenca foi emitida, mas o e-mail falhou: {error}")
        print(
            "Use a opcao 4 para reenviar a mesma licenca: "
            f"{payload.get('license_reference') or payload['license_id']}"
        )
        return
    action = "renovada" if payload.get("renewed") else "emitida"
    print(
        f"Licenca {action} e enviada apenas para o e-mail privado. "
        f"Prazo: {payload.get('duration_label', license_duration_label(duration_amount, duration_unit))}. "
        f"Valida ate {_expiry_label(payload['expires_at'])}."
    )


def _list_licenses(service: LocalSuperadmin) -> None:
    records = service.list_licenses()
    if not records:
        print("Nenhuma licenca foi emitida ainda.")
        return
    for record in records:
        print(
            f"{_license_reference(record)} | {record['customer_ref']} | {record['plan_name']} | "
            f"Dono (admin): {record.get('owner_username') or 'nao associado'} | "
            f"{record.get('duration_label', '-')} | renovacoes: {record.get('renewal_count', 0)} | "
            f"ate {_expiry_label(record.get('expires_at'))} | {record.get('license_status', record.get('revocation_status', 'ativa'))}"
        )


def _license_details(service: LocalSuperadmin) -> None:
    license_id = _read_license_identifier(service, "Referencia da licenca para ver todos os detalhes: ")
    print(json.dumps(service.license_details(license_id), ensure_ascii=False, indent=2))


def _resend_license(service: LocalSuperadmin) -> None:
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca a reenviar (ex.: MIRSON-0001): ",
        )
        code = service.license_code(license_id)
        record = _license_record(service, license_id)
        _smtp_send(service, code, record)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"A licenca nao foi reenviada: {error}")
        return
    print("Licenca reenviada apenas para o e-mail privado.")


def _suspend_license(service: LocalSuperadmin) -> None:
    records = service.list_licenses()
    candidates = [record for record in records if record.get("license_status") == "ativa"]
    if not candidates:
        print("Nao ha licencas ativas disponiveis para suspender.")
        return
    print("\nLICENCAS ATIVAS QUE PODEM SER SUSPENSAS")
    for record in candidates:
        print(
            f"{_license_reference(record)} | {record.get('customer_ref')} | "
            f"{record.get('plan_name')} | ate {_expiry_label(record.get('expires_at'))}"
        )
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca a suspender (ex.: MIRSON-0001): ",
        )
        selected_record = _license_record(service, license_id)
    except (SuperadminError, StopIteration) as error:
        print(f"A suspensao nao foi emitida: {error}")
        return
    if not _confirm_license_identifier(service, license_id, _license_reference(selected_record)):
        print("Suspensao nao confirmada. Nenhuma licenca foi alterada.")
        return
    reason = input("Motivo da suspensao (opcional): ").strip()
    try:
        code, payload, created = service.suspend_license(license_id, reason=reason)
    except SuperadminError as error:
        print(f"A suspensao nao foi emitida: {error}")
        return
    try:
        _smtp_send_suspension(service, code, payload)
        service.mark_license_suspension_sent(license_id)
    except (SuperadminError, OfflineEmailError) as error:
        print(f"A suspensao foi emitida, mas o e-mail falhou: {error}")
        print("Use a opcao 12 para reenviar o mesmo codigo de suspensao.")
        return
    action = "emitida" if created else "reenviada"
    print(f"Suspensao {action} para o e-mail privado.")
    print("O PC bloqueia somente depois de importar o codigo SIGE-SUS1. Pode ser reativado pela opcao 13.")


def _resend_license_suspension(service: LocalSuperadmin) -> None:
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca com suspensao (ex.: MIRSON-0001): ",
        )
        code = service.license_suspension_code(license_id)
        record = _license_record(service, license_id)
        payload = {
            "customer_ref": record.get("customer_ref"),
            "reason": record.get("suspension_reason"),
            "effective_at": record.get("suspension_effective_at"),
        }
        _smtp_send_suspension(service, code, payload)
        service.mark_license_suspension_sent(license_id)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"A suspensao nao foi reenviada: {error}")
        return
    print("Mesmo codigo de suspensao reenviado ao e-mail privado.")


def _reactivate_license(service: LocalSuperadmin) -> None:
    records = service.list_licenses()
    candidates = [
        record for record in records
        if str(record.get("suspension_status") or "").startswith("suspensao")
        and record.get("revocation_status") == "nao cancelada"
    ]
    if not candidates:
        print("Nao ha suspensoes pendentes que possam ser reativadas.")
        return
    print("\nLICENCAS SUSPENSAS QUE PODEM SER REATIVADAS")
    for record in candidates:
        print(
            f"{_license_reference(record)} | {record.get('customer_ref')} | "
            f"{record.get('plan_name')} | {record.get('suspension_status')}"
        )
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca a reativar (ex.: MIRSON-0001): ",
        )
        selected_record = _license_record(service, license_id)
    except (SuperadminError, StopIteration) as error:
        print(f"A reativacao nao foi emitida: {error}")
        return
    if not _confirm_license_identifier(service, license_id, _license_reference(selected_record)):
        print("Reativacao nao confirmada. Nenhuma licenca foi alterada.")
        return
    reason = input("Motivo da reativacao (opcional): ").strip()
    try:
        code, payload, created = service.reactivate_license(license_id, reason=reason)
    except SuperadminError as error:
        print(f"A reativacao nao foi emitida: {error}")
        return
    try:
        _smtp_send_reactivation(service, code, payload)
        service.mark_license_reactivation_sent(license_id)
    except (SuperadminError, OfflineEmailError) as error:
        print(f"A reativacao foi emitida, mas o e-mail falhou: {error}")
        print("Use a opcao 14 para reenviar o mesmo codigo de reativacao.")
        return
    action = "emitida" if created else "reenviada"
    print(f"Reativacao {action} para o e-mail privado.")
    print("O PC volta a funcionar somente depois de importar o codigo SIGE-RES1 recebido por e-mail.")


def _resend_license_reactivation(service: LocalSuperadmin) -> None:
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca com reativacao (ex.: MIRSON-0001): ",
        )
        code = service.license_reactivation_code(license_id)
        record = _license_record(service, license_id)
        payload = {
            "customer_ref": record.get("customer_ref"),
            "reason": record.get("reactivation_reason"),
            "effective_at": record.get("reactivation_effective_at"),
        }
        _smtp_send_reactivation(service, code, payload)
        service.mark_license_reactivation_sent(license_id)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"A reativacao nao foi reenviada: {error}")
        return
    print("Mesmo codigo de reativacao reenviado ao e-mail privado.")


def _revoke_license(service: LocalSuperadmin) -> None:
    records = service.list_licenses()
    active_records = [record for record in records if record.get("revocation_status") == "nao cancelada"]
    if not active_records:
        print("Nao ha licencas sem cancelamento definitivo emitido.")
        return
    print("\nLICENCAS QUE PODEM SER CANCELADAS DEFINITIVAMENTE")
    for record in active_records:
        print(
            f"{_license_reference(record)} | {record.get('customer_ref')} | "
            f"{record.get('plan_name')} | ate {_expiry_label(record.get('expires_at'))}"
        )
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca a cancelar definitivamente (ex.: MIRSON-0001): ",
        )
        selected_record = _license_record(service, license_id)
    except (SuperadminError, StopIteration) as error:
        print(f"O cancelamento nao foi emitido: {error}")
        return
    if not _confirm_license_identifier(service, license_id, _license_reference(selected_record)):
        print("Cancelamento nao confirmado. Nenhuma licenca foi alterada.")
        return
    print("ATENCAO: este cancelamento e definitivo. Para um bloqueio reversivel, use a opcao Suspender.")
    reason = input("Motivo do cancelamento (opcional): ").strip()
    try:
        code, payload, created = service.revoke_license(license_id, reason=reason)
    except SuperadminError as error:
        print(f"O cancelamento nao foi emitido: {error}")
        return
    try:
        _smtp_send_revocation(service, code, payload)
        service.mark_license_revocation_sent(license_id)
    except (SuperadminError, OfflineEmailError) as error:
        print(f"O cancelamento foi emitido, mas o e-mail falhou: {error}")
        print("Use a opcao 16 para reenviar o mesmo codigo de cancelamento.")
        return
    action = "emitido" if created else "reenviado"
    print(f"Cancelamento {action} para o e-mail privado.")
    print("Ele bloqueia o computador somente depois de o codigo SIGE-REV1 ser importado nele.")


def _resend_license_revocation(service: LocalSuperadmin) -> None:
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca com cancelamento (ex.: MIRSON-0001): ",
        )
        code = service.license_revocation_code(license_id)
        record = _license_record(service, license_id)
        payload = {
            "customer_ref": record.get("customer_ref"),
            "reason": record.get("revocation_reason"),
            "effective_at": record.get("revocation_effective_at"),
        }
        _smtp_send_revocation(service, code, payload)
        service.mark_license_revocation_sent(license_id)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"O cancelamento nao foi reenviado: {error}")
        return
    print("Mesmo codigo de cancelamento reenviado ao e-mail privado.")


def _restore_revoked_license(service: LocalSuperadmin) -> None:
    records = service.list_licenses()
    candidates = [
        record for record in records
        if str(record.get("license_status") or "").startswith("cancelada definitivamente")
    ]
    if not candidates:
        print("Nao ha cancelamentos definitivos pendentes de recuperacao.")
        return
    print("\nCANCELAMENTOS DEFINITIVOS QUE PODEM SER RECUPERADOS")
    for record in candidates:
        print(
            f"{_license_reference(record)} | {record.get('customer_ref')} | "
            f"{record.get('plan_name')} | {record.get('license_status')}"
        )
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca a recuperar (ex.: MIRSON-0001): ",
        )
        selected_record = _license_record(service, license_id)
    except (SuperadminError, StopIteration) as error:
        print(f"A recuperacao nao foi emitida: {error}")
        return
    if not _confirm_license_identifier(service, license_id, _license_reference(selected_record)):
        print("Recuperacao nao confirmada. Nenhuma licenca foi alterada.")
        return
    reason = input("Motivo da recuperacao (opcional): ").strip()
    try:
        code, payload, created = service.restore_revoked_license(license_id, reason=reason)
    except SuperadminError as error:
        print(f"A recuperacao nao foi emitida: {error}")
        return
    try:
        _smtp_send_restoration(service, code, payload)
        service.mark_license_restoration_sent(license_id)
    except (SuperadminError, OfflineEmailError) as error:
        print(f"A recuperacao foi emitida, mas o e-mail falhou: {error}")
        print("Use a opcao 18 para reenviar o mesmo codigo de recuperacao.")
        return
    action = "emitida" if created else "reenviada"
    print(f"Recuperacao {action} para o e-mail privado.")
    print("O PC volta a funcionar somente depois de importar o codigo SIGE-RST1 recebido por e-mail.")


def _resend_license_restoration(service: LocalSuperadmin) -> None:
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca com recuperacao (ex.: MIRSON-0001): ",
        )
        code = service.license_restoration_code(license_id)
        record = _license_record(service, license_id)
        payload = {
            "customer_ref": record.get("customer_ref"),
            "reason": record.get("restoration_reason"),
            "effective_at": record.get("restoration_effective_at"),
        }
        _smtp_send_restoration(service, code, payload)
        service.mark_license_restoration_sent(license_id)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"A recuperacao nao foi reenviada: {error}")
        return
    print("Mesmo codigo de recuperacao reenviado ao e-mail privado.")


def _automatic_smtp_settings(service: LocalSuperadmin) -> SMTPSettings:
    """Reutiliza a conta Gmail protegida ja configurada para o emissor."""
    settings = service.automatic_email_settings()
    return SMTPSettings(
        host="smtp.gmail.com",
        port=587,
        username=settings.gmail_email,
        password=settings.gmail_app_password,
        from_email=settings.gmail_email,
        use_tls=True,
        use_ssl=False,
    )


def _send_admin_provisioning(service: LocalSuperadmin, code: str, payload: dict) -> None:
    settings = _automatic_smtp_settings(service)
    send_admin_provisioning_email(
        settings,
        service.license_recipient_email(),
        code,
        username=str(payload.get("username") or ""),
        expires_at=str(payload.get("expires_at") or ""),
        customer_ref=str(payload.get("customer_ref") or "Cliente"),
    )


def _create_buyer_admin(service: LocalSuperadmin) -> None:
    licenses = service.list_licenses()
    if not licenses:
        print("Emita primeiro uma licenca para o computador do comprador.")
        return
    print("\nLicencas disponiveis:")
    for record in licenses:
        print(
            f"{_license_reference(record)} | {record['customer_ref']} | "
            f"{record['plan_name']} | ate {_expiry_label(record.get('expires_at'))}"
        )
    try:
        license_id = _read_license_identifier(
            service,
            "Referencia da licenca do comprador (ex.: MIRSON-0001): ",
        )
    except SuperadminError as error:
        print(f"A conta admin nao foi preparada: {error}")
        return
    existing = next(
        (record for record in service.list_admin_provisionings() if record.get("license_id") == license_id),
        None,
    )
    if existing:
        if existing.get("code_status") == "expirado":
            print("O codigo desta conta expirou. Use a opcao 10 para emitir um novo codigo temporario.")
            return
        try:
            code = service.admin_provisioning_code(str(existing.get("provisioning_id") or ""))
            _send_admin_provisioning(service, code, existing)
        except (SuperadminError, OfflineEmailError) as error:
            print(f"A conta existente nao foi reenviada: {error}")
            return
        print("A conta admin ja existia para esta licenca; o mesmo codigo foi reenviado ao e-mail privado.")
        return

    username = input("Utilizador admin do comprador: ").strip()
    email = input("E-mail do admin (opcional): ").strip() or None
    days = input("Validade do codigo temporario em dias [7]: ").strip() or "7"
    temporary_password = getpass.getpass("Defina a palavra-passe temporaria (minimo 12 caracteres): ")
    confirmation = getpass.getpass("Repita a palavra-passe temporaria: ")
    if temporary_password != confirmation:
        print("As palavras-passe nao coincidem.")
        return
    try:
        code, payload, _created = service.issue_or_get_admin_provisioning(
            license_id,
            username=username,
            temporary_password=temporary_password,
            email=email,
            valid_days=int(days),
        )
        _send_admin_provisioning(service, code, payload)
    except (SuperadminError, OfflineEmailError, ValueError) as error:
        print(f"A conta admin nao foi preparada: {error}")
        return
    print("Conta admin preparada e enviada ao e-mail privado.")
    print("Entregue a palavra-passe temporaria ao comprador por um canal seguro; ela nao fica guardada em texto.")


def _print_table(headers, rows, widths) -> None:
    """Tabela ASCII com quebra de linhas, sem cortar valores."""
    widths = list(widths)
    available = shutil.get_terminal_size(fallback=(140, 24)).columns - 1
    while sum(widths) + 3 * len(widths) + 1 > available and max(widths) > 4:
        widest = widths.index(max(widths))
        widths[widest] -= 1
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    print(border)
    for row in [headers, *rows]:
        cells = [textwrap.wrap(str(value if value is not None else "-"), width=width) or [""]
                 for value, width in zip(row, widths)]
        for line in range(max(map(len, cells))):
            print("| " + " | ".join((cell[line] if line < len(cell) else "").ljust(width)
                                     for cell, width in zip(cells, widths)) + " |")
        print(border)


def _list_system_users(service: LocalSuperadmin) -> None:
    from licensing.user_directory import local_user_directory

    directory = local_user_directory(service)
    users = directory["users"]
    installation = directory["installation_license"]
    print("\nUTILIZADORES DESTA INSTALACAO")
    print(f"Base: {directory['database_path']}")
    print(f"Superadmin do terminal: {SUPERADMIN_USERNAME} (conta separada das contas abaixo)")
    print(f"Licenca instalada: {installation.get('reference', '-')} | {installation['status']}")
    print(f"Validade: {_expiry_label(installation.get('expires_at'))}")
    rows = []
    for user in users:
        linked = user.get("owner_license") or {}
        rows.append([user.get("id"), user["username"], user["role"],
                     "ativa" if user.get("is_active", 1) else "inativa",
                     user.get("data_owner") or "-", user["password_storage"],
                     linked.get("license_reference") or "sem vinculo confirmado"])
    _print_table(["ID", "Utilizador", "Perfil", "Conta", "Admin responsavel", "Senha", "Licenca da conta"],
                 rows, [4, 14, 10, 7, 16, 22, 22])
    if not users:
        print("Nenhum utilizador local registado.")
    print("As senhas bcrypt nao podem ser recuperadas; os detalhes mostram o hash guardado.")
    print("A licenca instalada e partilhada pela aplicacao; o vinculo individual exige uma importacao registada.")
    _list_buyer_admins(service)
    while users:
        selected = input("\nID do utilizador para detalhes completos (Enter para voltar): ").strip()
        if not selected:
            return
        user = next((row for row in users if str(row.get("id")) == selected), None)
        if user is None:
            print("ID nao encontrado na tabela local.")
            continue
        print(json.dumps(user, ensure_ascii=False, indent=2))


def _list_buyer_admins(service: LocalSuperadmin) -> None:
    records = service.list_admin_provisionings()
    if not records:
        print("Nenhuma conta admin de comprador foi emitida ainda.")
        return
    licenses = {record.get("license_id"): record for record in service.list_licenses()}
    print("\nUTILIZADORES ADMIN CONHECIDOS PELO SUPERADMIN")
    print("O estado abaixo e do codigo emitido. Sem servidor, nao e uma consulta ao vivo ao PC do comprador.")
    rows = []
    for record in records:
        license_record = licenses.get(record.get("license_id"), {})
        rows.append([record.get('username'), record.get('email') or '-',
                     _license_reference(license_record) if license_record else '-',
                     license_record.get('license_status', 'desconhecido'),
                     record.get('code_status'), _expiry_label(license_record.get('expires_at'))])
    _print_table(["Admin emitido", "E-mail", "Licenca", "Estado da licenca", "Codigo admin", "Validade licenca"],
                 rows, [14, 23, 12, 25, 12, 23])
    print("Opcao 19: codigos, identificadores e historico completos de cada licenca.")


def _resend_buyer_admin(service: LocalSuperadmin) -> None:
    provisioning_id = input("Identificador da conta admin a reenviar: ").strip()
    try:
        code = service.admin_provisioning_code(provisioning_id)
        record = next(
            item for item in service.list_admin_provisionings()
            if item.get("provisioning_id") == provisioning_id
        )
        _send_admin_provisioning(service, code, record)
    except (SuperadminError, OfflineEmailError, StopIteration) as error:
        print(f"A conta admin nao foi reenviada: {error}")
        return
    print("Codigo temporario da conta admin reenviado ao e-mail privado.")


def _renew_expired_buyer_admin(service: LocalSuperadmin) -> None:
    records = service.list_admin_provisionings()
    expired = [record for record in records if record.get("code_status") == "expirado"]
    if not expired:
        print("Nao ha codigos admin expirados para substituir.")
        return
    print("\nCODIGOS ADMIN EXPIRADOS")
    for record in expired:
        print(
            f"{record.get('provisioning_id')} | {record.get('customer_ref') or '-'} | "
            f"{record.get('username')} | expirou em {str(record.get('expires_at') or '')[:10]}"
        )
    provisioning_id = input("Identificador da conta a substituir: ").strip()
    days = input("Validade do novo codigo em dias [7]: ").strip() or "7"
    temporary_password = getpass.getpass("Defina a nova palavra-passe temporaria (minimo 12 caracteres): ")
    confirmation = getpass.getpass("Repita a nova palavra-passe temporaria: ")
    if temporary_password != confirmation:
        print("As palavras-passe nao coincidem.")
        return
    try:
        code, payload = service.renew_expired_admin_provisioning(
            provisioning_id,
            temporary_password=temporary_password,
            valid_days=int(days),
        )
        _send_admin_provisioning(service, code, payload)
    except (SuperadminError, OfflineEmailError, ValueError) as error:
        print(f"O novo codigo admin nao foi preparado: {error}")
        return
    print("Novo codigo temporario enviado ao e-mail privado.")
    print("Entregue a nova palavra-passe temporaria ao comprador por um canal seguro.")


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("Execute este programa num terminal interativo.")
    service = LocalSuperadmin()
    try:
        if not service.initialized():
            # Reaproveita o hash criado localmente na configuracao anterior,
            # quando existir; caso contrario a nova senha nunca sai do terminal.
            try:
                migrated = service.bootstrap()
            except SuperadminError as error:
                if "Defina a palavra-passe" not in str(error):
                    raise
                migrated = service.bootstrap(_new_password())
            print("Credencial local anterior migrada com seguranca." if migrated else "Superadmin local configurado.")
        if not _authenticate(service):
            return 1
        key_file = service.configure_desktop_public_key()
    except SuperadminError as error:
        print(f"Nao foi possivel iniciar o superadmin: {error}")
        return 1

    while True:
        _clear_terminal()
        print("=" * 58)
        # Hifen ASCII para o titulo ficar legivel tambem no CMD classico do Windows.
        print(f"PAINEL LOCAL DO SUPERADMIN - {SUPERADMIN_USERNAME}")
        print("Licencas, contas e seguranca (sem servidor)")
        print("=" * 58)
        print("1. Definir e-mail privado das licencas")
        print("2. Emitir ou renovar licenca por e-mail")
        print("3. Listar licencas emitidas")
        print("4. Reenviar uma licenca")
        print("5. Configurar emissao automatica por Gmail")
        print("6. Iniciar emissor automatico agora")
        print("7. Criar conta admin do comprador")
        print("8. Tabela de utilizadores, senhas e licencas")
        print("9. Reenviar codigo de conta admin")
        print("10. Substituir codigo admin expirado")
        print("11. Suspender uma licenca (reversivel)")
        print("12. Reenviar codigo de suspensao")
        print("13. Reativar uma licenca suspensa")
        print("14. Reenviar codigo de reativacao")
        print("15. Cancelar uma licenca definitivamente")
        print("16. Reenviar codigo de cancelamento definitivo")
        print("17. Recuperar um cancelamento definitivo (emergencia)")
        print("18. Reenviar codigo de recuperacao")
        print("19. Ver todos os detalhes da licenca e do dono (admin)")
        print("V. Voltar / limpar a tela")
        print("0. Sair")
        option = input("Opcao: ").strip()
        if option.casefold() in {"v", "voltar", "b"}:
            continue
        if option == "0":
            return 0
        try:
            if option == "1":
                _configure_recipient(service)
            elif option == "2":
                _issue_license(service)
            elif option == "3":
                _list_licenses(service)
            elif option == "4":
                _resend_license(service)
            elif option == "5":
                _configure_automatic_email(service)
            elif option == "6":
                _start_automatic_emitter()
            elif option == "7":
                _create_buyer_admin(service)
            elif option == "8":
                _list_system_users(service)
            elif option == "9":
                _resend_buyer_admin(service)
            elif option == "10":
                _renew_expired_buyer_admin(service)
            elif option == "11":
                _suspend_license(service)
            elif option == "12":
                _resend_license_suspension(service)
            elif option == "13":
                _reactivate_license(service)
            elif option == "14":
                _resend_license_reactivation(service)
            elif option == "15":
                _revoke_license(service)
            elif option == "16":
                _resend_license_revocation(service)
            elif option == "17":
                _restore_revoked_license(service)
            elif option == "18":
                _resend_license_restoration(service)
            elif option == "19":
                _license_details(service)
            else:
                print("Opcao invalida.")
        except SuperadminError as error:
            print(f"Operacao nao concluida: {error}")
        _back_to_menu()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nOperacao cancelada.")
        raise SystemExit(130)
