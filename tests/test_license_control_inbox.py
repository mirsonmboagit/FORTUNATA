from licensing.control_inbox import (
    ControlInboxSettings,
    _apply_control_code,
    extract_control_code,
    poll_control_inbox,
)


class _Client:
    def __init__(self):
        self.received = []

    def activate(self, code):
        self.received.append(("activate", code))
        return object()

    def apply_revocation(self, code):
        self.received.append(("revocation", code))
        return object()

    def apply_suspension(self, code):
        self.received.append(("suspension", code))
        return object()

    def apply_reactivation(self, code):
        self.received.append(("reactivation", code))
        return object()

    def apply_restoration(self, code):
        self.received.append(("restoration", code))
        return object()


def test_inbox_extracts_signed_license_and_routes_it_to_automatic_activation():
    code = "SIGE-LIC1.payload.signature"
    raw_email = f"Subject: Licenca\nContent-Type: text/plain; charset=utf-8\n\n{code}".encode()

    assert extract_control_code(raw_email) == code
    client = _Client()
    _apply_control_code(client, code)

    assert client.received == [("activate", code)]


def test_inbox_routes_each_superadmin_control_code_to_its_signed_handler():
    client = _Client()
    cases = {
        "SIGE-REV1.payload.signature": "revocation",
        "SIGE-SUS1.payload.signature": "suspension",
        "SIGE-RES1.payload.signature": "reactivation",
        "SIGE-RST1.payload.signature": "restoration",
    }

    for code, expected_action in cases.items():
        _apply_control_code(client, code)
        assert client.received[-1] == (expected_action, code)


def test_control_inbox_only_scans_unread_messages():
    class Mailbox:
        searches = []

        def login(self, *_args):
            return "OK", []

        def select(self, *_args):
            return "OK", []

        def search(self, *_args):
            self.searches.append(_args)
            return "OK", [b""]

        def close(self):
            return "OK", []

        def logout(self):
            return "BYE", []

    mailbox = Mailbox()
    poll_control_inbox(
        _Client(),
        settings=ControlInboxSettings("imap.example.test", 993, "user", "password"),
        imap_factory=lambda *_args: mailbox,
    )

    assert mailbox.searches
    assert all("UNSEEN" in call for call in mailbox.searches)
