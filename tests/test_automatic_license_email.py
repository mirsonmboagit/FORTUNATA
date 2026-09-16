from __future__ import annotations

import imaplib
import socket
from email.message import EmailMessage

import pytest

from licensing.automatic_email import AutomaticEmailError, AutomaticEmailReport, poll_superadmin_once, poll_unread_requests
from licensing.offline_email import LICENSE_REQUEST_SUBJECT, gmail_settings, license_request_body
from licensing.superadmin import AutomaticEmailSettings


class MemoryProtector:
    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"protected:")
        return value[len(b"protected:") :]


class FakeMailbox:
    def __init__(self, messages):
        self.messages = dict(messages)
        self.seen = []
        self.searches = []
        self.closed = False
        self.logged_out = False

    def login(self, _email, _password):
        return "OK", [b"logged in"]

    def select(self, _mailbox):
        return "OK", [b"1"]

    def search(self, _charset, *query):
        self.searches.append(query)
        return "OK", [b" ".join(self.messages)]

    def fetch(self, message_id, _query):
        return "OK", [(b"RFC822", self.messages[message_id])]

    def store(self, message_id, _operation, _flag):
        self.seen.append(message_id)
        return "OK", [b"stored"]

    def close(self):
        self.closed = True

    def logout(self):
        self.logged_out = True


def _message(subject, body):
    message = EmailMessage()
    message["From"] = "Cliente <cliente@example.com>"
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


def test_automatic_emitter_reads_only_its_subject_and_marks_successful_request_seen(tmp_path):
    # Usa um caminho por teste para nao deixar qualquer ficheiro no repositorio.
    from datetime import datetime, timezone
    from licensing.offline import OfflineLicenseClient, OfflineLicenseIssuer, OfflineLicenseStore, generate_issuer_private_key

    issuer = OfflineLicenseIssuer(generate_issuer_private_key())
    client = OfflineLicenseClient(
        issuer.public_key,
        credential_store=OfflineLicenseStore(tmp_path / "state.dat", protector=MemoryProtector()),
        fingerprint_provider=lambda: "a" * 64,
        now_provider=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        request_recipient_email="owner@example.com",
    )
    request_code = client.activation_request()
    mailbox = FakeMailbox(
        {
            b"1": _message(LICENSE_REQUEST_SUBJECT, license_request_body(request_code)),
            b"2": _message("Outro assunto", "Nao e um pedido."),
        }
    )
    calls = []
    sent = []

    def issue_or_get(code, sender):
        calls.append((code, sender))
        return "SIGE-LIC1.teste", {
            "customer_ref": "Cliente teste",
            "plan_name": "Mensal",
            "expires_at": "2026-10-10T23:59:59+00:00",
        }, True

    def send(_settings, recipient, code, **payload):
        sent.append((recipient, code, payload))

    report = poll_unread_requests(
        gmail_email="owner@example.com",
        gmail_app_password="a" * 16,
        smtp_settings=gmail_settings("owner@example.com", "a" * 16),
        recipient_email="owner@example.com",
        issue_or_get=issue_or_get,
        imap_factory=lambda *_args: mailbox,
        send_license=send,
    )

    assert report.scanned == 1
    assert report.delivered == 1
    assert calls == [(request_code, "cliente@example.com")]
    assert sent[0][0:2] == ("owner@example.com", "SIGE-LIC1.teste")
    assert mailbox.seen == [b"1"]
    assert mailbox.searches == [(f'HEADER Subject "{LICENSE_REQUEST_SUBJECT}"',)]
    assert mailbox.closed and mailbox.logged_out


def test_automatic_emitter_keeps_request_unread_when_delivery_fails(tmp_path):
    from datetime import datetime, timezone
    from licensing.offline import OfflineLicenseClient, OfflineLicenseIssuer, OfflineLicenseStore, generate_issuer_private_key

    issuer = OfflineLicenseIssuer(generate_issuer_private_key())
    client = OfflineLicenseClient(
        issuer.public_key,
        credential_store=OfflineLicenseStore(tmp_path / "state.dat", protector=MemoryProtector()),
        fingerprint_provider=lambda: "a" * 64,
        now_provider=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        request_recipient_email="owner@example.com",
    )
    mailbox = FakeMailbox({b"1": _message(LICENSE_REQUEST_SUBJECT, license_request_body(client.activation_request()))})

    def issue_or_get(_code, _sender):
        return "SIGE-LIC1.teste", {"customer_ref": "Cliente", "plan_name": "Mensal", "expires_at": "2026-10-10"}, True

    def send_failure(*_args, **_kwargs):
        raise RuntimeError("Gmail indisponivel")

    report = poll_unread_requests(
        gmail_email="owner@example.com",
        gmail_app_password="a" * 16,
        smtp_settings=gmail_settings("owner@example.com", "a" * 16),
        recipient_email="owner@example.com",
        issue_or_get=issue_or_get,
        imap_factory=lambda *_args: mailbox,
        send_license=send_failure,
    )

    assert report.delivered == 0
    assert report.failures
    assert mailbox.seen == []


