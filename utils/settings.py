import sqlite3
import os
import json
from datetime import datetime
from threading import Thread
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDRectangleFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel
from kivymd.uix.card import MDCard
from kivymd.uix.list import TwoLineListItem, OneLineListItem
from kivymd.uix.selectioncontrol import MDCheckbox, MDSwitch
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.app import App
from kivy.animation import Animation
from database.provider import get_db
from AI.controller import ProactiveIntelligenceController
from kivy.lang import Builder
from utils.security_questions import QUESTIONS


def _get_logs_report_class():
    from pdfs.logs_report import LogsReport
    return LogsReport


def _get_api_manager_class():
    from api.api_manager import APIManager
    return APIManager


Builder.load_string('''
<BadgeButton@MDCard+ButtonBehavior>:
    ripple_behavior: True

<AdminSettingsScreen>:
    md_bg_color: app.theme_cls.bg_normal

    FloatLayout:
        MDBoxLayout:
            orientation: 'vertical'
            padding: dp(30)
            spacing: dp(20)

            MDBoxLayout:
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(80)
                spacing: dp(20)

                MDBoxLayout:
                    orientation: 'vertical'
                    spacing: dp(5)

                    MDLabel:
                        text: 'Configurações'
                        font_style: 'H4'
                        theme_text_color: 'Primary'

                    MDLabel:
                        text: 'Painel de Administração'
                        font_style: 'Body1'
                        theme_text_color: 'Secondary'

                Widget:
                    size_hint_x: 0.4

                MDRectangleFlatButton:
                    text: 'Voltar'
                    icon: 'arrow-left'
                    on_press: root.go_back()
                    size_hint: None, None
                    size: dp(130), dp(48)
                    pos_hint: {'center_y': 0.5}

            MDScrollView:

                MDGridLayout:
                    cols: 2
                    spacing: dp(20)
                    padding: dp(10)
                    adaptive_height: True
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.7, 0.3, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.add_user()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'account-plus'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Adicionar Usuário'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.6, 0.8, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.configure_security_questions()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'help-circle'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Perguntas de Recuperacao'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.9, 0.3, 0.3, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.delete_manager()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'account-remove'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Apagar Gerente'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.3, 0.5, 0.8, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.change_admin_data()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'account-edit'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Alterar Dados Admin'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.6, 0.4, 0.8, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.change_screen_size()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'monitor-screenshot'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Dimensões da Tela'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.8, 0.6, 0.2, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.view_system_logs()
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'text-box-search'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Logs do Sistema'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.15, 0.55, 0.7, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.prefill_ranxo_cache()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'database'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Pre-carregar cache Ranxo'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.55, 0.45, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.prefill_bazara_cache()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'database'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Pre-carregar cache Bazara'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.7, 0.35, 0.2, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.reset_bazara_cache()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'refresh'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Reset cache Bazara'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.4, 0.5, 0.8, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.backfill_bazara_barcodes()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'barcode'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Backfill codigos de barras Bazara'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.45, 0.7, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.prefill_upcitemdb_cache()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'database'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Atualizar cache UPCitemdb'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.5, 0.6, 1
                        radius: [15]
                        ripple_behavior: True
                        on_press: root.refresh_cache_from_apis()

                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)

                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)

                                MDIcon:
                                    icon: 'cloud-sync'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'

                            MDLabel:
                                text: 'Atualizar cache (APIs)'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.25, 0.45, 0.3, 1
                        radius: [15]
                        ripple_behavior: True

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)
                            size_hint_y: None
                            height: dp(40)

                            MDIcon:
                                icon: 'robot'
                                font_size: dp(32)
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                            MDLabel:
                                text: 'Monitor Inteligente'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)

                            MDLabel:
                                text: 'Ativar banners inteligentes'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                font_style: 'Body2'

                            Widget:

                            MDSwitch:
                                id: smart_monitor_toggle
                                active: True
                                on_active: root.toggle_smart_monitor(self.active)

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.22, 0.40, 0.62, 1
                        radius: [15]
                        ripple_behavior: True

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)
                            size_hint_y: None
                            height: dp(40)

                            MDIcon:
                                icon: 'api'
                                font_size: dp(32)
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'

                            MDLabel:
                                text: 'Gemini / API'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)

                            MDLabel:
                                text: 'Ativar analise externa opcional'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                font_style: 'Body2'

                            Widget:

                            MDSwitch:
                                id: api_ai_toggle
                                active: True
                                on_active: root.toggle_ai(self.active)

                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: app.theme_tokens['card_alt']
                        radius: [15]
                        ripple_behavior: True

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)
                            size_hint_y: None
                            height: dp(40)

                            MDIcon:
                                icon: 'weather-night'
                                font_size: dp(32)
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['text_primary']
                                halign: 'center'

                            MDLabel:
                                text: 'Modo Escuro'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['text_primary']

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)

                            MDLabel:
                                text: 'Ativar tema escuro'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['text_secondary']
                                font_style: 'Body2'

                            Widget:

                            MDSwitch:
                                id: theme_toggle
                                active: False
                                on_active: root.toggle_theme(self.active)
                
                    MDCard:
                        orientation: 'vertical'
                        padding: dp(20)
                        spacing: dp(10)
                        size_hint_y: None
                        height: dp(120)
                        md_bg_color: 0.2, 0.6, 0.7, 1
                        radius: [15]
                        ripple_behavior: True
                    
                        MDBoxLayout:
                            orientation: 'vertical'
                            spacing: dp(8)
                        
                            MDBoxLayout:
                                size_hint_y: None
                                height: dp(40)
                            
                                MDIcon:
                                    icon: 'shield-lock'
                                    font_size: dp(32)
                                    theme_text_color: 'Custom'
                                    text_color: app.theme_tokens['on_primary']
                                    halign: 'center'
                            
                            MDLabel:
                                text: 'Segurança'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                halign: 'center'
        MDFloatingActionButton:
            id: ai_button
            icon: 'assets/icon/idea.ico'
            elevation: 6
            pos_hint: {'right': 0.965, 'y': 0.04}
            on_release: root.open_ai_menu(self)

        # Badge com numero de notificacoes (so aparece quando > 0)
        MDCard:
            id: ai_badge
            size_hint: None, None
            size: dp(24), dp(24)
            md_bg_color: app.theme_tokens['badge']
            radius: [dp(12)]
            elevation: 8
            pos_hint: {'right': 0.978, 'y': 0.098}
            opacity: 0

            MDLabel:
                id: ai_badge_label
                text: '0'
                halign: 'center'
                valign: 'middle'
                theme_text_color: 'Custom'
                text_color: app.theme_tokens['on_primary']
                font_size: dp(12)
                bold: True

        FloatLayout:
            id: ai_banner_container
            size_hint: 1, 1
            pos: 0, 0
''')


