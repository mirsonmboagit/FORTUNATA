"""Onboarding seguro para ligar o Manager Mobile a uma API SIGE MPE."""

from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivymd.uix.screen import MDScreen

from database.client import DatabaseClient
from utils.config.app_config import save_remote_connection


KV_PATH = Path(__file__).with_name("connection_screen.kv")
try:
    Builder.unload_file(str(KV_PATH))
except Exception:
    pass
Builder.load_file(str(KV_PATH))


class MobileConnectionScreen(MDScreen):
    """Ecran que testa a API antes de guardar a configuracao no telefone."""

    endpoint_field = ObjectProperty(None)
    api_key_field = ObjectProperty(None)
    connection_status = StringProperty(
        "Introduza o endereco da API e a chave criada no servidor."
    )
    status_kind = StringProperty("info")
    testing = BooleanProperty(False)

    def on_pre_enter(self, *args):
        self._prefill_endpoint()

    def _prefill_endpoint(self):
        if self.endpoint_field is None or self.endpoint_field.text.strip():
            return
        try:
            from utils.config.app_config import get_api_base_url

            endpoint = get_api_base_url(force_reload=False)
            if endpoint and endpoint not in {"http://127.0.0.1:8080", "http://localhost:8080"}:
                self.endpoint_field.text = endpoint
        except Exception:
            pass

    @staticmethod
    def _normalise_endpoint(raw_value: str) -> str:
        endpoint = str(raw_value or "").strip().rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Use um endereco completo, por exemplo https://api.exemplo.mz")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("O endereco da API nao pode incluir credenciais, consulta ou fragmento")
        return endpoint

    def test_and_continue(self):
        if self.testing:
            return

        try:
            endpoint = self._normalise_endpoint(self.endpoint_field.text if self.endpoint_field else "")
            api_key = str(self.api_key_field.text if self.api_key_field else "").strip()
            if len(api_key) < 16:
                raise ValueError("Informe a chave de API completa fornecida pelo servidor")
        except ValueError as exc:
            self.connection_status = str(exc)
            self.status_kind = "error"
            return

        self.testing = True
        self.connection_status = "A testar uma ligacao autenticada com a API…"
        self.status_kind = "info"

        def worker():
            client = DatabaseClient(
                base_url=endpoint,
                api_key=api_key,
                timeout=8,
                config={"timeout": 8, "health_timeout": 4},
            )
            try:
                return client.get_health_status(force=True, timeout=8)
            finally:
                client.close()

        def finish(result=None, error=None):
            self.testing = False
            if error:
                self.connection_status = "Nao foi possivel testar a API. Verifique a rede e tente novamente."
                self.status_kind = "error"
                return

            result = result or {}
            if not result.get("ok"):
                detail = str(result.get("error") or "API indisponivel ou chave invalida").strip()
                self.connection_status = f"Ligacao recusada: {detail}"
                self.status_kind = "error"
                return

            try:
                save_remote_connection(endpoint, api_key)
            except Exception as exc:
                self.connection_status = f"A ligacao foi testada, mas nao foi guardada: {exc}"
                self.status_kind = "error"
                return

            self.connection_status = "Ligacao segura confirmada. A abrir o inicio de sessao…"
            self.status_kind = "success"
            # A chave ja foi enviada para o armazenamento privado. Nao fica
            # visivel nem retida no widget quando o ecran for reaberto.
            if self.api_key_field is not None:
                self.api_key_field.text = ""
            app = App.get_running_app()
            apply_connection = getattr(app, "apply_mobile_connection", None) if app else None
            if callable(apply_connection):
                apply_connection()

        def run_worker():
            try:
                result = worker()
                Clock.schedule_once(lambda _dt: finish(result=result), 0)
            except Exception as exc:
                Clock.schedule_once(lambda _dt, error=exc: finish(error=error), 0)

        Thread(target=run_worker, daemon=True).start()
