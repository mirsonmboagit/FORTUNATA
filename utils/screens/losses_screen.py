from kivy.lang import Builder
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.graphics import Color, Line
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.core.audio import SoundLoader
from kivy.animation import Animation
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout, NativeButton as MDRaisedButton, NativeCard as MDCard,
    NativeDialog as MDDialog, NativeDropdownMenu as MDDropdownMenu,
    NativeFlatButton as MDFlatButton, NativeIcon as MDIcon, NativeLabel as MDLabel,
    NativeListItem as TwoLineListItem, NativeScreen as MDScreen,
)
from kivy.properties import NumericProperty, ObjectProperty, StringProperty
from database.provider import get_db
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
        # Painel oculto nunca captura toques (deixa passar aos botoes de baixo)
        if self.disabled or self.opacity <= 0.01:
            return False
        if not self.collide_point(*touch.pos):
            return False

        # 1) Filhos clicaveis (X, CAPTURAR, etc.) têm prioridade sobre arrastar
        for child in reversed(list(self.children)):
            if child.dispatch("on_touch_down", touch):
                return True

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
        if self.disabled or self.opacity <= 0.01:
            return False
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

class ExpiredBatchRow(ButtonBehavior, MDCard):
    """Linha clicável no modal de lote — clicar alterna a seleção."""
    def __init__(self, product_id=None, **kwargs):
        super().__init__(**kwargs)
        self.product_id = product_id


