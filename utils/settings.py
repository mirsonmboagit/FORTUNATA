import sqlite3
import bcrypt
import os
import json
from datetime import datetime
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDRectangleFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel
from kivymd.uix.card import MDCard
from kivymd.uix.list import TwoLineListItem, OneLineListItem
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.selectioncontrol import MDCheckbox, MDSwitch
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.app import App
from kivy.animation import Animation
from database.database import Database
from pdfs.logs_report import LogsReport
from kivy.lang import Builder
from utils.ai_insights import build_admin_insights, build_admin_insights_ai
from utils.ai_popups import (
    build_auto_banner_data,
    build_banner_details_sections,
    render_auto_banners,
)
from utils.security_questions import QUESTIONS, hash_answer


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
                    on_press: root.manager.current = 'admin'
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
                                text: 'IA (Gemini)'
                                font_style: 'H6'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']

                        MDBoxLayout:
                            orientation: 'horizontal'
                            spacing: dp(10)

                            MDLabel:
                                text: 'Ativar insights automáticos'
                                theme_text_color: 'Custom'
                                text_color: app.theme_tokens['on_primary']
                                font_style: 'Body2'

                            Widget:

                            MDSwitch:
                                id: ai_toggle
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
            icon: 'icon/idea.ico'
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
                hint_text='Usuário Atual',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56)
            )
            content.add_widget(self.current_username)
            
            self.new_username = MDTextField(
                hint_text='Novo Usuário (opcional)',
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
        
        self.dialog.open()
    
    def dismiss(self, *args):
        self.dialog.dismiss()
    
    def save_changes(self, *args):
        current_username = self.current_username.text.strip()
        new_username = self.new_username.text.strip()
        current_password = self.current_password.text.strip()
        new_password = self.new_password.text.strip()
        confirm_password = self.confirm_password.text.strip()
        
        if not current_username or not current_password:
            self.show_message('Erro', 'Preencha usuário e senha atuais')
            return
        
        if new_password and new_password != confirm_password:
            self.show_message('Erro', 'As senhas não coincidem')
            return
        
        try:
            with Database() as db:
                db.cursor.execute(
                    "SELECT * FROM users WHERE username = ? AND role = 'admin'", 
                    (current_username,)
                )
                admin_data = db.cursor.fetchone()
                
                if not admin_data:
                    self.show_message('Erro', 'Usuário não encontrado ou não é administrador')
                    return
                
                role = db.validate_user(current_username, current_password)
                if role != 'admin':
                    self.show_message('Erro', 'Senha atual incorreta')
                    return
                
                if not new_username and not new_password:
                    self.show_message('Erro', 'Nenhuma alteração solicitada')
                    return
                
                update_parts = []
                update_params = []
                
                if new_username:
                    db.cursor.execute(
                        "SELECT * FROM users WHERE username = ? AND username != ?", 
                        (new_username, current_username)
                    )
                    if db.cursor.fetchone():
                        self.show_message('Erro', 'Este nome de usuário já está em uso')
                        return
                    
                    update_parts.append("username = ?")
                    update_params.append(new_username)
                
                if new_password:
                    update_parts.append("password = ?")
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
                    update_params.append(hashed_password)
                
                update_query = f"UPDATE users SET {', '.join(update_parts)} WHERE username = ? AND role = 'admin'"
                update_params.append(current_username)
                
                db.cursor.execute(update_query, update_params)
                db.conn.commit()
                
                db.log_action(
                    new_username if new_username else current_username,
                    'admin',
                    'UPDATE_ADMIN',
                    f'Dados do admin atualizados'
                )
                
                self.show_message('Sucesso', 'Dados atualizados com sucesso!')
                self.dialog.dismiss()
                
        except sqlite3.IntegrityError:
            self.show_message('Erro', 'Nome de usuário já existe')
        except Exception as e:
            self.show_message('Erro', f'Erro ao atualizar: {str(e)}')
    
    def show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())]
        ).open()


