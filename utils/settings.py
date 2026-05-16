import sqlite3
import os
import json
from collections import Counter
from datetime import datetime
from threading import Thread
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDRectangleFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.card import MDCard
from kivymd.uix.list import TwoLineListItem, OneLineListItem
from kivymd.uix.selectioncontrol import MDCheckbox, MDSwitch
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.progressbar import MDProgressBar
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.app import App
from kivy.animation import Animation
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from database.provider import get_db, uses_remote_backend
from AI.controller import ProactiveIntelligenceController
from ui.components.hover_widgets import HoverCard, HoverRaisedButton
from ui.components.loading_overlay import ScreenLoadingController
from utils.device_config import get_device_settings, save_device_settings
from utils.env_loader import load_dotenv
from utils.focus_navigation import FormKeyboardController
from utils.i18n import language_label, language_options, normalize_language, translate
from utils.paths import APP_SETTINGS_FILE, ENV_FILE
from utils.thermal_printer import (
    get_default_printer_name,
    list_system_printers,
    print_thermal_receipt,
)
from kivy.lang import Builder
from utils.security_questions import QUESTIONS
from utils.vat import VAT_RULES, DEFAULT_VAT_RULE_CODE, describe_vat_choice


def _get_logs_report_class():
    from pdfs.logs_report import LogsReport
    return LogsReport


def _describe_loader_error(exc, prefix):
    missing_name = getattr(exc, "name", "")
    if missing_name:
        return f"{prefix}: dependencia em falta ({missing_name})"
    text = str(exc or "").strip()
    if not text:
        text = exc.__class__.__name__
    return f"{prefix}: {text}"


def _build_unavailable_api_manager_class(error):
    message = _describe_loader_error(error, "APIManager indisponivel")

    class UnavailableAPIManager:
        def __init__(self, *args, **kwargs):
            self.is_loading = False

        @staticmethod
        def _stats(**extra):
            stats = {
                "total": 0,
                "processed": 0,
                "success": 0,
                "new": 0,
                "updated": 0,
                "no_sku": 0,
                "no_barcode": 0,
                "found": 0,
                "moved": 0,
                "skipped": 0,
                "errors": 1,
                "message": message,
            }
            stats.update(extra)
            return stats

        def prefill_ranxo_cache(self, on_progress=None, delay=0.2):
            stats = self._stats()
            if callable(on_progress):
                on_progress(dict(stats))
            return stats

        def prefill_bazara_offline_cache(self, on_progress=None, delay=0.2, reset=False):
            stats = self._stats(pages=0)
            if callable(on_progress):
                on_progress(dict(stats))
            return stats

        def backfill_bazara_barcodes(self, on_progress=None, delay=0.2, limit=None):
            stats = self._stats()
            if callable(on_progress):
                on_progress(dict(stats))
            return stats

        def refresh_offline_cache_from_apis(self, source_names=None, on_progress=None, delay=0.2):
            stats = self._stats()
            if callable(on_progress):
                on_progress(dict(stats))
            return stats

        def prefill_openfoodfacts_cache(self, on_progress=None, delay=0.2):
            stats = self._stats()
            if callable(on_progress):
                on_progress(dict(stats))
            return stats

    return UnavailableAPIManager


def _get_api_manager_class():
    try:
        from api.api_manager import APIManager
        return APIManager
    except Exception as exc:
        return _build_unavailable_api_manager_class(exc)


Builder.load_file(os.path.join(os.path.dirname(__file__), "settings_layout.kv"))


class ChangeAdminDataDialog:
    # Dialogo para alterar credenciais do administrador.
    def __init__(self):
        self.dialog = None
        self._field_navigation = None

    def _audit_event(self, username, role, action, details):
        actor = str(username or "").strip() or "desconhecido"
        actor_role = str(role or "").strip() or "guest"
        try:
            with get_db() as db:
                db.log_action(actor, actor_role, action, details)
        except Exception:
            pass

    def show(self):
        app = App.get_running_app()
        session_user = (getattr(app, 'current_user', None) or '').strip() if app else ''
        session_role = (getattr(app, 'current_role', None) or '').strip() if app else ''

        if session_role and session_role != 'admin':
            self._audit_event(
                session_user,
                session_role,
                'ACCESS_DENIED',
                'Tentativa de abrir a alteracao de credenciais do administrador sem privilegio admin',
            )
            self.show_message('Erro', 'Apenas administrador pode alterar estes dados')
            return

        if not self.dialog:
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(20),
                adaptive_height=True
            )

            content.add_widget(MDLabel(
                text='Atualize suas credenciais de acesso',
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(30)
            ))

            self.current_username = MDTextField(
                hint_text='Usuario Atual',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.current_username)

            self.new_username = MDTextField(
                hint_text='Novo Usuario (opcional)',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.new_username)

            self.current_password = MDTextField(
                hint_text='Senha Atual',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.current_password)

            self.new_password = MDTextField(
                hint_text='Nova Senha (opcional)',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.new_password)

            self.confirm_password = MDTextField(
                hint_text='Confirmar Nova Senha',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.confirm_password)

            self.dialog = MDDialog(
                title='Alterar Dados do Administrador',
                type='custom',
                content_cls=content,
                buttons=[
                    MDFlatButton(
                        text='CANCELAR',
                        on_release=self.dismiss
                    ),
                    MDRaisedButton(
                        text='SALVAR',
                        on_release=self.save_changes
                    )
                ]
            )
            self._field_navigation = FormKeyboardController(
                host=self.dialog,
                fields=[
                    self.current_username,
                    self.new_username,
                    self.current_password,
                    self.new_password,
                    self.confirm_password,
                ],
                initial_field=lambda: self.new_username if self.current_username.readonly else self.current_username,
                on_escape=self.dismiss,
                on_submit=self.save_changes,
                shortcuts={"ctrl+s": self.save_changes},
            )
            self.dialog.bind(on_pre_open=lambda *_: self._field_navigation.activate(focus_initial=True))
            self.dialog.bind(on_dismiss=self._field_navigation.deactivate)

        # Abre sempre com o usuario logado e campos sensiveis limpos.
        self.current_username.text = session_user
        self.current_username.readonly = bool(session_user)
        self.new_username.text = ''
        self.current_password.text = ''
        self.new_password.text = ''
        self.confirm_password.text = ''

        self.dialog.open()

    def dismiss(self, *args):
        self.dialog.dismiss()

    def save_changes(self, *args):
        app = App.get_running_app()
        session_user = (getattr(app, 'current_user', None) or '').strip() if app else ''

        current_username = session_user or self.current_username.text.strip()
        new_username = self.new_username.text.strip()
        current_password = self.current_password.text.strip()
        new_password = self.new_password.text.strip()
        confirm_password = self.confirm_password.text.strip()

        if not current_username or not current_password:
            self.show_message('Erro', 'Preencha usuario e senha atuais')
            return

        if new_username and new_username == current_username:
            new_username = ''

        if confirm_password and not new_password:
            self.show_message('Erro', 'Informe a nova senha para confirmar')
            return

        if new_password and new_password != confirm_password:
            self.show_message('Erro', 'As senhas nao coincidem')
            return

        if not new_username and not new_password:
            self.show_message('Erro', 'Nenhuma alteracao solicitada')
            return

        try:
            with get_db() as db:
                current_role = db.get_user_role(current_username)
                if current_role != 'admin':
                    self._audit_event(
                        current_username,
                        current_role,
                        'ACCESS_DENIED',
                        'Tentativa de alterar credenciais de administrador com utilizador invalido ou sem privilegio admin',
                    )
                    self.show_message('Erro', 'Usuario nao encontrado ou nao e administrador')
                    return

                role = db.validate_user(current_username, current_password)
                if role != 'admin':
                    self._audit_event(
                        current_username,
                        current_role,
                        'ACCESS_ATTEMPT',
                        'Tentativa de alterar credenciais de administrador com senha atual incorreta',
                    )
                    self.show_message('Erro', 'Senha atual incorreta')
                    return

                if new_username and db.user_exists(new_username, exclude_username=current_username):
                    self.show_message('Erro', 'Este nome de usuario ja esta em uso')
                    return

                if not db.update_admin_profile(
                    current_username,
                    new_username=new_username or None,
                    new_password=new_password or None,
                ):
                    self.show_message('Erro', 'Nao foi possivel atualizar os dados')
                    return

                updated_username = new_username if new_username else current_username

                db.log_action(
                    updated_username,
                    'admin',
                    'UPDATE_ADMIN',
                    'Dados do admin atualizados'
                )

                if app:
                    app.current_user = updated_username
                    app.current_role = 'admin'
                    app._ai_notifications_seen_key = None
                    app._ai_banners_shown = False

                self.show_message('Sucesso', 'Dados atualizados com sucesso!')
                self.dialog.dismiss()

        except sqlite3.IntegrityError:
            self.show_message('Erro', 'Nome de usuario ja existe')
        except Exception as e:
            self.show_message('Erro', f'Erro ao atualizar: {str(e)}')

    def show_message(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK')]
        )
        dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())
        dialog.open()


class AddUserDialog:
    # Dialogo para criar utilizadores e definir o escopo dos dados.
    def __init__(self):
        self.dialog = None
        self.db = get_db()
        self._field_navigation = None
        self.selected_data_scope = "own"

    def _active_db(self):
        app = App.get_running_app()
        return getattr(app, "db", None) or self.db

    def _current_data_owner(self):
        app = App.get_running_app()
        session_user = (getattr(app, "current_user", None) or "").strip() if app else ""
        db = self._active_db()
        if session_user:
            getter = getattr(db, "get_user_data_owner", None)
            if callable(getter):
                try:
                    owner = getter(session_user)
                    if owner:
                        return owner
                except Exception:
                    pass
            return session_user
        try:
            admins = db.get_admin_usernames()
            if admins:
                return admins[0]
        except Exception:
            pass
        return ""
        
    def show(self):
        if not self.dialog:
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(20),
                adaptive_height=True
            )
            
            content.add_widget(MDLabel(
                text='Preencha os dados do novo usuário',
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(30)
            ))
            
            self.username = MDTextField(
                hint_text='Nome de Usuário',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.username)

            self.email = MDTextField(
                hint_text='Email (opcional)',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.email)

            self.password = MDTextField(
                hint_text='Senha',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.password)

            role_box = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(56)
            )

            role_box.add_widget(MDLabel(
                text='Função:',
                size_hint_x=0.3
            ))

            self.role_admin_btn = MDRectangleFlatButton(
                text='Admin',
                size_hint_x=0.35,
                on_release=lambda x: self.select_role('admin')
            )
            self.role_manager_btn = MDRectangleFlatButton(
                text='Manager',
                size_hint_x=0.35,
                on_release=lambda x: self.select_role('manager')
            )

            role_box.add_widget(self.role_admin_btn)
            role_box.add_widget(self.role_manager_btn)
            content.add_widget(role_box)

            self.selected_role = None

            access_box = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(56)
            )
            access_box.add_widget(MDLabel(
                text='Dados:',
                size_hint_x=0.3
            ))
            self.access_own_btn = MDRectangleFlatButton(
                text='Proprios',
                size_hint_x=0.35,
                on_release=lambda x: self.select_data_scope('own')
            )
            self.access_shared_btn = MDRectangleFlatButton(
                text='Loja atual',
                size_hint_x=0.35,
                on_release=lambda x: self.select_data_scope('shared')
            )
            access_box.add_widget(self.access_own_btn)
            access_box.add_widget(self.access_shared_btn)
            content.add_widget(access_box)
            self.select_data_scope('own')
            
            self.dialog = MDDialog(
                title='Adicionar Novo Usuário',
                type='custom',
                content_cls=content,
                buttons=[
                    MDFlatButton(
                        text='CANCELAR',
                        on_release=self.dismiss
                    ),
                    MDRaisedButton(
                        text='CRIAR',
                        on_release=self.save_user
                    )
                ]
            )
            self._field_navigation = FormKeyboardController(
                host=self.dialog,
                fields=[self.username, self.email, self.password],
                initial_field=self.username,
                on_escape=self.dismiss,
                on_submit=self.save_user,
                shortcuts={
                    "ctrl+s": self.save_user,
                    "alt+a": lambda: self.select_role('admin'),
                    "alt+m": lambda: self.select_role('manager'),
                },
            )
            self.dialog.bind(on_pre_open=lambda *_: self._field_navigation.activate(focus_initial=True))
            self.dialog.bind(on_dismiss=self._field_navigation.deactivate)

        self._reset_form_defaults()
        self.dialog.open()

    def _reset_form_defaults(self):
        for field in (getattr(self, "username", None), getattr(self, "email", None), getattr(self, "password", None)):
            if field is not None:
                field.text = ""
        self.select_role("manager")
        self.select_data_scope("own")
    
    def select_role(self, role):
        self.selected_role = role
        if role == 'admin':
            self.role_admin_btn.md_bg_color = (0.2, 0.5, 0.8, 1)
            self.role_admin_btn.text_color = (1, 1, 1, 1)
            self.role_manager_btn.md_bg_color = (0, 0, 0, 0)
            self.role_manager_btn.text_color = (0, 0, 0, 1)
        else:
            self.role_manager_btn.md_bg_color = (0.2, 0.5, 0.8, 1)
            self.role_manager_btn.text_color = (1, 1, 1, 1)
            self.role_admin_btn.md_bg_color = (0, 0, 0, 0)
            self.role_admin_btn.text_color = (0, 0, 0, 1)

    def select_data_scope(self, scope):
        self.selected_data_scope = scope if scope in ("own", "shared") else "own"
        own_selected = self.selected_data_scope == "own"
        self.access_own_btn.md_bg_color = (0.2, 0.5, 0.8, 1) if own_selected else (0, 0, 0, 0)
        self.access_own_btn.text_color = (1, 1, 1, 1) if own_selected else (0, 0, 0, 1)
        self.access_shared_btn.md_bg_color = (0.2, 0.5, 0.8, 1) if not own_selected else (0, 0, 0, 0)
        self.access_shared_btn.text_color = (1, 1, 1, 1) if not own_selected else (0, 0, 0, 1)
    
    def dismiss(self, *args):
        self.dialog.dismiss()
    
    def save_user(self, *args):
        username = self.username.text.strip()
        password = self.password.text.strip()
        email = self.email.text.strip() if hasattr(self, "email") else ""
        
        if not username or not password or not self.selected_role:
            self.show_message('Erro', 'Todos os campos são obrigatórios')
            return

        if len(password) < 4:
            self.show_message('Erro', 'A senha deve ter no minimo 4 caracteres')
            return

        db = self._active_db()
        if db.user_exists(username):
            self.show_message('Erro', 'Nome de usuário já existe')
            return

        email_value = email if email else None
        data_owner = None if self.selected_data_scope == "own" else self._current_data_owner()
        if self.selected_data_scope == "shared" and not data_owner:
            self.show_message('Erro', 'Nao foi possivel identificar a loja atual')
            return

        try:
            create_kwargs = {"email": email_value}
            if data_owner:
                create_kwargs["data_owner"] = data_owner
            if not db.create_user(username, password, self.selected_role, **create_kwargs):
                self.show_message('Erro', 'Não foi possível criar o usuário')
                return

            scope_label = "dados proprios" if not data_owner else f"dados de {data_owner}"
            db.log_action(
                username,
                self.selected_role,
                'CREATE_USER',
                f'Novo usuário criado: {username} ({self.selected_role})'
            )

            self.show_message('Sucesso', f'Usuário "{username}" criado com sucesso!')
            self.dialog.dismiss()

        except Exception as e:
            self.show_message('Erro', f'Erro ao adicionar: {str(e)}')
    
    def show_message(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK')]
        )
        dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())
        dialog.open()