class ChangeAdminDataDialog:
    def __init__(self):
        self.dialog = None

    def show(self):
        app = App.get_running_app()
        session_user = (getattr(app, 'current_user', None) or '').strip() if app else ''
        session_role = (getattr(app, 'current_role', None) or '').strip() if app else ''

        if session_role and session_role != 'admin':
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
                    self.show_message('Erro', 'Usuario nao encontrado ou nao e administrador')
                    return

                role = db.validate_user(current_username, current_password)
                if role != 'admin':
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
    def __init__(self):
        self.dialog = None
        self.db = get_db()
        
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
        
        self.dialog.open()
    
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
    
    def dismiss(self, *args):
        self.dialog.dismiss()
    
    def save_user(self, *args):
        username = self.username.text.strip()
        password = self.password.text.strip()
        email = self.email.text.strip() if hasattr(self, "email") else ""
        
        if not username or not password or not self.selected_role:
            self.show_message('Erro', 'Todos os campos são obrigatórios')
            return
        
        if self.db.user_exists(username):
            self.show_message('Erro', 'Nome de usuário já existe')
            return

        email_value = email if email else None

        try:
            if not self.db.create_user(username, password, self.selected_role, email=email_value):
                self.show_message('Erro', 'Não foi possível criar o usuário')
                return

            self.db.log_action(
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
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())]
        ).open()


