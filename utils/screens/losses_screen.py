from kivy.lang import Builder
from kivy.app import App
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.graphics import Color, Line
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.core.audio import SoundLoader
from kivy.animation import Animation
from kivymd.uix.card import MDCard
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.menu import MDDropdownMenu
from kivy.properties import NumericProperty, ObjectProperty, StringProperty
from database.provider import get_db, uses_remote_backend
from datetime import date, datetime
from threading import Thread
from time import perf_counter
from pathlib import Path
import time
import os
from ui.components.tooltip_widgets import TooltipIconButton
from utils.hardware.vision import get_vision_dependencies, open_optimized_camera_capture
from utils.business.damage_evidence import DamageEvidenceError, create_local_damage_evidence
from utils.config.paths import temp_path

def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)

LOSS_TYPES = [
    ("DANIFICADO", "DAMAGE"),
    ("EXPIRADO", "EXPIRED"),
    ("ROUBO", "THEFT"),
    ("AJUSTE", "ADJUSTMENT"),
]
EXPIRY_LOSS_REASON = "Data de validade"
LOSS_REASONS = {
    "DAMAGE": (
        "Produto danificado",
        "Embalagem danificada",
        "Produto quebrado",
        "Contaminacao confirmada",
    ),
    "EXPIRED": (EXPIRY_LOSS_REASON,),
    "THEFT": (
        "Furto confirmado",
        "Roubo reportado",
        "Desaparecimento em inventario",
    ),
    "ADJUSTMENT": (
        "Contagem de stock",
        "Correcao de inventario",
        "Diferenca de stock",
    ),
}


class LossesFloatingScannerPanel(MDCard):
    min_panel_width = NumericProperty(dp(220))
    min_panel_height = NumericProperty(dp(190))
    drag_bar_height = NumericProperty(dp(34))
    resize_handle_size = NumericProperty(dp(24))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active_mode = None
        self._drag_offset = (0.0, 0.0)
        self._start_touch = (0.0, 0.0)
        self._start_size = (0.0, 0.0)

        with self.canvas.after:
            self._handle_color_instruction = Color(rgba=[0.56, 0.90, 0.54, 0.85])
            self._handle_line_one = Line(points=[], width=1.1)
            self._handle_line_two = Line(points=[], width=1.1)
            self._handle_line_three = Line(points=[], width=1.1)

        self.bind(pos=self._sync_handle, size=self._sync_handle, opacity=self._sync_handle)

    def _sync_handle(self, *_args):
        if self.opacity <= 0.01:
            self._handle_line_one.points = []
            self._handle_line_two.points = []
            self._handle_line_three.points = []
            return

        inset = dp(8)
        span = dp(9)
        step = dp(5)
        right = self.right - inset
        bottom = self.y + inset

        self._handle_line_one.points = [right - span, bottom, right, bottom + span]
        self._handle_line_two.points = [right - span - step, bottom, right, bottom + span + step]
        self._handle_line_three.points = [right - span - (step * 2), bottom, right, bottom + span + (step * 2)]

    def clamp_to_parent(self):
        parent = self.parent
        if parent is None:
            return

        max_width = max(dp(160), parent.width - dp(16))
        max_height = max(dp(170), parent.height - dp(16))
        min_width = min(self.min_panel_width, max_width)
        min_height = min(self.min_panel_height, max_height)
        self.width = min(max(self.width, min_width), max_width)
        self.height = min(max(self.height, min_height), max_height)
        self.x = min(max(self.x, dp(8)), max(dp(8), parent.width - self.width - dp(8)))
        self.y = min(max(self.y, dp(8)), max(dp(8), parent.height - self.height - dp(8)))

    def _touch_in_resize_zone(self, touch):
        return touch.x >= (self.right - self.resize_handle_size) and touch.y <= (self.y + self.resize_handle_size)

    def _touch_in_drag_zone(self, touch):
        return touch.y >= (self.top - self.drag_bar_height)

    def on_touch_down(self, touch):
        if self.disabled or self.opacity <= 0.01 or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        if self._touch_in_resize_zone(touch):
            touch.grab(self)
            self._active_mode = "resize"
            self._start_touch = tuple(touch.pos)
            self._start_size = tuple(self.size)
            return True

        if self._touch_in_drag_zone(touch):
            touch.grab(self)
            self._active_mode = "move"
            self._drag_offset = (touch.x - self.x, touch.y - self.y)
            return True

        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        parent = self.parent
        if parent is None:
            return True

        if self._active_mode == "move":
            self.pos = (touch.x - self._drag_offset[0], touch.y - self._drag_offset[1])
            self.clamp_to_parent()
            return True

        if self._active_mode == "resize":
            delta_x = touch.x - self._start_touch[0]
            delta_y = touch.y - self._start_touch[1]
            max_width = max(dp(160), parent.width - self.x - dp(8))
            max_height = max(dp(170), parent.height - self.y - dp(8))
            min_width = min(self.min_panel_width, max_width)
            min_height = min(self.min_panel_height, max_height)
            self.width = min(max(min_width, self._start_size[0] + delta_x), max_width)
            self.height = min(max(min_height, self._start_size[1] + delta_y), max_height)
            self.clamp_to_parent()
            return True

        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._active_mode = None
            self.clamp_to_parent()
            return True
        return super().on_touch_up(touch)


Factory.register("LossesFloatingScannerPanel", cls=LossesFloatingScannerPanel)
Builder.load_file(os.path.join(os.path.dirname(__file__), "losses_screen.kv"))