class SecurityQuestionsDialog:
    # Dialogo para configurar perguntas de recuperacao de senha.
    def __init__(self):
        self.dialog = None
        self.db = get_db()
        self._field_navigation = None

    def show(self):
        if not self.dialog:
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(20),
                adaptive_height=True
            )

            content.add_widget(MDLabel(
                text='Configurar perguntas de recuperacao',
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(30)
            ))

            self.username = MDTextField(
                hint_text='Nome de usuario',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.username)

            self.answer_fields = []
            for question in QUESTIONS:
                content.add_widget(MDLabel(
                    text=question,
                    theme_text_color='Secondary',
                    size_hint_y=None,
                    height=dp(24)
                ))
                field = MDTextField(
                    hint_text='Resposta',
                    password=True,
                    mode='rectangle',
                    size_hint_y=None,
                    height=dp(56)
                )
                self.answer_fields.append(field)
                content.add_widget(field)

            self.dialog = MDDialog(
                title='Perguntas de Recuperacao',
                type='custom',
                content_cls=content,
                size_hint=(0.9, None),
                height=dp(560),
                buttons=[
                    MDFlatButton(
                        text='CANCELAR',
                        on_release=self.dismiss
                    ),
                    MDRaisedButton(
                        text='SALVAR',
                        on_release=self.save_answers
                    )
                ]
            )
            self._field_navigation = FormKeyboardController(
                host=self.dialog,
                fields=[self.username, *self.answer_fields],
                initial_field=self.username,
                on_escape=self.dismiss,
                on_submit=self.save_answers,
                shortcuts={"ctrl+s": self.save_answers},
            )
            self.dialog.bind(on_pre_open=lambda *_: self._field_navigation.activate(focus_initial=True))
            self.dialog.bind(on_dismiss=self._field_navigation.deactivate)

        self.dialog.open()

    def dismiss(self, *args):
        self.dialog.dismiss()

    def save_answers(self, *args):
        username = self.username.text.strip()
        answers = [field.text.strip() for field in self.answer_fields]

        if not username or any(not ans for ans in answers):
            self.show_message('Erro', 'Preencha usuario e todas as respostas')
            return

        try:
            if not self.db.user_exists(username):
                self.show_message('Erro', 'Usuario nao encontrado')
                return

            if not self.db.set_security_questions(username, answers):
                self.show_message('Erro', 'Erro ao salvar perguntas')
                return

            app = App.get_running_app()
            actor = getattr(app, 'current_user', None) or username
            role = getattr(app, 'current_role', None) or 'admin'
            self.db.log_action(
                actor,
                role,
                'UPDATE_SECURITY_QUESTIONS',
                f'Perguntas de recuperacao atualizadas para {username}'
            )

            self.show_message('Sucesso', 'Perguntas de recuperacao atualizadas!')
            self.dialog.dismiss()
        except Exception as e:
            self.show_message('Erro', f'Erro ao salvar: {str(e)}')

    def show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())]
        ).open()
class DeleteManagerDialog:
    # Dialogo para remover contas de gerente.
    def __init__(self):
        self.dialog = None
        
    def show(self):
        with get_db() as db:
            self.managers = db.get_all_managers()
        
        if not self.dialog:
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(20),
                adaptive_height=True
            )
            
            content.add_widget(MDLabel(
                text='Atenção: Esta ação não pode ser desfeita',
                theme_text_color='Error',
                size_hint_y=None,
                height=dp(30),
                bold=True
            ))
            
            self.manager_list = MDBoxLayout(
                orientation='vertical',
                spacing=dp(8),
                adaptive_height=True
            )
            
            self.selected_manager = None
            
            for manager in self.managers:
                item = OneLineListItem(
                    text=manager,
                    on_release=lambda x, m=manager: self.select_manager(m)
                )
                self.manager_list.add_widget(item)
            
            content.add_widget(self.manager_list)
            
            if len(self.managers) == 1:
                confirm_box = MDBoxLayout(
                    orientation='horizontal',
                    spacing=dp(10),
                    size_hint_y=None,
                    height=dp(40)
                )
                
                self.confirm_checkbox = MDCheckbox(size_hint_x=None, width=dp(30))
                confirm_box.add_widget(self.confirm_checkbox)
                confirm_box.add_widget(MDLabel(
                    text='Confirmo a exclusão do último gerente',
                    theme_text_color='Error'
                ))
                
                content.add_widget(confirm_box)
            else:
                self.confirm_checkbox = None
            
            self.dialog = MDDialog(
                title='Excluir Gerente',
                type='custom',
                content_cls=content,
                buttons=[
                    MDFlatButton(
                        text='CANCELAR',
                        on_release=self.dismiss
                    ),
                    MDRaisedButton(
                        text='EXCLUIR',
                        md_bg_color=(0.9, 0.3, 0.3, 1),
                        on_release=self.delete_manager
                    )
                ]
            )
        
        self.dialog.open()
    
    def select_manager(self, manager):
        self.selected_manager = manager
    
    def dismiss(self, *args):
        self.dialog.dismiss()
    
    def delete_manager(self, *args):
        if not self.selected_manager:
            self.show_message('Erro', 'Selecione um gerente')
            return
        
        is_last = len(self.managers) == 1
        if is_last and self.confirm_checkbox and not self.confirm_checkbox.active:
            self.show_message('Erro', 'Marque a confirmação')
            return
        
        try:
            with get_db() as db:
                success, msg = db.delete_manager(self.selected_manager)
                if not success:
                    self.show_message('Erro', msg)
                    return

                db.log_action(
                    'admin',
                    'admin',
                    'DELETE_USER',
                    f'Gerente excluído: {self.selected_manager}'
                )

                self.show_message('Sucesso', f'Gerente "{self.selected_manager}" excluído!')
                self.dialog.dismiss()
        
        except Exception as e:
            self.show_message('Erro', f'Erro: {str(e)}')
    
    def show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())]
        ).open()


class SystemLogsDialog:
    # Dialogo simples para consultar e exportar logs.
    def __init__(self):
        self.dialog = None
        self.search_btn = None
        self.export_btn = None
        self.clear_btn = None
        self._loading_logs = False
        self._exporting_logs = False
        self._action_labels = {
            "LOGIN": "Login realizado",
            "LOGOUT": "Logout realizado",
            "CREATE_USER": "Usuário criado",
            "DELETE_USER": "Usuário removido",
            "UPDATE_ADMIN": "Dados do admin atualizados",
            "ADD_PRODUCT": "Produto adicionado",
            "UPDATE_PRODUCT": "Produto atualizado",
            "DELETE_PRODUCT": "Produto removido",
            "SALE": "Venda registrada",
            "CANCEL_SALE": "Venda cancelada",
            "SAVE_RECEIPT": "Recibo salvo",
            "REGISTER_LOSS": "Perda registrada",
            "APPROVE_LOSS": "Perda aprovada",
        }
        
    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    def _tone_color(self, tone):
        tokens = self._theme_tokens()
        return tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))

    def _style_text_field(self, field):
        tokens = self._theme_tokens()
        field.text_color_normal = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
        field.text_color_focus = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
        field.fill_color_normal = tokens.get("card", [1, 1, 1, 1])
        field.fill_color_focus = tokens.get("card", [1, 1, 1, 1])
        field.line_color_normal = tokens.get("divider", [0, 0, 0, 0.12])
        field.line_color_focus = tokens.get("primary", [0.10, 0.35, 0.65, 1])
        field.hint_text_color_normal = tokens.get("text_muted", [0.55, 0.60, 0.70, 1])
        field.hint_text_color_focus = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])

    def _make_label(self, text="", *, font_style="Body1", color=None, bold=False, halign="left", markup=False):
        tokens = self._theme_tokens()
        label = MDLabel(
            text=text,
            font_style=font_style,
            bold=bold,
            halign=halign,
            markup=markup,
            size_hint_y=None,
            theme_text_color="Custom",
            text_color=color or tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
        )
        label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", max(size[1], dp(20))),
        )
        return label

    def _build_state_label(self, text, tone="text_secondary"):
        tokens = self._theme_tokens()
        return self._make_label(
            text,
            font_style="Body2",
            color=tokens.get(tone, tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])),
            halign="center",
        )

    def _action_style(self, action):
        styles = {
            "LOGIN": ("login", "success"),
            "LOGOUT": ("logout", "warning"),
            "CREATE_USER": ("account-plus", "info"),
            "DELETE_USER": ("account-remove", "danger"),
            "UPDATE_ADMIN": ("account-edit", "info"),
            "UPDATE_SECURITY_QUESTIONS": ("security", "info"),
            "RESET_PASSWORD_QA": ("refresh", "warning"),
            "ACCESS_ATTEMPT": ("shield-key-outline", "warning"),
            "ACCESS_DENIED": ("shield-alert-outline", "danger"),
            "SECURITY_ALERT": ("lock-alert-outline", "danger"),
            "FRAUD_ALERT": ("shield-search-outline", "danger"),
            "RUPTURE_ATTEMPT": ("package-variant-remove", "warning"),
            "ADD_PRODUCT": ("package-variant-closed-plus", "success"),
            "UPDATE_PRODUCT": ("package-variant-closed-check", "info"),
            "DELETE_PRODUCT": ("package-variant-closed-remove", "danger"),
            "SALE": ("cart-check", "success"),
            "CANCEL_SALE": ("cart-remove", "danger"),
            "SAVE_RECEIPT": ("content-save", "info"),
            "REGISTER_LOSS": ("alert-circle-outline", "warning"),
            "APPROVE_LOSS": ("check-decagram-outline", "success"),
        }
        return styles.get(action, ("information", "primary"))
        
    def show(self):
        tokens = self._theme_tokens()
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(10),
            adaptive_height=True,
            md_bg_color=tokens.get("surface", [0.96, 0.96, 0.98, 1])
        )
        
        filter_box = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint_y=None,
            height=dp(56)
        )
        
        self.user_filter = MDTextField(
            hint_text='Filtrar por usuário',
            mode='rectangle',
            size_hint_x=0.5
        )
        
        self.action_filter = MDTextField(
            hint_text='Filtrar por ação',
            mode='rectangle',
            size_hint_x=0.5
        )
        
        self._style_text_field(self.user_filter)
        self._style_text_field(self.action_filter)
        filter_box.add_widget(self.user_filter)
        filter_box.add_widget(self.action_filter)
        content.add_widget(filter_box)

        role_box = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(8),
            size_hint_y=None,
            height=dp(40)
        )
        role_label = self._make_label(
            text='Somente gerente',
            color=tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
        )
        role_label.size_hint_x = None
        role_label.width = dp(140)
        self.manager_only = MDCheckbox(active=False)
        self.manager_only.selected_color = tokens.get("primary", [0.10, 0.35, 0.65, 1])
        self.manager_only.unselected_color = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])
        self.manager_only.disabled_color = tokens.get("text_muted", [0.55, 0.60, 0.70, 1])
        role_box.add_widget(role_label)
        role_box.add_widget(self.manager_only)
        role_box.add_widget(self._make_label(""))
        content.add_widget(role_box)

        btn_row = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint_y=None,
            height=dp(40)
        )
        
        search_btn = MDRaisedButton(
            text='BUSCAR',
            size_hint_y=None,
            height=dp(40),
            md_bg_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
            theme_text_color='Custom',
            text_color=tokens.get("on_primary", [1, 1, 1, 1]),
            on_release=lambda x: self.load_logs()
        )
        export_btn = MDRectangleFlatButton(
            text='EXPORTAR PDF',
            size_hint_y=None,
            height=dp(40),
            theme_text_color='Custom',
            text_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
            line_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
            on_release=lambda x: self.export_logs_pdf()
        )
        clear_btn = MDRectangleFlatButton(
            text='LIMPAR LOGS',
            size_hint_y=None,
            height=dp(40),
            theme_text_color='Custom',
            text_color=tokens.get("danger", [0.90, 0.30, 0.30, 1]),
            line_color=tokens.get("danger", [0.90, 0.30, 0.30, 1]),
            on_release=lambda x: self._confirm_clear_logs()
        )
        self.search_btn = search_btn
        self.export_btn = export_btn
        self.clear_btn = clear_btn
        btn_row.add_widget(search_btn)
        btn_row.add_widget(export_btn)
        btn_row.add_widget(clear_btn)
        content.add_widget(btn_row)
        
        from kivymd.uix.scrollview import MDScrollView
        scroll = MDScrollView(size_hint=(1, None), height=dp(400))
        
        self.logs_list = MDBoxLayout(
            orientation='vertical',
            spacing=dp(5),
            adaptive_height=True,
            md_bg_color=tokens.get("surface", [0.96, 0.96, 0.98, 1])
        )
        
        scroll.add_widget(self.logs_list)
        content.add_widget(scroll)
        
        self.dialog = MDDialog(
            title='Logs do Sistema',
            type='custom',
            content_cls=content,
            size_hint=(0.9, 0.9),
            buttons=[
                MDFlatButton(
                    text='FECHAR',
                    theme_text_color='Custom',
                    text_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
                    on_release=lambda x: self.dialog.dismiss()
                )
            ]
        )
        
        self.load_logs()
        self.dialog.open()

    def _set_logs_busy_state(self, *, loading=None, exporting=None):
        if loading is not None:
            self._loading_logs = bool(loading)
        if exporting is not None:
            self._exporting_logs = bool(exporting)
        if self.search_btn:
            self.search_btn.disabled = self._loading_logs or self._exporting_logs
            self.search_btn.text = 'A BUSCAR...' if self._loading_logs else 'BUSCAR'
        if self.export_btn:
            self.export_btn.disabled = self._loading_logs or self._exporting_logs
            self.export_btn.text = 'A EXPORTAR...' if self._exporting_logs else 'EXPORTAR PDF'
        if self.clear_btn:
            self.clear_btn.disabled = self._loading_logs or self._exporting_logs

    def _fetch_logs(self, limit=100):
        user_filter = self.user_filter.text.strip() if hasattr(self, 'user_filter') else ''
        action_filter = self.action_filter.text.strip() if hasattr(self, 'action_filter') else ''
        role_filter = 'manager' if getattr(self, 'manager_only', None) and self.manager_only.active else ''
        excluded_actions = {'LOGIN', 'LOGOUT'}

        with get_db() as db:
            fetch_limit = None
            if limit:
                fetch_limit = max(int(limit) * 4, 200)
            rows = db.get_user_logs(user_filter, action_filter, role_filter, limit=fetch_limit)
            filtered = [row for row in (rows or []) if str(row[3] or "").upper() not in excluded_actions]
            if limit:
                if len(filtered) < int(limit) and fetch_limit:
                    rows = db.get_user_logs(user_filter, action_filter, role_filter, limit=None)
                    filtered = [row for row in (rows or []) if str(row[3] or "").upper() not in excluded_actions]
                return filtered[: int(limit)]
            return filtered

    def load_logs(self):
        if self._loading_logs or not hasattr(self, 'logs_list'):
            return
        tokens = self._theme_tokens()
        self.logs_list.clear_widgets()
        self._set_logs_busy_state(loading=True)

        def worker():
            logs = None
            error = None
            try:
                logs = self._fetch_logs(limit=100)
            except Exception as exc:
                error = exc
            Clock.schedule_once(lambda dt, rows=logs, err=error: apply_result(rows, err), 0)

        def apply_result(logs, error):
            self._set_logs_busy_state(loading=False)
            if error:
                self.logs_list.add_widget(self._build_state_label(
                    f'Erro ao carregar logs: {str(error)}',
                    tone='danger',
                ))
                return

            if not logs:
                self.logs_list.add_widget(self._build_state_label(
                    'Nenhum log encontrado',
                    tone='text_secondary',
                ))
                return

            for log in logs:
                log_id, username, role, action, details, timestamp = log

                timestamp_formatted = self.format_timestamp(timestamp)
                action_label = self._action_to_label(action)
                icon, tone = self._action_style(action)

                log_card = MDCard(
                    orientation='horizontal',
                    padding=dp(15),
                    spacing=dp(15),
                    size_hint_y=None,
                    adaptive_height=True,
                    radius=[10],
                    md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1])
                )
                log_card.bind(minimum_height=log_card.setter("height"))

                from kivymd.uix.boxlayout import MDBoxLayout as BL
                icon_box = AnchorLayout(size_hint_x=None, width=dp(50))
                from kivymd.uix.label import MDIcon
                log_icon = MDIcon(
                    icon=icon,
                    size_hint=(None, None),
                    size=(dp(32), dp(32)),
                    font_size=dp(32),
                    theme_text_color='Custom',
                    text_color=self._tone_color(tone),
                    halign='center',
                    valign='middle',
                )
                log_icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
                icon_box.add_widget(log_icon)
                log_card.add_widget(icon_box)

                info_box = BL(orientation='vertical', spacing=dp(5), adaptive_height=True, size_hint_y=None)
                info_box.bind(minimum_height=info_box.setter("height"))

                header = BL(orientation='horizontal', size_hint_y=None, height=dp(25))
                user_label = self._make_label(
                    text=f'[b]{username}[/b] ({role})',
                    markup=True,
                    color=tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
                    font_style='Body2'
                )
                user_label.size_hint_x = 0.5
                header.add_widget(user_label)
                time_label = self._make_label(
                    text=timestamp_formatted,
                    color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
                    halign='right',
                    font_style='Caption'
                )
                time_label.size_hint_x = 0.5
                header.add_widget(time_label)
                info_box.add_widget(header)

                action_text = self._make_label(
                    text=f'[b]{action_label}[/b]',
                    markup=True,
                    color=self._tone_color(tone),
                    font_style='Body2'
                )
                info_box.add_widget(action_text)

                if details:
                    details_label = self._make_label(
                        text=details,
                        color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
                        font_style='Caption'
                    )
                    info_box.add_widget(details_label)

                log_card.add_widget(info_box)
                self.logs_list.add_widget(log_card)

        Thread(target=worker, daemon=True).start()

    def _confirm_clear_logs(self):
        tokens = self._theme_tokens()
        dialog = MDDialog(
            title='Limpar Logs',
            text='Tem certeza que deseja apagar todos os logs do sistema?',
            buttons=[
                MDFlatButton(
                    text='CANCELAR',
                    theme_text_color='Custom',
                    text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
                    on_release=lambda x: dialog.dismiss(),
                ),
                MDRaisedButton(
                    text='LIMPAR',
                    md_bg_color=tokens.get("danger", [0.90, 0.30, 0.30, 1]),
                    theme_text_color='Custom',
                    text_color=tokens.get("on_primary", [1, 1, 1, 1]),
                    on_release=lambda x: self._clear_logs(dialog),
                ),
            ],
        )
        dialog.open()

    def _clear_logs(self, dialog):
        try:
            with get_db() as db:
                if not db.clear_user_logs():
                    raise RuntimeError('Falha ao apagar logs')
            dialog.dismiss()
            self.load_logs()
            self._show_simple_dialog('Sucesso', 'Logs apagados com sucesso.')
        except Exception as e:
            self._show_simple_dialog('Erro', f'Falha ao apagar logs: {e}')

    def _show_simple_dialog(self, title, message):
        tokens = self._theme_tokens()
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[
                MDFlatButton(
                    text='OK',
                    theme_text_color='Custom',
                    text_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
                    on_release=lambda x: dialog.dismiss(),
                )
            ],
        )
        dialog.open()

    def _action_to_label(self, action):
        if not action:
            return "Ação desconhecida"
        label = self._action_labels.get(action)
        if label:
            return label
        return f"Ação: {action}"

    def export_logs_pdf(self):
        if self._exporting_logs:
            return

        filters = {
            "user": self.user_filter.text.strip(),
            "action": self.action_filter.text.strip(),
            "role": "manager" if self.manager_only.active else "todos",
        }
        self._set_logs_busy_state(exporting=True)

        def worker():
            result = {"status": "empty", "pdf_path": None, "error": None}
            try:
                logs = self._fetch_logs(limit=None)
                if logs:
                    result["status"] = "ok"
                    result["pdf_path"] = _get_logs_report_class()().generate(logs, filters)
                else:
                    result["status"] = "empty"
            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
            Clock.schedule_once(lambda dt, payload=result: apply_result(payload), 0)

        def apply_result(result):
            self._set_logs_busy_state(exporting=False)
            status = result.get("status")
            if status == "ok":
                self._show_simple_dialog("PDF Gerado", f"Arquivo criado em:\\n{result.get('pdf_path')}")
                return
            if status == "empty":
                self._show_simple_dialog("Aviso", "Nenhum log para exportar.")
                return
            self._show_simple_dialog("Erro", f"Falha ao gerar PDF: {result.get('error')}")

        Thread(target=worker, daemon=True).start()

    def _show_simple_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: dialog.dismiss())],
        )
        dialog.open()
    
    def format_timestamp(self, timestamp):
        try:
            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            return dt.strftime('%d/%m/%Y %H:%M')
        except:
            return timestamp


