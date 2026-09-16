"""Check the login request flow without opening a window or sending email."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote

SOURCE = Path(__file__).resolve().parents[1] / "user" / "login.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UnifiedLoginScreen")
methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {
    "_confirm_license_request_email", "_send_license_request_email", "_open_prepared_license_request_email"}]


def handlers(**overrides):
    namespace = dict(quote=quote, LICENSE_REQUEST_SUBJECT="Pedido",
                     license_request_body=lambda code: "Request " + code,
                     EmailServiceNotConfigured=LookupError)
    namespace.update(overrides)
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


def screen():
    client = Mock()
    client.pending_license_request.return_value = ("owner@example.com", "code", False)
    return SimpleNamespace(license_client=client, operation_in_progress=False, username=None,
        _send_license_request_email=Mock(), _set_license_feedback=Mock(),
        _show_license_request_fallback=Mock(), _open_prepared_license_request_email=Mock(),
        _finish_license_request_submission=Mock())


def test_request_sends_directly_without_form_or_confirmation():
    ui = screen()
    handlers()["_confirm_license_request_email"](ui)
    ui.license_client.prepare_license_request.assert_called_once_with(username="", plan="")
    ui._send_license_request_email.assert_called_once_with()


def test_missing_recipient_still_allows_copying_request():
    ui = screen()
    ui.license_client.pending_license_request.side_effect = RuntimeError("request_email_not_configured")
    ui.license_client.prepare_license_request.return_value = "prepared"
    handlers()["_confirm_license_request_email"](ui)
    ui._show_license_request_fallback.assert_called_once_with("", "prepared")
    ui._send_license_request_email.assert_not_called()


def test_smtp_failure_opens_prepared_email_without_marking_sent():
    ui = screen()
    def run(task, callback, **kwargs):
        try:
            mode = task()
        except Exception as error:
            callback(None, error)
        else:
            callback(mode, None)
    ui._run_background_task = run
    send = Mock(side_effect=RuntimeError("offline"))
    handlers(send_system_email=send)["_send_license_request_email"](ui)
    ui._open_prepared_license_request_email.assert_called_once_with("owner@example.com", "code")
    ui._finish_license_request_submission.assert_not_called()


def test_opening_mail_editor_does_not_claim_delivery():
    ui = screen()
    browser = SimpleNamespace(open=Mock(return_value=True))
    handlers(webbrowser=browser)["_open_prepared_license_request_email"](ui, "owner@example.com", "code")
    ui._finish_license_request_submission.assert_not_called()
    ui.license_client.mark_license_request_submitted.assert_not_called()
    assert "Clique em Enviar" in ui._set_license_feedback.call_args.args[0]


def test_missing_mail_application_offers_copy():
    ui = screen()
    browser = SimpleNamespace(open=Mock(return_value=False))
    handlers(webbrowser=browser)["_open_prepared_license_request_email"](ui, "owner@example.com", "code")
    ui._show_license_request_fallback.assert_called_once_with("owner@example.com", "code")


def test_selected_plan_is_forwarded_without_extra_form():
    ui = screen()
    ui._license_selected_plan = "Vitalicia"
    handlers()["_confirm_license_request_email"](ui)
    ui.license_client.prepare_license_request.assert_called_once_with(username="", plan="Vitalicia")
    ui._send_license_request_email.assert_called_once_with()
