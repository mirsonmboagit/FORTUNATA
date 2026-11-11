"""Interface grafica local para gerir administradores e licencas offline."""

from __future__ import annotations

import sys
import subprocess
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from licensing.superadmin import LocalSuperadmin, SuperadminError


BG = (0.055, 0.075, 0.060, 1)
SURFACE = (0.095, 0.125, 0.100, 1)
SURFACE_ALT = (0.125, 0.160, 0.125, 1)
ACCENT = (0.56, 0.72, 0.38, 1)
TEXT = (0.93, 0.94, 0.89, 1)
MUTED = (0.68, 0.72, 0.65, 1)
DANGER = (0.80, 0.35, 0.30, 1)


class SuperadminApp(App):
    title = "SIGE · Superadmin"

    def build(self):
        Window.minimum_width, Window.minimum_height = dp(900), dp(580)
        Window.clearcolor = BG
        self.service = LocalSuperadmin()
        self.root_layout = BoxLayout(orientation="vertical", padding=dp(28), spacing=dp(16))
        self.show_access()
        return self.root_layout

    def clear(self):
        self.root_layout.clear_widgets()

    def label(self, text, *, size=14, color=TEXT, height=None, bold=False):
        widget = Label(text=text, color=color, font_size=dp(size), bold=bold, halign="left", valign="middle")
        widget.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        if height:
            widget.size_hint_y = None
            widget.height = dp(height)
        return widget

    def button(self, text, callback, *, primary=False, width=None):
        widget = Button(text=text, font_size=dp(13), background_normal="", background_down="")
        widget.background_color = ACCENT if primary else SURFACE_ALT
        widget.color = (0.06, 0.08, 0.05, 1) if primary else TEXT
        if width:
            widget.size_hint_x = None
            widget.width = dp(width)
        widget.bind(on_release=callback)
        return widget

    def input(self, hint, value="", *, password=False):
        return TextInput(text=value, hint_text=hint, multiline=False, password=password, font_size=dp(14),
                         foreground_color=TEXT, hint_text_color=MUTED, background_color=SURFACE_ALT,
                         padding=[dp(12), dp(10)])

    def spinner(self, value, values):
        return Spinner(text=value, values=values, font_size=dp(14), color=TEXT,
                       background_normal="", background_down="", background_color=SURFACE_ALT,
                       size_hint_y=None, height=dp(52))

    def show_access(self):
        self.clear()
        self.root_layout.add_widget(self.label("SIGE", size=28, color=ACCENT, height=48, bold=True))
        self.root_layout.add_widget(self.label("Painel local do superadmin", size=21, height=36, bold=True))
        self.root_layout.add_widget(self.label(
            "Gestão visual de administradores, contas e licenças.",
            size=14, color=MUTED, height=44))
        card = BoxLayout(orientation="vertical", size_hint=(0.62, None), height=dp(280), pos_hint={"center_x": .5},
                         padding=dp(22), spacing=dp(12))
        self.access_password = self.input("Palavra-passe do superadmin", password=True)
        card.add_widget(self.access_password)
        if not self.service.initialized():
            self.access_confirmation = self.input("Repita a palavra-passe (mínimo 16 caracteres)", password=True)
            card.add_widget(self.access_confirmation)
            card.add_widget(self.button("CRIAR PAINEL SUPERADMIN", self.bootstrap, primary=True))
        else:
            card.add_widget(self.button("ENTRAR NO PAINEL", self.authenticate, primary=True))
        self.root_layout.add_widget(card)
        self.root_layout.add_widget(Label())

    def bootstrap(self, *_args):
        if self.access_password.text != self.access_confirmation.text:
            return self.message("Confirmação", "As palavras-passe não coincidem.")
        try:
            self.service.bootstrap(self.access_password.text)
            self.service.configure_desktop_public_key()
        except SuperadminError as error:
            return self.message("Não foi possível criar", str(error))
        self.show_dashboard()

    def authenticate(self, *_args):
        if not self.service.authenticate(self.access_password.text):
            return self.message("Acesso negado", "Palavra-passe inválida.")
        self.show_dashboard()

    def show_dashboard(self):
        self.clear()
        header = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(12))
        header.add_widget(self.label("SIGE · Superadmin", size=23, color=ACCENT, bold=True))
        header.add_widget(self.button("ATUALIZAR", lambda *_: self.show_dashboard(), width=120))
        header.add_widget(self.button("SAIR", lambda *_: self.show_access(), width=90))
        self.root_layout.add_widget(header)
        self.root_layout.add_widget(self.label("Administre as contas e licenças num único lugar. A emissão é tratada automaticamente pelo emissor configurado.", size=13, color=MUTED, height=28))

        licenses = self.service.list_licenses()
        admins = self.service.list_admin_provisionings()
        active = sum(1 for row in licenses if row.get("license_status", "ativa") == "ativa")
        metrics = BoxLayout(size_hint_y=None, height=dp(90), spacing=dp(12))
        for value, title in ((len(admins), "Administradores"), (len(licenses), "Licenças"), (active, "Licenças ativas")):
            card = BoxLayout(orientation="vertical", padding=dp(12))
            card.add_widget(self.label(str(value), size=26, color=ACCENT, bold=True))
            card.add_widget(self.label(title, size=12, color=MUTED))
            metrics.add_widget(card)
        self.root_layout.add_widget(metrics)

        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        actions.add_widget(self.button("CONFIGURAR E-MAIL", self.configure_recipient, primary=True))
        actions.add_widget(self.button("OBTER SENHA GMAIL", self.open_google_app_passwords))
        actions.add_widget(self.button("CONFIGURAR EMISSOR", self.configure_emitter))
        actions.add_widget(self.button("INICIAR EMISSOR", self.start_emitter))
        self.root_layout.add_widget(actions)

        self.root_layout.add_widget(self.label("Administradores, contas e licenças", size=17, height=30, bold=True))
        self.root_layout.add_widget(self.build_table(licenses, admins))

    def build_table(self, licenses, admins):
        owners = {str(row.get("license_id")): row for row in admins if row.get("status") != "replaced"}
        grid = GridLayout(cols=6, size_hint_y=None, row_default_height=dp(40), row_force_default=True,
                          spacing=dp(1), padding=dp(1))
        grid.bind(minimum_height=grid.setter("height"))
        headers = ("Referência", "Administrador", "E-mail", "Plano", "Validade", "Estado")
        for title in headers:
            grid.add_widget(self.table_cell(title, header=True))
        for license_row in licenses:
            owner = owners.get(str(license_row.get("license_id")), {})
            values = (
                license_row.get("license_reference") or "-",
                owner.get("username") or "Sem conta",
                owner.get("email") or "-",
                license_row.get("plan_name") or "-",
                str(license_row.get("expires_at") or "-").replace("T", " ")[:16],
                license_row.get("license_status") or "ativa",
            )
            for value in values:
                grid.add_widget(self.table_cell(str(value)))
        if not licenses:
            grid.add_widget(self.table_cell("Ainda não existem licenças. Configure o emissor e aguarde um pedido do login.", span=True))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(grid)
        return scroll

    def table_cell(self, text, *, header=False, span=False):
        label = self.label(text, size=12, color=ACCENT if header else TEXT, bold=header)
        label.text_size = (None, None)
        label.halign, label.valign = "center", "middle"
        label.padding = [dp(8), 0]
        if span:
            label.size_hint_x = None
            label.width = dp(900)
        return label

    def popup_form(self, title, fields, submit_text, callback):
        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(18))
        widgets = {}
        for field in fields:
            key, hint, value = field[:3]
            widgets[key] = self.spinner(value, field[3]) if len(field) == 4 else self.input(hint, value)
            content.add_widget(widgets[key])
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        popup = Popup(title=title, content=content, size_hint=(.58, None), height=dp(420), auto_dismiss=False)
        buttons.add_widget(self.button("CANCELAR", lambda *_: popup.dismiss()))
        buttons.add_widget(self.button(submit_text, lambda *_: callback(widgets, popup), primary=True))
        content.add_widget(buttons)
        popup.open()

    def configure_recipient(self, *_args):
        self.popup_form("E-mail de entrega", [("email", "E-mail que recebe pedidos e licenças", self.service.license_recipient_email())], "GUARDAR", self.save_recipient)

    def save_recipient(self, fields, popup):
        try:
            self.service.set_license_recipient_email(fields["email"].text)
        except SuperadminError as error:
            return self.message("E-mail inválido", str(error))
        popup.dismiss(); self.show_dashboard()

    def configure_emitter(self, *_args):
        status = self.service.automatic_email_status()
        validity_options = (
            "7 dias", "15 dias", "30 dias", "1 mês", "3 meses",
            "6 meses", "1 ano", "Vitalícia",
        )
        current_validity = status.get("duration_label", "1 mês")
        if current_validity not in validity_options:
            current_validity = "1 mês"
        self.popup_form("Entrega automática", [
            ("password", "Palavra-passe de aplicação Gmail (visível)", ""),
            ("plan", "Nome do plano", status.get("plan_name", "Mensal")),
            ("duration", "Selecione a validade", current_validity, validity_options),
        ], "ATIVAR EMISSOR", self.save_emitter)

    def open_google_app_passwords(self, *_args):
        """Abre o fluxo oficial que exige autenticacao da propria conta Gmail."""
        opened = webbrowser.open("https://myaccount.google.com/apppasswords")
        if opened:
            self.message(
                "Criar palavra-passe Gmail",
                "Foi aberta a página do Google. Ative a verificação em duas etapas, crie uma palavra-passe de aplicação e cole os 16 caracteres em CONFIGURAR EMISSOR.",
            )
        else:
            self.message(
                "Criar palavra-passe Gmail",
                "Abra myaccount.google.com/apppasswords no navegador, crie a palavra-passe de aplicação e cole-a em CONFIGURAR EMISSOR.",
            )

    def start_emitter(self, *_args):
        if not self.service.automatic_email_status().get("configured"):
            return self.message("Emissor não configurado", "Configure primeiro o e-mail e a entrega automática.")
        script = PROJECT_ROOT / "scripts" / "emissor_licencas_automatico.py"
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=str(PROJECT_ROOT),
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except OSError as error:
            return self.message("Emissor", f"Não foi possível iniciar: {error}")
        self.message("Emissor iniciado", "A janela de entrega automática foi aberta. Deixe-a em execução para processar pedidos.")

    def save_emitter(self, fields, popup):
        try:
            self.service.configure_automatic_email(fields["password"].text, plan_name=fields["plan"].text,
                                                   duration_amount=fields["duration"].text)
        except (SuperadminError, ValueError) as error:
            return self.message("Emissor", str(error))
        popup.dismiss(); self.show_dashboard()

    def create_admin(self, *_args):
        licenses = self.service.list_licenses()
        if not licenses:
            return self.message("Sem licença", "Aguarde a emissão automática da primeira licença antes de criar a conta do administrador.")
        choices = ", ".join(str(row.get("license_reference")) for row in licenses)
        self.popup_form("Criar administrador", [
            ("license", f"Referência da licença: {choices}", ""),
            ("username", "Nome de utilizador", ""),
            ("email", "E-mail do administrador (opcional)", ""),
            ("password", "Palavra-passe temporária (visível, mínimo 12)", ""),
        ], "CRIAR CONTA", self.save_admin)

    def save_admin(self, fields, popup):
        try:
            license_id = self.service.resolve_license_identifier(fields["license"].text)
            self.service.issue_or_get_admin_provisioning(license_id, username=fields["username"].text,
                                                         email=fields["email"].text or None,
                                                         temporary_password=fields["password"].text)
        except SuperadminError as error:
            return self.message("Conta", str(error))
        popup.dismiss(); self.show_dashboard(); self.message("Conta criada", "A conta do administrador foi preparada para a licença selecionada.")

    def message(self, title, text):
        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(14))
        content.add_widget(self.label(text, size=14))
        popup = Popup(title=title, content=content, size_hint=(.5, None), height=dp(220))
        content.add_widget(self.button("FECHAR", lambda *_: popup.dismiss(), primary=True))
        popup.open()


if __name__ == "__main__":
    SuperadminApp().run()