class EnhancedSystemLogsDialog:
    # Dialogo avancado para filtrar, resumir e exportar logs.
    def __init__(self):
        self.dialog = None
        self.search_btn = None
        self.export_btn = None
        self.clear_btn = None
        self.reset_filters_btn = None
        self.role_filter_btn = None
        self.limit_filter_btn = None
        self.results_meta_label = None
        self.results_range_label = None
        self.active_filters_label = None
        self.logs_list = None
        self.progress_bar = None
        self.summary_cards = {}
        self.role_menu = None
        self.limit_menu = None
        self.user_filter = None
        self.action_filter = None
        self._loading_logs = False
        self._exporting_logs = False
        self._selected_role_filter = ""
        self._selected_role_label = "Todos"
        self._selected_limit = 250
        self._selected_limit_label = "250 recentes"
        self._role_options = [
            ("Todos", ""),
            ("Admin", "admin"),
            ("Manager", "manager"),
        ]
        self._limit_options = [
            ("100 recentes", 100),
            ("250 recentes", 250),
            ("500 recentes", 500),
            ("Todos", None),
        ]
        self._action_labels = {
            "LOGIN": "Login realizado",
            "LOGOUT": "Logout realizado",
            "CREATE_USER": "Usuario criado",
            "DELETE_USER": "Usuario removido",
            "UPDATE_ADMIN": "Dados do admin atualizados",
            "UPDATE_SECURITY_QUESTIONS": "Perguntas de recuperacao atualizadas",
            "RESET_PASSWORD_QA": "Senha redefinida por perguntas",
            "ACCESS_ATTEMPT": "Tentativa de acesso",
            "ACCESS_DENIED": "Acesso negado",
            "SECURITY_ALERT": "Alerta de seguranca",
            "FRAUD_ALERT": "Alerta de fraude",
            "RUPTURE_ATTEMPT": "Tentativa com stock insuficiente",
            "UPDATE_SECURITY_QUESTIONS": "Perguntas de recuperacao atualizadas",
            "RESET_PASSWORD_QA": "Senha redefinida por perguntas",
            "ADD_PRODUCT": "Produto adicionado",
            "UPDATE_PRODUCT": "Produto atualizado",
            "DELETE_PRODUCT": "Produto removido",
            "SALE": "Venda registrada",
            "CANCEL_SALE": "Venda cancelada",
            "REFUND_SALE": "Estorno de venda",
            "SAVE_RECEIPT": "Recibo salvo",
            "REGISTER_LOSS": "Perda registrada",
            "APPROVE_LOSS": "Perda aprovada",
        }

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    def _tone_color(self, tone):
        tokens = self._theme_tokens()
        return tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))

    def _style_text_field(self, field):
        tokens = self._theme_tokens()
        field.text_color_normal = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
        field.text_color_focus = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
        field.line_color_normal = tokens.get("divider", [0, 0, 0, 0.12])
        field.line_color_focus = tokens.get("primary", [0.10, 0.35, 0.65, 1])
        field.hint_text_color_normal = tokens.get("text_muted", [0.55, 0.60, 0.70, 1])
        field.hint_text_color_focus = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])

    def _make_label(self, text="", *, font_style="Body1", color=None, bold=False, halign="left", markup=False):
        tokens = self._theme_tokens()
        label = MDLabel(
            text=text,
            font_style=font_style,
            bold=bold,
            halign=halign,
            markup=markup,
            size_hint_y=None,
            theme_text_color="Custom",
            text_color=color or tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
        )
        label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", max(size[1], dp(20))),
        )
        return label

    def _build_state_label(self, text, tone="text_secondary"):
        tokens = self._theme_tokens()
        return self._make_label(
            text,
            font_style="Body2",
            color=tokens.get(tone, tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])),
            halign="center",
        )

    def _action_style(self, action):
        styles = {
            "LOGIN": ("login", "success"),
            "LOGOUT": ("logout", "warning"),
            "CREATE_USER": ("account-plus", "info"),
            "DELETE_USER": ("account-remove", "danger"),
            "UPDATE_ADMIN": ("account-edit", "info"),
            "ADD_PRODUCT": ("package-variant-closed-plus", "success"),
            "UPDATE_PRODUCT": ("package-variant-closed-check", "info"),
            "DELETE_PRODUCT": ("package-variant-closed-remove", "danger"),
            "SALE": ("cart-check", "success"),
            "CANCEL_SALE": ("cart-remove", "danger"),
            "SAVE_RECEIPT": ("content-save", "info"),
            "REGISTER_LOSS": ("alert-circle-outline", "warning"),
            "APPROVE_LOSS": ("check-decagram-outline", "success"),
        }
        return styles.get(action, ("information", "primary"))
        self._action_styles = {
            "LOGIN": {"icon": "login", "tone": "success"},
            "LOGOUT": {"icon": "logout", "tone": "warning"},
            "CREATE_USER": {"icon": "account-plus", "tone": "info"},
            "DELETE_USER": {"icon": "account-remove", "tone": "danger"},
            "UPDATE_ADMIN": {"icon": "account-edit", "tone": "info"},
            "UPDATE_SECURITY_QUESTIONS": {"icon": "security", "tone": "info"},
            "RESET_PASSWORD_QA": {"icon": "refresh", "tone": "warning"},
            "ADD_PRODUCT": {"icon": "package-variant-closed-plus", "tone": "success"},
            "UPDATE_PRODUCT": {"icon": "package-variant-closed-check", "tone": "info"},
            "DELETE_PRODUCT": {"icon": "package-variant-closed-remove", "tone": "danger"},
            "SALE": {"icon": "cart-check", "tone": "success"},
            "CANCEL_SALE": {"icon": "cart-remove", "tone": "danger"},
            "REFUND_SALE": {"icon": "cash", "tone": "warning"},
            "SAVE_RECEIPT": {"icon": "content-save", "tone": "info"},
            "REGISTER_LOSS": {"icon": "alert-circle-outline", "tone": "warning"},
            "APPROVE_LOSS": {"icon": "check-decagram-outline", "tone": "success"},
        }

    def show(self):
        self.summary_cards = {}
        self.role_menu = None
        self.limit_menu = None

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(5))
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(6), dp(6), dp(6), dp(10)],
            size_hint_y=None,
            adaptive_height=True,
        )
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)

        content.add_widget(self._build_filters_card())
        content.add_widget(self._build_summary_card())
        content.add_widget(self._build_results_card())

        self.dialog = MDDialog(
            title="Logs do Sistema",
            type="custom",
            content_cls=scroll,
            size_hint=(0.94, 0.94),
            buttons=[
                MDFlatButton(
                    text="FECHAR",
                    on_release=lambda _x: self.dialog.dismiss(),
                )
            ],
        )

        self._refresh_active_filters_label()
        self._update_summary_cards([])
        self._set_result_state(
            meta="Pronto para carregar os registos.",
            detail="Use os filtros acima para refinar a leitura.",
        )
        self.load_logs()
        self.dialog.open()

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    def _tone_color(self, tone):
        tokens = self._theme_tokens()
        return tokens.get(tone, tokens.get("info", [0.15, 0.45, 0.75, 1]))

    def _soft_color(self, tone, alpha=0.14):
        base = list(self._tone_color(tone))
        if len(base) < 4:
            base.append(1)
        return [base[0], base[1], base[2], alpha]

    def _build_text(self, text, *, font_style="Body1", color=None, bold=False, halign="left"):
        tokens = self._theme_tokens()
        label = MDLabel(
            text=text,
            font_style=font_style,
            bold=bold,
            halign=halign,
            size_hint_y=None,
            theme_text_color="Custom",
            text_color=color or tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
        )
        label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        return label

    def _build_icon_slot(self, icon, tone, size=42):
        slot = MDCard(
            size_hint=(None, None),
            size=(dp(size), dp(size)),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=self._soft_color(tone, 0.16),
        )
        icon_widget = MDIcon(
            icon=icon,
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=self._tone_color(tone),
        )
        icon_widget.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        slot.add_widget(icon_widget)
        return slot

    def _create_section_card(self, tone="card"):
        tokens = self._theme_tokens()
        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(14), dp(14), dp(14), dp(14)],
            spacing=dp(10),
            radius=[dp(18)],
            elevation=0,
            md_bg_color=tokens.get(tone, [1, 1, 1, 1]),
        )
        card.bind(minimum_height=card.setter("height"))
        return card

    def _build_summary_item(self, key, title, icon, tone):
        tokens = self._theme_tokens()
        card = MDCard(
            orientation="vertical",
            padding=[dp(12), dp(12), dp(12), dp(12)],
            spacing=dp(8),
            size_hint_x=0.5,
            size_hint_y=None,
            height=dp(116),
            radius=[dp(16)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )

        top_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(28),
        )
        top_row.add_widget(self._build_icon_slot(icon, tone, size=28))
        top_row.add_widget(self._build_text(
            title,
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))
        card.add_widget(top_row)

        value_label = self._build_text(
            "--",
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        )
        caption_label = self._build_text(
            "Sem leitura ainda",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        )
        card.add_widget(value_label)
        card.add_widget(caption_label)
        self.summary_cards[key] = {
            "value": value_label,
            "caption": caption_label,
        }
        return card

    def _build_filters_card(self):
        tokens = self._theme_tokens()
        card = self._create_section_card()
        card.add_widget(self._build_text(
            "Pesquisa, filtros e operacoes",
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        ))
        card.add_widget(self._build_text(
            "Refine a consulta por utilizador, acao, perfil e quantidade de registos sem sair da configuracao.",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))

        filter_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(64),
        )
        self.user_filter = MDTextField(
            hint_text="Filtrar por utilizador",
            helper_text="Ex.: admin, jose, manager01",
            helper_text_mode="persistent",
            mode="rectangle",
            size_hint_x=0.5,
        )
        self.action_filter = MDTextField(
            hint_text="Filtrar por acao",
            helper_text="Ex.: SALE, ACCESS_DENIED, REGISTER_LOSS",
            helper_text_mode="persistent",
            mode="rectangle",
            size_hint_x=0.5,
        )
        self.user_filter.bind(on_text_validate=lambda *_args: self.load_logs())
        self.action_filter.bind(on_text_validate=lambda *_args: self.load_logs())
        filter_row.add_widget(self.user_filter)
        filter_row.add_widget(self.action_filter)
        card.add_widget(filter_row)

        option_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(40),
        )
        self.role_filter_btn = MDRectangleFlatButton(
            text=f"PERFIL: {self._selected_role_label.upper()}",
            on_release=lambda *_args: self._open_role_menu(),
        )
        self.limit_filter_btn = MDRectangleFlatButton(
            text=f"MOSTRAR: {self._selected_limit_label.upper()}",
            on_release=lambda *_args: self._open_limit_menu(),
        )
        self.reset_filters_btn = MDRectangleFlatButton(
            text="REPOR FILTROS",
            on_release=lambda *_args: self._reset_filters(),
        )
        option_row.add_widget(self.role_filter_btn)
        option_row.add_widget(self.limit_filter_btn)
        option_row.add_widget(self.reset_filters_btn)
        card.add_widget(option_row)

        action_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(42),
        )
        self.search_btn = MDRaisedButton(
            text="ATUALIZAR LOGS",
            on_release=lambda *_args: self.load_logs(),
        )
        self.export_btn = MDRectangleFlatButton(
            text="EXPORTAR PDF",
            on_release=lambda *_args: self.export_logs_pdf(),
        )
        self.clear_btn = MDRectangleFlatButton(
            text="LIMPAR LOGS",
            on_release=lambda *_args: self._confirm_clear_logs(),
        )
        action_row.add_widget(self.search_btn)
        action_row.add_widget(self.export_btn)
        action_row.add_widget(self.clear_btn)
        card.add_widget(action_row)

        self.active_filters_label = self._build_text(
            "",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        )
        card.add_widget(self.active_filters_label)
        card.add_widget(self._build_text(
            "Nota: o limite afeta apenas a visualizacao. A exportacao PDF usa todos os registos que corresponderem aos filtros atuais.",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))
        return card

    def _build_summary_card(self):
        tokens = self._theme_tokens()
        card = self._create_section_card()
        card.add_widget(self._build_text(
            "Resumo instantaneo",
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        ))
        card.add_widget(self._build_text(
            "Leitura rapida para perceber volume, perfis envolvidos e qual acao dominou o periodo carregado.",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))

        first_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(116),
        )
        second_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(116),
        )
        first_row.add_widget(self._build_summary_item("total", "Registos visiveis", "text-box-search", "info"))
        first_row.add_widget(self._build_summary_item("admin", "Movimentos admin", "shield-account", "warning"))
        second_row.add_widget(self._build_summary_item("manager", "Movimentos manager", "account-multiple", "success"))
        second_row.add_widget(self._build_summary_item("top_action", "Acao dominante", "chart-timeline-variant", "primary"))
        card.add_widget(first_row)
        card.add_widget(second_row)
        return card

    def _build_results_card(self):
        tokens = self._theme_tokens()
        card = self._create_section_card()
        card.add_widget(self._build_text(
            "Linha do tempo",
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        ))
        self.results_meta_label = self._build_text(
            "A iniciar consulta...",
            font_style="Body2",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        )
        self.results_range_label = self._build_text(
            "Os detalhes do intervalo carregado aparecem aqui.",
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        )
        card.add_widget(self.results_meta_label)
        card.add_widget(self.results_range_label)

        self.progress_bar = MDProgressBar(
            value=0,
            max=100,
            size_hint_y=None,
            height=dp(3),
            color=tokens.get("info", [0.15, 0.45, 0.75, 1]),
            opacity=0,
        )
        card.add_widget(self.progress_bar)

        self.logs_list = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            adaptive_height=True,
            size_hint_y=None,
        )
        self.logs_list.bind(minimum_height=self.logs_list.setter("height"))
        card.add_widget(self.logs_list)
        return card

    def _build_state_card(self, *, icon, title, message, tone):
        tokens = self._theme_tokens()
        card = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(14), dp(14), dp(14), dp(14)],
            spacing=dp(12),
            radius=[dp(16)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(self._build_icon_slot(icon, tone))

        text_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(6),
            adaptive_height=True,
            size_hint_y=None,
        )
        text_box.bind(minimum_height=text_box.setter("height"))
        text_box.add_widget(self._build_text(
            title,
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        ))
        text_box.add_widget(self._build_text(
            message,
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))
        card.add_widget(text_box)
        return card

    def _build_log_card(self, log):
        _log_id, username, role, action, details, timestamp = log
        tokens = self._theme_tokens()
        style = self._action_styles.get(action, {"icon": "information", "tone": "info"})
        role_key = (role or "").strip().lower()
        role_tone = "warning" if role_key == "admin" else "success" if role_key == "manager" else "info"

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(14), dp(14), dp(14), dp(14)],
            spacing=dp(10),
            radius=[dp(16)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        card.bind(minimum_height=card.setter("height"))

        header = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True,
            size_hint_y=None,
        )
        header.bind(minimum_height=header.setter("height"))
        header.add_widget(self._build_icon_slot(style["icon"], style["tone"]))

        info_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(4),
            adaptive_height=True,
            size_hint_y=None,
        )
        info_box.bind(minimum_height=info_box.setter("height"))
        info_box.add_widget(self._build_text(
            username or "Sistema",
            font_style="Subtitle1",
            color=tokens.get("text_primary", [0.15, 0.2, 0.3, 1]),
            bold=True,
        ))
        info_box.add_widget(self._build_text(
            self._action_to_label(action),
            font_style="Body2",
            color=self._tone_color(style["tone"]),
            bold=True,
        ))

        meta_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(20),
        )
        meta_row.add_widget(self._build_text(
            f"Perfil: {(role or 'desconhecido').upper()}",
            font_style="Caption",
            color=self._tone_color(role_tone),
        ))
        meta_row.add_widget(self._build_text(
            self.format_timestamp(timestamp),
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
            halign="right",
        ))
        info_box.add_widget(meta_row)
        header.add_widget(info_box)
        card.add_widget(header)

        detail_text = (details or "").strip() or "Sem detalhes adicionais para este registo."
        detail_card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(12), dp(10), dp(12), dp(10)],
            radius=[dp(14)],
            elevation=0,
            md_bg_color=self._soft_color(style["tone"], 0.08),
        )
        detail_card.bind(minimum_height=detail_card.setter("height"))
        detail_card.add_widget(self._build_text(
            detail_text,
            font_style="Caption",
            color=tokens.get("text_secondary", [0.35, 0.4, 0.5, 1]),
        ))
        card.add_widget(detail_card)
        return card

    def _set_result_state(self, *, meta, detail, tone="info"):
        if self.results_meta_label:
            self.results_meta_label.text = meta
            self.results_meta_label.text_color = self._tone_color(tone)
        if self.results_range_label:
            tokens = self._theme_tokens()
            self.results_range_label.text = detail
            self.results_range_label.text_color = tokens.get("text_secondary", [0.35, 0.4, 0.5, 1])

    def _refresh_active_filters_label(self):
        if not self.active_filters_label:
            return

        parts = []
        user_text = self.user_filter.text.strip() if self.user_filter else ""
        action_text = self.action_filter.text.strip() if self.action_filter else ""
        if user_text:
            parts.append(f'Utilizador "{user_text}"')
        if action_text:
            parts.append(f'Acao "{action_text}"')
        if self._selected_role_filter:
            parts.append(f"Perfil {self._selected_role_label}")
        parts.append(f"Limite {self._selected_limit_label}")
        self.active_filters_label.text = "Filtros ativos: " + " | ".join(parts)

    def _update_summary_cards(self, logs, error=None):
        if not self.summary_cards:
            return

        if error is not None:
            for payload in self.summary_cards.values():
                payload["value"].text = "--"
                payload["caption"].text = "Consulta indisponivel"
            return

        logs = logs or []
        role_counts = Counter((str(row[2] or "").strip().lower() or "desconhecido") for row in logs)
        action_counts = Counter(str(row[3] or "").strip() for row in logs if row[3])
        top_action, top_count = action_counts.most_common(1)[0] if action_counts else ("", 0)

        self.summary_cards["total"]["value"].text = str(len(logs))
        self.summary_cards["total"]["caption"].text = "Registos atualmente listados"

        self.summary_cards["admin"]["value"].text = str(role_counts.get("admin", 0))
        self.summary_cards["admin"]["caption"].text = "Acoes feitas por perfis admin"

        self.summary_cards["manager"]["value"].text = str(role_counts.get("manager", 0))
        self.summary_cards["manager"]["caption"].text = "Acoes feitas por perfis manager"

        if top_action:
            self.summary_cards["top_action"]["value"].text = self._action_to_label(top_action)
            self.summary_cards["top_action"]["caption"].text = f"{top_count} ocorrencia(s) nesta leitura"
        else:
            self.summary_cards["top_action"]["value"].text = "Sem dados"
            self.summary_cards["top_action"]["caption"].text = "Nenhuma acao destacada"

    def _set_logs_busy_state(self, *, loading=None, exporting=None):
        if loading is not None:
            self._loading_logs = bool(loading)
        if exporting is not None:
            self._exporting_logs = bool(exporting)
        if self.search_btn:
            self.search_btn.disabled = self._loading_logs or self._exporting_logs
            self.search_btn.text = "A CARREGAR..." if self._loading_logs else "ATUALIZAR LOGS"
        if self.export_btn:
            self.export_btn.disabled = self._loading_logs or self._exporting_logs
            self.export_btn.text = "A EXPORTAR..." if self._exporting_logs else "EXPORTAR PDF"
        if self.clear_btn:
            self.clear_btn.disabled = self._loading_logs or self._exporting_logs
        if self.reset_filters_btn:
            self.reset_filters_btn.disabled = self._loading_logs or self._exporting_logs
        if self.role_filter_btn:
            self.role_filter_btn.disabled = self._loading_logs or self._exporting_logs
        if self.limit_filter_btn:
            self.limit_filter_btn.disabled = self._loading_logs or self._exporting_logs
        if self.progress_bar:
            self.progress_bar.opacity = 1 if self._loading_logs else 0
            self.progress_bar.value = 100 if self._loading_logs else 0

    def _fetch_logs(self, limit="selected"):
        user_filter = self.user_filter.text.strip() if self.user_filter else ""
        action_filter = self.action_filter.text.strip() if self.action_filter else ""
        role_filter = self._selected_role_filter
        if limit == "selected":
            limit = self._selected_limit
        with get_db() as db:
            return db.get_user_logs(user_filter, action_filter, role_filter, limit=limit)

    def load_logs(self):
        if self._loading_logs or not self.logs_list:
            return
        self._refresh_active_filters_label()
        self.logs_list.clear_widgets()
        self.logs_list.add_widget(self._build_state_card(
            icon="database-search-outline",
            title="A carregar atividade recente",
            message="Estou a consultar os registos e a preparar um resumo visual para esta sessao.",
            tone="info",
        ))
        self._set_result_state(
            meta="A carregar registos filtrados...",
            detail="Aguarde um instante enquanto a consulta termina.",
            tone="info",
        )
        self._set_logs_busy_state(loading=True)

        def worker():
            logs = None
            error = None
            try:
                logs = self._fetch_logs()
            except Exception as exc:
                error = exc
            Clock.schedule_once(lambda _dt, rows=logs, err=error: apply_result(rows, err), 0)

        def apply_result(logs, error):
            self._set_logs_busy_state(loading=False)
            self.logs_list.clear_widgets()
            if error:
                self.logs_list.add_widget(self._build_state_card(
                    icon="alert-circle-outline",
                    title="Falha ao carregar os logs",
                    message=f"Ocorreu um erro ao consultar os registos: {str(error)}",
                    tone="danger",
                ))
                self._update_summary_cards(None, error=error)
                self._set_result_state(
                    meta="Falha ao obter os registos.",
                    detail=str(error),
                    tone="danger",
                )
                return

            if not logs:
                self.logs_list.add_widget(self._build_state_card(
                    icon="text-box-search-outline",
                    title="Nenhum registo encontrado",
                    message="Ajuste os filtros ou amplie o limite para procurar atividade mais antiga.",
                    tone="warning",
                ))
                self._update_summary_cards([])
                self._set_result_state(
                    meta="Sem resultados para os filtros atuais.",
                    detail="Experimente limpar filtros ou escolher um limite maior.",
                    tone="warning",
                )
                return

            for log in logs:
                self.logs_list.add_widget(self._build_log_card(log))

            self._update_summary_cards(logs)
            newest = logs[0]
            oldest = logs[-1]
            self._set_result_state(
                meta=f"{len(logs)} registo(s) carregado(s) com sucesso.",
                detail=(
                    f"Mais recente: {self.format_timestamp(newest[5])} por {newest[1] or 'Sistema'}"
                    f" | Mais antigo: {self.format_timestamp(oldest[5])}"
                ),
                tone="success",
            )

        Thread(target=worker, daemon=True).start()

    def _open_role_menu(self):
        items = [
            {
                "viewclass": "OneLineListItem",
                "text": label,
                "height": dp(42),
                "on_release": lambda selected_label=label, selected_value=value: self._set_role_filter(
                    selected_label, selected_value
                ),
            }
            for label, value in self._role_options
        ]
        if self.role_menu:
            self.role_menu.dismiss()
        self.role_menu = MDDropdownMenu(
            caller=self.role_filter_btn,
            items=items,
            width_mult=3.2,
            max_height=dp(220),
            position="bottom",
        )
        self.role_menu.open()

    def _open_limit_menu(self):
        items = [
            {
                "viewclass": "OneLineListItem",
                "text": label,
                "height": dp(42),
                "on_release": lambda selected_label=label, selected_value=value: self._set_limit_filter(
                    selected_label, selected_value
                ),
            }
            for label, value in self._limit_options
        ]
        if self.limit_menu:
            self.limit_menu.dismiss()
        self.limit_menu = MDDropdownMenu(
            caller=self.limit_filter_btn,
            items=items,
            width_mult=3.4,
            max_height=dp(220),
            position="bottom",
        )
        self.limit_menu.open()

    def _set_role_filter(self, label, value):
        self._selected_role_label = label
        self._selected_role_filter = value
        if self.role_filter_btn:
            self.role_filter_btn.text = f"PERFIL: {label.upper()}"
        if self.role_menu:
            self.role_menu.dismiss()
            self.role_menu = None
        self._refresh_active_filters_label()
        self.load_logs()

    def _set_limit_filter(self, label, value):
        self._selected_limit_label = label
        self._selected_limit = value
        if self.limit_filter_btn:
            self.limit_filter_btn.text = f"MOSTRAR: {label.upper()}"
        if self.limit_menu:
            self.limit_menu.dismiss()
            self.limit_menu = None
        self._refresh_active_filters_label()
        self.load_logs()

    def _reset_filters(self):
        if self.user_filter:
            self.user_filter.text = ""
        if self.action_filter:
            self.action_filter.text = ""
        self._selected_role_filter = ""
        self._selected_role_label = "Todos"
        self._selected_limit = 250
        self._selected_limit_label = "250 recentes"
        if self.role_filter_btn:
            self.role_filter_btn.text = "PERFIL: TODOS"
        if self.limit_filter_btn:
            self.limit_filter_btn.text = "MOSTRAR: 250 RECENTES"
        self._refresh_active_filters_label()
        self.load_logs()

    def _confirm_clear_logs(self):
        dialog = MDDialog(
            title="Limpar Logs",
            text="Tem certeza que deseja apagar todos os logs do sistema? Esta acao remove todo o historico visivel nesta tela.",
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda _x: dialog.dismiss()),
                MDRaisedButton(text="LIMPAR", on_release=lambda _x: self._clear_logs(dialog)),
            ],
        )
        dialog.open()

    def _clear_logs(self, dialog):
        try:
            with get_db() as db:
                if not db.clear_user_logs():
                    raise RuntimeError("Falha ao apagar logs")
            dialog.dismiss()
            self.load_logs()
            self._show_simple_dialog("Sucesso", "Logs apagados com sucesso.")
        except Exception as exc:
            self._show_simple_dialog("Erro", f"Falha ao apagar logs: {exc}")

    def export_logs_pdf(self):
        if self._exporting_logs:
            return

        filters = {
            "user": self.user_filter.text.strip() if self.user_filter else "",
            "action": self.action_filter.text.strip() if self.action_filter else "",
            "role": self._selected_role_label.lower(),
        }
        self._set_logs_busy_state(exporting=True)

        def worker():
            result = {"status": "empty", "pdf_path": None, "error": None}
            try:
                logs = self._fetch_logs(limit=None)
                if logs:
                    result["status"] = "ok"
                    result["pdf_path"] = _get_logs_report_class()().generate(logs, filters)
                else:
                    result["status"] = "empty"
            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
            Clock.schedule_once(lambda _dt, payload=result: apply_result(payload), 0)

        def apply_result(result):
            self._set_logs_busy_state(exporting=False)
            status = result.get("status")
            if status == "ok":
                self._show_simple_dialog("PDF Gerado", f"Arquivo criado em:\n{result.get('pdf_path')}")
                return
            if status == "empty":
                self._show_simple_dialog("Aviso", "Nenhum log para exportar.")
                return
            self._show_simple_dialog("Erro", f"Falha ao gerar PDF: {result.get('error')}")

        Thread(target=worker, daemon=True).start()

    def _show_simple_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda _x: dialog.dismiss())],
        )
        dialog.open()

    def _action_to_label(self, action):
        if not action:
            return "Acao desconhecida"
        label = self._action_labels.get(action)
        if label:
            return label
        return f"Acao: {action}"

    def format_timestamp(self, timestamp):
        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return timestamp