class SecurityQuestionsDialog:
    def __init__(self):
        self.dialog = None
        self.db = get_db()

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
    def __init__(self):
        self.dialog = None
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
        
    def show(self):
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(10),
            adaptive_height=True
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
        
        filter_box.add_widget(self.user_filter)
        filter_box.add_widget(self.action_filter)
        content.add_widget(filter_box)

        role_box = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(8),
            size_hint_y=None,
            height=dp(40)
        )
        role_box.add_widget(MDLabel(
            text='Somente gerente',
            size_hint_x=None,
            width=dp(140),
            valign='middle'
        ))
        self.manager_only = MDCheckbox(active=False)
        role_box.add_widget(self.manager_only)
        role_box.add_widget(MDLabel())
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
            on_release=lambda x: self.load_logs()
        )
        export_btn = MDRectangleFlatButton(
            text='EXPORTAR PDF',
            size_hint_y=None,
            height=dp(40),
            on_release=lambda x: self.export_logs_pdf()
        )
        clear_btn = MDRectangleFlatButton(
            text='LIMPAR LOGS',
            size_hint_y=None,
            height=dp(40),
            on_release=lambda x: self._confirm_clear_logs()
        )
        btn_row.add_widget(search_btn)
        btn_row.add_widget(export_btn)
        btn_row.add_widget(clear_btn)
        content.add_widget(btn_row)
        
        from kivymd.uix.scrollview import MDScrollView
        scroll = MDScrollView(size_hint=(1, None), height=dp(400))
        
        self.logs_list = MDBoxLayout(
            orientation='vertical',
            spacing=dp(5),
            adaptive_height=True
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
                    on_release=lambda x: self.dialog.dismiss()
                )
            ]
        )
        
        self.load_logs()
        self.dialog.open()

    def _fetch_logs(self, limit=100):
        user_filter = self.user_filter.text.strip() if hasattr(self, 'user_filter') else ''
        action_filter = self.action_filter.text.strip() if hasattr(self, 'action_filter') else ''
        role_filter = 'manager' if getattr(self, 'manager_only', None) and self.manager_only.active else ''

        with get_db() as db:
            return db.get_user_logs(user_filter, action_filter, role_filter, limit=limit)

    def load_logs(self):
        self.logs_list.clear_widgets()
        try:
            logs = self._fetch_logs(limit=100)
            if not logs:
                self.logs_list.add_widget(MDLabel(
                    text='Nenhum log encontrado',
                    theme_text_color='Secondary',
                    halign='center',
                    size_hint_y=None,
                    height=dp(50)
                ))
                return

            for log in logs:
                log_id, username, role, action, details, timestamp = log
                
                timestamp_formatted = self.format_timestamp(timestamp)
                action_label = self._action_to_label(action)
                
                action_icons = {
                    'LOGIN': 'login',
                    'LOGOUT': 'logout',
                    'CREATE_USER': 'account-plus',
                    'DELETE_USER': 'account-remove',
                    'UPDATE_ADMIN': 'account-edit',
                    'ADD_PRODUCT': 'package-variant-closed-plus',
                    'UPDATE_PRODUCT': 'package-variant-closed-check',
                    'DELETE_PRODUCT': 'package-variant-closed-remove',
                    'SALE': 'cart-check',
                    'CANCEL_SALE': 'cart-remove',
                    'SAVE_RECEIPT': 'content-save',
                }
                
                icon = action_icons.get(action, 'information')
                
                log_card = MDCard(
                    orientation='horizontal',
                    padding=dp(15),
                    spacing=dp(15),
                    size_hint_y=None,
                    height=dp(80),
                    radius=[10],
                    md_bg_color=(0.95, 0.95, 0.97, 1)
                )
                
                from kivymd.uix.boxlayout import MDBoxLayout as BL
                icon_box = BL(size_hint_x=None, width=dp(50))
                from kivymd.uix.label import MDIcon
                log_icon = MDIcon(
                    icon=icon,
                    font_size=dp(32),
                    theme_text_color='Primary',
                    halign='center'
                )
                icon_box.add_widget(log_icon)
                log_card.add_widget(icon_box)
                
                info_box = BL(orientation='vertical', spacing=dp(5))
                
                header = BL(orientation='horizontal', size_hint_y=None, height=dp(25))
                header.add_widget(MDLabel(
                    text=f'[b]{username}[/b] ({role})',
                    markup=True,
                    size_hint_x=0.5,
                    font_style='Body2'
                ))
                header.add_widget(MDLabel(
                    text=timestamp_formatted,
                    theme_text_color='Secondary',
                    size_hint_x=0.5,
                    halign='right',
                    font_style='Caption'
                ))
                info_box.add_widget(header)
                
                info_box.add_widget(MDLabel(
                    text=f'[b]{action_label}[/b]',
                    markup=True,
                    font_style='Body2',
                    size_hint_y=None,
                    height=dp(20)
                ))
                
                if details:
                    info_box.add_widget(MDLabel(
                        text=details,
                        theme_text_color='Secondary',
                        font_style='Caption',
                        size_hint_y=None,
                        height=dp(20)
                    ))
                
                log_card.add_widget(info_box)
                self.logs_list.add_widget(log_card)
                        
        except Exception as e:
            self.logs_list.add_widget(MDLabel(
                text=f'Erro ao carregar logs: {str(e)}',
                theme_text_color='Error',
                halign='center',
                size_hint_y=None,
                height=dp(50)
            ))

    def _confirm_clear_logs(self):
        dialog = MDDialog(
            title='Limpar Logs',
            text='Tem certeza que deseja apagar todos os logs do sistema?',
            buttons=[
                MDFlatButton(text='CANCELAR', on_release=lambda x: dialog.dismiss()),
                MDRaisedButton(text='LIMPAR', on_release=lambda x: self._clear_logs(dialog)),
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
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: dialog.dismiss())],
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
        try:
            logs = self._fetch_logs(limit=None)
            if not logs:
                self._show_simple_dialog("Aviso", "Nenhum log para exportar.")
                return

            filters = {
                "user": self.user_filter.text.strip(),
                "action": self.action_filter.text.strip(),
                "role": "manager" if self.manager_only.active else "todos",
            }
            pdf_path = _get_logs_report_class()().generate(logs, filters)
            self._show_simple_dialog("PDF Gerado", f"Arquivo criado em:\\n{pdf_path}")
        except Exception as e:
            self._show_simple_dialog("Erro", f"Falha ao gerar PDF: {e}")

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