def test_automatic_emitter_processes_a_request_even_after_it_was_opened_in_gmail(tmp_path):
    from datetime import datetime, timezone
    from licensing.offline import OfflineLicenseClient, OfflineLicenseIssuer, OfflineLicenseStore, generate_issuer_private_key

    issuer = OfflineLicenseIssuer(generate_issuer_private_key())
    client = OfflineLicenseClient(
        issuer.public_key,
        credential_store=OfflineLicenseStore(tmp_path / "state.dat", protector=MemoryProtector()),
        fingerprint_provider=lambda: "a" * 64,
        now_provider=lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
        request_recipient_email="owner@example.com",
    )
    request_code = client.activation_request()
    # A caixa devolve a mensagem mesmo que ela ja esteja marcada como lida.
    mailbox = FakeMailbox({b"1": _message(LICENSE_REQUEST_SUBJECT, license_request_body(request_code))})
    delivered_ids = set()
    issued = []
    sent = []

    def issue_or_get(code, _sender):
        issued.append(code)
        return "SIGE-LIC1.teste", {"customer_ref": "Cliente", "plan_name": "Mensal", "expires_at": "2026-10-10"}, True

    def send(*_args, **_kwargs):
        sent.append(True)

    options = dict(
        gmail_email="owner@example.com",
        gmail_app_password="a" * 16,
        smtp_settings=gmail_settings("owner@example.com", "a" * 16),
        recipient_email="owner@example.com",
        issue_or_get=issue_or_get,
        was_delivered=lambda message_hash: message_hash in delivered_ids,
        mark_delivered=lambda message_hash: delivered_ids.add(message_hash),
        imap_factory=lambda *_args: mailbox,
        send_license=send,
    )

    first = poll_unread_requests(**options)
    second = poll_unread_requests(**options)

    assert first.delivered == 1
    assert second.delivered == 0
    assert issued == [request_code]
    assert sent == [True]


def test_superadmin_automatic_emitter_requires_explicit_permission_for_renewals(monkeypatch):
    settings = AutomaticEmailSettings(
        gmail_email="owner@example.com",
        gmail_app_password="a" * 16,
        recipient_email="owner@example.com",
        customer_ref="Cliente por e-mail",
        plan_name="Mensal",
        months=1,
        duration_amount=1,
        duration_unit="months",
        auto_renewals=False,
        poll_seconds=60,
    )
    calls = []

    class Service:
        def automatic_email_settings(self):
            return settings

        def issue_or_get_license(self, request_code, **kwargs):
            calls.append((request_code, kwargs))
            return "SIGE-LIC1.teste", {"customer_ref": "Cliente", "plan_name": "Mensal", "expires_at": "2026-10-10"}, True

        def automatic_email_message_was_delivered(self, _message_hash):
            return False

        def mark_automatic_email_message_delivered(self, _message_hash):
            return None

    def fake_poll(**kwargs):
        kwargs["issue_or_get"]("SIGE-REQ1.teste", "cliente@example.com")
        return AutomaticEmailReport()

    monkeypatch.setattr("licensing.automatic_email.poll_unread_requests", fake_poll)
    assert isinstance(poll_superadmin_once(Service()), AutomaticEmailReport)
    assert calls[0][1]["duration_amount"] == 1
    assert calls[0][1]["duration_unit"] == "months"
    assert calls[0][1]["allow_renewal"] is False


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (
            lambda *_args: (_ for _ in ()).throw(
                imaplib.IMAP4.error("[ALERT] Application-specific password required")
            ),
            "palavra-passe de aplicacao",
        ),
        (
            lambda *_args: (_ for _ in ()).throw(socket.gaierror("sem rede")),
            "imap.gmail.com na porta 993",
        ),
    ],
)
def test_automatic_emitter_explains_gmail_failures_without_raw_error(factory, expected):
    with pytest.raises(AutomaticEmailError, match=expected):
        poll_unread_requests(
            gmail_email="owner@example.com",
            gmail_app_password="a" * 16,
            smtp_settings=gmail_settings("owner@example.com", "a" * 16),
            recipient_email="owner@example.com",
            issue_or_get=lambda *_args: ("unused", {}, True),
            imap_factory=factory,
        )