class LossesScreen(MDScreen):
    db = ObjectProperty(None)
    selected_loss_type = StringProperty("")
    selected_loss_reason = StringProperty("")
    PRODUCTS_CACHE_SECONDS = 5
    ENTER_REFRESH_DELAY_SECONDS = 0.08
    PRODUCT_RENDER_BATCH_SIZE = 20
    PRODUCTS_PAGE_SIZE = 10
    SCANNER_AUTO_START_DELAY_SECONDS = 0.18
    DAMAGE_CAMERA_MAX_INDEX = 8
    
    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.back_target = "admin_home"
        self.products = []
        self._products_page_offset = 0
        self._products_has_more = False
        self._pending_products_page_request = None
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

        # Lote de vencidos
        self._expired_batch_rows = []
        self._expired_batch_selection = set()
        self._expired_batch_dialog = None
        self._expired_batch_checking = False
        self._expired_batch_total_label = None
        self._expired_batch_confirm_btn = None
        self._pending_products_page_request = None
        self._pending_products_offset = 0

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
        self.current_step = 1
        self.update_ui_state()
        self._update_responsive_layout()
        Clock.schedule_once(lambda dt: self._check_expired_batch(), 0.3)
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
            "attempts": 0,
        }
        # Uma página pode não conter o produto do alerta. A pesquisa abaixo
        # força uma consulta SQL por ID/código em vez de procurar apenas os 10
        # itens visíveis.
        search_text = str(query or product_id or "").strip()
        self._pending_search = search_text
        if "search_input" in self.ids:
            self.ids.search_input.text = search_text
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
            # Restaura tamanho minimo antes de posicionar
            if panel.width < dp(100) or panel.height < dp(100):
                panel.size = (dp(280), dp(240))
            self._ensure_scanner_panel_geometry(reset=reset_geometry or True)
            # Trazer para a frente
            parent = panel.parent
            if parent is not None:
                parent.remove_widget(panel)
                parent.add_widget(panel)
        else:
            panel.opacity = 0
            panel.disabled = True
            # Fora da area clicavel
            panel.size = (dp(1), dp(1))
            panel.pos = (-dp(500), -dp(500))

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
            if panel.width < dp(100) or panel.height < dp(100):
                panel.size = (dp(340), dp(380))
            self._ensure_damage_camera_panel_geometry(reset=reset_geometry or True)
            parent = panel.parent
            if parent is not None:
                parent.remove_widget(panel)
                parent.add_widget(panel)
        else:
            panel.opacity = 0
            panel.disabled = True
            panel.size = (dp(1), dp(1))
            panel.pos = (-dp(500), -dp(500))

        Clock.schedule_once(lambda _dt: self._update_responsive_layout(), 0)

    def close_scanner_panel(self, *_args):
        self._cancel_scanner_auto_start()
        self.stop_scanner(status_text="Scanner fechado", hide_panel=True)

    def _update_responsive_layout(self):
        """So gere o espaco inferior quando um painel flutuante esta aberto."""
        ids = getattr(self, "ids", None)
        if not ids or "content_column" not in ids:
            return
        narrow = float(self.width or Window.width or 1200) < dp(720)
        panels = []
        for pid, ensure in (
            ("scanner_preview_card", self._ensure_scanner_panel_geometry),
            ("damage_camera_preview_card", self._ensure_damage_camera_panel_geometry),
        ):
            panel = ids.get(pid)
            if panel is not None and panel.opacity > 0.5 and not panel.disabled:
                ensure()
                panels.append(panel)
        visible_h = max((p.height for p in panels), default=0)
        side = dp(12) if narrow else dp(14)
        ids.content_column.padding = [side, dp(10), side, visible_h + dp(28) if visible_h else dp(16)]
        ids.content_column.spacing = dp(10) if narrow else dp(12)


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
    def _scroll_loss_form_to_top(self, _dt=0):
        if "losses_scroll" in self.ids:
            self.ids.losses_scroll.scroll_y = 1

    def update_ui_state(self):
        """Mostra o passo 1 OU o passo 2. Sem animacoes, sem alturas manuais."""
        if self.current_step == 2 and not self.selected_product:
            self.current_step = 1
        step1 = self.current_step == 1
        ids = self.ids
        if "search_card" in ids:
            ids.search_card.disabled = not step1
        if "loss_form_card" in ids:
            ids.loss_form_card.disabled = step1
        if "loss_action_bar" in ids:
            ids.loss_action_bar.disabled = step1
        if not step1:
            Clock.schedule_once(self._scroll_loss_form_to_top, 0.05)
        self._refresh_step2_controls()


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
            self.camera = open_optimized_camera_capture(
                cv2,
                self.current_camera_index,
                width=640,
                height=480,
                preview_fps=20,
            )
            
            if self.camera and self.camera.isOpened():
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
    def load_products(self, offset=0):
        """Carrega uma página de produtos (offset = posição inicial)."""
        offset = max(0, int(offset or 0))
        if self._products_loading:
            self._pending_products_load = True
            self._pending_products_offset = offset
            return

        token = self._products_load_token + 1
        self._products_load_token = token
        self._products_loading = True
        query = str(self._pending_search or "").strip()
        if hasattr(self, "ids") and self.ids:
            label = self.ids.get("losses_page_label")
            if label is not None:
                label.text = "A carregar…"
            for bid in ("losses_prev_btn", "losses_next_btn"):
                btn = self.ids.get(bid)
                if btn is not None:
                    btn.disabled = True

        def worker():
            try:
                getter = getattr(self.db, "get_products_for_losses_page", None)
                payload = getter(query, self.PRODUCTS_PAGE_SIZE, offset) if callable(getter) else {"rows": [], "has_more": False}
            except Exception as e:
                print(f"[losses] Erro ao carregar produtos (offset={offset}): {e}")
                payload = {"rows": [], "has_more": False}
            Clock.schedule_once(
                lambda dt, data=payload, tok=token, off=offset: self._apply_loaded_products(data, tok, off),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_products(self, payload, token, offset=0):
        if token != self._products_load_token:
            return

        self._products_loading = False
        self._last_products_load_at = perf_counter()
        rows = [
            n for n in (self._normalize_product_row(r) for r in (payload or {}).get("rows", []))
            if n is not None
        ]

        # Página vazia depois da primeira: volta à anterior em vez de mostrar lista vazia
        if not rows and offset > 0:
            self._products_has_more = False
            self.load_products(max(0, offset - self.PRODUCTS_PAGE_SIZE))
            return

        self.products = rows
        self._products_page_offset = offset
        self._products_has_more = bool((payload or {}).get("has_more"))
        # se a BD nao devolver has_more, assumir mais paginas quando a pagina veio cheia
        if not self._products_has_more and len(rows) >= self.PRODUCTS_PAGE_SIZE:
            self._products_has_more = True
        self.show_products(self.products)
        self._sync_products_page_controls()
        self._consume_pending_product_focus()

        if self._pending_products_load:
            self._pending_products_load = False
            pending_offset = getattr(self, "_pending_products_offset", 0)
            self._pending_products_offset = 0
            Clock.schedule_once(lambda dt, off=pending_offset: self.load_products(off), 0.05)

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
            request["attempts"] = int(request.get("attempts", 0)) + 1
            if request["attempts"] >= 3:
                self._pending_product_focus = None
                self.show_dialog(
                    "Produto não encontrado",
                    "Não foi possível localizar automaticamente o produto para registar a perda. "
                    "Utilize a pesquisa manual para encontrá-lo.",
                )
                return False

            search_text = str(request.get("query") or request.get("product_id") or "").strip()
            if search_text and "search_input" in self.ids:
                self._pending_search = search_text
                self.ids.search_input.text = search_text
                # A lista é paginada; recarrega do SQLite e mantém o pedido
                # pendente para selecionar a linha quando chegar.
                self.load_products()
            return False

        self._pending_product_focus = None
        self.select_product(product)
        label = request.get("loss_type_label")
        code = request.get("loss_type_code")
        if label and code:
            self.set_loss_type(label, code)
        return True

    def _stop_products_render(self):
        if getattr(self, "_products_render_ev", None):
            try:
                self._products_render_ev.cancel()
            except Exception:
                pass
            self._products_render_ev = None

    def show_products(self, products):
        """Renderiza a pagina actual de produtos como tabela de cartoes."""
        if "products_list" not in self.ids:
            return

        self._stop_products_render()
        self.ids.products_list.clear_widgets()

        rows = list(products or [])
        if not rows:
            empty = MDBoxLayout(
                orientation="vertical",
                size_hint_y=None,
                height=dp(72),
                padding=[dp(12), dp(16)],
            )
            empty.add_widget(MDLabel(
                text="Nenhum produto encontrado",
                bold=True,
                halign="center",
                theme_text_color="Custom",
                text_color=_theme_color("text_primary", [0.9, 0.92, 0.95, 1]),
            ))
            empty.add_widget(MDLabel(
                text="Ajuste a pesquisa ou verifique o stock disponivel.",
                halign="center",
                font_size=dp(12),
                theme_text_color="Custom",
                text_color=_theme_color("text_secondary", [0.55, 0.6, 0.65, 1]),
            ))
            self.ids.products_list.add_widget(empty)
            return

        self._products_render_rows = rows
        self._products_render_index = 0
        self._render_next_products_batch(0)
        if self._products_render_index < len(self._products_render_rows):
            self._products_render_ev = Clock.schedule_interval(
                self._render_next_products_batch, 0.016
            )

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
        """Linha de produto robusta, clicavel, com stock/preco/estado."""
        pid, name, stock, price, _cost, barcode, is_weight, exp, status, _vat = product
        unit = "KG" if is_weight else "UN"
        stock_val = float(stock or 0)
        stock_txt = f"{stock_val:.2f} {unit}" if is_weight else f"{int(stock_val)} {unit}"
        price_txt = f"{float(price or 0):.2f} MT"
        code_txt = str(barcode or "").strip() or f"#{pid}"

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        is_expired = status == "EXPIRADO"
        is_near = status == "PERTO_DO_PRAZO"

        bg = tokens.get("card_alt", [0.16, 0.19, 0.24, 1])
        fg = tokens.get("text_primary", [0.95, 0.96, 0.98, 1])
        muted = tokens.get("text_secondary", [0.55, 0.60, 0.66, 1])
        danger = tokens.get("danger", [0.85, 0.25, 0.28, 1])
        warning = tokens.get("warning", [0.90, 0.65, 0.15, 1])
        success = tokens.get("success", [0.20, 0.70, 0.42, 1])
        primary = tokens.get("primary", [0.15, 0.48, 0.82, 1])

        if is_expired:
            badge_text, badge_color = "EXPIRADO", danger
        elif is_near:
            badge_text, badge_color = "PERTO", warning
        else:
            badge_text, badge_color = "OK", success

        display_name = str(name or "Produto").strip()
        if len(display_name) > 36:
            display_name = display_name[:35].rstrip() + "…"

        row = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(10), dp(6), dp(8), dp(6)],
            spacing=dp(8),
            radius=[dp(10)],
            elevation=0,
            md_bg_color=bg,
        )

        left = MDBoxLayout(orientation="vertical", spacing=dp(2), size_hint_x=0.48)
        left.add_widget(MDLabel(
            text=display_name,
            bold=True,
            font_size=dp(13),
            shorten=True,
            shorten_from="right",
            theme_text_color="Custom",
            text_color=fg,
            size_hint_y=None,
            height=dp(20),
        ))
        left.add_widget(MDLabel(
            text=f"{code_txt}  ·  {stock_txt}",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=muted,
            size_hint_y=None,
            height=dp(16),
        ))
        row.add_widget(left)

        price_lbl = MDLabel(
            text=price_txt,
            bold=True,
            font_size=dp(13),
            size_hint_x=0.22,
            halign="right",
            valign="middle",
            theme_text_color="Custom",
            text_color=fg,
        )
        price_lbl.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        row.add_widget(price_lbl)

        badge = MDCard(
            size_hint=(None, None),
            size=(dp(78), dp(26)),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=[badge_color[0], badge_color[1], badge_color[2], 0.22],
            padding=[dp(4), 0],
            pos_hint={"center_y": 0.5},
        )
        badge.add_widget(MDLabel(
            text=badge_text,
            bold=True,
            font_size=dp(10),
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=badge_color,
            text_size=(dp(70), dp(26)),
        ))
        row.add_widget(badge)

        select_btn = MDRaisedButton(
            text="Usar",
            size_hint=(None, None),
            size=(dp(58), dp(28)),
            font_size=dp(11),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=primary,
            pos_hint={"center_y": 0.5},
        )
        select_btn.bind(on_release=lambda _b, p=product: self.select_product(p))
        row.add_widget(select_btn)

        def _on_row_touch(instance, touch, p=product):
            if not instance.collide_point(*touch.pos):
                return False
            if select_btn.collide_point(*touch.pos):
                return False
            if getattr(touch, "is_mouse_scrolling", False):
                return False
            if touch.grab_current is not None and touch.grab_current is not instance:
                return False
            self.select_product(p)
            return True

        row.bind(on_touch_up=_on_row_touch)
        return row

    def previous_products_page(self, *_args):
        """Pagina anterior — sempre responde ao clique."""
        if self._products_page_offset <= 0:
            return
        # se ficou preso em loading, liberta
        if self._products_loading:
            self._products_loading = False
        new_offset = max(0, self._products_page_offset - self.PRODUCTS_PAGE_SIZE)
        self.load_products(new_offset)

    def next_products_page(self, *_args):
        """Pagina seguinte — tenta avançar se houver indício de mais dados."""
        count = len(self.products or [])
        can_try = self._products_has_more or count >= self.PRODUCTS_PAGE_SIZE
        if not can_try:
            return
        if self._products_loading:
            self._products_loading = False
        self.load_products(self._products_page_offset + self.PRODUCTS_PAGE_SIZE)

    def _sync_products_page_controls(self):
        """Actualiza label e estado dos botoes Anterior/Proximo."""
        if not hasattr(self, "ids") or not self.ids:
            return
        label = self.ids.get("losses_page_label")
        prev_btn = self.ids.get("losses_prev_btn")
        next_btn = self.ids.get("losses_next_btn")

        count = len(self.products or [])
        start = self._products_page_offset + 1 if count else 0
        end = self._products_page_offset + count
        page_num = (self._products_page_offset // max(1, self.PRODUCTS_PAGE_SIZE)) + 1
        can_next = bool(self._products_has_more) or count >= self.PRODUCTS_PAGE_SIZE

        if label is not None:
            if count:
                suffix = " +" if can_next else ""
                label.text = f"Pag. {page_num}  ·  {start}–{end}{suffix}"
            else:
                label.text = "Sem resultados"

        if prev_btn is not None:
            prev_btn.disabled = self._products_page_offset <= 0
            prev_btn.opacity = 0.45 if prev_btn.disabled else 1.0

        if next_btn is not None:
            next_btn.disabled = not can_next
            next_btn.opacity = 0.45 if next_btn.disabled else 1.0

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
        self._products_page_offset = 0
        self.load_products(0)

    # def _load_products_page(self, offset):
    #     if self._products_loading:
    #         self._pending_products_page_request = int(offset)
    #         return
    #     self._products_page_offset = max(0, int(offset))
    #     token = self._products_load_token + 1
    #     self._products_load_token = token
    #     self._products_loading = True
    #     query = str(self._pending_search or "").strip()
    #     def worker():
    #         try:
    #             payload = self.db.get_products_for_losses_page(query, self.PRODUCTS_PAGE_SIZE, self._products_page_offset)
    #         except Exception as exc:
    #             print(f"[losses] ERRO ao paginar produtos (offset={self._products_page_offset}): {exc}")
    #             payload = {"rows": [], "has_more": False}
    #         Clock.schedule_once(lambda _dt: self._apply_products_page(payload, token), 0)
    #     Thread(target=worker, daemon=True).start()

    # def _apply_products_page(self, payload, token):
    #     if token != self._products_load_token:
    #         return
    #     self._products_loading = False
    #     self.products = [p for p in (self._normalize_product_row(row) for row in (payload or {}).get("rows", [])) if p]
    #     self._products_has_more = bool((payload or {}).get("has_more"))
    #     self.show_products(self.products)
    #     self._sync_products_page_controls()

    #     pending_offset = self._pending_products_page_request
    #     if pending_offset is not None:
    #         self._pending_products_page_request = None
    #         Clock.schedule_once(lambda _dt, off=pending_offset: self._load_products_page(off), 0.05)

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
        """Pesquisa no banco desde o inicio (offset 0)."""
        if self._search_ev:
            Clock.unschedule(self._search_ev)
            self._search_ev = None
        raw = self.ids.search_input.text if "search_input" in self.ids else ""
        self._pending_search = str(raw or "").strip()
        self._products_page_offset = 0
        self.load_products(0)

    def find_product_by_barcode(self, barcode):
        """Busca produto pelo código de barras"""
        for p in self.products:
            if len(p) > 5 and p[5] and str(p[5]).strip() == str(barcode).strip():
                return p
        return None

    def select_product(self, product):
        """Seleciona um produto e avanca para o passo 2."""
        normalized = self._normalize_product_row(product)
        if normalized is None:
            self.show_dialog("Erro", "Produto invalido para selecao.")
            return
        self.selected_product = normalized
        pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat = normalized
        unit = "KG" if is_weight else "UN"
        stock = float(stock or 0)
        if stock <= 0:
            self.show_dialog("Sem stock", "Este produto nao tem stock disponivel para perda.")
            self.selected_product = None
            return

        self.ids.selected_name.text = str(name or "Produto")
        self.ids.selected_stock.text = f"Stock: {stock:g} {unit}  ·  Preco: {float(price or 0):.2f} MZN"
        if "qty_hint" in self.ids:
            self.ids.qty_hint.text = f"de {stock:g} {unit}"
        self.ids.qty_input.disabled = False
        self.ids.qty_input.input_filter = "float" if is_weight else "int"
        self.ids.qty_input.text = "1"

        self._clear_damage_evidence_attempt()
        self.selected_loss_type = ""
        self.selected_loss_reason = ""
        if status == "EXPIRADO":
            self.set_loss_type("EXPIRADO", "EXPIRED")
        else:
            self._rebuild_reason_buttons()
        self._update_damage_evidence_visibility()
        self.update_summary()

        self.current_step = 2
        self.update_ui_state()


    def clear_selection(self, *_args):
        """Botao TROCAR: volta ao passo 1."""
        self.clear_form()
        self.current_step = 1
        self.update_ui_state()
        Clock.schedule_once(lambda _dt: self.load_products(0), 0.05)

    def set_loss_type(self, label, code):
        """1 clique: define o tipo e prepara motivo, quantidade e foto."""
        if not self.selected_product:
            return
        code = str(code or "").strip().upper()
        previous = self.selected_loss_type
        self.selected_loss_type = code

        qty_input = self.ids.qty_input
        is_weight = bool(self.selected_product[6])
        stock = max(0.0, float(self.selected_product[2] or 0))
        qty_input.input_filter = "float" if is_weight else "int"

        if code == "EXPIRED":
            qty_input.text = f"{stock:g}" if is_weight else str(int(stock))
            qty_input.disabled = True
            self.selected_loss_reason = EXPIRY_LOSS_REASON
        else:
            qty_input.disabled = False
            if previous == "EXPIRED" or not (qty_input.text or "").strip():
                qty_input.text = "1"
            self.selected_loss_reason = ""

        self._rebuild_reason_buttons()
        self._update_damage_evidence_visibility()
        self.update_summary()
        self._refresh_step2_controls()

    def _rebuild_reason_buttons(self):
        """Motivos como botoes visiveis (1 clique) em vez de menu."""
        if not hasattr(self, "ids") or "reason_box" not in self.ids:
            return
        box = self.ids.reason_box
        box.clear_widgets()
        primary = _theme_color("primary", [0.15, 0.48, 0.82, 1])
        neutral = _theme_color("card_alt", [0.16, 0.19, 0.24, 1])
        on_primary = _theme_color("on_primary", [1, 1, 1, 1])
        text_main = _theme_color("text_primary", [0.9, 0.92, 0.95, 1])
        muted = _theme_color("text_secondary", [0.55, 0.6, 0.65, 1])

        code = self.selected_loss_type
        if not code or code == "EXPIRED":
            msg = "Escolha primeiro o tipo." if not code else f"Automatico: {EXPIRY_LOSS_REASON}"
            box.add_widget(MDLabel(
                text=msg, font_size=dp(12), size_hint_y=None, height=dp(24),
                theme_text_color="Custom", text_color=muted,
            ))
            return

        for reason in LOSS_REASONS.get(code, ()):
            selected = reason == self.selected_loss_reason
            btn = MDRaisedButton(
                text=reason,
                size_hint=(1, None),
                height=dp(40),
                font_size=dp(13),
                radius=[dp(10)],
                elevation=0,
                md_bg_color=primary if selected else neutral,
                theme_text_color="Custom",
                text_color=on_primary if selected else text_main,
            )
            btn.bind(on_release=lambda _b, r=reason: self.set_loss_reason(r))
            box.add_widget(btn)

    def set_loss_reason(self, reason):
        self.selected_loss_reason = str(reason or "").strip()
        self._rebuild_reason_buttons()
        self._refresh_step2_controls()

    def change_qty(self, delta):
        """Botoes - / +."""
        if not self.selected_product or self.selected_loss_type == "EXPIRED":
            return
        is_weight = bool(self.selected_product[6])
        stock = max(1.0, float(self.selected_product[2] or 0))
        new_qty = min(max((self.get_qty() or 0) + delta, 1), stock)
        self.ids.qty_input.text = f"{new_qty:g}" if is_weight else str(int(new_qty))

    def _refresh_step2_controls(self):
        """Destaca o tipo escolhido e indica o que falta."""
        ids = getattr(self, "ids", None)
        if not ids or "loss_action_bar" not in ids:
            return
        primary = _theme_color("primary", [0.15, 0.48, 0.82, 1])
        neutral = _theme_color("card_alt", [0.16, 0.19, 0.24, 1])
        for _label, code in LOSS_TYPES:
            btn = ids.get(f"type_btn_{code}")
            if btn is not None:
                btn.md_bg_color = primary if code == self.selected_loss_type else neutral

        missing = []
        if not self.selected_loss_type:
            missing.append("tipo")
        elif not self.selected_loss_reason:
            missing.append("motivo")
        qty = self.get_qty() if self.selected_product else None
        if not qty or qty <= 0:
            missing.append("quantidade")
        if self.selected_loss_type == "DAMAGE" and not self.damage_evidence_id:
            missing.append("foto")

        hint = ids.get("loss_missing_hint")
        if hint is not None:
            hint.text = ("Falta: " + ", ".join(missing)) if missing else "Tudo pronto"
            hint.text_color = (
                _theme_color("warning", [0.9, 0.65, 0.15, 1]) if missing
                else _theme_color("success", [0.2, 0.7, 0.3, 1])
            )
        submit = ids.get("submit_loss_btn")
        if submit is not None and not self._saving_loss:
            submit.opacity = 0.6 if missing else 1.0
        self.update_summary()


    def _update_damage_evidence_visibility(self):
        if not hasattr(self, "ids") or "damage_evidence_card" not in self.ids:
            return
        enabled = self.selected_loss_type == "DAMAGE"
        self.ids.damage_evidence_card.disabled = not enabled
        if not enabled:
            self.close_damage_camera_panel()
            self._clear_damage_evidence_attempt()
            if "damage_evidence_status" in self.ids:
                self.ids.damage_evidence_status.text = ""
        elif not self.damage_evidence_id:
            self.ids.damage_evidence_status.text = "Foto obrigatoria do dano"


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

    def close_damage_camera_panel(self, *_args):
        """Fecha o painel flutuante da camera de evidencia."""
        try:
            self.close_damage_camera_device(clear_preview=True)
        except Exception as exc:
            print(f"[losses] close_damage_camera_device: {exc}")
        try:
            self._set_damage_camera_preview_visible(False)
        except Exception as exc:
            print(f"[losses] hide damage panel: {exc}")
        self.damage_camera_running = False


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
        self.update_summary()
        self._refresh_step2_controls()


    def update_summary(self):
        label = self.ids.get("loss_impact_label") if self.ids else None
        if label is None:
            return
        qty = self.get_qty() if self.selected_product else None
        if not qty or qty <= 0:
            label.text = "Custo 0.00 MZN  ·  Receita perdida 0.00 MZN"
            return
        price = float(self.selected_product[3] or 0)
        cost = float(self.selected_product[4] or 0)
        label.text = f"Custo {cost * qty:.2f} MZN  ·  Receita perdida {price * qty:.2f} MZN"


    def get_qty(self):
        """Usa todo o stock para validade e a quantidade digitada nos outros tipos."""
        if self.selected_loss_type == "EXPIRED" and self.selected_product:
            return float(self.selected_product[2] or 0)
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
        if not self._saving_loss:
            self._refresh_step2_controls()

    # ========== REGISTRO ==========
    def submit_loss(self):
        """Mantem compatibilidade com callbacks antigos do KV."""
        self.register_loss()

    def register_loss(self):
        """Registra a perda"""
        if self._saving_loss:
            return

        # Validacoes
        if not self.selected_product:
            self.show_dialog("Erro", "Nenhum produto selecionado")
            self.current_step = 1
            self.update_ui_state()
            return

        if not self.selected_loss_type:
            self.show_dialog("Erro", "Selecione o tipo de perda")
            return

        pid, name, stock, price, cost, barcode, is_weight, exp, status, _vat_rule_code = self.selected_product

        # Expirado significa retirar integralmente o lote seleccionado. Nao
        # depende do estado visual do campo para preservar essa regra.
        qty = self.get_qty()
        if not qty or qty <= 0:
            self.show_dialog("Erro", "Quantidade invalida ou vazia")
            return

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

    # ========== LOTE DE PRODUTOS VENCIDOS ==========
    def _check_expired_batch(self, on_ready=None):
        """Verifica, em segundo plano, quantos produtos estão vencidos no catálogo inteiro."""
        if self._expired_batch_checking:
            return
        self._expired_batch_checking = True

        def worker():
            try:
                payload = self.db.get_products_for_losses_page("", 500, 0)
                rows = (payload or {}).get("rows", [])
            except Exception as exc:
                print(f"[losses] erro ao verificar vencidos em lote: {exc}")
                rows = []
            normalized = [
                r for r in (self._normalize_product_row(row) for row in rows) if r is not None
            ]
            expired = [r for r in normalized if r[8] == "EXPIRADO"]
            Clock.schedule_once(
                lambda _dt, data=expired, cb=on_ready: self._apply_expired_batch_check(data, cb), 0
            )

        Thread(target=worker, daemon=True).start()

    def _apply_expired_batch_check(self, expired_rows, on_ready=None):
        self._expired_batch_checking = False
        self._expired_batch_rows = expired_rows
        self._update_expired_batch_banner()
        if callable(on_ready):
            on_ready()

    def _update_expired_batch_banner(self):
        if not hasattr(self, "ids") or "expired_batch_banner" not in self.ids:
            return
        banner = self.ids.expired_batch_banner
        count = len(self._expired_batch_rows)
        threshold = 3
        if count >= threshold:
            self.ids.expired_batch_label.text = f"{count} produtos vencidos encontrados"
            banner.height = dp(48)
            banner.opacity = 1
            banner.disabled = False
        else:
            banner.height = 0
            banner.opacity = 0
            banner.disabled = True

    def open_expired_batch_modal(self, *args, preloaded_items=None):
        if preloaded_items is not None:
            def worker():
                data = self._enrich_batch_items(list(preloaded_items))
                Clock.schedule_once(lambda _dt, d=data: self._set_batch_rows_and_show(d), 0)
            Thread(target=worker, daemon=True).start()
            return
        if not self._expired_batch_rows:
            self._check_expired_batch(on_ready=self.open_expired_batch_modal)
            return
        self._show_expired_batch_dialog()

    def _set_batch_rows_and_show(self, items):
        self._expired_batch_rows = [
            r for r in (self._normalize_product_row(i) for i in items) if r is not None
        ]
        self._show_expired_batch_dialog()

    def _show_expired_batch_dialog(self):
        if not self._expired_batch_rows:
            self.show_dialog("Aviso", "Não há produtos vencidos para registar em lote.")
            return

        self._expired_batch_selection = {row[0] for row in self._expired_batch_rows}
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        danger = tokens.get("danger", [0.85, 0.2, 0.2, 1])
        muted = tokens.get("text_secondary", [0.55, 0.58, 0.63, 1])
        foreground = tokens.get("text_primary", [0.92, 0.94, 0.97, 1])

        content = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, height=dp(460))

        header = MDBoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        header.add_widget(
            MDIcon(
                icon="clock-alert-outline",
                theme_text_color="Custom",
                text_color=danger,
                size_hint=(None, None),
                size=(dp(20), dp(20)),
            )
        )
        header.add_widget(
            MDLabel(
                text=f"{len(self._expired_batch_rows)} produtos vencidos",
                bold=True,
                theme_text_color="Custom",
                text_color=foreground,
                font_style="Body2",
            )
        )
        content.add_widget(header)

        content.add_widget(
            MDLabel(
                text="Desmarque os produtos que não devem ser dados como perda agora.",
                theme_text_color="Custom",
                text_color=muted,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
                halign="left",
            )
        )

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(6), size_hint_y=None, height=dp(300))
        rows_box = MDBoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        rows_box.bind(minimum_height=rows_box.setter("height"))
        scroll.add_widget(rows_box)

        for row in self._expired_batch_rows:
            rows_box.add_widget(self._build_expired_batch_row(row, tokens))

        content.add_widget(scroll)

        self._expired_batch_total_label = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=foreground,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
            halign="left",
        )
        content.add_widget(self._expired_batch_total_label)

        cancel_btn = MDFlatButton(
            text="CANCELAR", theme_text_color="Custom", text_color=muted, radius=[dp(10)]
        )
        self._expired_batch_confirm_btn = MDRaisedButton(
            text=f"REGISTAR {len(self._expired_batch_selection)}",
            md_bg_color=danger,
            radius=[dp(10)],
        )
        self._update_expired_batch_totals()

        dialog = MDDialog(
            title="Perdas por validade — lote",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(520), Window.width - dp(48)), dp(520)),
            buttons=[cancel_btn, self._expired_batch_confirm_btn],
        )
        cancel_btn.bind(on_release=lambda _x: dialog.dismiss())
        self._expired_batch_confirm_btn.bind(on_release=lambda _x: self._confirm_expired_batch(dialog))
        self._expired_batch_dialog = dialog
        dialog.open()

    def _build_expired_batch_row(self, row, tokens):
        pid, name, stock, price, cost, _barcode, is_weight, _exp, _status, _vat = row
        unit = "KG" if is_weight else "UN"
        stock_val = float(stock or 0)
        stock_text = f"{stock_val:.2f} {unit}" if is_weight else f"{int(stock_val)} {unit}"
        cost_text = f"{stock_val * float(cost or 0):.2f} MZN"

        card_alt = tokens.get("card_alt", [0.16, 0.19, 0.24, 1])
        foreground = tokens.get("text_primary", [0.92, 0.94, 0.97, 1])
        muted = tokens.get("text_secondary", [0.55, 0.58, 0.63, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])

        row_widget = ExpiredBatchRow(
            product_id=pid,
            orientation="horizontal",
            size_hint_y=None,
            height=dp(46),
            padding=[dp(8), dp(4)],
            spacing=dp(8),
            radius=[dp(6)],
            elevation=0,
            md_bg_color=card_alt,
        )

        check_icon = MDIcon(
            icon="check-circle",
            theme_text_color="Custom",
            text_color=success,
            size_hint=(None, None),
            size=(dp(22), dp(22)),
        )
        row_widget.add_widget(check_icon)

        info = MDBoxLayout(orientation="vertical", size_hint_x=1)
        info.add_widget(
            MDLabel(
                text=str(name or "-"),
                theme_text_color="Custom",
                text_color=foreground,
                font_style="Caption",
                bold=True,
                halign="left",
                shorten=True,
                shorten_from="right",
                size_hint_y=None,
                height=dp(18),
            )
        )
        info.add_widget(
            MDLabel(
                text=f"{stock_text}  •  {cost_text}",
                theme_text_color="Custom",
                text_color=muted,
                font_style="Caption",
                halign="left",
                size_hint_y=None,
                height=dp(16),
            )
        )

        for lbl in info.children:
            lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        row_widget.add_widget(info)

        def toggle(_instance, product_id=pid, icon_ref=check_icon):
            if product_id in self._expired_batch_selection:
                self._expired_batch_selection.discard(product_id)
                icon_ref.icon = "close-circle"
                icon_ref.text_color = muted
            else:
                self._expired_batch_selection.add(product_id)
                icon_ref.icon = "check-circle"
                icon_ref.text_color = success
            self._update_expired_batch_totals()

        row_widget.bind(on_release=toggle)
        return row_widget
        """"novo codigo"""
    def _enrich_batch_items(self, items):
        """Completa stock/custo/preço com a linha real da BD (o banner não os traz)."""
        enriched = []
        for item in items:
            pid = item.get("id")
            row = None
            if pid not in (None, ""):
                try:
                    row = self.db.get_product(pid)
                except Exception as exc:
                    print(f"[losses] get_product({pid!r}) falhou: {exc}")
            if not row:
                print(f"[losses] produto sem linha na BD: {item!r}")
                enriched.append(item)
                continue
            enriched.append({
                **item,
                "stock": row[2],
                "price": row[4],
                "cost": row[6],
                "expiry_date": row[13] if len(row) > 13 else item.get("expiry_date"),
                "is_weight": bool(row[15]) if len(row) > 15 else item.get("is_weight"),
                "barcode": row[12] if len(row) > 12 else item.get("barcode"),
            })
        return enriched    

    def _update_expired_batch_totals(self):
        if not self._expired_batch_total_label:
            return
        selected_rows = [r for r in self._expired_batch_rows if r[0] in self._expired_batch_selection]
        total_units = sum(float(r[2] or 0) for r in selected_rows)
        total_cost = sum(float(r[2] or 0) * float(r[4] or 0) for r in selected_rows)
        self._expired_batch_total_label.text = (
            f"{len(selected_rows)} selecionado(s)  •  {total_units:.2f} unidades  •  "
            f"custo total {total_cost:.2f} MZN"
        )
        if self._expired_batch_confirm_btn:
            self._expired_batch_confirm_btn.text = f"REGISTAR {len(selected_rows)}"
            self._expired_batch_confirm_btn.disabled = not selected_rows

    def _confirm_expired_batch(self, dialog):
        selected_rows = [r for r in self._expired_batch_rows if r[0] in self._expired_batch_selection]
        if not selected_rows:
            return
        dialog.dismiss()

        app = App.get_running_app()
        user = getattr(app, "current_user", None)
        role = getattr(app, "current_role", "manager")

        def worker():
            results = {"approved": 0, "pending": 0, "failed": 0, "skipped": 0, "errors": []}
            for row in selected_rows:
                pid, name, stock, price, cost, barcode, is_weight, _exp, _status, _vat = row
                qty = float(stock or 0)
                if pid in (None, ""):
                    results["failed"] += 1
                    results["errors"].append(f"{name}: sem ID de produto")
                    continue
                if qty <= 0:
                    results["skipped"] += 1
                    continue
                try:
                    movement_id = self.db.request_stock_movement(
                        pid, "EXPIRED", qty, EXPIRY_LOSS_REASON, user, role,
                        direction="OUT", note="Registo em lote de vencidos", evidence_id=None,
                        unit_cost=cost, unit_price=price,
                    )
                    print(f"[losses] lote: pid={pid} qty={qty} -> movement_id={movement_id!r}")
                    if not movement_id:
                        results["failed"] += 1
                        results["errors"].append(f"{name}: a BD recusou o registo")
                        continue
                    approval = self.db.get_stock_movement_approval_status(movement_id) or {}
                    is_pending = str(approval.get("approval_status") or "APPROVED").upper() == "PENDING"
                    results["pending" if is_pending else "approved"] += 1
                    if user:
                        try:
                            action = "REQUEST_LOSS_APPROVAL" if is_pending else "REGISTER_LOSS"
                            self.db.log_action(user, role, action, f"EXPIRED (lote) | {name} | {qty}")
                        except Exception:
                            pass
                except Exception as exc:
                    print(f"[losses] lote: erro em pid={pid}: {exc}")
                    results["failed"] += 1
                    results["errors"].append(f"{name}: {exc}")
            return results

        def finish():
            payload = worker()
            Clock.schedule_once(lambda _dt, data=payload: self._finish_expired_batch(data), 0)

        Thread(target=finish, daemon=True).start()

    def _finish_expired_batch(self, results):
        lines = [f"{results.get('approved', 0)} perda(s) registada(s) e stock atualizado."]
        if results.get("pending"):
            lines.append(f"{results['pending']} enviada(s) para aprovação (o stock só muda depois de aprovadas).")
        if results.get("skipped"):
            lines.append(f"{results['skipped']} ignorada(s): já sem stock, nada a dar baixa.")
        if results.get("failed"):
            lines.append(f"{results['failed']} falha(s):")
            lines += [f"• {e}" for e in results.get("errors", [])[:5]]
        self.show_dialog("Registo em lote concluído", "\n".join(lines))
        self.load_products()
        self._check_expired_batch()
        self._refresh_home_alerts()

    def _refresh_home_alerts(self):
        if not self.manager or "admin_home" not in self.manager.screen_names:
            return
        home = self.manager.get_screen("admin_home")
        home._snapshot_loaded_at = 0.0
        if hasattr(home, "_ensure_snapshot_loaded"):
            home._ensure_snapshot_loaded(force=True)

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
        self.selected_product = None
        self.selected_loss_type = ""
        self.selected_loss_reason = ""
        ids = self.ids
        if not ids:
            return
        if "qty_input" in ids:
            ids.qty_input.disabled = False
            ids.qty_input.text = ""
        if "qty_hint" in ids:
            ids.qty_hint.text = ""
        if "note_input" in ids:
            ids.note_input.text = ""
        if "selected_name" in ids:
            ids.selected_name.text = "Produto Selecionado"
        if "selected_stock" in ids:
            ids.selected_stock.text = ""
        if "search_input" in ids:
            ids.search_input.text = ""
        self._clear_damage_evidence_attempt()
        try:
            self.close_damage_camera_panel()
        except Exception:
            pass
        if "damage_evidence_status" in ids:
            ids.damage_evidence_status.text = ""
        if "damage_evidence_card" in ids:
            ids.damage_evidence_card.disabled = True
        self._rebuild_reason_buttons()
        self.update_summary()
        self._refresh_step2_controls()


    def show_dialog(self, title, message):
        """Mostra mensagem"""
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: dialog.dismiss())]
        )
        dialog.open()
