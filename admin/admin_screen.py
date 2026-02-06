from kivy.uix.screenmanager import Screen
from kivy.properties import ObjectProperty, ListProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.app import App
from kivy.graphics import Color, Line
from kivy.animation import Animation
from datetime import datetime

from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.snackbar import MDSnackbar

from database.database import Database
from utils.ai_insights import build_admin_insights, build_admin_insights_ai
from utils.ai_popups import (
    build_auto_banner_data,
    build_banner_details_sections,
    render_auto_banners,
)
from .detail_popup import DetailPopup
from .product_form import ProductForm


Builder.load_file('admin/admin_screen.kv')


# ---------------------------------------------------------------------------
# Column proportions – ajustadas para melhor distribuição
# ---------------------------------------------------------------------------
COL_HINTS = [0.06, 0.20, 0.09, 0.09, 0.07, 0.11, 0.11, 0.13, 0.14]


class AdminScreen(Screen):
    product_table = ObjectProperty(None)
    search_input = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    products = ListProperty([])

    def __init__(self, **kwargs):
        super(AdminScreen, self).__init__(**kwargs)
        self.db = Database()
        self.category_menu = None
        self._manual_categories = set()
        
        # Variáveis para controle de notificações e animação
        self.swing_event = None
        self.notification_count = 0
        
        Window.bind(on_resize=self._on_window_resize)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_enter(self):
        self.load_products()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(self.update_ai_badge, 0.15)
        Clock.schedule_once(self.show_auto_ai_popups, 0.2)

    def _on_window_resize(self, instance, width, height):
        """Rebuild table rows so every cell re-measures at the new size."""
        Clock.unschedule(self._deferred_rebuild)
        Clock.schedule_once(self._deferred_rebuild, 0.15)

    def _deferred_rebuild(self, dt):
        if hasattr(self, '_current_display'):
            self.update_product_table(self._current_display)
        else:
            self.update_product_table(self.products)

    # ------------------------------------------------------------------
    # Sistema de Notificações e Animação de Abanar
    # ------------------------------------------------------------------
    def _init_badge(self, dt):
        """Inicializa o badge de notificações"""
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

    def add_notification(self):
        """Adiciona uma nova notificação"""
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        """Limpa todas as notificações"""
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        """
        Atualiza o badge e controla a animação de abanar
        
        Args:
            count (int): Número de notificações
        """
        self.notification_count = count
        
        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return
        
        # Atualizar texto
        self.ids.ai_badge_label.text = str(count)
        
        if count > 0:
            self._show_badge()
            self._start_swing_animation()
        else:
            self._hide_badge()
            self._stop_swing_animation()

    def _show_badge(self):
        """Mostra o badge com animação pop"""
        if not hasattr(self.ids, 'ai_badge'):
            return
        
        # Pop in animation
        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1
        
        anim = Animation(
            size=(dp(24), dp(24)),
            duration=0.3,
            transition='out_back'
        )
        anim.start(self.ids.ai_badge)

    def _hide_badge(self):
        """Esconde o badge com animação"""
        if not hasattr(self.ids, 'ai_badge'):
            return
        
        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

    def _start_swing_animation(self):
        """Inicia animação de abanar/balançar a lâmpada"""
        if not hasattr(self.ids, 'ai_button'):
            return
        
        self._stop_swing_animation()
        
        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False
            
            # Usar pos_hint para criar efeito de balanço (movimento lateral e vertical)
            original_pos = {"right": 0.965, "y": 0.04}
            
            # Sequência de balanço simulando oscilação
            swing = (
                # Balanço para direita-cima
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                # Balanço para esquerda-baixo
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.3, transition='in_out_sine') +
                # Balanço direita-meio
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                # Balanço esquerda-meio
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                # Balanço direita-pequeno
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.2, transition='in_out_sine') +
                # Balanço esquerda-pequeno
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.2, transition='in_out_sine') +
                # Volta ao centro
                Animation(pos_hint=original_pos, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True
        
        # Executar balanço a cada 2.5 segundos
        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)  # Executar imediatamente
    
    def _stop_swing_animation(self):
        """Para a animação de abanar"""
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None
        
        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            
            # Retornar à posição original
            anim = Animation(
                pos_hint={"right": 0.965, "y": 0.04},
                duration=0.2,
                transition='out_sine'
            )
            anim.start(self.ids.ai_button)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def go_to_definitions(self):
        self.manager.current = 'settings'

    def logout(self):
        app = App.get_running_app()
        if app and app.current_user:
            Database().log_action(app.current_user, app.current_role or "admin", "LOGOUT", "Logout admin")
            app.current_user = None
            app.current_role = None
        if app:
            app._ai_banners_shown = False
            app._ai_notifications_seen_key = None
        self.manager.current = "login"

    # ------------------------------------------------------------------
    # Category Menu
    # ------------------------------------------------------------------
    def get_categories(self):
        categories = set(self._manual_categories)
        for p in self.products:
            if len(p) > 11 and p[11]:
                categories.add(p[11])
        return sorted(categories)

    def register_category(self, category):
        if category:
            self._manual_categories.add(category)
        if self.category_menu:
            self.category_menu.dismiss()
            self.category_menu = None

    def show_category_menu(self, button):
        """Show dropdown menu for category selection"""
        menu_items = [
            {
                "text": "Todas as Categorias",
                "on_release": lambda x="Todas": self.set_category(x),
            }
        ]

        for cat in self.get_categories():
            menu_items.append({
                "text": cat,
                "on_release": lambda x=cat: self.set_category(x),
            })

        if self.category_menu:
            self.category_menu.dismiss()

        self.category_menu = MDDropdownMenu(
            caller=button,
            items=menu_items,
            width_mult=4,
        )
        
        self.category_menu.open()

    def set_category(self, category):
        """Set the selected category and filter products"""
        self.category_spinner.text = category if category != "Todas" else "Todas as Categorias"
        if self.category_menu:
            self.category_menu.dismiss()
        self.filter_products(self.search_input.text if self.search_input else "")

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------
    def filter_products(self, search_text):
        category_text = self.category_spinner.text
        category = category_text if category_text != "Todas as Categorias" else "Todas"
        filtered = []

        for product in self.products:
            search_match = (
                search_text.lower() in str(product[0]).lower() or
                search_text.lower() in product[1].lower() or
                (len(product) > 11 and search_text.lower() in str(product[11]).lower()) or
                (len(product) > 12 and product[12] and search_text.lower() in str(product[12]).lower())
            )
            category_match = (
                category in ('Todas', 'Todas as Categorias') or
                (len(product) > 11 and category == product[11])
            )
            if search_match and category_match:
                filtered.append(product)

        self.update_product_table(filtered)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_products(self):
        self.products = self.db.get_all_products()
        self.update_product_table(self.products)

    # ------------------------------------------------------------------
    # Date formatting
    # ------------------------------------------------------------------
    def format_datetime(self, datetime_str):
        try:
            if datetime_str and datetime_str != "N/A":
                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                return dt.strftime("%d/%m/%Y\n%H:%M")
        except Exception as e:
            print(f"Erro ao formatar data: {e}")
        return datetime_str

    def format_date(self, date_str):
        try:
            if date_str and date_str != "N/A":
                try:
                    dt = datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S")
                    return dt.strftime("%d/%m/%Y")
                except ValueError:
                    dt = datetime.strptime(str(date_str), "%Y-%m-%d")
                    return dt.strftime("%d/%m/%Y")
        except Exception as e:
            print(f"Erro ao formatar data: {e}")
        return str(date_str)

    # ------------------------------------------------------------------
    # Responsive sizing
    # ------------------------------------------------------------------
    def _row_height(self):
        """Compute a single row height that scales with the window."""
        base_height = max(dp(46), Window.height * 0.054)
        return min(base_height, dp(62))

    # ------------------------------------------------------------------
    # Table rendering com linhas separadoras PRETAS
    # ------------------------------------------------------------------
    def update_product_table(self, products_to_display=None):
        """Atualizar a tabela de produtos com separadores visuais pretos."""
        self.product_table.clear_widgets()

        if products_to_display is None:
            products_to_display = self.products

        self._current_display = products_to_display
        row_h = self._row_height()

        for idx, product in enumerate(products_to_display):
            # Cores alternadas com melhor contraste
            row_bg_color = [0.97, 0.98, 0.99, 1] if idx % 2 == 0 else [1, 1, 1, 1]
            border_color = [0, 0, 0, 0.25]  # Preto suave para as bordas

            # Helper: criar célula com bordas PRETAS
            def make_cell(col_idx, bg_color=row_bg_color, align='center'):
                cell = MDBoxLayout(
                    size_hint_x=COL_HINTS[col_idx],
                    size_hint_y=None,
                    height=row_h,
                    md_bg_color=bg_color,
                    padding=[dp(6), 0] if align == 'center' else [dp(10), 0]
                )
                
                # Função para desenhar as bordas
                def draw_borders(instance, value):
                    instance.canvas.after.clear()
                    with instance.canvas.after:
                        Color(*border_color)  # COR PRETA
                        # Borda direita
                        Line(points=[instance.x + instance.width, instance.y, 
                                   instance.x + instance.width, instance.y + instance.height], width=1)
                        # Borda inferior
                        Line(points=[instance.x, instance.y, 
                                   instance.x + instance.width, instance.y], width=1)
                
                # Bind para redesenhar quando posição ou tamanho mudarem
                cell.bind(pos=draw_borders, size=draw_borders)
                # Desenhar inicialmente
                Clock.schedule_once(lambda dt: draw_borders(cell, None), 0)
                
                return cell

            # Helper values
            is_sold_by_weight = product[15] if len(product) > 15 else 0
            unit_label = "KG" if is_sold_by_weight else ""

            # ── 0 – ID ──────────────────────────────────────────────
            cell = make_cell(0)
            cell.add_widget(MDLabel(
                text=str(product[0]),
                theme_text_color="Custom",
                text_color=[0.25, 0.30, 0.40, 1],
                halign='center',
                bold=True,
                font_style="Body1"
            ))
            self.product_table.add_widget(cell)

            # ── 1 – Descrição ───────────────────────────────────────
            cell = make_cell(1, align='left')
            cell.add_widget(MDLabel(
                text=product[1],
                theme_text_color="Custom",
                text_color=[0.15, 0.20, 0.30, 1],
                halign='left',
                font_style="Body2",
                shorten=True,
                shorten_from="right"
            ))
            self.product_table.add_widget(cell)

            # ── 2 – Estoque ─────────────────────────────────────────
            stock_value = product[2]
            stock_text = (f"{stock_value:.2f} {unit_label}" if is_sold_by_weight
                          else f"{int(stock_value)} {unit_label}")
            
            # Cores baseadas no estoque
            stock_color = [0.8, 0.2, 0.2, 1] if stock_value < 10 else [0.2, 0.25, 0.35, 1]
            
            cell = make_cell(2)
            cell.add_widget(MDLabel(
                text=stock_text,
                theme_text_color="Custom",
                text_color=stock_color,
                halign='center',
                font_style="Body2",
                bold=stock_value < 10
            ))
            self.product_table.add_widget(cell)

            # ── 3 – Vendido ─────────────────────────────────────────
            sold_value = product[3]
            sold_text = (f"{sold_value:.2f} {unit_label}" if is_sold_by_weight
                         else f"{int(sold_value)} {unit_label}")
            cell = make_cell(3)
            cell.add_widget(MDLabel(
                text=sold_text,
                theme_text_color="Custom",
                text_color=[0.2, 0.25, 0.35, 1],
                halign='center',
                font_style="Body2"
            ))
            self.product_table.add_widget(cell)

            # ── 4 – Tipo de Venda ───────────────────────────────────
            cell = make_cell(4)
            sale_type_text = "KG" if is_sold_by_weight else "UN"
            cell.add_widget(MDLabel(
                text=sale_type_text,
                theme_text_color="Custom",
                text_color=[0.75, 0.45, 0.10, 1] if is_sold_by_weight else [0.15, 0.50, 0.75, 1],
                halign='center',
                bold=True,
                font_style="Subtitle2"
            ))
            self.product_table.add_widget(cell)

            # ── 5 – Preço ───────────────────────────────────────────
            cell = make_cell(5)
            cell.add_widget(MDLabel(
                text=f"{product[4]:.2f} MT",
                theme_text_color="Custom",
                text_color=[0.10, 0.55, 0.25, 1],
                halign='center',
                bold=True,
                font_style="Body1"
            ))
            self.product_table.add_widget(cell)

            # ── 6 – Lucro ───────────────────────────────────────────
            cell = make_cell(6)
            cell.add_widget(MDLabel(
                text=f"{product[8]:.2f} MT",
                theme_text_color="Custom",
                text_color=[0.05, 0.42, 0.68, 1],
                halign='center',
                bold=True,
                font_style="Body1"
            ))
            self.product_table.add_widget(cell)

            # ── 7 – Data ────────────────────────────────────────────
            date_added = str(product[14]) if len(product) > 14 and product[14] else "N/A"
            cell = make_cell(7)
            cell.add_widget(MDLabel(
                text=self.format_datetime(date_added),
                theme_text_color="Custom",
                text_color=[0.45, 0.50, 0.55, 1],
                halign='center',
                font_style="Caption"
            ))
            self.product_table.add_widget(cell)

            # ── 8 – Ações ───────────────────────────────────────────
            cell = make_cell(8)
            action_layout = MDBoxLayout(spacing=dp(4), padding=[dp(4), 0])
            action_layout.add_widget(self.create_detail_button(product[0]))
            action_layout.add_widget(self.create_edit_button(product))
            action_layout.add_widget(self.create_delete_button(product[0]))
            cell.add_widget(action_layout)
            self.product_table.add_widget(cell)

    # ------------------------------------------------------------------
    # Action buttons com Material Design
    # ------------------------------------------------------------------
    def create_detail_button(self, product_id):
        btn = MDIconButton(
            icon="information",
            theme_text_color="Custom",
            text_color=[0.1, 0.3, 0.9, 1],
            md_bg_color=[0.92, 0.95, 1, 1],
            icon_size=sp(20)
        )
        btn.product_id = product_id
        btn.bind(on_release=self.show_product_details)
        return btn

    def create_edit_button(self, product):
        btn = MDIconButton(
            icon="pencil",
            theme_text_color="Custom",
            text_color=[0.1, 0.65, 0.2, 1],
            md_bg_color=[0.92, 1, 0.92, 1],
            icon_size=sp(20)
        )
        btn.product_id = product
        btn.bind(on_release=self.edit_product)
        return btn

    def create_delete_button(self, product_id):
        btn = MDIconButton(
            icon="delete",
            theme_text_color="Custom",
            text_color=[0.9, 0.2, 0.2, 1],
            md_bg_color=[1, 0.92, 0.92, 1],
            icon_size=sp(20)
        )
        btn.product_id = product_id
        btn.bind(on_release=self.delete_product)
        return btn

    # ------------------------------------------------------------------
    # Product actions
    # ------------------------------------------------------------------
    def show_product_details(self, instance):
        product = self.db.get_product(instance.product_id)
        if product:
            DetailPopup(product).open()

    def add_product(self):
        ProductForm(self).open()

    def edit_product(self, instance):
        ProductForm(self, instance.product_id).open()

    def delete_product(self, instance):
        product_id = instance.product_id
        
        self.dialog = MDDialog(
            title="Confirmar Exclusão",
            text="Tem certeza que deseja excluir este produto?",
            buttons=[
                MDFlatButton(
                    text="NÃO",
                    theme_text_color="Custom",
                    text_color=[0.3, 0.3, 0.3, 1],
                    on_release=lambda x: self.dialog.dismiss()
                ),
                MDRaisedButton(
                    text="SIM",
                    md_bg_color=[0.9, 0.3, 0.3, 1],
                    on_release=lambda x: self.confirm_delete(product_id)
                ),
            ],
        )
        self.dialog.open()

    def confirm_delete(self, product_id):
        self.db.delete_product(product_id)
        self.dialog.dismiss()
        self.load_products()
        self.show_snackbar("Produto excluído com sucesso!")

    # ------------------------------------------------------------------
    # Snackbar for notifications
    # ------------------------------------------------------------------
    def show_snackbar(self, message):
        MDSnackbar(
            MDLabel(
                text=message,
                theme_text_color="Custom",
                text_color=[1, 1, 1, 1],
            ),
            pos=(dp(10), dp(10)),
            size_hint_x=0.5,
        ).open()

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
        insights = insights or build_admin_insights(self.db)
        key = self._get_alert_key(insights)
        app = App.get_running_app()
        if app:
            app._ai_notifications_seen_key = key
        self.update_notification_badge(0)

    def show_ai_insights(self, *args):
        """Abrir notificacoes em formato de banner"""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = build_admin_insights_ai(self.db)
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
        """Abre menu AI e marca notificações como vistas"""
        if not hasattr(self, "_ai_menu") or not self._ai_menu:
            items = [
                {"text": "Insights completos", "on_release": lambda x="full": self._open_ai_from_menu(x)},
                {"text": "Reposicao de stock", "on_release": lambda x="stock": self._open_ai_from_menu(x)},
                {"text": "Avisos de vencimento", "on_release": lambda x="expiry": self._open_ai_from_menu(x)},
            ]
            self._ai_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        else:
            self._ai_menu.caller = caller
        
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
        """Mostrar apenas banner de stock baixo"""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai(self.db)
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
        """Mostrar apenas banner de vencimentos"""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai(self.db)
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
        if getattr(app, "_ai_banners_shown", False):
            return

        insights = build_admin_insights_ai(self.db)
        banners = build_auto_banner_data(insights)
        if not banners:
            return

        container = self.ids.ai_banner_container
        render_auto_banners(container, banners, auto_dismiss_seconds=10)
        if app:
            app._ai_banners_shown = True

    def update_ai_badge(self, *args):
        """Atualiza o badge do botão de insights com animação de abanar"""
        insights = build_admin_insights(self.db)
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        count = badge_counts.get("total", 0)

        if not key:
            count = 0

        app = App.get_running_app()
        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            count = 0

        self.update_notification_badge(count)

    # ------------------------------------------------------------------
    # Reports & filter toggle
    # ------------------------------------------------------------------
    def generate_report(self):
        self.manager.current = 'reports'
        if 'reports' in self.manager.screen_names:
            reports_screen = self.manager.get_screen('reports')
            Clock.schedule_once(lambda dt: reports_screen.select_date_range(), 0.1)

    def toggle_kg_products(self):
        if not hasattr(self, 'filter_mode'):
            self.filter_mode = 0

        self.filter_mode = (self.filter_mode + 1) % 3

        if self.filter_mode == 1:
            kg_products = self.db.get_products_by_weight()
            if kg_products:
                self.update_product_table(kg_products)
                self.show_snackbar("Mostrando apenas produtos vendidos por KG")
            else:
                self.filter_mode = 2
                unit_products = [p for p in self.products if not (len(p) > 15 and p[15])]
                if unit_products:
                    self.update_product_table(unit_products)
                    self.show_snackbar("Mostrando apenas produtos vendidos por unidade")
                else:
                    self.filter_mode = 0
                    self.update_product_table(self.products)
                    self.show_snackbar("Mostrando todos os produtos")
        elif self.filter_mode == 2:
            unit_products = [p for p in self.products if not (len(p) > 15 and p[15])]
            if unit_products:
                self.update_product_table(unit_products)
                self.show_snackbar("Mostrando apenas produtos vendidos por unidade")
            else:
                self.filter_mode = 0
                self.update_product_table(self.products)
                self.show_snackbar("Mostrando todos os produtos")
        else:
            self.update_product_table(self.products)
            self.show_snackbar("Mostrando todos os produtos")