class LossesScreen(MDScreen):
    db = ObjectProperty(None)
    selected_loss_type = StringProperty("")
    selected_loss_reason = StringProperty("")
    PRODUCTS_CACHE_SECONDS = 5
    ENTER_REFRESH_DELAY_SECONDS = 0.08
    PRODUCT_RENDER_BATCH_SIZE = 20
    SCANNER_AUTO_START_DELAY_SECONDS = 0.18
    DAMAGE_CAMERA_MAX_INDEX = 8
    
    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.back_target = "admin_home"
        self.products = []
        self.selected_product = None
        self.loss_menu = None
        self.reason_menu = None
        # Scanner
        self.scanning = False
        self.camera = None
        self.current_camera_index = 0
        self.sound_ok = None
        self.sound_error = None
        self.last_scan_code = None
        self.last_scan_time = 0
        
        # UI State
        self.current_step = 1  # 1 = selecionar produto, 2 = preencher perda
        self._search_ev = None
        self._pending_search = ""
        self._products_load_token = 0
        self._products_loading = False
        self._pending_products_load = False
        self._last_products_load_at = 0.0
        self._products_render_ev = None
        self._products_render_rows = []
        self._products_render_index = 0
        self._enter_refresh_ev = None
        self._scanner_auto_start_ev = None
        self._scanner_panel_initialized = False
        self._saving_loss = False
        self._pending_product_focus = None
        self.damage_evidence_id = None
        self.damage_evidence_source = None
        self._damage_analysis_in_progress = False
        self.damage_camera = None
        self.damage_camera_index = 0
        self.damage_camera_running = False
        self._damage_camera_frame = None
        self._damage_camera_snapshot_path = None
        self._damage_camera_cleanup_path = None
        self._damage_camera_panel_initialized = False
        
        Clock.schedule_once(self.init_screen, 0.1)

    @staticmethod
    def _normalize_product_row(product):
        """Normaliza produtos para a estrutura usada pela tela."""
        if isinstance(product, dict):
            return (
                product.get("id"),
                product.get("description") or product.get("name"),
                product.get("existing_stock", product.get("stock", 0)),
                product.get("sale_price", product.get("price", 0)),
                product.get("unit_purchase_price", product.get("cost", 0)),
                product.get("barcode"),
                product.get("is_sold_by_weight", product.get("is_weight", False)),
                product.get("expiry_date"),
                product.get("status"),
                product.get("vat_rule_code"),
            )

        row = list(product or [])
        if len(row) < 9:
            return None
        if len(row) < 10:
            row.append(None)
        return tuple(row[:10])

    def init_screen(self, dt):
        """Inicializa a tela"""
        self.load_sounds()
        self.set_scanner_status("Pronto para escanear", _theme_color("text_secondary", [0.5, 0.5, 0.5, 1]))
        self.update_ui_state()
        self._update_responsive_layout()

    def on_enter(self):
        """Quando entra na tela"""
        self.request_enter_refresh(force=not bool(self.products))
        self.clear_form()
        self.update_ui_state()
        self._update_responsive_layout()
        app = App.get_running_app()
        warmup = getattr(app, "warmup_screens", None) if app else None
        if callable(warmup):
            Clock.schedule_once(lambda dt: warmup(("losses_history",), delay=0.1), 0.16)

    def on_leave(self):
        """Quando sai da tela"""
        if self._enter_refresh_ev:
            self._enter_refresh_ev.cancel()
            self._enter_refresh_ev = None
        self._cancel_scanner_auto_start()
        self._stop_products_render()
        self.stop_scanner(hide_panel=True)
        self.close_damage_camera_panel()

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def prepare_open_from_admin(self):
        self.request_enter_refresh(force=not bool(self.products), delay=0.02)

    def open_loss_for_product(self, product_id=None, query=None, loss_type_label=None, loss_type_code=None):
        self._pending_product_focus = {
            "product_id": product_id,
            "query": str(query or "").strip(),
            "loss_type_label": loss_type_label,
            "loss_type_code": loss_type_code,
        }
        if self.products and not self._products_loading:
            Clock.schedule_once(lambda dt: self._consume_pending_product_focus(), 0)
            return
        self.load_products()

    def _cancel_scanner_auto_start(self):
        if self._scanner_auto_start_ev:
            self._scanner_auto_start_ev.cancel()
            self._scanner_auto_start_ev = None

    def _schedule_scanner_auto_start(self, delay=None):
        self._cancel_scanner_auto_start()
        return

    def _auto_start_scanner(self, _dt):
        self._scanner_auto_start_ev = None
        return

    def _ensure_scanner_panel_geometry(self, reset=False):
        if not hasattr(self, "ids") or "scanner_preview_card" not in self.ids:
            return

        panel = self.ids.scanner_preview_card
        width = self.width or dp(1200)
        height = self.height or dp(760)
        compact = width < dp(1120)
        max_width = max(dp(180), width - dp(20))
        max_height = max(dp(170), height - dp(20))
        min_width = min(panel.min_panel_width, max_width)
        min_height = min(panel.min_panel_height, max_height)

        if reset or not self._scanner_panel_initialized:
            if width < dp(760):
                default_width = min(max_width, max(min_width, width - dp(20)))
                default_height = min(max_height, max(min_height, dp(184)))
                default_x = max(dp(10), (width - default_width) / 2)
                default_y = dp(10)
            elif compact:
                default_width = min(max_width, max(min_width, dp(236)))
                default_height = min(max_height, max(min_height, dp(204)))
                default_x = max(dp(14), width - default_width - dp(14))
                default_y = dp(14)
            else:
                default_width = min(max_width, max(min_width, dp(280)))
                default_height = min(max_height, max(min_height, dp(228)))
                default_x = max(dp(18), width - default_width - dp(18))
                default_y = dp(18)

            panel.size = (default_width, default_height)
            panel.pos = (default_x, default_y)
            self._scanner_panel_initialized = True

        if hasattr(panel, "clamp_to_parent"):
            panel.clamp_to_parent()

    def _set_scanner_preview_visible(self, visible, reset_geometry=False):
        if not hasattr(self, "ids") or "scanner_preview_card" not in self.ids:
            return

        panel = self.ids.scanner_preview_card
        if visible:
            panel.opacity = 1
            panel.disabled = False
            self._ensure_scanner_panel_geometry(reset=reset_geometry)
        else:
            panel.opacity = 0
            panel.disabled = True

        Clock.schedule_once(lambda _dt: self._update_responsive_layout(), 0)

    def _ensure_damage_camera_panel_geometry(self, reset=False):
        if not hasattr(self, "ids") or "damage_camera_preview_card" not in self.ids:
            return

        panel = self.ids.damage_camera_preview_card
        width = self.width or dp(1200)
        height = self.height or dp(760)
        compact = width < dp(1120)
        max_width = max(dp(220), width - dp(20))
        max_height = max(dp(230), height - dp(20))
        min_width = min(panel.min_panel_width, max_width)
        min_height = min(panel.min_panel_height, max_height)

        if reset or not self._damage_camera_panel_initialized:
            if width < dp(760):
                default_width = min(max_width, max(min_width, width - dp(20)))
                default_height = min(max_height, max(min_height, dp(310)))
                default_x = max(dp(10), (width - default_width) / 2)
                default_y = dp(10)
            elif compact:
                default_width = min(max_width, max(min_width, dp(300)))
                default_height = min(max_height, max(min_height, dp(330)))
                default_x = max(dp(14), width - default_width - dp(14))
                default_y = dp(14)
            else:
                default_width = min(max_width, max(min_width, dp(350)))
                default_height = min(max_height, max(min_height, dp(360)))
                default_x = max(dp(18), width - default_width - dp(18))
                default_y = dp(18)

            panel.size = (default_width, default_height)
            panel.pos = (default_x, default_y)
            self._damage_camera_panel_initialized = True

        if hasattr(panel, "clamp_to_parent"):
            panel.clamp_to_parent()

    def _set_damage_camera_preview_visible(self, visible, reset_geometry=False):
        if not hasattr(self, "ids") or "damage_camera_preview_card" not in self.ids:
            return

        panel = self.ids.damage_camera_preview_card
        if visible:
            panel.opacity = 1
            panel.disabled = False
            self._ensure_damage_camera_panel_geometry(reset=reset_geometry)
        else:
            panel.opacity = 0
            panel.disabled = True

        Clock.schedule_once(lambda _dt: self._update_responsive_layout(), 0)

    def close_scanner_panel(self):
        self._cancel_scanner_auto_start()
        self.stop_scanner(status_text="Scanner fechado", hide_panel=True)

    def _update_responsive_layout(self):
        if not hasattr(self, "ids") or "loss_type_qty_row" not in self.ids:
            return

        width = self.width or dp(1200)
        compact = width < dp(1120)

        content_column = self.ids.content_column
        selected_meta = self.ids.selected_product_meta_row
        scanner_preview = self.ids.scanner_preview_card
        damage_camera_preview = self.ids.damage_camera_preview_card
        scanner_buttons = self.ids.scanner_buttons_row
        loss_type_row = self.ids.loss_type_qty_row
        loss_type_btn = self.ids.loss_type_btn
        qty_input = self.ids.qty_input

        selected_meta.orientation = "vertical" if compact else "horizontal"
        selected_meta.height = dp(58) if compact else dp(20)
        self._ensure_scanner_panel_geometry()
        self._ensure_damage_camera_panel_geometry()
        scanner_buttons.width = dp(116) if compact else dp(132)
        visible_panel_height = max(
            scanner_preview.height if scanner_preview.opacity > 0.01 else 0,
            damage_camera_preview.height if damage_camera_preview.opacity > 0.01 else 0,
        )
        bottom_padding = visible_panel_height + dp(34) if visible_panel_height else dp(16)
        content_column.padding = [dp(16), dp(16), dp(16), bottom_padding]
        loss_type_row.orientation = "vertical" if compact else "horizontal"
        loss_type_row.height = dp(104) if compact else dp(52)
        loss_type_btn.size_hint_x = 1 if compact else 0.55
        qty_input.size_hint_x = 1 if compact else 0.45

    def request_enter_refresh(self, force=False, delay=None):
        delay = self.ENTER_REFRESH_DELAY_SECONDS if delay is None else max(0, float(delay))
        if self._enter_refresh_ev:
            self._enter_refresh_ev.cancel()
            self._enter_refresh_ev = None

        stale = (perf_counter() - self._last_products_load_at) >= self.PRODUCTS_CACHE_SECONDS
        if not force and self.products and not stale:
            return

        self._enter_refresh_ev = Clock.schedule_once(lambda dt: self._run_scheduled_refresh(), delay)

    def _run_scheduled_refresh(self):
        self._enter_refresh_ev = None
        self.load_products()

    def go_back(self):
        """Volta para tela anterior"""
        if not self.manager:
            return
        if getattr(self, "back_target", None) in self.manager.screen_names:
            self.manager.current = self.back_target
            return
        app = App.get_running_app()
        role = getattr(app, "current_role", "manager")
        self.manager.current = "admin" if role == "admin" else "manager"

    def open_losses_history(self, *args):
        """Abre a tela de histórico de perdas"""
        if not self.manager:
            return
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None)
        if "losses_history" not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen("losses_history")
        if "losses_history" not in self.manager.screen_names:
            return
        self.manager.current = "losses_history"

    # ========== UI STATE MANAGEMENT (NOVO) ==========
    def _loss_form_target_height(self):
        """Mantem o formulario ajustado ao seu conteudo, sem areas vazias."""
        return dp(800 if self.selected_loss_type == "DAMAGE" else 460)

    def _scroll_loss_form_to_top(self, _dt=0):
        if "losses_scroll" in self.ids:
            self.ids.losses_scroll.scroll_y = 1

    def update_ui_state(self):
        """Atualiza visibilidade dos cards baseado no estado"""
        if self.current_step == 1:
            # Step 1: Selecionar produto
            self._show_card(self.ids.search_card, 360)
            self._hide_card(self.ids.loss_form_card)
            self._hide_card(self.ids.selected_product_card)
            
            # Atualizar indicadores
            self.ids.step1_icon.icon = "numeric-1-circle"
            self.ids.step1_icon.text_color = _theme_color("info", [0.15, 0.65, 0.85, 1])
            self.ids.step1_label.bold = True
            self.ids.step1_label.theme_text_color = "Primary"
            
            self.ids.step2_icon.icon = "numeric-2-circle-outline"
            self.ids.step2_icon.text_color = _theme_color("text_secondary", [0.5, 0.5, 0.5, 1])
            self.ids.step2_label.bold = False
            self.ids.step2_label.theme_text_color = "Hint"
            
        elif self.current_step == 2:
            # Step 2: Preencher perda
            self._hide_card(self.ids.search_card)
            self._show_card(self.ids.loss_form_card, self._loss_form_target_height())
            self._show_card(self.ids.selected_product_card, 80)
            
            # Atualizar indicadores
            self.ids.step1_icon.icon = "check-circle"
            self.ids.step1_icon.text_color = _theme_color("success", [0.2, 0.7, 0.3, 1])
            self.ids.step1_label.bold = False
            self.ids.step1_label.theme_text_color = "Secondary"
            
            self.ids.step2_icon.icon = "numeric-2-circle"
            self.ids.step2_icon.text_color = _theme_color("info", [0.15, 0.65, 0.85, 1])
            self.ids.step2_label.bold = True
            self.ids.step2_label.theme_text_color = "Primary"

    def _show_card(self, card, height):
        """Anima card para aparecer"""
        anim = Animation(height=height, opacity=1, duration=0.3, t='out_cubic')
        anim.start(card)

    def _hide_card(self, card):
        """Anima card para desaparecer"""
        anim = Animation(height=0, opacity=0, duration=0.3, t='out_cubic')
        anim.start(card)

    # ========== SONS ==========
    def load_sounds(self):
        """Carrega sons do scanner"""
        try:
            self.sound_ok = SoundLoader.load("assets/sounds/beep.wav")
            self.sound_error = SoundLoader.load("assets/sounds/beeperror.mp3")
        except:
            self.sound_ok = None
            self.sound_error = None

    def play_sound(self, success=True):
        """Toca som de sucesso ou erro"""
        try:
            if success and self.sound_ok:
                self.sound_ok.play()
            elif not success and self.sound_error:
                self.sound_error.play()
        except:
            pass

    def _load_vision_modules(self):
        return get_vision_dependencies()

    # ========== SCANNER ==========
    def set_scanner_status(self, text, color):
        """Atualiza status do scanner"""
        if "scanner_status" in self.ids:
            self.ids.scanner_status.text = text
            self.ids.scanner_status.text_color = color

    def toggle_scanner(self):
        """Liga/desliga o scanner"""
        self._cancel_scanner_auto_start()
        if self.scanning:
            self.stop_scanner()
        else:
            self.start_scanner()

    def start_scanner(self):
        """Inicia o scanner"""
        self._cancel_scanner_auto_start()
        if self.scanning and self.camera:
            return
        self._set_scanner_preview_visible(True)
        self.scanning = True
        self.ids.scan_btn.icon = "barcode-off"
        self.ids.scan_btn.md_bg_color = _theme_color("danger", [0.9, 0.3, 0.3, 1])
        self.set_scanner_status("Iniciando...", _theme_color("warning", [0.9, 0.7, 0.1, 1]))
        Clock.unschedule(self.open_camera)
        Clock.unschedule(self.scan_frame)
        Clock.schedule_once(self.open_camera, 0.1)

    def stop_scanner(self, status_text="Scanner parado", status_color=None, hide_panel=False):
        """Para o scanner"""
        self._cancel_scanner_auto_start()
        self.scanning = False
        status_color = status_color or _theme_color("text_secondary", [0.5, 0.5, 0.5, 1])
        self.ids.scan_btn.icon = "barcode-scan"
        self.ids.scan_btn.md_bg_color = _theme_color("success", [0.2, 0.65, 0.3, 1])
        self.set_scanner_status(status_text, status_color)
        Clock.unschedule(self.open_camera)
        Clock.unschedule(self.scan_frame)
        self.close_camera()
        if hide_panel:
            self._set_scanner_preview_visible(False)

    def open_camera(self, dt):
        """Abre a câmera"""
        if not self.scanning:
            return
        try:
            cv2, _np, _decode = self._load_vision_modules()
            self.close_camera()
            self.camera = cv2.VideoCapture(self.current_camera_index)
            
            if self.camera.isOpened():
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.set_scanner_status("✓ Escaneando...", _theme_color("success", [0.2, 0.7, 0.3, 1]))
                self.last_scan_code = None
                self.last_scan_time = 0
                Clock.schedule_interval(self.scan_frame, 1/20)
            else:
                self.stop_scanner(
                    "Camera nao encontrada",
                    _theme_color("danger", [0.9, 0.2, 0.2, 1]),
                )
        except Exception as e:
            print(f"Erro ao abrir câmera: {e}")
            self.stop_scanner(
                "Erro na camera",
                _theme_color("danger", [0.9, 0.2, 0.2, 1]),
            )

    def close_camera(self):
        """Fecha a câmera"""
        if self.camera:
            try:
                self.camera.release()
            except:
                pass
            self.camera = None
        if "camera_image" in self.ids:
            self.ids.camera_image.texture = None

    def scan_frame(self, dt):
        """Escaneia um frame da câmera"""
        if not self.scanning or not self.camera:
            return

        try:
            cv2, _np, decode = self._load_vision_modules()
            ret, frame = self.camera.read()
            if not ret:
                return

            # Melhorar contraste
            frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
            
            # Procurar códigos de barras
            codes = decode(frame)
            if codes:
                self.process_barcode(codes[0], frame)
            
            # Mostrar frame na tela
            self.show_frame(frame)
            
        except Exception as e:
            print(f"Erro ao escanear: {e}")

    def process_barcode(self, code, frame):
        """Processa código de barras encontrado"""
        try:
            cv2, np, _decode = self._load_vision_modules()
            # Decodificar
            barcode = code.data.decode("utf-8").strip()
            
            # Evitar duplicatas
            now = time.time()
            if barcode == self.last_scan_code and (now - self.last_scan_time) < 2:
                return
            
            self.last_scan_code = barcode
            self.last_scan_time = now
            
            # Buscar produto
            product = self.find_product_by_barcode(barcode)
            
            if product:
                # Encontrou!
                self.ids.search_input.text = barcode
                self.select_product(product)
                self.play_sound(success=True)
                name = product[1][:25]
                self.set_scanner_status(f"✓ {name}", _theme_color("success", [0.2, 0.7, 0.3, 1]))
                
                # Desenhar quadrado verde
                pts = code.polygon
                if len(pts) == 4:
                    pts = [(p.x, p.y) for p in pts]
                    cv2.polylines(frame, [np.array(pts, dtype=np.int32)], True, (0, 255, 0), 3)
            else:
                # Não encontrou
                self.play_sound(success=False)
                self.set_scanner_status("✗ Produto não encontrado", _theme_color("danger", [0.9, 0.3, 0.2, 1]))
                
        except Exception as e:
            print(f"Erro ao processar código: {e}")

    def show_frame(self, frame):
        """Mostra frame na tela"""
        try:
            cv2, _np, _decode = self._load_vision_modules()
            buf = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(
                size=(frame.shape[1], frame.shape[0]),
                colorfmt="bgr"
            )
            texture.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
            self.ids.camera_image.texture = texture
        except:
            pass

    def switch_camera(self):
        """Troca para próxima câmera"""
        was_scanning = self.scanning
        if was_scanning:
            self.stop_scanner()
        
        self.current_camera_index = (self.current_camera_index + 1) % 4
        
        if was_scanning:
            Clock.schedule_once(lambda dt: self.start_scanner(), 0.1)

    # ========== PRODUTOS ==========
    def load_products(self):
        """Carrega produtos do banco"""
        if self._products_loading:
            self._pending_products_load = True
            return

        token = self._products_load_token + 1
        self._products_load_token = token
        self._products_loading = True

        def worker():
            try:
                rows = self.db.get_products_for_losses() or []
            except Exception as e:
                print(f"Erro ao carregar produtos: {e}")
                rows = []
            Clock.schedule_once(
                lambda dt, data=rows, tok=token: self._apply_loaded_products(data, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_products(self, rows, token):
        if token != self._products_load_token:
            return

        self._products_loading = False
        self._last_products_load_at = perf_counter()
        self.products = [
            normalized
            for normalized in (self._normalize_product_row(row) for row in (rows or []))
            if normalized is not None
        ]

        query = (self.ids.search_input.text if "search_input" in self.ids else self._pending_search).strip().lower()
        if query:
            self.show_products(self._filter_products(query))
        else:
            self.show_products(self.products)

        self._consume_pending_product_focus()

        if self._pending_products_load:
            self._pending_products_load = False
            Clock.schedule_once(lambda dt: self.load_products(), 0.05)

    def _find_product_for_focus(self, product_id=None, query=None):
        target_id = str(product_id or "").strip()
        query_text = str(query or "").strip().lower()

        if target_id:
            for product in self.products or []:
                normalized = self._normalize_product_row(product)
                if normalized is not None and str(normalized[0] or "").strip() == target_id:
                    return normalized

        if query_text:
            for product in self.products or []:
                normalized = self._normalize_product_row(product)
                if normalized is None:
                    continue
                pid, name, _stock, _price, _cost, barcode, _is_weight, _exp, _status, _vat_rule_code = normalized
                terms = (
                    str(pid or "").lower(),
                    str(name or "").lower(),
                    str(barcode or "").lower(),
                )
                if any(query_text in term for term in terms):
                    return normalized
        return None

    def _consume_pending_product_focus(self):
        request = self._pending_product_focus
        if not request:
            return False

        product = self._find_product_for_focus(
            product_id=request.get("product_id"),
            query=request.get("query"),
        )
        if product is None:
            search_text = str(request.get("query") or request.get("product_id") or "").strip()
            if search_text and "search_input" in self.ids:
                self._pending_search = search_text
                self.ids.search_input.text = search_text
                self.show_products(self._filter_products(search_text.lower()))
            return False

        self._pending_product_focus = None
        self.select_product(product)
        label = request.get("loss_type_label")
        code = request.get("loss_type_code")
        if label and code:
            self.set_loss_type(label, code)
        return True

    def show_products(self, products):
        """Mostra produtos na lista"""
        if "products_list" not in self.ids:
            return
            
        self._stop_products_render()
        self.ids.products_list.clear_widgets()
        
        if not products:
            empty = TwoLineListItem(
                text="Nenhum produto disponível",
                secondary_text="Stock vazio ou filtro aplicado"
            )
            self.ids.products_list.add_widget(empty)
            return

        # Antes a lista completa era criada num unico frame; com muitos itens a
        # interface ficava menos responsiva logo ao abrir a tela.
        self._products_render_rows = list(products or [])
        self._products_render_index = 0
        self._render_next_products_batch(0)
        if self._products_render_index < len(self._products_render_rows):
            self._products_render_ev = Clock.schedule_interval(self._render_next_products_batch, 0.016)
        return
        
        for p in products:
            pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = p
            unit = "KG" if is_weight else "UN"
            
            # Status tag
            tag = ""
            if status == "EXPIRADO":
                tag = " • ⚠️ EXPIRADO"
            elif status == "PERTO_DO_PRAZO":
                tag = " • ⏰ PERTO DO PRAZO"
            
            # Criar item clicável
            def on_item_click(instance, product=p):
                self.select_product(product)
            
            item = TwoLineListItem(
                text=name,
                secondary_text=f"Stock: {stock:.1f} {unit} • {price:.2f} MZN{tag}"
            )
            item.bind(on_release=on_item_click)
            
            self.ids.products_list.add_widget(item)

    def _stop_products_render(self):
        if self._products_render_ev:
            self._products_render_ev.cancel()
            self._products_render_ev = None

    def _render_next_products_batch(self, _dt):
        products_list = self.ids.get("products_list") if hasattr(self, "ids") else None
        if products_list is None:
            self._stop_products_render()
            return False
        if self._products_render_index >= len(self._products_render_rows):
            self._stop_products_render()
            return False

        start = self._products_render_index
        end = min(start + self.PRODUCT_RENDER_BATCH_SIZE, len(self._products_render_rows))
        for product in self._products_render_rows[start:end]:
            products_list.add_widget(self._build_product_list_item(product))
        self._products_render_index = end

        if self._products_render_index >= len(self._products_render_rows):
            self._stop_products_render()
            return False
        return True

    def _build_product_list_item(self, product):
        _pid, name, stock, price, _cost, _barcode, is_weight, _exp, status, _vat_rule_code = product
        unit = "KG" if is_weight else "UN"
        tag = ""
        if status == "EXPIRADO":
            tag = " • EXPIRADO"
        elif status == "PERTO_DO_PRAZO":
            tag = " • PERTO DO PRAZO"

        item = TwoLineListItem(
            text=name,
            secondary_text=f"Stock: {stock:.1f} {unit} • {price:.2f} MZN{tag}"
        )
        item.bind(on_release=lambda instance, current=product: self.select_product(current))
        return item

    def on_search(self, text):
        """Filtra produtos pela pesquisa (debounce)."""
        self._pending_search = text or ""
        if self._search_ev:
            Clock.unschedule(self._search_ev)
        self._search_ev = Clock.schedule_once(self._apply_search, 0.3)
        return
        
        query = text.strip().lower()
        
        if not query:
            self.show_products(self.products)
            return
        
        # Filtrar produtos
        filtered = []
        for p in self.products:
            product = self._normalize_product_row(p)
            if product is None:
                continue
            
            pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = product
            
            # Buscar em: ID, nome ou código de barras
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            
            if (query in search_in_id or 
                query in search_in_name or 
                query in search_in_barcode):
                filtered.append(product)
        
        self.show_products(filtered)

    def _apply_search(self, dt):
        self._search_ev = None
        query = (self._pending_search or "").strip().lower()
        if not query:
            self.show_products(self.products)
            return
        filtered = self._filter_products(query)
        self.show_products(filtered)

    def _filter_products(self, query):
        filtered = []
        for p in self.products:
            product = self._normalize_product_row(p)
            if product is None:
                continue
            pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = product
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            if (query in search_in_id or query in search_in_name or query in search_in_barcode):
                filtered.append(product)
        return filtered

    def on_search_enter(self):
        """Quando usuário pressiona Enter na busca"""
        query = self.ids.search_input.text.strip().lower()
        if not query:
            return

        if self._search_ev:
            Clock.unschedule(self._search_ev)
            self._search_ev = None

        filtered = self._filter_products(query)
        self.show_products(filtered)
        if len(filtered) == 1:
            self.select_product(filtered[0])
        elif len(filtered) > 1:
            self.show_dialog("?? Busca", f"Encontrados {len(filtered)} produtos. Clique em um ou refine a busca.")
        else:
            self.show_dialog("?? Busca", "Nenhum produto encontrado.")
        return
        
        # Buscar produtos filtrados
        filtered = []
        for p in self.products:
            product = self._normalize_product_row(p)
            if product is None:
                continue
            
            pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = product
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            
            if (query in search_in_id or 
                query in search_in_name or 
                query in search_in_barcode):
                filtered.append(product)
        
        # Se encontrou exatamente 1, selecionar automaticamente
        if len(filtered) == 1:
            self.select_product(filtered[0])
        elif len(filtered) > 1:
            # Se encontrou vários, mostrar mensagem
            self.show_dialog("🔍 Busca", f"Encontrados {len(filtered)} produtos. Clique em um ou refine a busca.")
        else:
            self.show_dialog("🔍 Busca", "Nenhum produto encontrado.")

    def find_product_by_barcode(self, barcode):
        """Busca produto pelo código de barras"""
        for p in self.products:
            if len(p) > 5 and p[5] and str(p[5]).strip() == str(barcode).strip():
                return p
        return None

    def select_product(self, product):
        """Seleciona um produto e avança para step 2"""
        normalized_product = self._normalize_product_row(product)
        if normalized_product is None:
            self.show_dialog("Erro", "Produto invalido para selecao.")
            return
        self.selected_product = normalized_product
        pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = normalized_product
        unit = "KG" if is_weight else "UN"
        
        # Atualizar UI do produto selecionado
        self.ids.selected_name.text = name
        self.ids.selected_stock.text = f"Stock: {stock:.1f} {unit}"
        self.ids.selected_unit.text = f"Unidade: {unit}"
        self.ids.selected_price.text = f"Preço: {price:.2f} MZN"
        
        # Configurar input de quantidade
        self.ids.qty_input.text = "1"
        self.ids.qty_input.input_filter = "float" if is_weight else "int"
        
        # Um produto identificado como vencido sugere o tipo; o motivo continua
        # uma escolha controlada, nunca texto livre.
        if status == "EXPIRADO":
            self.set_loss_type("EXPIRADO", "EXPIRED")
        else:
            # Limpar tipo e motivo anteriores
            self.selected_loss_type = ""
            self.selected_loss_reason = ""
            self.ids.loss_type_btn.text = "Selecionar Tipo"
            self.ids.reason_spinner_btn.text = "Selecionar motivo"
        
        self._update_damage_evidence_visibility()
        self.update_summary()
        
        # Avançar para step 2
        self.current_step = 2
        self.update_ui_state()
        Clock.schedule_once(self._scroll_loss_form_to_top, 0.35)

    def clear_selection(self):
        """Limpa seleção e volta para step 1"""
        self.selected_product = None
        self.current_step = 1
        self.update_ui_state()
        self.clear_form()

    # ========== TIPO DE PERDA ==========
    def open_loss_menu(self):
        """Abre menu de tipos de perda"""
        if not self.loss_menu:
            items = []
            for label, code in LOSS_TYPES:
                items.append({
                    "text": label,
                    "on_release": lambda x=label, y=code: self.set_loss_type(x, y)
                })
            self.loss_menu = MDDropdownMenu(
                caller=self.ids.loss_type_btn,
                items=items,
                width_mult=3
            )
        self.loss_menu.open()

    def set_loss_type(self, label, code):
        """Define o tipo e preenche automaticamente o motivo de validade."""
        self.selected_loss_type = code
        self.ids.loss_type_btn.text = label
        self.selected_loss_reason = EXPIRY_LOSS_REASON if code == "EXPIRED" else ""
        self.ids.reason_spinner_btn.text = (
            f"Motivo: {EXPIRY_LOSS_REASON} (automatico)"
            if code == "EXPIRED"
            else "Selecionar motivo"
        )
        self._update_damage_evidence_visibility()
        if self.current_step == 2:
            self._show_card(self.ids.loss_form_card, self._loss_form_target_height())
        
        if self.loss_menu:
            self.loss_menu.dismiss()

    def open_reason_menu(self):
        """Abre a lista de motivos permitidos; validade ja vem preenchida."""
        if not self.selected_loss_type or self.selected_loss_type == "EXPIRED":
            return
        if self.reason_menu:
            self.reason_menu.dismiss()
        reasons = LOSS_REASONS.get(self.selected_loss_type, ())
        self.reason_menu = MDDropdownMenu(
            caller=self.ids.reason_spinner_btn,
            items=[
                {
                    "text": reason,
                    "on_release": lambda *_args, value=reason: self.set_loss_reason(value),
                }
                for reason in reasons
            ],
            width_mult=5,
        )
        self.reason_menu.open()

    def set_loss_reason(self, reason):
        self.selected_loss_reason = str(reason or "").strip()
        self.ids.reason_spinner_btn.text = self.selected_loss_reason or "Selecionar motivo"
        if self.reason_menu:
            self.reason_menu.dismiss()

    @staticmethod
    def _is_product_expired(expiry_date):
        if not expiry_date:
            return False
        text = str(expiry_date).strip()
        if not text:
            return False
        try:
            return datetime.fromisoformat(text).date() < date.today()
        except ValueError:
            for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(text, date_format).date() < date.today()
                except ValueError:
                    continue
        return False

    # ========== EVIDENCIA INTELIGENTE DE DANO ==========
    def _update_damage_evidence_visibility(self):
        if not hasattr(self, "ids") or "damage_evidence_card" not in self.ids:
            return
        enabled = self.selected_loss_type == "DAMAGE"
        card = self.ids.damage_evidence_card
        card.opacity = 1 if enabled else 0
        card.disabled = not enabled
        card.height = dp(326) if enabled else 0
        if not enabled:
            self.close_damage_camera_panel()
            self._clear_damage_evidence_attempt()
            self.ids.damage_evidence_status.text = ""

    def _clear_damage_evidence_attempt(self):
        """Remove da interface uma foto que nao pode servir de evidencia.

        As capturas da camara sao temporarias e sao removidas pelo respetivo
        ciclo de limpeza. O formulario nao aceita ficheiros externos.
        """
        self.damage_evidence_id = None
        self.damage_evidence_source = None
        if not hasattr(self, "ids"):
            return
        if "damage_evidence_file" in self.ids:
            self.ids.damage_evidence_file.text = ""
        if "damage_evidence_preview" in self.ids:
            self.ids.damage_evidence_preview.source = ""
            self.ids.damage_evidence_preview.opacity = 0

    def _set_damage_camera_status(self, text, color=None):
        if "damage_camera_status" in self.ids:
            self.ids.damage_camera_status.text = text
            self.ids.damage_camera_status.text_color = color or _theme_color(
                "text_secondary", [0.5, 0.5, 0.5, 1]
            )

    def _set_damage_camera_controls(self, captured=False):
        if "damage_camera_capture_btn" not in self.ids:
            return
        self.ids.damage_camera_capture_btn.disabled = bool(captured)
        self.ids.damage_camera_use_btn.disabled = not captured
        self.ids.damage_camera_retake_btn.disabled = not captured

    def _discard_damage_camera_snapshot(self):
        path = self._damage_camera_snapshot_path
        self._damage_camera_snapshot_path = None
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    def _cleanup_confirmed_damage_capture(self):
        path = self._damage_camera_cleanup_path
        self._damage_camera_cleanup_path = None
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    def capture_damage_image(self):
        """Abre a camara; o anexo da foto depende de confirmacao manual."""
        self.open_damage_camera()

    def open_damage_camera(self):
        """Abre a pre-visualizacao flutuante para uma captura manual."""
        if self.selected_loss_type != "DAMAGE" or self._damage_analysis_in_progress:
            return
        if self.scanning:
            self.stop_scanner(hide_panel=True)
        self._discard_damage_camera_snapshot()
        self._set_damage_camera_preview_visible(True, reset_geometry=True)
        self._set_damage_camera_controls(captured=False)
        self._set_damage_camera_status("A iniciar a camera...")
        self.ids.damage_evidence_status.text = "Enquadre o dano e toque em CAPTURAR. A foto nao sera usada sem confirmacao."
        self.start_damage_camera()

    def start_damage_camera(self):
        if self.damage_camera_running and self.damage_camera:
            return
        self.damage_camera_running = True
        Clock.unschedule(self.open_damage_camera_device)
        Clock.unschedule(self.preview_damage_camera_frame)
        Clock.schedule_once(self.open_damage_camera_device, 0.08)

    def open_damage_camera_device(self, _dt):
        if not self.damage_camera_running:
            return
        try:
            import cv2

            self.close_damage_camera_device(clear_preview=False)
            self.damage_camera = open_optimized_camera_capture(
                cv2,
                self.damage_camera_index,
                width=640,
                height=480,
                preview_fps=20,
            )
            if not self.damage_camera or not self.damage_camera.isOpened():
                raise RuntimeError("Camera nao encontrada")
            self._set_damage_camera_status(
                "Camera pronta. Capture apenas quando o dano estiver nitido.",
                _theme_color("success", [0.2, 0.7, 0.3, 1]),
            )
            Clock.schedule_interval(self.preview_damage_camera_frame, 1 / 20)
        except Exception:
            self.damage_camera_running = False
            self.close_damage_camera_device(clear_preview=False)
            self._set_damage_camera_status(
                "Camera indisponivel. Use TROCAR CAMERA para selecionar Iriun Webcam.",
                _theme_color("danger", [0.9, 0.2, 0.2, 1]),
            )

    def close_damage_camera_device(self, clear_preview=True):
        if self.damage_camera:
            try:
                self.damage_camera.release()
            except Exception:
                pass
            self.damage_camera = None
        self._damage_camera_frame = None
        if clear_preview and "damage_camera_image" in self.ids:
            self.ids.damage_camera_image.texture = None

    def stop_damage_camera(self, hide_panel=False, clear_preview=True):
        self.damage_camera_running = False
        Clock.unschedule(self.open_damage_camera_device)
        Clock.unschedule(self.preview_damage_camera_frame)
        self.close_damage_camera_device(clear_preview=clear_preview)
        if hide_panel:
            self._set_damage_camera_preview_visible(False)

    def close_damage_camera_panel(self):
        self.stop_damage_camera(hide_panel=True)
        self._discard_damage_camera_snapshot()
        self._set_damage_camera_controls(captured=False)

    def preview_damage_camera_frame(self, _dt):
        if not self.damage_camera_running or not self.damage_camera:
            return
        try:
            ok, frame = self.damage_camera.read()
            if not ok or frame is None:
                return
            self._damage_camera_frame = frame.copy()
            self._show_damage_camera_frame(frame)
        except Exception:
            self._set_damage_camera_status(
                "A leitura da camera falhou. Tente TROCAR CAMERA.",
                _theme_color("danger", [0.9, 0.2, 0.2, 1]),
            )

    def _show_damage_camera_frame(self, frame):
        try:
            import cv2

            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt="bgr")
            texture.blit_buffer(cv2.flip(frame, 0).tobytes(), colorfmt="bgr", bufferfmt="ubyte")
            self.ids.damage_camera_image.texture = texture
        except Exception:
            pass

    def capture_damage_camera_frame(self):
        """Guarda o frame apresentado; o anexo so inicia apos confirmacao explicita."""
        if not self.damage_camera_running or self._damage_camera_frame is None:
            self._set_damage_camera_status(
                "Aguarde a pre-visualizacao da camera antes de capturar.",
                _theme_color("warning", [0.9, 0.7, 0.1, 1]),
            )
            return
        try:
            import cv2

            self._discard_damage_camera_snapshot()
            path = temp_path("damage-captures", f"damage-{datetime.now():%Y%m%d-%H%M%S-%f}.jpg")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(path), self._damage_camera_frame):
                raise RuntimeError("Nao foi possivel guardar a foto capturada")
            self._damage_camera_snapshot_path = str(path)
            self.stop_damage_camera(clear_preview=False)
            self._set_damage_camera_controls(captured=True)
            self._set_damage_camera_status(
                "Foto capturada. Confirme UTILIZAR FOTO para a anexar ou REPETIR para tirar outra.",
                _theme_color("info", [0.15, 0.65, 0.85, 1]),
            )
        except Exception as exc:
            self._set_damage_camera_status(
                f"Falha ao capturar: {exc}",
                _theme_color("danger", [0.9, 0.2, 0.2, 1]),
            )

    def use_damage_camera_snapshot(self):
        path = self._damage_camera_snapshot_path
        if not path or not Path(path).is_file():
            self._set_damage_camera_status(
                "Capture uma foto antes de a utilizar.",
                _theme_color("warning", [0.9, 0.7, 0.1, 1]),
            )
            return
        self._damage_camera_snapshot_path = None
        self._damage_camera_cleanup_path = str(path)
        self.stop_damage_camera(hide_panel=True)
        self._attach_captured_damage_image(str(path))

    def retake_damage_camera_photo(self):
        self._discard_damage_camera_snapshot()
        self._set_damage_camera_controls(captured=False)
        self._set_damage_camera_status("A iniciar a camera para uma nova foto...")
        self.start_damage_camera()

    def switch_damage_camera(self):
        self._discard_damage_camera_snapshot()
        self.damage_camera_index = (self.damage_camera_index + 1) % self.DAMAGE_CAMERA_MAX_INDEX
        self.stop_damage_camera(clear_preview=True)
        self._set_damage_camera_controls(captured=False)
        self._set_damage_camera_status(
            "A procurar outra camera. O Iriun Webcam surge como uma camera virtual.",
            _theme_color("info", [0.15, 0.65, 0.85, 1]),
        )
        self.start_damage_camera()

    def _uses_remote_evidence_service(self):
        module_name = str(getattr(self.db.__class__, "__module__", ""))
        return module_name.startswith("database.client") or uses_remote_backend(self.db)

    def _attach_captured_damage_image(self, source_path):
        """Prepara e anexa apenas uma foto produzida pela camera desta sessao."""
        if self.selected_loss_type != "DAMAGE" or self._damage_analysis_in_progress:
            return
        try:
            capture_root = temp_path("damage-captures").resolve()
            captured_path = Path(str(source_path)).resolve()
            captured_path.relative_to(capture_root)
            if not captured_path.is_file():
                raise ValueError
        except (OSError, ValueError):
            self.show_dialog(
                "Captura obrigatoria",
                "Para registar dano, capture a foto agora pela camera do sistema.",
            )
            return
        self._damage_analysis_in_progress = True
        self.damage_evidence_id = None
        self.damage_evidence_source = str(captured_path)
        self.ids.damage_evidence_status.text = "A anexar a foto..."
        self.ids.damage_evidence_file.text = captured_path.name
        self.ids.damage_evidence_preview.source = str(captured_path)
        self.ids.damage_evidence_preview.opacity = 1
        app = App.get_running_app()
        user = getattr(app, "current_user", None)

        def worker():
            try:
                if self._uses_remote_evidence_service():
                    result = self.db.upload_damage_evidence(str(captured_path))
                    if result is None:
                        error = getattr(self.db, "last_error", lambda: "")()
                        raise DamageEvidenceError(error or "Nao foi possivel contactar o servidor para anexar a foto.")
                else:
                    result = create_local_damage_evidence(self.db, captured_path, created_by=user)
                return {"ok": True, "result": result}
            except DamageEvidenceError as exc:
                return {"ok": False, "message": str(exc)}
            except Exception as exc:
                return {"ok": False, "message": f"Nao foi possivel anexar a foto: {exc}"}

        def finish():
            payload = worker()
            Clock.schedule_once(lambda _dt, data=payload: self._apply_damage_attachment(data), 0)

        Thread(target=finish, daemon=True).start()

    def _apply_damage_attachment(self, payload):
        self._damage_analysis_in_progress = False
        self._cleanup_confirmed_damage_capture()
        if not payload.get("ok"):
            self._clear_damage_evidence_attempt()
            self.ids.damage_evidence_status.text = payload.get("message") or "Nao foi possivel anexar a foto."
            return
        result = payload.get("result") or {}
        if result.get("attached") and result.get("evidence_id"):
            self.damage_evidence_id = result["evidence_id"]
            self.ids.damage_evidence_status.text = result.get("message") or "Foto anexada. Pode registar a perda."
            return
        self._clear_damage_evidence_attempt()
        self.ids.damage_evidence_status.text = result.get("message") or "Nao foi possivel anexar a foto. Tente outra imagem."

    # ========== RESUMO ==========
    def on_qty_change(self, text):
        """Quando quantidade muda"""
        self.update_summary()

    def update_summary(self):
        """Atualiza resumo financeiro"""
        if not self.selected_product:
            self.ids.cost_label.text = "0.00 MZN"
            self.ids.revenue_label.text = "0.00 MZN"
            return
        
        qty = self.get_qty()
        if qty is None or qty <= 0:
            self.ids.cost_label.text = "0.00 MZN"
            self.ids.revenue_label.text = "0.00 MZN"
            return
        
        price = float(self.selected_product[3] or 0)
        cost = float(self.selected_product[4] or 0)
        
        total_cost = cost * qty
        total_revenue = price * qty
        
        self.ids.cost_label.text = f"{total_cost:.2f} MZN"
        self.ids.revenue_label.text = f"{total_revenue:.2f} MZN"

    def get_qty(self):
        """Pega quantidade digitada"""
        try:
            text = self.ids.qty_input.text.strip()
            if not text:
                return None
            return float(text)
        except:
            return None

    def _set_loss_busy(self, busy):
        self._saving_loss = bool(busy)
        submit_btn = self.ids.get("submit_loss_btn") if self.ids else None
        if submit_btn is None:
            return
        submit_btn.disabled = self._saving_loss
        submit_btn.text = "A PROCESSAR..." if self._saving_loss else "REGISTRAR PERDA"

    # ========== REGISTRO ==========
    def submit_loss(self):
        """Mantem compatibilidade com callbacks antigos do KV."""
        self.register_loss()

    def register_loss(self):
        """Registra a perda"""
        if self._saving_loss:
            return

        # Valida??es
        if not self.selected_product:
            self.show_dialog("Erro", "Nenhum produto selecionado")
            return

        if not self.selected_loss_type:
            self.show_dialog("Erro", "Selecione o tipo de perda")
            return

        qty = self.get_qty()
        if not qty or qty <= 0:
            self.show_dialog("Erro", "Quantidade invalida ou vazia")
            return

        pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = self.selected_product

        # Validar quantidade inteira para unidades
        if not is_weight and not float(qty).is_integer():
            self.show_dialog("Erro", "Quantidade deve ser um numero inteiro para produtos por unidade")
            return

        # Validar stock
        if qty > float(stock):
            self.show_dialog("Erro", f"Quantidade maior que stock disponivel ({stock:.1f})")
            return

        # O motivo e sempre escolhido na lista; para validade ele ja aparece
        # automaticamente e a data e conferida antes da chamada ao banco.
        if self.selected_loss_type == "EXPIRED":
            reason = self.selected_loss_reason
            if reason != EXPIRY_LOSS_REASON:
                self.show_dialog("Motivo obrigatorio", "O motivo automatico para este tipo e 'Data de validade'.")
                return
            if not self._is_product_expired(exp):
                self.show_dialog(
                    "Produto nao expirado",
                    "A perda nao foi registada porque a data de validade ainda nao expirou.",
                )
                return
        else:
            reason = self.selected_loss_reason
        if not reason:
            self.show_dialog("Motivo obrigatorio", "Selecione um motivo na lista.")
            return

        note = self.ids.note_input.text.strip()
        evidence_id = self.damage_evidence_id
        if self.selected_loss_type == "DAMAGE" and not evidence_id:
            self.show_dialog(
                "Foto necessaria",
                "Tire ou escolha uma foto nitida que mostre o dano antes de continuar.",
            )
            return

        app = App.get_running_app()
        user = getattr(app, "current_user", None)
        role = getattr(app, "current_role", "manager")
        loss_type = self.selected_loss_type

        self._set_loss_busy(True)

        def worker():
            try:
                movement_id = self.db.request_stock_movement(
                    pid,
                    loss_type,
                    qty,
                    reason,
                    user,
                    role,
                    direction="OUT",
                    note=note,
                    evidence_id=evidence_id,
                    unit_cost=cost,
                    unit_price=price,
                )
                if not movement_id:
                    return {"ok": False, "message": "Erro ao registrar perda no banco de dados"}

                approval = self.db.get_stock_movement_approval_status(movement_id) or {}
                approval_status = str(approval.get("approval_status") or "APPROVED").upper()
                is_pending = approval_status == "PENDING"

                stock_before = float(stock)
                stock_after = stock_before if is_pending else stock_before - float(qty)
                self._append_loss_log({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "movement_id": movement_id,
                    "product_id": pid,
                    "product_name": name,
                    "barcode": barcode,
                    "loss_type": loss_type,
                    "qty": float(qty),
                    "unit": "KG" if is_weight else "UN",
                    "reason": reason,
                    "note": note,
                    "evidence_id": evidence_id,
                    "user": user,
                    "role": role,
                    "unit_cost": float(cost or 0),
                    "unit_price": float(price or 0),
                    "total_cost": float(cost or 0) * float(qty),
                    "total_price": float(price or 0) * float(qty),
                    "stock_before": stock_before,
                    "stock_after": stock_after,
                    "approval_status": approval_status,
                })
                if user:
                    try:
                        action = "REQUEST_LOSS_APPROVAL" if is_pending else "REGISTER_LOSS"
                        self.db.log_action(user, role, action, f"{loss_type} | {name} | {qty}")
                    except Exception:
                        pass
                return {"ok": True, "pending": is_pending}
            except Exception as exc:
                print(f"Erro: {exc}")
                return {"ok": False, "message": f"Erro ao registrar perda: {exc}"}

        def apply_result(result):
            self._set_loss_busy(False)
            if not result.get("ok"):
                self.show_dialog("Erro", result.get("message") or "Erro ao registrar perda.")
                return
            if result.get("pending"):
                self.show_dialog(
                    "Aguardando aprovacao",
                    "A perda foi enviada para validacao do administrador. O stock nao foi alterado.",
                )
            else:
                self.show_dialog("Sucesso", "Perda registrada com sucesso!")
            self.clear_form()
            self.load_products()
            self.current_step = 1
            self.update_ui_state()

        def finish_worker():
            result = worker()
            Clock.schedule_once(lambda dt, payload=result: apply_result(payload), 0)

        Thread(target=finish_worker, daemon=True).start()

    # ========== HELPERS ==========
    def _append_loss_log(self, entry):
        """Grava um registro simples em losses_log.py"""
        try:
            log_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "losses_log.py"))
            if not os.path.exists(log_path):
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("# Auto-generated loss log entries\n")
                    f.write("LOGS = []\n")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"LOGS.append({entry!r})\n")
        except Exception as e:
            print(f"Erro ao salvar log de perda: {e}")

    def clear_form(self):
        """Limpa o formulário"""
        self.selected_product = None
        self.selected_loss_type = ""
        self.selected_loss_reason = ""
        self.ids.loss_type_btn.text = "Selecionar Tipo"
        self.ids.qty_input.text = ""
        self.ids.reason_spinner_btn.text = "Selecionar motivo"
        self.ids.note_input.text = ""
        self._clear_damage_evidence_attempt()
        if "damage_evidence_card" in self.ids:
            self.close_damage_camera_panel()
            self.ids.damage_evidence_status.text = ""
            self._update_damage_evidence_visibility()
        self.ids.selected_name.text = "Produto Selecionado"
        self.ids.selected_stock.text = "Stock: --"
        self.ids.selected_unit.text = "Tipo: --"
        self.ids.selected_price.text = "Preço: --"
        self.ids.search_input.text = ""
        self.update_summary()

    def show_dialog(self, title, message):
        """Mostra mensagem"""
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: dialog.dismiss())]
        )
        dialog.open()