class AddUserDialog:
    def __init__(self):
        self.dialog = None
        self.db = Database()
        
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
                hint_text='Nome de Usu??rio',
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
                text='Fun????o:',
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
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
        if self.db.cursor.fetchone()[0] > 0:
            self.show_message('Erro', 'Nome de usuário já existe')
            return
        
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        email_value = email if email else None

        try:
            self.db.cursor.execute(
                "INSERT INTO users (username, password, role, email) VALUES (?, ?, ?, ?)", 
                (username, hashed_password, self.selected_role, email_value)
            )
            self.db.conn.commit()
            
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
        self.db = Database()

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
            self.db.cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', (username,))
            if self.db.cursor.fetchone()[0] == 0:
                self.show_message('Erro', 'Usuario nao encontrado')
                return

            hashes = [hash_answer(ans) for ans in answers]
            placeholder = hash_answer("__unused__")
            now = datetime.now().isoformat()
            self.db.cursor.execute(
                'INSERT OR REPLACE INTO user_security_questions '
                '(username, q1_hash, q2_hash, q3_hash, q4_hash, attempts, lock_until, updated_at) '
                'VALUES (?, ?, ?, ?, ?, 0, NULL, ?)',
                (username, hashes[0], hashes[1], hashes[2], placeholder, now)
            )
            self.db.conn.commit()

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
        with Database() as db:
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
            with Database() as db:
                db.cursor.execute(
                    "DELETE FROM users WHERE username = ? AND role = 'manager'", 
                    (self.selected_manager,)
                )
                db.conn.commit()
                
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
        btn_row.add_widget(search_btn)
        btn_row.add_widget(export_btn)
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

        query = "SELECT * FROM user_logs WHERE 1=1"
        params = []

        if user_filter:
            query += " AND username LIKE ?"
            params.append(f'%{user_filter}%')

        if action_filter:
            query += " AND action LIKE ?"
            params.append(f'%{action_filter}%')

        if role_filter:
            query += " AND role = ?"
            params.append(role_filter)

        query += " ORDER BY timestamp DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        with Database() as db:
            db.cursor.execute(query, params)
            return db.cursor.fetchall()

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
            pdf_path = LogsReport().generate(logs, filters)
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
        self.name = 'settings'
        self.notification_count = 0
        self._ai_poll_ev = None
        self._ai_toggle_ready = False
        self._theme_toggle_ready = False
        self._security_questions_dialog = None

    def on_kv_post(self, base_widget):
        self._ai_toggle_ready = False
        self._theme_toggle_ready = False
        app = App.get_running_app()
        enabled = bool(getattr(app, "ai_enabled", True)) if app else True
        if "ai_toggle" in self.ids:
            self.ids.ai_toggle.active = enabled
        if "theme_toggle" in self.ids:
            is_dark = bool(app and getattr(app.theme_cls, "theme_style", "Light") == "Dark")
            self.ids.theme_toggle.active = is_dark
        Clock.schedule_once(self._enable_ai_toggle, 0)
        Clock.schedule_once(self._enable_theme_toggle, 0)

    def on_enter(self):
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(self.update_ai_badge, 0.15)
        Clock.schedule_once(self.show_auto_ai_popups, 0.2)
        self._start_ai_polling()

    def on_leave(self):
        self._stop_ai_polling()

    def _enable_ai_toggle(self, dt):
        self._ai_toggle_ready = True
    
    def _enable_theme_toggle(self, dt):
        self._theme_toggle_ready = True

    def _settings_path(self):
        app = App.get_running_app()
        base_dir = getattr(app, "base_dir", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        return os.path.join(base_dir, "app_settings.json")

    def _save_app_settings_fallback(self, ai_enabled=None, theme_style=None):
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
            if theme_style:
                data["theme_style"] = theme_style
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def toggle_ai(self, enabled):
        if not getattr(self, "_ai_toggle_ready", True):
            return
        app = App.get_running_app()
        if app:
            app.ai_enabled = bool(enabled)
            if hasattr(app, "save_app_settings"):
                app.save_app_settings()
            else:
                self._save_app_settings_fallback(app.ai_enabled, getattr(app, "theme_style", None))
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
                self._save_app_settings_fallback(getattr(app, "ai_enabled", None), style)
        else:
            self._save_app_settings_fallback(theme_style=style)

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
        ChangeAdminDataDialog().show()
    
    def change_screen_size(self):
        ScreenSizeDialog(self.app).show()
    
    def view_system_logs(self):
        SystemLogsDialog().show()

    def _get_alert_key(self, insights):
        low_stock = sorted([item[0] for item in insights.get("low_stock", [])])
        exp7 = sorted([item[0] for item in insights.get("expiring_7", [])])
        exp15 = sorted([item[0] for item in insights.get("expiring_15", [])])

        parts = []
        if low_stock:
            parts.append("ls:" + ",".join(low_stock))
        if exp7:
            parts.append("e7:" + ",".join(exp7))
        if exp15:
            parts.append("e15:" + ",".join(exp15))
        return "|".join(parts)

    def mark_notifications_seen(self, insights=None):
        insights = insights or build_admin_insights()
        key = self._get_alert_key(insights)
        app = App.get_running_app()
        if app:
            app._ai_notifications_seen_key = key
        self.update_notification_badge(0)

    def show_ai_insights(self, *args):
        """Abrir notificacoes em formato de banner"""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = build_admin_insights_ai()
        banners = build_auto_banner_data(insights)
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def open_ai_menu(self, caller):
        app = App.get_running_app()
        insights = build_admin_insights()
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        stock_count = badge_counts.get("stock", 0)
        expiry_count = badge_counts.get("expiry_7", 0) + badge_counts.get("expiry_15", 0)
        total_count = badge_counts.get("total", 0)

        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            stock_count = 0
            expiry_count = 0
            total_count = 0

        def _label(base, count):
            return f"{base} ({count})" if count > 0 else base

        items = [
            {"text": _label("Insights completos", total_count), "on_release": lambda x="full": self._open_ai_from_menu(x)},
            {"text": _label("Reposicao de stock", stock_count), "on_release": lambda x="stock": self._open_ai_from_menu(x)},
            {"text": _label("Avisos de vencimento", expiry_count), "on_release": lambda x="expiry": self._open_ai_from_menu(x)},
        ]
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        self._ai_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._ai_menu.open()
        self.mark_notifications_seen()

    def _open_ai_from_menu(self, key):
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        if key == "stock":
            self.show_ai_stock_popup()
        elif key == "expiry":
            self.show_ai_expiry_popup()
        else:
            self.show_ai_insights()

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai()
        banners = [b for b in build_auto_banner_data(insights) if b.get("kind") == "stock"]
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai()
        banners = [b for b in build_auto_banner_data(insights) if b.get("kind") == "expiry"]
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_auto_ai_popups(self, *args):
        """Mostra banners automaticos (stock e vencimentos)."""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

        app = App.get_running_app()
        insights = build_admin_insights_ai()
        banners = build_auto_banner_data(insights)
        key = self._get_alert_key(insights)

        if not banners:
            if app:
                app._ai_banners_last_key = key
            return

        if app:
            last_key = getattr(app, "_ai_banners_last_key", None)
            if last_key == key:
                return
            app._ai_banners_last_key = key

        container = self.ids.ai_banner_container
        render_auto_banners(container, banners, auto_dismiss_seconds=10)

    def update_ai_badge(self, *args):
        """Atualiza o badge do botao de insights com animacao vibrante."""
        insights = build_admin_insights()
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        count = badge_counts.get("total", 0)

        if not key:
            count = 0

        app = App.get_running_app()
        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            count = 0

        self.update_notification_badge(count)

    def _poll_ai_alerts(self, dt):
        self.update_ai_badge()
        self.show_auto_ai_popups()

    def _start_ai_polling(self):
        if self._ai_poll_ev:
            self._ai_poll_ev.cancel()
        self._ai_poll_ev = Clock.schedule_interval(self._poll_ai_alerts, 30)

    def _stop_ai_polling(self):
        if self._ai_poll_ev:
            self._ai_poll_ev.cancel()
            self._ai_poll_ev = None