class ScreenSizeDialog:
    # Dialogo para ajustar o tamanho da janela.
    def __init__(self, app):
        self.app = app
        self.dialog = None
        self._field_navigation = None
        
    def show(self):
        if not self.dialog:
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(20),
                adaptive_height=True
            )
            
            content.add_widget(MDLabel(
                text='Escolha ou personalize a resolução',
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(30)
            ))
            
            resolutions_box = MDBoxLayout(
                orientation='vertical',
                spacing=dp(8),
                adaptive_height=True
            )
            
            resolutions = [
                ('HD', '1280x720'),
                ('Full HD', '1920x1080'),
                ('QHD', '2560x1440'),
                ('4K', '3840x2160')
            ]
            
            for name, res in resolutions:
                btn = MDRectangleFlatButton(
                    text=f'{name} ({res})',
                    size_hint_y=None,
                    height=dp(48),
                    on_release=lambda x, r=res: self.apply_resolution(r)
                )
                resolutions_box.add_widget(btn)
            
            content.add_widget(resolutions_box)
            
            content.add_widget(MDLabel(
                text='Ou personalize:',
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(30)
            ))
            
            custom_box = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(56)
            )
            
            self.width_input = MDTextField(
                hint_text='Largura',
                mode='rectangle',
                input_filter='int'
            )
            self.height_input = MDTextField(
                hint_text='Altura',
                mode='rectangle',
                input_filter='int'
            )
            
            custom_box.add_widget(self.width_input)
            custom_box.add_widget(self.height_input)
            content.add_widget(custom_box)
            
            self.dialog = MDDialog(
                title='Dimensões da Tela',
                type='custom',
                content_cls=content,
                buttons=[
                    MDFlatButton(
                        text='CANCELAR',
                        on_release=self.dismiss
                    ),
                    MDRaisedButton(
                        text='APLICAR',
                        on_release=self.apply_custom
                    )
                ]
            )
            self._field_navigation = FormKeyboardController(
                host=self.dialog,
                fields=[self.width_input, self.height_input],
                initial_field=self.width_input,
                on_escape=self.dismiss,
                on_submit=self.apply_custom,
                shortcuts={"ctrl+s": self.apply_custom},
            )
            self.dialog.bind(on_pre_open=lambda *_: self._field_navigation.activate(focus_initial=True))
            self.dialog.bind(on_dismiss=self._field_navigation.deactivate)
        
        self.dialog.open()
    
    def apply_resolution(self, resolution):
        width, height = map(int, resolution.split('x'))
        self.apply_size(width, height)
    
    def apply_custom(self, *args):
        width = self.width_input.text.strip()
        height = self.height_input.text.strip()
        
        if not width or not height:
            self.show_message('Erro', 'Preencha largura e altura')
            return
        
        try:
            self.apply_size(int(width), int(height))
        except ValueError:
            self.show_message('Erro', 'Use apenas números')
    
    def apply_size(self, width, height):
        if width < 640 or height < 480:
            self.show_message('Erro', 'Dimensões muito pequenas (mín: 640x480)')
            return
        
        try:
            self.app.change_screen_size(width, height)
            applied_width, applied_height = map(int, Window.size)
            self.show_message('Sucesso', f'Tela: {applied_width}x{applied_height}')
            self.dialog.dismiss()
        except Exception as e:
            self.show_message('Erro', f'Erro: {str(e)}')
    
    def dismiss(self, *args):
        self.dialog.dismiss()
    
    def show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())]
        ).open()