class ScreenSizeDialog:
    def __init__(self, app):
        self.app = app
        self.dialog = None
        
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
            self.show_message('Sucesso', f'Tela: {width}x{height}')
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
        self._theme_toggle_ready = False
        self._security_questions_dialog = None
        self._change_admin_data_dialog = None
        self._ranxo_prefill_dialog = None
        self._ranxo_prefill_running = False
        self._bazara_prefill_reset = False
        self._bazara_backfill_mode = False

    def on_kv_post(self, base_widget):
        self._api_toggle_ready = False
        self._smart_monitor_toggle_ready = False
        self._theme_toggle_ready = False
        app = App.get_running_app()
        enabled = bool(getattr(app, "smart_monitor_enabled", True)) if app else True
        api_enabled = bool(getattr(app, "ai_enabled", True)) if app else True
        if "smart_monitor_toggle" in self.ids:
            self.ids.smart_monitor_toggle.active = enabled
        if "api_ai_toggle" in self.ids:
            self.ids.api_ai_toggle.active = api_enabled
        if "theme_toggle" in self.ids:
            is_dark = bool(app and getattr(app.theme_cls, "theme_style", "Light") == "Dark")
            self.ids.theme_toggle.active = is_dark
        Clock.schedule_once(self._enable_api_toggle, 0)
        Clock.schedule_once(self._enable_smart_monitor_toggle, 0)
        Clock.schedule_once(self._enable_theme_toggle, 0)

    def on_enter(self):
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)

    def on_leave(self):
        self._stop_ai_polling()

    def go_back(self):
        if not self.manager:
            return
        target = self.back_target if getattr(self, "back_target", None) in self.manager.screen_names else "admin_home"
        self.manager.current = target

    def _enable_api_toggle(self, dt):
        self._api_toggle_ready = True

    def _enable_smart_monitor_toggle(self, dt):
        self._smart_monitor_toggle_ready = True
    
    def _enable_theme_toggle(self, dt):
        self._theme_toggle_ready = True

    def _settings_path(self):
        app = App.get_running_app()
        base_dir = getattr(app, "base_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        return os.path.join(base_dir, "app_settings.json")

    def _save_app_settings_fallback(self, ai_enabled=None, smart_monitor_enabled=None, theme_style=None):
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
            if theme_style:
                data["theme_style"] = theme_style
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def toggle_smart_monitor(self, enabled):
        if not getattr(self, "_smart_monitor_toggle_ready", True):
            return
        app = App.get_running_app()
        if app:
            app.smart_monitor_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=getattr(app, "ai_enabled", None),
                    smart_monitor_enabled=app.smart_monitor_enabled,
                    theme_style=getattr(app, "theme_style", None),
                )
        else:
            self._save_app_settings_fallback(smart_monitor_enabled=enabled)
        self._intelligence.set_enabled(bool(enabled))

    def toggle_ai(self, enabled):
        if not getattr(self, "_api_toggle_ready", True):
            return
        app = App.get_running_app()
        if app:
            app.ai_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(
                    ai_enabled=app.ai_enabled,
                    smart_monitor_enabled=getattr(app, "smart_monitor_enabled", None),
                    theme_style=getattr(app, "theme_style", None),
                )
        else:
            self._save_app_settings_fallback(ai_enabled=enabled)

    def toggle_theme(self, enabled):
        if not getattr(self, "_theme_toggle_ready", True):
            return
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
        self._intelligence.open_history()

    def _open_ai_from_menu(self, key):
        self._intelligence.open_history()

    def open_ai_assistant(self, *args):
        self._intelligence.open_history()

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