class AdminSettingsScreen(MDScreen):
    # Tela de configuracoes do administrador.
    notification_count = NumericProperty(0)
    monitor_enabled = BooleanProperty(True)
    auto_banners_enabled = BooleanProperty(True)
    api_ai_enabled = BooleanProperty(True)
    dark_theme_enabled = BooleanProperty(False)
    physical_scanner_enabled = BooleanProperty(True)
    receipt_auto_print = BooleanProperty(False)
    receipt_printer_name = StringProperty("Impressora padrao")
    receipt_paper_width_mm = NumericProperty(80)
    language_code = StringProperty("pt")
    language_label = StringProperty("Português")
    vat_overview_text = StringProperty("Taxa geral ativa: --")

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.db = getattr(app, "db", None) or get_db()
        self.back_target = "admin_home"
        self.name = 'settings'
        self.notification_count = 0
        self._ai_poll_ev = None
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de monitorizacao",
            auto_present_enabled=False,
        )
        self._api_toggle_ready = False
        self._smart_monitor_toggle_ready = False
        self._auto_banners_toggle_ready = False
        self._theme_toggle_ready = False
        self._device_toggle_ready = False
        self._language_menu = getattr(self, "_language_menu", None)
        self._language_bound_app = getattr(self, "_language_bound_app", None)
        self._security_questions_dialog = None
        self._change_admin_data_dialog = None
        self._ranxo_prefill_dialog = None
        self._ranxo_prefill_running = False
        self._bazara_prefill_reset = False
        self._bazara_backfill_mode = False
        self._vat_settings_dialog = None
        self._vat_rule_form_rows = []
        self._printer_settings_dialog = None
        self._printer_name_field = None
        self._printer_width_field = None
        self._printer_status_label = None
        self._gemini_settings_dialog = None
        self._gemini_api_key_field = None
        self._gemini_model_field = None
        self._gemini_status_label = None
        self._loading_controller = getattr(self, "_loading_controller", None)
        self._background_task_title = ""

    def on_kv_post(self, base_widget):
        self._ensure_loading_overlay()
        self._bind_app_language()
        self._api_toggle_ready = False
        self._smart_monitor_toggle_ready = False
        self._auto_banners_toggle_ready = False
        self._theme_toggle_ready = False
        self._device_toggle_ready = False
        app = App.get_running_app()
        enabled = bool(getattr(app, "smart_monitor_enabled", True)) if app else True
        auto_banners_enabled = bool(getattr(app, "auto_banners_enabled", True)) if app else True
        api_enabled = bool(getattr(app, "ai_enabled", True)) if app else True
        is_dark = bool(app and getattr(app.theme_cls, "theme_style", "Light") == "Dark")
        self.monitor_enabled = enabled
        self.auto_banners_enabled = auto_banners_enabled
        self.api_ai_enabled = api_enabled
        self.dark_theme_enabled = is_dark
        self._sync_device_settings_state()
        self._sync_language_state()
        if "smart_monitor_toggle" in self.ids:
            self.ids.smart_monitor_toggle.active = enabled
        if "auto_banners_toggle" in self.ids:
            self.ids.auto_banners_toggle.active = auto_banners_enabled
        if "api_ai_toggle" in self.ids:
            self.ids.api_ai_toggle.active = api_enabled
        if "theme_toggle" in self.ids:
            self.ids.theme_toggle.active = is_dark
        if "physical_scanner_toggle" in self.ids:
            self.ids.physical_scanner_toggle.active = self.physical_scanner_enabled
        if "receipt_auto_print_toggle" in self.ids:
            self.ids.receipt_auto_print_toggle.active = self.receipt_auto_print
        Clock.schedule_once(self._enable_api_toggle, 0)
        Clock.schedule_once(self._enable_smart_monitor_toggle, 0)
        Clock.schedule_once(self._enable_auto_banners_toggle, 0)
        Clock.schedule_once(self._enable_theme_toggle, 0)
        Clock.schedule_once(self._enable_device_toggle, 0)
        Clock.schedule_once(lambda dt: self._refresh_vat_overview(), 0)
        Clock.schedule_once(self._apply_responsive_layout, 0)

    def on_enter(self):
        self._bind_app_language()
        self._sync_device_settings_state()
        self._sync_language_state()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)
        Clock.schedule_once(lambda dt: self._refresh_vat_overview(), 0)
        Clock.schedule_once(self._apply_responsive_layout, 0)
        if self._ranxo_prefill_running:
            self._set_background_task_loading(True, self._background_task_title or "Tarefa tecnica em andamento...")

    def on_leave(self):
        self._stop_ai_polling()
        self._clear_loading_overlay()

    def on_size(self, *args):
        Clock.schedule_once(self._apply_responsive_layout, 0)

    def _ensure_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is None:
            self._loading_controller = ScreenLoadingController(self)
        self._loading_controller.attach()
        return self._loading_controller

    def _set_loading_overlay(self, key, active, message="", detail=""):
        controller = self._ensure_loading_overlay()
        if active:
            controller.show(key, message, detail)
            return
        controller.hide(key)

    def _clear_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is not None:
            self._loading_controller.clear()

    def _set_background_task_loading(self, active, title):
        if active:
            self._background_task_title = str(title or "Tarefa tecnica em andamento...")
            self._set_loading_overlay(
                "settings_task",
                True,
                self._background_task_title,
                "A tarefa continua em segundo plano. Pode acompanhar o progresso tambem no dialogo.",
            )
            return
        self._background_task_title = ""
        self._set_loading_overlay("settings_task", False)

    def go_back(self):
        if not self.manager:
            return
        target = self.back_target if getattr(self, "back_target", None) in self.manager.screen_names else "admin_home"
        self.manager.current = target

    def _apply_responsive_layout(self, *args):
        width = float(self.width or Window.width or 0)
        grid_cols = {
            "hero_signal_grid": 4 if width >= dp(1260) else 2 if width >= dp(780) else 1,
            "prefs_grid": 4 if width >= dp(1240) else 2 if width >= dp(860) else 1,
            "devices_grid": 3 if width >= dp(1120) else 2 if width >= dp(760) else 1,
            "status_grid": 4 if width >= dp(1260) else 2 if width >= dp(860) else 1,
            "access_grid": 2 if width >= dp(980) else 1,
            "vat_grid": 2 if width >= dp(980) else 1,
            "system_grid": 2 if width >= dp(860) else 1,
            "cache_grid": 2 if width >= dp(980) else 1,
        }
        for grid_id, cols in grid_cols.items():
            grid = self.ids.get(grid_id)
            if grid is not None:
                grid.cols = cols

        hero_content = self.ids.get("hero_content")
        hero_actions = self.ids.get("hero_actions")
        if hero_content is not None:
            hero_content.orientation = "horizontal" if width >= dp(980) else "vertical"
            hero_content.spacing = dp(16) if width >= dp(980) else dp(12)
        if hero_actions is not None:
            hero_actions.orientation = "vertical" if width >= dp(980) else "horizontal"
            hero_actions.size_hint_x = None if width >= dp(980) else 1
            hero_actions.width = dp(260) if width >= dp(980) else 0

    def _enable_api_toggle(self, dt):
        self._api_toggle_ready = True

    def _enable_smart_monitor_toggle(self, dt):
        self._smart_monitor_toggle_ready = True

    def _enable_auto_banners_toggle(self, dt):
        self._auto_banners_toggle_ready = True
    
    def _enable_theme_toggle(self, dt):
        self._theme_toggle_ready = True

    def _enable_device_toggle(self, dt):
        self._device_toggle_ready = True

    def _bind_app_language(self):
        app = App.get_running_app()
        bound_app = getattr(self, "_language_bound_app", None)
        if not app or bound_app is app:
            return
        if bound_app is not None:
            try:
                bound_app.unbind(language=self._on_app_language)
            except Exception:
                pass
        try:
            app.bind(language=self._on_app_language)
            self._language_bound_app = app
        except Exception:
            self._language_bound_app = None

    def _on_app_language(self, *args):
        self._sync_language_state()

    def _tr(self, key, **kwargs):
        app = App.get_running_app()
        if app and hasattr(app, "t"):
            return app.t(key, **kwargs)
        return translate(key, **kwargs)

    def _sync_language_state(self):
        app = App.get_running_app()
        code = normalize_language(getattr(app, "language", "pt") if app else "pt")
        self.language_code = code
        self.language_label = language_label(code, include_short=True)

    def open_language_menu(self, caller=None):
        if getattr(self, "_language_menu", None):
            self._language_menu.dismiss()
            self._language_menu = None
        if caller is None and hasattr(self, "ids"):
            caller = self.ids.get("language_card")
        if caller is None:
            return
        items = []
        for option in language_options():
            code = option["code"]
            items.append(
                {
                    "text": f"{option['native_name']} ({option['short']})",
                    "height": dp(44),
                    "on_release": lambda selected=code: self._select_language(selected),
                }
            )
        self._language_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._language_menu.open()

    def _select_language(self, language_code):
        if getattr(self, "_language_menu", None):
            self._language_menu.dismiss()
            self._language_menu = None
        app = App.get_running_app()
        if app and hasattr(app, "set_language"):
            app.set_language(language_code)
        else:
            self._save_app_settings_fallback(language=normalize_language(language_code))
        self._sync_language_state()
        self.show_message(
            self._tr("common.success"),
            self._tr("settings.language.changed", language=self.language_label),
        )

    def _sync_device_settings_state(self):
        settings = get_device_settings(force_reload=True)
        self.physical_scanner_enabled = bool(settings.get("physical_scanner_enabled", True))
        self.receipt_auto_print = bool(settings.get("receipt_auto_print", False))
        printer_name = str(settings.get("receipt_printer_name") or "").strip()
        self.receipt_printer_name = printer_name or "Impressora padrao"
        self.receipt_paper_width_mm = int(settings.get("receipt_paper_width_mm") or 80)
        if hasattr(self, "ids"):
            scanner_toggle = self.ids.get("physical_scanner_toggle")
            if scanner_toggle is not None and scanner_toggle.active != self.physical_scanner_enabled:
                scanner_toggle.active = self.physical_scanner_enabled
            auto_toggle = self.ids.get("receipt_auto_print_toggle")
            if auto_toggle is not None and auto_toggle.active != self.receipt_auto_print:
                auto_toggle.active = self.receipt_auto_print

    def toggle_physical_scanner(self, enabled):
        if not getattr(self, "_device_toggle_ready", True):
            return
        save_device_settings(physical_scanner_enabled=bool(enabled))
        self._sync_device_settings_state()

    def toggle_receipt_auto_print(self, enabled):
        if not getattr(self, "_device_toggle_ready", True):
            return
        save_device_settings(receipt_auto_print=bool(enabled))
        self._sync_device_settings_state()

    def open_printer_settings(self):
        if self._printer_settings_dialog is not None:
            try:
                self._printer_settings_dialog.dismiss()
            except Exception:
                pass
            self._printer_settings_dialog = None
        printers = list_system_printers()
        default_printer = get_default_printer_name()
        settings = get_device_settings(force_reload=True)
        configured = str(settings.get("receipt_printer_name") or "").strip()
        selected_name = configured or default_printer
        width_value = int(settings.get("receipt_paper_width_mm") or 80)

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(16), dp(12), dp(16), dp(8)],
            adaptive_height=True,
        )

        detected_text = (
            "Detectadas: " + ", ".join(printers[:4])
            if printers
            else "Lista automatica indisponivel. Pode escrever o nome instalado no Windows."
        )
        if printers and len(printers) > 4:
            detected_text += f" (+{len(printers) - 4})"

        info = MDLabel(
            text=detected_text,
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(44),
        )
        info.bind(size=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)))
        content.add_widget(info)

        self._printer_name_field = MDTextField(
            text=selected_name,
            hint_text="Nome da impressora termica",
            helper_text="Deixe vazio para usar a impressora padrao do Windows.",
            helper_text_mode="persistent",
            mode="rectangle",
            size_hint_y=None,
            height=dp(64),
        )
        content.add_widget(self._printer_name_field)

        self._printer_width_field = MDTextField(
            text=str(width_value),
            hint_text="Largura do papel: 58 ou 80",
            helper_text="Use 58mm ou 80mm conforme a bobina da impressora.",
            helper_text_mode="persistent",
            input_filter="int",
            mode="rectangle",
            size_hint_y=None,
            height=dp(64),
        )
        content.add_widget(self._printer_width_field)

        self._printer_status_label = MDLabel(
            text="",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(34),
        )
        self._printer_status_label.bind(
            size=lambda inst, _value: setattr(inst, "text_size", (inst.width, None))
        )
        content.add_widget(self._printer_status_label)

        self._printer_settings_dialog = MDDialog(
            title="Impressora termica",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(620), Window.width * 0.92), dp(430)),
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda _x: self._printer_settings_dialog.dismiss()),
                MDFlatButton(text="Testar", on_release=lambda _x: self.test_receipt_printer()),
                MDRaisedButton(text="Salvar", on_release=lambda _x: self._save_printer_settings_from_dialog()),
            ],
        )
        self._printer_settings_dialog.open()

    def _save_printer_settings_from_dialog(self, close_dialog=True, silent=False):
        name = (
            self._printer_name_field.text.strip()
            if self._printer_name_field is not None
            else ""
        )
        width_text = (
            self._printer_width_field.text.strip()
            if self._printer_width_field is not None
            else ""
        )
        try:
            width = int(width_text or 80)
        except Exception:
            width = 80
        width = 58 if width <= 58 else 80
        save_device_settings(
            receipt_printer_name=name,
            receipt_paper_width_mm=width,
        )
        self._sync_device_settings_state()
        if self._printer_status_label is not None:
            label = name or "impressora padrao"
            self._printer_status_label.text = f"Configurada: {label} | {width}mm"
        if close_dialog and self._printer_settings_dialog is not None:
            self._printer_settings_dialog.dismiss()
        if not silent:
            self.show_message("Sucesso", "Configuracao da impressora atualizada.")
        return True

    def _build_test_receipt_data(self):
        return {
            "store_name": "MERCEARIA",
            "receipt_code": "TESTE",
            "issued_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "operator": getattr(App.get_running_app(), "current_user", None) or "Administrador",
            "items_count": 1,
            "items": [
                {
                    "name": "Teste de impressao termica",
                    "qty_text": "1 un",
                    "unit_price": 1.0,
                    "line_total": 1.0,
                    "sale_mode_label": "Teste",
                    "vat_tag": "",
                }
            ],
            "subtotal": 1.0,
            "vat_total": 0.0,
            "total": 1.0,
            "paid_amount": 1.0,
            "change_amount": 0.0,
            "vat_note": "Teste de configuracao da impressora.",
        }

    def test_receipt_printer(self):
        self._save_printer_settings_from_dialog(close_dialog=False, silent=True)
        settings = get_device_settings(force_reload=True)
        printer_name = str(settings.get("receipt_printer_name") or "").strip()
        paper_width = int(settings.get("receipt_paper_width_mm") or 80)
        if self._printer_status_label is not None:
            self._printer_status_label.text = "A enviar recibo de teste..."
        receipt_data = self._build_test_receipt_data()

        def worker():
            ok, message = print_thermal_receipt(
                receipt_data,
                printer_name=printer_name,
                paper_width_mm=paper_width,
            )
            Clock.schedule_once(lambda _dt, success=ok, msg=message: apply_result(success, msg), 0)

        def apply_result(success, message):
            if self._printer_status_label is not None:
                self._printer_status_label.text = message
            if success:
                self.show_message("Sucesso", message)
            else:
                self.show_message("Aviso", message)

        Thread(target=worker, daemon=True).start()

    def _settings_path(self):
        return str(APP_SETTINGS_FILE)

    def _dotenv_path(self):
        return str(ENV_FILE)

    def _read_env_values(self):
        env_path = self._dotenv_path()
        values = {}
        if not os.path.exists(env_path):
            return values
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if not key:
                        continue
                    values[key] = value.strip().strip('"').strip("'")
        except Exception:
            return {}
        return values

    def _write_env_values(self, updates):
        env_path = self._dotenv_path()
        lines = []
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except Exception:
                lines = []

        pending = {str(key): str(value) for key, value in (updates or {}).items()}
        written = []

        for raw_line in lines:
            stripped = raw_line.strip()
            candidate = stripped[7:].strip() if stripped.startswith("export ") else stripped
            if candidate and not candidate.startswith("#") and "=" in candidate:
                key = candidate.split("=", 1)[0].strip()
                if key in pending:
                    prefix = "export " if stripped.startswith("export ") else ""
                    written.append(f"{prefix}{key}={pending.pop(key)}")
                    continue
            written.append(raw_line)

        if pending:
            if written and written[-1].strip():
                written.append("")
            for key, value in pending.items():
                written.append(f"{key}={value}")

        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(written).rstrip() + "\n")

    @staticmethod
    def _mask_secret(value):
        secret = str(value or "").strip()
        if not secret:
            return "Nao configurada"
        tail = secret[-4:] if len(secret) >= 4 else "*" * len(secret)
        return f"Configurada (termina em {tail})"

    def _default_vat_rule_dicts(self):
        return [dict(rule) for rule in VAT_RULES]

    def _map_vat_row(self, row):
        if isinstance(row, dict):
            return dict(row)
        return {
            "code": row[0],
            "label": row[1],
            "short_label": row[2],
            "rate_percent": row[3],
            "taxable_ratio": row[4],
            "effective_from": row[5],
            "effective_to": row[6],
            "legal_reference": row[7],
            "description": row[8],
            "price_mode": row[9] if len(row) > 9 else "INCLUSIVE",
        }

    def _load_vat_rules(self):
        getter = getattr(self.db, "get_vat_rules", None)
        rows = []
        if callable(getter):
            try:
                rows = getter() or []
            except Exception:
                rows = []
        if not rows:
            rows = self._default_vat_rule_dicts()
        return [self._map_vat_row(row) for row in rows]

    def _refresh_vat_overview(self):
        try:
            rules = self._load_vat_rules()
            standard_rules = [rule for rule in rules if str(rule.get("code") or "").upper() == DEFAULT_VAT_RULE_CODE]
            if standard_rules:
                latest = sorted(standard_rules, key=lambda item: str(item.get("effective_from") or ""), reverse=True)[0]
                mode = str(latest.get("price_mode") or "INCLUSIVE").upper()
                mode_label = "preco final" if mode == "INCLUSIVE" else "preco base + IVA"
                self.vat_overview_text = (
                    f"Taxa geral ativa: {float(latest.get('rate_percent') or 0.0):.2f}% | "
                    f"Modo: {mode_label}"
                )
            else:
                self.vat_overview_text = "Taxa geral ativa: sem regra definida"
        except Exception:
            self.vat_overview_text = "Taxa geral ativa: sem regra definida"

    def open_gemini_settings(self):
        if not self._gemini_settings_dialog:
            content = MDBoxLayout(
                orientation="vertical",
                spacing=dp(12),
                padding=dp(16),
                adaptive_height=True,
            )

            intro = MDLabel(
                text="Atualize a chave e o modelo usados nas leituras avancadas do Gemini.",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(40),
            )
            content.add_widget(intro)

            self._gemini_status_label = MDLabel(
                text="",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(24),
            )
            content.add_widget(self._gemini_status_label)

            self._gemini_api_key_field = MDTextField(
                hint_text="Nova chave Gemini (opcional)",
                helper_text="Se deixar vazio, a chave atual e mantida.",
                helper_text_mode="persistent",
                password=True,
                mode="rectangle",
                size_hint_y=None,
                height=dp(64),
            )
            content.add_widget(self._gemini_api_key_field)

            self._gemini_model_field = MDTextField(
                hint_text="Modelo Gemini",
                helper_text="Ex.: models/gemini-2.5-flash",
                helper_text_mode="persistent",
                mode="rectangle",
                size_hint_y=None,
                height=dp(64),
            )
            content.add_widget(self._gemini_model_field)

            self._gemini_settings_dialog = MDDialog(
                title="Configurar Gemini",
                type="custom",
                content_cls=content,
                buttons=[
                    MDFlatButton(text="Cancelar", on_release=lambda _x: self._gemini_settings_dialog.dismiss()),
                    MDRaisedButton(text="Salvar", on_release=lambda _x: self._save_gemini_settings()),
                ],
            )

        env_values = self._read_env_values()
        current_key = str(env_values.get("GEMINI_API_KEY") or "").strip()
        current_model = str(env_values.get("GEMINI_MODEL") or "models/gemini-2.5-flash").strip()

        if self._gemini_status_label is not None:
            self._gemini_status_label.text = (
                f"Chave atual: {self._mask_secret(current_key)} | Modelo atual: {current_model}"
            )
        if self._gemini_api_key_field is not None:
            self._gemini_api_key_field.text = ""
        if self._gemini_model_field is not None:
            self._gemini_model_field.text = current_model

        self._gemini_settings_dialog.open()

    def _save_gemini_settings(self):
        env_values = self._read_env_values()
        current_key = str(env_values.get("GEMINI_API_KEY") or "").strip()
        current_model = str(env_values.get("GEMINI_MODEL") or "models/gemini-2.5-flash").strip()

        typed_key = (
            self._gemini_api_key_field.text.strip()
            if self._gemini_api_key_field is not None
            else ""
        )
        typed_model = (
            self._gemini_model_field.text.strip()
            if self._gemini_model_field is not None
            else ""
        )

        final_key = typed_key or current_key
        final_model = typed_model or current_model or "models/gemini-2.5-flash"
        lowered_key = final_key.lower()

        if not final_key:
            self.show_message("Erro", "Informe uma chave Gemini valida.")
            return
        if lowered_key in {"changeme", "your_api_key_here", "your_gemini_key_here"}:
            self.show_message("Erro", "Informe uma chave Gemini real.")
            return
        if final_key == current_key and final_model == current_model and not typed_key:
            self.show_message("Aviso", "Nenhuma alteracao foi feita.")
            return

        try:
            self._write_env_values({
                "GEMINI_API_KEY": final_key,
                "GEMINI_MODEL": final_model,
            })
            load_dotenv(override=True)
        except Exception as exc:
            self.show_message("Erro", f"Nao foi possivel atualizar o Gemini: {exc}")
            return

        if self._gemini_settings_dialog:
            self._gemini_settings_dialog.dismiss()
        self.show_message("Sucesso", "Configuracao do Gemini atualizada.")

    def _build_vat_input(self, text="", hint_text="", helper_text="", input_filter=None):
        field = MDTextField(
            text="" if text is None else str(text),
            hint_text=hint_text,
            mode="rectangle",
            size_hint_y=None,
            height=dp(52),
        )
        if input_filter:
            field.input_filter = input_filter
        if helper_text:
            field.helper_text = helper_text
            field.helper_text_mode = "persistent"
        return field

    def _build_vat_rule_editor(self, rule):
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        code = str(rule.get("code") or DEFAULT_VAT_RULE_CODE).strip().upper()
        short_label_value = str(rule.get("short_label") or "").strip() or code
        description_value = str(rule.get("description") or "").strip()
        legal_reference_value = str(rule.get("legal_reference") or "").strip()

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(12), dp(12), dp(12), dp(12)],
            spacing=dp(10),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        card.bind(minimum_height=card.setter("height"))

        header_card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(10), dp(10), dp(10), dp(10)],
            spacing=dp(4),
            radius=[dp(12)],
            elevation=0,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
        )
        header_card.bind(minimum_height=header_card.setter("height"))

        title = MDLabel(
            text=str(rule.get("label") or code),
            bold=True,
            font_style="Subtitle1",
            theme_text_color="Custom",
            text_color=tokens.get("text_primary", [0.15, 0.15, 0.15, 1]),
            size_hint_y=None,
        )
        title.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        header_card.add_widget(title)

        subtitle = MDLabel(
            text=f"Codigo: {code} | Etiqueta: {short_label_value}",
            font_style="Caption",
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.45, 0.45, 0.45, 1]),
            size_hint_y=None,
        )
        subtitle.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        header_card.add_widget(subtitle)

        if description_value:
            description_label = MDLabel(
                text=description_value,
                font_style="Caption",
                theme_text_color="Custom",
                text_color=tokens.get("text_secondary", [0.45, 0.45, 0.45, 1]),
                size_hint_y=None,
            )
            description_label.bind(
                width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
                texture_size=lambda inst, size: setattr(inst, "height", size[1]),
            )
            header_card.add_widget(description_label)

        card.add_widget(header_card)

        label_field = self._build_vat_input(
            text=rule.get("label") or "",
            hint_text="Rotulo da regra",
            helper_text="Ex.: Taxa geral ou Isencao temporaria",
        )
        short_field = self._build_vat_input(
            text=rule.get("short_label") or "",
            hint_text="Etiqueta curta",
            helper_text="Ex.: IVA 16%, Isento, IVA 5%",
        )
        rate_field = self._build_vat_input(
            text=rule.get("rate_percent") or 0,
            hint_text="Taxa %",
            helper_text="Percentagem usada no calculo",
            input_filter="float",
        )
        mode_field = self._build_vat_input(
            text=rule.get("price_mode") or "INCLUSIVE",
            hint_text="Modo de preco",
            helper_text="INCLUSIVE ou EXCLUSIVE",
        )
        start_field = self._build_vat_input(
            text=rule.get("effective_from") or "",
            hint_text="Inicio",
            helper_text="Formato YYYY-MM-DD",
        )
        end_field = self._build_vat_input(
            text=rule.get("effective_to") or "",
            hint_text="Fim",
            helper_text="Deixe vazio se ainda vigora",
        )

        identity_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(64),
        )
        label_field.size_hint_x = 0.66
        short_field.size_hint_x = 0.34
        identity_row.add_widget(label_field)
        identity_row.add_widget(short_field)
        card.add_widget(identity_row)

        calc_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(64),
        )
        rate_field.size_hint_x = 0.34
        mode_field.size_hint_x = 0.66
        calc_row.add_widget(rate_field)
        calc_row.add_widget(mode_field)
        card.add_widget(calc_row)

        period_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(64),
        )
        start_field.size_hint_x = 0.5
        end_field.size_hint_x = 0.5
        period_row.add_widget(start_field)
        period_row.add_widget(end_field)
        card.add_widget(period_row)

        footer_lines = []
        if legal_reference_value:
            footer_lines.append(f"Base legal: {legal_reference_value}")
        footer_lines.append("Nota: esta regra afeta apenas novas vendas.")
        footer_label = MDLabel(
            text=" | ".join(footer_lines),
            font_style="Caption",
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.45, 0.45, 0.45, 1]),
            size_hint_y=None,
        )
        footer_label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        card.add_widget(footer_label)

        self._vat_rule_form_rows.append(
            {
                "code": code,
                "label": label_field,
                "short_label": short_field,
                "rate_percent": rate_field,
                "price_mode": mode_field,
                "effective_from": start_field,
                "effective_to": end_field,
                "legal_reference": rule.get("legal_reference"),
                "description": rule.get("description"),
            }
        )
        return card

    def open_vat_settings(self):
        self._vat_rule_form_rows = []
        wrapper = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint_y=None,
            height=dp(640),
        )
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}

        intro_card = MDCard(
            size_hint_y=None,
            adaptive_height=True,
            padding=[dp(14), dp(14), dp(14), dp(14)],
            spacing=dp(6),
            radius=[dp(16)],
            elevation=0,
            orientation="vertical",
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        intro_card.bind(minimum_height=intro_card.setter("height"))
        intro_title = MDLabel(
            text="Edite cada regra por bloco",
            font_style="Subtitle1",
            bold=True,
            theme_text_color="Custom",
            text_color=tokens.get("text_primary", [0.15, 0.15, 0.15, 1]),
            size_hint_y=None,
        )
        intro_title.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        intro_card.add_widget(intro_title)

        intro = MDLabel(
            text=(
                "Ajuste taxa, modo de preco e vigencia em cada cartao. "
                "As vendas ja gravadas nao sao recalculadas."
            ),
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.45, 0.45, 0.45, 1]),
            size_hint_y=None,
        )
        intro.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        intro_card.add_widget(intro)
        wrapper.add_widget(intro_card)

        scroll = ScrollView(do_scroll_x=False)
        body = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(2), dp(2), dp(2), dp(8)],
            adaptive_height=True,
            size_hint_y=None,
        )
        body.bind(minimum_height=body.setter("height"))
        for rule in self._load_vat_rules():
            body.add_widget(self._build_vat_rule_editor(rule))
        scroll.add_widget(body)
        wrapper.add_widget(scroll)

        dialog = MDDialog(
            title="Regras de IVA",
            type="custom",
            content_cls=wrapper,
            size_hint=(0.94, None),
            height=min(Window.height * 0.92, dp(760)),
            buttons=[
                MDFlatButton(text="Restaurar oficiais", on_release=lambda _x: self._reset_vat_rules_from_dialog(dialog)),
                MDFlatButton(text="Cancelar", on_release=lambda _x: dialog.dismiss()),
                MDRaisedButton(text="Salvar", on_release=lambda _x: self._save_vat_rules_from_dialog(dialog)),
            ],
        )
        self._vat_settings_dialog = dialog
        dialog.open()

    def _save_vat_rules_from_dialog(self, dialog):
        payload = []
        for row in self._vat_rule_form_rows:
            payload.append(
                {
                    "code": row["code"],
                    "label": row["label"].text.strip() or row["code"],
                    "short_label": row["short_label"].text.strip() or row["label"].text.strip() or row["code"],
                    "rate_percent": row["rate_percent"].text.strip() or "0",
                    "effective_from": row["effective_from"].text.strip(),
                    "effective_to": row["effective_to"].text.strip(),
                    "price_mode": row["price_mode"].text.strip().upper() or "INCLUSIVE",
                    "legal_reference": row.get("legal_reference"),
                    "description": row.get("description"),
                }
            )

        saver = getattr(self.db, "replace_vat_rules", None)
        if not callable(saver):
            self._show_inline_message("Erro", "Base de dados nao suporta edicao de IVA.")
            return
        if not saver(payload):
            self._show_inline_message("Erro", "Nao foi possivel salvar as regras de IVA.")
            return

        self._sync_local_vat_rules_if_needed(payload=payload)
        dialog.dismiss()
        self._refresh_vat_overview()
        self._show_inline_message("Sucesso", "Regras de IVA atualizadas.")

    def _reset_vat_rules_from_dialog(self, dialog):
        resetter = getattr(self.db, "reset_vat_rules", None)
        if not callable(resetter):
            self._show_inline_message("Erro", "Base de dados nao suporta restauracao de IVA.")
            return
        if not resetter():
            self._show_inline_message("Erro", "Nao foi possivel restaurar as regras oficiais.")
            return
        self._sync_local_vat_rules_if_needed(reset=True)
        dialog.dismiss()
        self._refresh_vat_overview()
        self._show_inline_message("Sucesso", "Regras oficiais de IVA restauradas.")

    def _sync_local_vat_rules_if_needed(self, payload=None, reset=False):
        if not uses_remote_backend(self.db):
            return
        local_db = getattr(self.db, "local_db", None)
        if local_db is None:
            return
        try:
            if reset:
                local_resetter = getattr(local_db, "reset_vat_rules", None)
                if callable(local_resetter):
                    local_resetter()
                return
            local_saver = getattr(local_db, "replace_vat_rules", None)
            if callable(local_saver):
                local_saver(payload or [])
        except Exception:
            pass

    def _show_inline_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: x.parent.parent.parent.parent.dismiss())],
        ).open()

    def show_message(self, title, message):
        self._show_inline_message(title, message)

    def _save_app_settings_fallback(
        self,
        ai_enabled=None,
        smart_monitor_enabled=None,
        auto_banners_enabled=None,
        theme_style=None,
        language=None,
    ):
        try:
            settings_path = self._settings_path()
            data = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                except Exception:
                    data = {}
            if ai_enabled is not None:
                data["ai_enabled"] = bool(ai_enabled)
            if smart_monitor_enabled is not None:
                data["smart_monitor_enabled"] = bool(smart_monitor_enabled)
            if auto_banners_enabled is not None:
                data["auto_banners_enabled"] = bool(auto_banners_enabled)
            if theme_style:
                data["theme_style"] = theme_style
            if language:
                data["language"] = normalize_language(language)
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def toggle_smart_monitor(self, enabled):
        if not getattr(self, "_smart_monitor_toggle_ready", True):
            return
        self.monitor_enabled = bool(enabled)
        app = App.get_running_app()
        if app:
            app.smart_monitor_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=getattr(app, "ai_enabled", None),
                    smart_monitor_enabled=app.smart_monitor_enabled,
                    auto_banners_enabled=getattr(app, "auto_banners_enabled", None),
                    theme_style=getattr(app, "theme_style", None),
                )
        else:
            self._save_app_settings_fallback(smart_monitor_enabled=enabled)
        self._intelligence.set_enabled(bool(enabled))

    def toggle_auto_banners(self, enabled):
        if not getattr(self, "_auto_banners_toggle_ready", True):
            return
        self.auto_banners_enabled = bool(enabled)
        app = App.get_running_app()
        if app:
            app.auto_banners_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=getattr(app, "ai_enabled", None),
                    smart_monitor_enabled=getattr(app, "smart_monitor_enabled", None),
                    auto_banners_enabled=app.auto_banners_enabled,
                    theme_style=getattr(app, "theme_style", None),
                )
        else:
            self._save_app_settings_fallback(auto_banners_enabled=enabled)

    def toggle_ai(self, enabled):
        if not getattr(self, "_api_toggle_ready", True):
            return
        self.api_ai_enabled = bool(enabled)
        app = App.get_running_app()
        if app:
            app.ai_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=app.ai_enabled,
                    smart_monitor_enabled=getattr(app, "smart_monitor_enabled", None),
                    auto_banners_enabled=getattr(app, "auto_banners_enabled", None),
                    theme_style=getattr(app, "theme_style", None),
                )
        else:
            self._save_app_settings_fallback(ai_enabled=enabled)

    def toggle_theme(self, enabled):
        if not getattr(self, "_theme_toggle_ready", True):
            return
        self.dark_theme_enabled = bool(enabled)
        app = App.get_running_app()
        style = "Dark" if enabled else "Light"
        if app:
            if hasattr(app, "apply_theme"):
                app.apply_theme(style)
            elif hasattr(app, "save_app_settings"):
                app.theme_cls.theme_style = style
                app.theme_style = style
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=getattr(app, "ai_enabled", None),
                    smart_monitor_enabled=getattr(app, "smart_monitor_enabled", None),
                    auto_banners_enabled=getattr(app, "auto_banners_enabled", None),
                    theme_style=style,
                )
        else:
            self._save_app_settings_fallback(theme_style=style)

    # ------------------------------------------------------------------
    # Prefill Ranxo cache
    # ------------------------------------------------------------------
    def prefill_ranxo_cache(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Prefill Ranxo em andamento.")
            return

        dialog = MDDialog(
            title="Pre-carregar cache Ranxo",
            text="Isto pode demorar alguns minutos e usar internet. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_ranxo_prefill(dialog)),
            ],
        )
        dialog.open()

    def _confirm_ranxo_prefill(self, dialog):
        dialog.dismiss()
        self._start_ranxo_prefill()

    def _start_ranxo_prefill(self):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._set_background_task_loading(True, "A pre-carregar cache Ranxo...")
        self._ranxo_prefill_dialog = MDDialog(
            title="Pre-carregar cache Ranxo",
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_ranxo_prefill, daemon=True).start()

    def _dismiss_ranxo_prefill(self, *args):
        if self._ranxo_prefill_running:
            return
        if self._ranxo_prefill_dialog:
            self._ranxo_prefill_dialog.dismiss()
            self._ranxo_prefill_dialog = None

    def _run_ranxo_prefill(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_ranxo_progress(s), 0)

        stats = manager.prefill_ranxo_cache(on_progress=on_progress, delay=0.2)
        Clock.schedule_once(lambda dt, s=stats: self._finish_ranxo_prefill(s), 0)

    def _update_ranxo_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Sucessos: {stats.get('success', 0)}")
        lines.append(f"Sem codigo de barras: {stats.get('no_sku', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_ranxo_prefill(self, stats: dict):
        self._ranxo_prefill_running = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Prefill concluido.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Sucessos: {stats.get('success', 0)}",
            f"Sem codigo de barras: {stats.get('no_sku', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    # ------------------------------------------------------------------
    # Prefill Bazara cache (GraphQL)
    # ------------------------------------------------------------------
    def prefill_bazara_cache(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Pre-carregar cache Bazara",
            text="Vai buscar todos os produtos via GraphQL e abrir cada pagina para obter o codigo de barras. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_bazara_prefill(dialog)),
            ],
        )
        dialog.open()

    def _confirm_bazara_prefill(self, dialog):
        dialog.dismiss()
        self._start_bazara_prefill(reset=False)

    def backfill_bazara_barcodes(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Backfill codigos de barras Bazara",
            text="Vai buscar codigos de barras para itens ja no cache. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_bazara_backfill(dialog)),
            ],
        )
        dialog.open()

    def _confirm_bazara_backfill(self, dialog):
        dialog.dismiss()
        self._start_bazara_backfill()

    def reset_bazara_cache(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Reset cache Bazara",
            text="Vai apagar o cache Bazara e recriar do zero via GraphQL. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_reset_bazara(dialog)),
            ],
        )
        dialog.open()

    def _confirm_reset_bazara(self, dialog):
        dialog.dismiss()
        self._start_bazara_prefill(reset=True)

    def _start_bazara_prefill(self, reset: bool):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._bazara_prefill_reset = bool(reset)
        self._bazara_backfill_mode = False
        title = "Reset cache Bazara" if self._bazara_prefill_reset else "Pre-carregar cache Bazara"
        overlay_title = "A recriar cache Bazara..." if self._bazara_prefill_reset else "A pre-carregar cache Bazara..."
        self._set_background_task_loading(True, overlay_title)
        self._ranxo_prefill_dialog = MDDialog(
            title=title,
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_bazara_prefill, daemon=True).start()

    def _start_bazara_backfill(self):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._bazara_prefill_reset = False
        self._bazara_backfill_mode = True
        self._set_background_task_loading(True, "A completar codigos de barras Bazara...")
        self._ranxo_prefill_dialog = MDDialog(
            title="Backfill codigos de barras Bazara",
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_bazara_backfill, daemon=True).start()

    def _run_bazara_prefill(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_bazara_progress(s), 0)

        stats = manager.prefill_bazara_offline_cache(
            on_progress=on_progress,
            delay=0.2,
            reset=self._bazara_prefill_reset,
        )
        Clock.schedule_once(lambda dt, s=stats: self._finish_bazara_prefill(s), 0)

    def _run_bazara_backfill(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_bazara_backfill_progress(s), 0)

        stats = manager.backfill_bazara_barcodes(on_progress=on_progress, delay=0.2)
        Clock.schedule_once(lambda dt, s=stats: self._finish_bazara_backfill(s), 0)

    def _update_bazara_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Sucessos: {stats.get('success', 0)}")
        lines.append(f"Novos: {stats.get('new', 0)}")
        lines.append(f"Sem SKU: {stats.get('no_sku', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _update_bazara_backfill_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Atualizados: {stats.get('updated', 0)}")
        lines.append(f"Movidos: {stats.get('moved', 0)}")
        lines.append(f"Sem codigo de barras: {stats.get('no_barcode', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_bazara_prefill(self, stats: dict):
        self._ranxo_prefill_running = False
        self._bazara_prefill_reset = False
        self._bazara_backfill_mode = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Prefill concluido.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Sucessos: {stats.get('success', 0)}",
            f"Novos: {stats.get('new', 0)}",
            f"Sem SKU: {stats.get('no_sku', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_bazara_backfill(self, stats: dict):
        self._ranxo_prefill_running = False
        self._bazara_backfill_mode = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Backfill concluido.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Atualizados: {stats.get('updated', 0)}",
            f"Movidos: {stats.get('moved', 0)}",
            f"Sem codigo de barras: {stats.get('no_barcode', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    # ------------------------------------------------------------------
    # Atualizar cache via Open Food Facts
    # ------------------------------------------------------------------
    def prefill_openfoodfacts_cache(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Atualizar cache Open Food Facts",
            text="Vai usar os barcodes do banco e do cache atual para buscar no site oficial do Open Food Facts e guardar os dados offline. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_openfoodfacts_prefill(dialog)),
            ],
        )
        dialog.open()

    def _confirm_openfoodfacts_prefill(self, dialog):
        dialog.dismiss()
        self._start_openfoodfacts_prefill()

    def _start_openfoodfacts_prefill(self):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._set_background_task_loading(True, "A atualizar cache Open Food Facts...")
        self._ranxo_prefill_dialog = MDDialog(
            title="Atualizar cache Open Food Facts",
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_openfoodfacts_prefill, daemon=True).start()

    def _run_openfoodfacts_prefill(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_openfoodfacts_progress(s), 0)

        stats = manager.prefill_openfoodfacts_cache(on_progress=on_progress, delay=0.2)
        Clock.schedule_once(lambda dt, s=stats: self._finish_openfoodfacts_prefill(s), 0)

    def _update_openfoodfacts_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Encontrados: {stats.get('found', 0)}")
        lines.append(f"Sucessos: {stats.get('success', 0)}")
        lines.append(f"Novos: {stats.get('new', 0)}")
        lines.append(f"Atualizados: {stats.get('updated', 0)}")
        lines.append(f"Sem resultado: {stats.get('missing', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_openfoodfacts_prefill(self, stats: dict):
        self._ranxo_prefill_running = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Atualizacao concluida.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Encontrados: {stats.get('found', 0)}",
            f"Sucessos: {stats.get('success', 0)}",
            f"Novos: {stats.get('new', 0)}",
            f"Atualizados: {stats.get('updated', 0)}",
            f"Sem resultado: {stats.get('missing', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    # ------------------------------------------------------------------
    # Atualizar cache via UPCitemdb
    # ------------------------------------------------------------------
    def prefill_upcitemdb_cache(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Atualizar cache UPCitemdb",
            text="Vai usar os barcodes do cache atual e consultar UPCitemdb. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_upcitemdb_prefill(dialog)),
            ],
        )
        dialog.open()

    def _confirm_upcitemdb_prefill(self, dialog):
        dialog.dismiss()
        self._start_upcitemdb_prefill()

    def _start_upcitemdb_prefill(self):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._set_background_task_loading(True, "A atualizar cache UPCitemdb...")
        self._ranxo_prefill_dialog = MDDialog(
            title="Atualizar cache UPCitemdb",
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_upcitemdb_prefill, daemon=True).start()

    def _run_upcitemdb_prefill(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_upcitemdb_progress(s), 0)

        stats = manager.refresh_offline_cache_from_apis(
            source_names=["UPCitemdb"],
            on_progress=on_progress,
            delay=0.2,
        )
        Clock.schedule_once(lambda dt, s=stats: self._finish_upcitemdb_prefill(s), 0)

    def _update_upcitemdb_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Encontrados: {stats.get('found', 0)}")
        lines.append(f"Atualizados: {stats.get('updated', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_upcitemdb_prefill(self, stats: dict):
        self._ranxo_prefill_running = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Atualizacao concluida.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Encontrados: {stats.get('found', 0)}",
            f"Atualizados: {stats.get('updated', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    # ------------------------------------------------------------------
    # Atualizar cache via APIs (UPCitemdb/Ranxo/Open Food Facts)
    # ------------------------------------------------------------------
    def refresh_cache_from_apis(self):
        if self._ranxo_prefill_running:
            self.show_message("Aviso", "Outra tarefa em andamento.")
            return

        dialog = MDDialog(
            title="Atualizar cache via APIs",
            text="Vai usar os barcodes do cache atual e consultar UPCitemdb, Ranxo e Open Food Facts. Continuar?",
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text="Iniciar", on_release=lambda x: self._confirm_refresh_cache(dialog)),
            ],
        )
        dialog.open()

    def _confirm_refresh_cache(self, dialog):
        dialog.dismiss()
        self._start_refresh_cache()

    def _start_refresh_cache(self):
        if self._ranxo_prefill_running:
            return
        self._ranxo_prefill_running = True
        self._set_background_task_loading(True, "A atualizar cache via APIs...")
        self._ranxo_prefill_dialog = MDDialog(
            title="Atualizar cache via APIs",
            text="Preparando...",
            buttons=[MDFlatButton(text="Fechar", on_release=self._dismiss_ranxo_prefill)],
        )
        self._ranxo_prefill_dialog.open()
        Thread(target=self._run_refresh_cache, daemon=True).start()

    def _run_refresh_cache(self):
        db = getattr(self.app, "db", None) or get_db()
        manager = _get_api_manager_class()(
            database=db,
            on_success=lambda *args, **kwargs: None,
            on_failure=lambda *args, **kwargs: None,
            on_status=None,
        )

        def on_progress(stats):
            Clock.schedule_once(lambda dt, s=stats: self._update_refresh_progress(s), 0)

        stats = manager.refresh_offline_cache_from_apis(
            source_names=["UPCitemdb", "Ranxo", "Open Food Facts"],
            on_progress=on_progress,
            delay=0.2,
        )
        Clock.schedule_once(lambda dt, s=stats: self._finish_refresh_cache(s), 0)

    def _update_refresh_progress(self, stats: dict):
        if not self._ranxo_prefill_dialog:
            return
        message = stats.get("message")
        lines = []
        if message:
            lines.append(message)
        lines.append(f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}")
        lines.append(f"Encontrados: {stats.get('found', 0)}")
        lines.append(f"Atualizados: {stats.get('updated', 0)}")
        lines.append(f"Erros: {stats.get('errors', 0)}")
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    def _finish_refresh_cache(self, stats: dict):
        self._ranxo_prefill_running = False
        self._set_background_task_loading(False, "")
        if not self._ranxo_prefill_dialog:
            return
        lines = [
            "Atualizacao concluida.",
            f"Processados: {stats.get('processed', 0)}/{stats.get('total', 0)}",
            f"Encontrados: {stats.get('found', 0)}",
            f"Atualizados: {stats.get('updated', 0)}",
            f"Erros: {stats.get('errors', 0)}",
        ]
        self._ranxo_prefill_dialog.text = "\n".join(lines)

    # ------------------------------------------------------------------
    # Sistema de Notificacoes e Animacao de Abanar
    # ------------------------------------------------------------------
    def _init_badge(self, dt):
        """Inicializa o badge de notificacoes"""
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

    def add_notification(self):
        """Adiciona uma nova notificacao"""
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        """Limpa todas as notificacoes"""
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        """Atualiza o badge e controla a animacao vibrante"""
        self.notification_count = count

        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return

        self.ids.ai_badge_label.text = str(count)

        if count > 0:
            self._show_badge()
            self._start_swing_animation()
        else:
            self._hide_badge()
            self._stop_swing_animation()

    def _show_badge(self):
        """Mostra o badge com animacao pop"""
        if not hasattr(self.ids, 'ai_badge'):
            return

        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1

        anim = Animation(
            size=(dp(24), dp(24)),
            duration=0.3,
            transition='out_back'
        )
        anim.start(self.ids.ai_badge)

    def _hide_badge(self):
        """Esconde o badge com animacao"""
        if not hasattr(self.ids, 'ai_badge'):
            return

        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

    def _start_swing_animation(self):
        """Inicia animacao vibrante do botao"""
        if not hasattr(self.ids, 'ai_button'):
            return

        self._stop_swing_animation()

        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False

            original_pos = {"right": 0.965, "y": 0.04}

            swing = (
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.3, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.2, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.2, transition='in_out_sine') +
                Animation(pos_hint=original_pos, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True

        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)

    def _stop_swing_animation(self):
        """Para a animacao vibrante"""
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None

        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            anim = Animation(
                pos_hint={"right": 0.965, "y": 0.04},
                duration=0.2,
                transition='out_sine'
            )
            anim.start(self.ids.ai_button)
    
    def add_user(self):
        AddUserDialog().show()

    def configure_security_questions(self):
        if not self._security_questions_dialog:
            self._security_questions_dialog = SecurityQuestionsDialog()
        self._security_questions_dialog.show()

    def delete_manager(self):
        DeleteManagerDialog().show()
    
    def change_admin_data(self):
        if not self._change_admin_data_dialog:
            self._change_admin_data_dialog = ChangeAdminDataDialog()
        self._change_admin_data_dialog.show()
    
    def change_screen_size(self):
        ScreenSizeDialog(self.app).show()
    
    def view_system_logs(self):
        SystemLogsDialog().show()

    def show_ai_insights(self, *args):
        self.open_ai_menu()

    def open_ai_menu(self, caller=None):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._intelligence.open_history(caller=caller)

    def _open_ai_from_menu(self, key):
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
        self._intelligence.open_history(caller=caller)

    def open_ai_assistant(self, *args):
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
        self._intelligence.open_history(caller=caller)

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_auto_ai_popups(self, *args):
        self._intelligence.refresh()

    def update_ai_badge(self, *args):
        self.update_notification_badge(0)

    def _poll_ai_alerts(self, dt):
        self._intelligence.refresh()

    def _start_ai_polling(self):
        self._intelligence.start()

    def _stop_ai_polling(self):
        self._intelligence.stop()

