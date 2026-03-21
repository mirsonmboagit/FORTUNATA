from kivymd.uix.screen import MDScreen
import os
import sys
from kivymd.uix.card import MDCard
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.uix.scatter import Scatter
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.app import App
from kivy.metrics import dp
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.core.window import Window
from threading import Thread
import time
from database.provider import get_db
from datetime import datetime
from kivymd.uix.snackbar import MDSnackbar
from kivy.core.audio import SoundLoader
from kivy.animation import Animation
import traceback

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

from AI.controller import ProactiveIntelligenceController
from utils.perf_utils import perf_start, perf_log, should_log_debug
from utils.vision import get_vision_dependencies

def _theme_color(name, fallback):
  app = App.get_running_app()
  tokens = getattr(app, "theme_tokens", {}) if app else {}
  return tokens.get(name, fallback)

# ==================== PRECO DEFINIDO PELO ADMIN ====================

def _safe_float(value, default=0.0):
  try:
    return float(value)
  except Exception:
    return default

def _calculate_promo(product):
  """Preco aplicado e sempre definido pelo administrador.

  O status do produto indica o contexto promocional para fins de registo.
  """
  base_price = _safe_float(product[3] if len(product) > 3 else 0.0)
  status = ""
  if len(product) > 16 and isinstance(product[16], str):
    status = product[16]
  elif len(product) > 7 and isinstance(product[7], str):
    status = product[7]
  promo_active = status.strip().upper() == "PERTO_DO_PRAZO"
  return base_price, base_price, promo_active, 0.0, None


def _unpack_sale_product(product):
  """Normaliza a tupla de produto de venda para um formato estavel."""
  return {
    "id": product[0],
    "name": product[1],
    "stock": _safe_float(product[2], 0.0),
    "unit_price": _safe_float(product[3], 0.0),
    "barcode": product[4] if len(product) > 4 else None,
    "is_weight": bool(product[5]) if len(product) > 5 else False,
    "expiry_date": product[6] if len(product) > 6 else None,
    "status": product[7] if len(product) > 7 else None,
    "units_per_package": int(_safe_float(product[8], 0)) if len(product) > 8 and product[8] not in (None, "") else None,
    "allow_pack_sale": bool(product[9]) if len(product) > 9 else False,
  }


# Carregar o arquivo KV
Builder.load_file(os.path.join(CURRENT_DIR, 'sales_screen.kv'))


class ProductCard(MDCard):
  """Card de produto individual"""

  def _noop_add_callback(self, *_args, **_kwargs):
    return None
  
  def __init__(self, product_data=None, add_callback=None, **kwargs):
    super().__init__(**kwargs)
    self.product_data = product_data
    self.add_callback = add_callback or self._noop_add_callback
    self._allow_pack_sale = False
    self._is_sold_by_weight = False
    self._units_per_package = None
    self.bind(width=lambda *_: self._apply_compact_add_buttons())
    if product_data is not None:
      self.setup_product()
    Clock.schedule_once(lambda dt: self._apply_compact_add_buttons(), 0)

  def _resolve_sales_screen(self):
    callback_owner = getattr(self.add_callback, "__self__", None)
    if callback_owner is not None and hasattr(callback_owner, "add_to_cart"):
      return callback_owner

    app = App.get_running_app()
    manager = getattr(app, "root", None) if app else None
    if manager is not None and hasattr(manager, "has_screen"):
      try:
        if manager.has_screen("manager"):
          return manager.get_screen("manager")
      except Exception:
        pass
    return None

  def on_touch_down(self, touch):
    return super().on_touch_down(touch)

  def on_touch_up(self, touch):
    return super().on_touch_up(touch)

  def _dispatch_add(self, sale_mode):
    screen = self._resolve_sales_screen()
    if self.product_data is None:
      if screen is not None:
        screen.show_message("Produto indisponivel.")
      return

    if sale_mode == "pack" and not self._allow_pack_sale:
      if screen is not None:
        screen.show_message("Este produto nao possui venda por embalagem.")
      return

    callback = getattr(screen, "add_to_cart", None) if screen is not None else None
    if not callable(callback):
      callback = self.add_callback
    if not callable(callback):
      if screen is not None:
        screen.show_message("Acao indisponivel no momento.")
      return

    try:
      callback(self.product_data, sale_mode=sale_mode, source="manual")
    except Exception as exc:
      print(f"Erro ao acionar adicao do produto: {exc}")
      traceback.print_exc()
      if screen is not None:
        screen.show_message("Falha ao adicionar produto.")

  def set_product_payload(self, product_data, add_callback=None):
    self.product_data = product_data
    if add_callback is not None:
      self.add_callback = add_callback
    if product_data is None:
      return
    self.setup_product()
  
  def setup_product(self):
    """Configurar dados do produto"""
    if self.product_data is None:
      return
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    primary = tokens.get("primary", [0.1, 0.5, 0.8, 1])
    info = tokens.get("info", [0.1, 0.5, 0.8, 1])
    warning = tokens.get("warning", [0.8, 0.4, 0.0, 1])
    success = tokens.get("success", [0.15, 0.7, 0.3, 1])
    danger = tokens.get("danger", [0.9, 0.2, 0.2, 1])

    info_data = _unpack_sale_product(self.product_data)
    product_id = info_data["id"]
    product_name = info_data["name"]
    product_stock = info_data["stock"]
    is_sold_by_weight = info_data["is_weight"]
    units_per_package = info_data["units_per_package"]
    allow_pack_sale = bool(
      info_data["allow_pack_sale"] and units_per_package and units_per_package >= 2 and not is_sold_by_weight
    )
    self._allow_pack_sale = allow_pack_sale
    self._is_sold_by_weight = is_sold_by_weight
    self._units_per_package = units_per_package
    
    # Preencher labels
    self.ids.product_id_label.text = str(product_id)
    self.ids.product_name_label.text = product_name
    meta_label = self.ids.product_meta_label
    
    # Tipo
    if is_sold_by_weight:
      self.ids.product_type_label.text = "KG"
      self.ids.product_type_label.text_color = warning
      self.ids.product_price_header.text = "PREÃ‡O/KG"
      meta_label.text = "Venda por peso"
    else:
      self.ids.product_type_label.text = "UN"
      self.ids.product_type_label.text_color = info
      self.ids.product_price_header.text = "PREÃ‡O/UN"
      if allow_pack_sale:
        meta_label.text = f"Embalagem com {int(units_per_package)} un"
      else:
        meta_label.text = "Venda por unidade"
    
    # Estoque com cores
    stock_text = f"{product_stock:.2f}" if is_sold_by_weight else f"{int(product_stock)}"
    self.ids.product_stock_label.text = stock_text
    
    if product_stock > 50:
      self.ids.product_stock_label.text_color = success
    elif product_stock > 20:
      self.ids.product_stock_label.text_color = warning
    else:
      self.ids.product_stock_label.text_color = danger
    
    # PreÃ§o
    base_price, promo_price, promo_active, _discount_pct, _days = _calculate_promo(self.product_data)
    base_label = self.ids.product_price_base_label
    promo_label = self.ids.product_price_promo_label

    if False:
      base_label.text = f"Base: {base_price:.2f} MZN"
      base_label.opacity = 1
      base_label.size_hint_y = 0.3
      promo_label.text = f"Promo: {promo_price:.2f} MZN"
      promo_label.size_hint_y = 0.35
    else:
      base_label.text = ""
      base_label.opacity = 0
      base_label.size_hint_y = 0.0
      promo_label.text = f"{base_price:.2f} MZN"
      promo_label.size_hint_y = 0.65

    # Botoes de adicao (sem popup)
    unit_btn = self.ids.add_unit_btn
    pack_btn = self.ids.add_pack_btn
    unit_wrap = self.ids.add_unit_wrap
    pack_wrap = self.ids.add_pack_wrap
    unit_lbl = self.ids.add_unit_label
    pack_lbl = self.ids.add_pack_label
    unit_btn.disabled = False
    unit_wrap.opacity = 1
    if is_sold_by_weight:
      unit_btn.icon = "scale-balance"
      unit_lbl.text = "KG"
      unit_wrap.size_hint_x = 1
      pack_wrap.size_hint_x = 0
      pack_wrap.opacity = 0
      pack_btn.disabled = True
      pack_lbl.text = ""
    elif allow_pack_sale:
      unit_btn.icon = "plus-circle"
      unit_wrap.size_hint_x = 0.47
      pack_wrap.size_hint_x = 0.53
      pack_wrap.opacity = 1
      pack_btn.disabled = False
    else:
      unit_btn.icon = "plus-circle"
      unit_wrap.size_hint_x = 1
      pack_wrap.size_hint_x = 0
      pack_wrap.opacity = 0
      pack_btn.disabled = True
      pack_lbl.text = ""

    self._apply_compact_add_buttons()

  def _apply_compact_add_buttons(self):
    """Ajusta os botoes de unidade e embalagem ao tamanho do card."""
    if not self.ids:
      return
    compact = self.width < dp(460) or Window.width < dp(1100)
    btn_size = dp(34) if compact else dp(40)
    lbl_size = dp(7.5) if compact else dp(9)
    lbl_h = dp(12) if compact else dp(14)
    spacing = dp(4) if compact else dp(6)

    if "add_buttons_box" in self.ids:
      self.ids.add_buttons_box.spacing = spacing
      self.ids.add_buttons_box.size_hint_x = 0.28 if compact else 0.24

    if "add_unit_btn" in self.ids:
      self.ids.add_unit_btn.size = (btn_size, btn_size)
    if "add_pack_btn" in self.ids:
      self.ids.add_pack_btn.size = (btn_size, btn_size)
    if "add_unit_label" in self.ids:
      self.ids.add_unit_label.font_size = lbl_size
      self.ids.add_unit_label.height = lbl_h
    if "add_pack_label" in self.ids:
      self.ids.add_pack_label.font_size = lbl_size
      self.ids.add_pack_label.height = lbl_h

    if "add_unit_label" in self.ids:
      self.ids.add_unit_label.text = "UNID" if not compact and not self._is_sold_by_weight else "KG" if self._is_sold_by_weight else "UN"
    if "add_pack_label" in self.ids:
      if self._allow_pack_sale:
        self.ids.add_pack_label.text = "OUTROS" if not compact else "EMB"
      else:
        self.ids.add_pack_label.text = ""
  
  def on_add_click(self):
    """Compatibilidade com chamada antiga."""
    self.on_add_unit_click()

  def on_add_unit_click(self):
    self._dispatch_add("unit")

  def on_add_pack_click(self):
    self._dispatch_add("pack")


class RecycleProductCard(RecycleDataViewBehavior, ProductCard):
  def refresh_view_attrs(self, rv, index, data):
    payload = data.get("product_data")
    callback = data.get("add_callback")
    attrs = dict(data)
    attrs.pop("product_data", None)
    attrs.pop("add_callback", None)
    result = super().refresh_view_attrs(rv, index, attrs)
    self.set_product_payload(payload, callback)
    return result


class SalesScreen(MDScreen):
  STOCK_SYNC_INTERVAL_SECONDS = 15
  PRODUCTS_PAGE_SIZE = 120
  PRODUCTS_CACHE_SECONDS = 8
  current_date = StringProperty("")
  current_time = StringProperty("")
  theme_action_text = StringProperty("Modo escuro")

  def __init__(self, **kwargs):
    db = kwargs.pop("db", None)
    super().__init__(**kwargs)
    self.db = db or get_db()
    self.back_target = "manager"
    self.cart_items = []
    self.total_amount = 0.0
    self.products_dict = {}
    self.scanning = False
    self.camera_active = False
    self.current_camera = 0
    self.camera_capture = None
    self.scanner_sound_success = None
    self.scanner_sound_error = None
    self.last_barcode = None
    self.last_barcode_time = 0
    self.notification_count = 0
    self.swing_event = None
    self._ai_poll_ev = None
    self._vision_modules = None
    self._intelligence = ProactiveIntelligenceController(
      screen=self,
      db=self.db,
      history_title="Historico de monitorizacao da operacao",
      auto_present_enabled=False,
    )
    self._stock_poll_ev = None
    self._products_loading = False
    self._products_has_more = False
    self._products_offset = 0
    self._products_token = 0
    self._search_ev = None
    self._pending_search = ""
    self._loaded_products = []
    self._last_products_refresh_at = 0.0
    self._qty_update_events = {}
    self._barcode_lookup_active = False
    self._sale_submitting = False
    
    # Propriedades para o header
    self.current_date = datetime.now().strftime("%d/%m/%Y")
    self.current_time = datetime.now().strftime("%H:%M")
    
    Clock.schedule_once(self.post_init, 0.1)

  def on_kv_post(self, base_widget):
    self._update_responsive_layout()

  def on_size(self, *args):
    Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)
  
  def post_init(self, dt):
    """InicializaÃ§Ã£o apÃ³s o KV estar carregado"""
    self.load_scanner_sounds()
    self.load_products()
    self._sync_theme_action()
    self._update_action_states()
    app = App.get_running_app()
    if getattr(app, "debug_mode", False):
      self.test_barcode_database()
    
    # Atualizar relÃ³gio a cada minuto
    Clock.schedule_interval(self.update_time, 60)
  
  def update_time(self, dt):
    """Atualizar hora"""
    self.current_time = datetime.now().strftime("%H:%M")

  def _sync_theme_action(self):
    app = App.get_running_app()
    is_dark = bool(app and getattr(app, "theme_style", "Light") == "Dark")
    self.theme_action_text = "Modo claro" if is_dark else "Modo escuro"

  def toggle_theme(self, *args):
    app = App.get_running_app()
    if not app or not hasattr(app, "apply_theme"):
      return
    current = getattr(app, "theme_style", "Light")
    app.apply_theme("Dark" if current != "Dark" else "Light")
    self._sync_theme_action()
    Clock.schedule_once(lambda dt: self._refresh_theme_widgets(), 0)

  def _refresh_theme_widgets(self):
    self._update_responsive_layout()
    filtered = self._filter_sale_products(self._loaded_products, self._current_search_text())
    self.display_products(filtered)
    self.update_cart_display()

  def _update_action_states(self):
    if not hasattr(self, "ids"):
      return
    has_cart = bool(self.cart_items)
    loading_products = bool(self._products_loading)
    sale_busy = bool(self._sale_submitting)
    search_text = self._current_search_text()

    for widget_id, disabled in (
      ("clear_cart_btn", (not has_cart) or sale_busy),
      ("finalize_btn", (not has_cart) or sale_busy),
      ("receipt_btn", (not has_cart) or sale_busy),
      ("cancel_btn", (not has_cart) or sale_busy),
      ("refresh_action_btn", loading_products or sale_busy),
      ("products_action_btn", sale_busy),
      ("history_action_btn", sale_busy),
      ("losses_action_btn", sale_busy),
      ("scan_btn", sale_busy),
      ("clear_search_btn", (not bool(search_text)) or sale_busy),
    ):
      widget = self.ids.get(widget_id)
      if widget is not None:
        widget.disabled = bool(disabled)

    paid_input = self.ids.get("paid_input")
    if paid_input is not None:
      paid_input.disabled = sale_busy

  def _update_responsive_layout(self):
    if not hasattr(self, "ids") or "top_actions_grid" not in self.ids:
      return

    width = self.width or Window.width
    top_bar = self.ids.top_bar
    actions_grid = self.ids.top_actions_grid
    toolbar_card = self.ids.manager_toolbar_card
    main_content = self.ids.main_content
    search_card = self.ids.search_card
    products_card = self.ids.products_card
    products_panel = self.ids.products_panel
    cart_panel = self.ids.cart_panel
    side_panel = self.ids.side_panel
    scanner_card = self.ids.scanner_card
    camera_container = self.ids.camera_container
    payment_card = self.ids.payment_card
    payment_actions_box = self.ids.payment_actions_box
    products_list = self.ids.products_list
    layout_manager = getattr(products_list, "layout_manager", None)

    top_bar.title = "OPERACAO DE VENDAS" if width >= dp(1280) else "VENDAS"

    if width >= dp(1420):
      main_content.orientation = "horizontal"
      side_panel.orientation = "vertical"
      actions_grid.cols = 5
      toolbar_card.padding = [dp(10), dp(8), dp(10), dp(8)]
      search_card.height = dp(92)
      products_panel.size_hint_x = 0.39
      products_panel.size_hint_y = 1
      cart_panel.size_hint_x = 0.39
      cart_panel.size_hint_y = 1
      side_panel.size_hint_x = 0.22
      side_panel.size_hint_y = 1
      main_content.padding = dp(10)
      main_content.spacing = dp(10)
      scanner_card.size_hint_x = 1
      scanner_card.size_hint_y = None
      scanner_card.height = scanner_card.minimum_height
      camera_container.height = dp(164)
      payment_card.size_hint_x = 1
      payment_card.size_hint_y = 0.60
      payment_card.elevation = 2
      payment_actions_box.height = dp(115)
      if layout_manager is not None:
        layout_manager.default_size = (None, dp(82))
        layout_manager.spacing = dp(5)
    elif width >= dp(1220):
      main_content.orientation = "horizontal"
      side_panel.orientation = "vertical"
      actions_grid.cols = 3
      toolbar_card.padding = [dp(10), dp(8), dp(10), dp(8)]
      search_card.height = dp(92)
      products_panel.size_hint_x = 0.41
      products_panel.size_hint_y = 1
      cart_panel.size_hint_x = 0.37
      cart_panel.size_hint_y = 1
      side_panel.size_hint_x = 0.22
      side_panel.size_hint_y = 1
      main_content.padding = dp(9)
      main_content.spacing = dp(8)
      scanner_card.size_hint_x = 1
      scanner_card.size_hint_y = None
      scanner_card.height = scanner_card.minimum_height
      camera_container.height = dp(152)
      payment_card.size_hint_x = 1
      payment_card.size_hint_y = 0.60
      payment_card.elevation = 2
      payment_actions_box.height = dp(115)
      if layout_manager is not None:
        layout_manager.default_size = (None, dp(80))
        layout_manager.spacing = dp(4)
    elif width >= dp(1040):
      main_content.orientation = "horizontal"
      side_panel.orientation = "vertical"
      actions_grid.cols = 3
      toolbar_card.padding = [dp(8), dp(7), dp(8), dp(7)]
      search_card.height = dp(92)
      products_panel.size_hint_x = 0.43
      products_panel.size_hint_y = 1
      cart_panel.size_hint_x = 0.35
      cart_panel.size_hint_y = 1
      side_panel.size_hint_x = 0.22
      side_panel.size_hint_y = 1
      main_content.padding = dp(8)
      main_content.spacing = dp(6)
      scanner_card.size_hint_x = 1
      scanner_card.size_hint_y = None
      scanner_card.height = scanner_card.minimum_height
      camera_container.height = dp(136)
      payment_card.size_hint_x = 1
      payment_card.size_hint_y = 0.60
      payment_card.elevation = 1
      payment_actions_box.height = dp(115)
      if layout_manager is not None:
        layout_manager.default_size = (None, dp(78))
        layout_manager.spacing = dp(4)
    else:
      main_content.orientation = "vertical"
      side_panel.orientation = "horizontal"
      actions_grid.cols = 2
      toolbar_card.padding = [dp(7), dp(6), dp(7), dp(6)]
      search_card.height = dp(90)
      products_panel.size_hint_x = 1
      products_panel.size_hint_y = 0.42
      cart_panel.size_hint_x = 1
      cart_panel.size_hint_y = 0.34
      side_panel.size_hint_x = 1
      side_panel.size_hint_y = None
      side_panel.height = dp(266)
      main_content.padding = dp(7)
      main_content.spacing = dp(5)
      scanner_card.size_hint_x = 0.36
      scanner_card.size_hint_y = 1
      scanner_card.height = 0
      camera_container.height = dp(118)
      payment_card.size_hint_x = 0.64
      payment_card.size_hint_y = 1
      payment_card.elevation = 1
      payment_actions_box.height = dp(108)
      if layout_manager is not None:
        layout_manager.default_size = (None, dp(76))
        layout_manager.spacing = dp(3)

    if main_content.orientation == "horizontal":
      products_card.padding = dp(10)
      cart_panel.padding = dp(10)
      payment_card.padding = dp(10)
    else:
      products_card.padding = dp(9)
      cart_panel.padding = dp(9)
      payment_card.padding = dp(9)
  
  def _log_action(self, action, details=""):
    """Log de aÃ§Ãµes"""
    app = App.get_running_app()
    username = getattr(app, "current_user", None)
    role = getattr(app, "current_role", None) or "manager"
    if username:
      self.db.log_action(username, role, action, details)
  
  def load_scanner_sounds(self):
    """Carregar sons do scanner"""
    try:
      self.scanner_sound_success = SoundLoader.load('assets/sounds/beep.wav')
      self.scanner_sound_error = SoundLoader.load('assets/sounds/beeperror.mp3')
      
      if (not self.scanner_sound_success or not self.scanner_sound_error) and should_log_debug():
        print("Arquivos de som do scanner nao encontrados")
    except Exception as e:
      if should_log_debug():
        print(f"Erro ao carregar sons: {e}")
      self.scanner_sound_success = None
      self.scanner_sound_error = None
  
  def play_scanner_sound(self, success=True):
    """Reproduzir som do scanner"""
    try:
      if success and self.scanner_sound_success:
        self.scanner_sound_success.play()
      elif not success and self.scanner_sound_error:
        self.scanner_sound_error.play()
    except Exception as e:
      if should_log_debug():
        print(f"Erro ao reproduzir som: {e}")
  
  def test_barcode_database(self):
    """Teste: verificar produtos com cÃ³digo de barras"""
    try:
      print("\n" + "="*70)
      print("ðŸ“Š TESTE - Produtos com CÃ³digo de Barras")
      print("="*70)
      
      produtos = self.db.get_products_with_barcodes()
      
      if produtos:
        print(f"âœ“ {len(produtos)} produto(s) com cÃ³digo de barras:\n")
        for p in produtos:
          tipo = "KG" if (len(p) > 4 and p[4]) else "UN"
          print(f"  ID: {p[0]:4d} | Barcode: '{p[2]:15s}' | {p[1]:30s} | "
             f"Estoque: {p[3]} | Tipo: {tipo}")
      else:
        print("âš  NENHUM produto possui cÃ³digo de barras!")
      
      print("="*70 + "\n")
      
    except Exception as e:
      print(f"âŒ Erro no teste: {e}")
  
  def load_products(self):
    return self._request_products_page(reset=True, search_text=self._current_search_text(), silent=True)

  def _current_search_text(self):
    if not hasattr(self, "ids"):
      return (self._pending_search or "").strip()
    search_widget = self.ids.get("search_input") if hasattr(self.ids, "get") else None
    if search_widget is None and hasattr(self.ids, "search_input"):
      search_widget = self.ids.search_input
    if search_widget is None:
      return (self._pending_search or "").strip()
    return (getattr(search_widget, "text", "") or "").strip()

  def _request_products_page(self, reset=True, search_text="", silent=True):
    # Avoid duplicate in-flight fetches that only increase RPC load.
    if self._products_loading:
      return False

    token = self._products_token + 1
    self._products_token = token
    offset = 0 if reset else self._products_offset
    limit = self.PRODUCTS_PAGE_SIZE
    query_text = (search_text or "").strip()
    started_at = perf_start()
    self._products_loading = True
    self._update_action_states()

    def worker():
      try:
        rows = self.db.get_products_for_sale_page(
          search_text=query_text,
          limit=limit,
          offset=offset,
        ) or []
      except Exception as exc:
        if should_log_debug():
          print(f"Erro ao carregar produtos da venda: {exc}")
        rows = []
      Clock.schedule_once(
        lambda dt, data=rows, tok=token, rst=reset, off=offset, st=started_at, sl=silent:
        self._apply_products_page(data, tok, rst, off, st, sl),
        0,
      )

    Thread(target=worker, daemon=True).start()
    return True

  def _filter_sale_products(self, products, text):
    text_lower = (text or "").lower().strip()
    if not text_lower:
      return list(products or [])
    return [
      p for p in (products or [])
      if (
        text_lower in str(p[1]).lower() or
        text_lower in str(p[0]).lower() or
        (len(p) > 4 and p[4] and text_lower in str(p[4]).lower())
      )
    ]

  def _sync_cart_with_live_stock(self):
    if not self.cart_items:
      return
    changed = False
    for item in self.cart_items:
      live_product = self.products_dict.get(item.get('id'))
      if not live_product:
        continue
      live_stock = _unpack_sale_product(live_product)['stock']
      if item.get('max_stock') != live_stock:
        item['max_stock'] = live_stock
        changed = True
    if changed:
      self.update_cart_display()

  def _apply_products_page(self, rows, token, reset, offset, started_at, silent):
    if token != self._products_token:
      return

    if reset:
      self._loaded_products = list(rows)
    else:
      self._loaded_products.extend(rows)

    self.products_dict = {p[0]: p for p in self._loaded_products}
    self._products_offset = offset + len(rows)
    self._products_has_more = len(rows) >= self.PRODUCTS_PAGE_SIZE
    self._products_loading = False
    self._last_products_refresh_at = time.perf_counter()
    self.display_products(self._loaded_products)
    self._sync_cart_with_live_stock()
    perf_log(
      "sales.load_products",
      started_at,
      f"reset={reset} added={len(rows)} total={len(self._loaded_products)} offset={self._products_offset}",
    )

    if not silent and reset:
      self.show_message("✓ Stock atualizado")
    self._update_action_states()

  def manual_refresh_stock(self, *args, silent=False):
    """Refresh manual/automatico da lista de venda e limites de stock do carrinho."""
    try:
      if self._products_loading:
        if not silent:
          self.show_message("Atualizacao em andamento...")
        return False
      return self._request_products_page(
        reset=True,
        search_text=self._current_search_text(),
        silent=silent,
      )
    except Exception as e:
      print(f"âŒ Erro no refresh de stock: {e}")
      if not silent:
        self.show_message("âŒ Falha ao atualizar stock")
      return False

  def _poll_stock_refresh(self, dt):
    if self._products_loading:
      return
    try:
      self.manual_refresh_stock(silent=True)
    except Exception:
      pass

  def _start_stock_polling(self):
    if self._stock_poll_ev:
      self._stock_poll_ev.cancel()
    self._stock_poll_ev = Clock.schedule_interval(
      self._poll_stock_refresh, self.STOCK_SYNC_INTERVAL_SECONDS
    )

  def _stop_stock_polling(self):
    if self._stock_poll_ev:
      self._stock_poll_ev.cancel()
      self._stock_poll_ev = None
  
  def display_products(self, products):
    """Exibir produtos na lista"""
    started_at = perf_start()
    products_list = self.ids.products_list
    empty_label = self.ids.get("products_empty_label") if hasattr(self.ids, "get") else None
    
    if not products:
      products_list.data = []
      self.ids.products_count_label.text = '0 itens'
      if empty_label is not None:
        empty_label.opacity = 1
        empty_label.disabled = False
      return
    
    self.ids.products_count_label.text = f'{len(products)} itens'
    if empty_label is not None:
      empty_label.opacity = 0
      empty_label.disabled = True
    products_list.data = [
      {"product_data": product, "add_callback": self.add_to_cart}
      for product in products
    ]
    self._update_action_states()
    perf_log("sales.display_products", started_at, f"rows={len(products)}")
  
  def on_search(self, instance, text):
    """Filtrar produtos por nome, ID ou cÃ³digo"""
    self._pending_search = text or ""
    local_results = self._filter_sale_products(self._loaded_products, self._pending_search)
    self.display_products(local_results)
    if self._search_ev:
      self._search_ev.cancel()
    self._search_ev = Clock.schedule_once(self._dispatch_search, 0.22)

  def clear_search(self, *args):
    search_input = self.ids.get("search_input") if hasattr(self, "ids") else None
    if search_input is not None:
      search_input.text = ""
      try:
        search_input.focus = True
      except Exception:
        pass
    self._pending_search = ""
    self.display_products(self._loaded_products)

  def _dispatch_search(self, _dt):
    self._search_ev = None
    self._request_products_page(
      reset=True,
      search_text=self._pending_search,
      silent=True,
    )

  def on_products_scroll(self, scroll_y):
    if scroll_y > 0.02:
      return
    if self._products_has_more and not self._products_loading:
      self._request_products_page(
        reset=False,
        search_text=self._pending_search,
        silent=True,
      )
  
  def on_search_enter(self, instance):
    """Ao pressionar Enter, busca por cÃ³digo de barras exato"""
    if self._search_ev:
      self._search_ev.cancel()
      self._search_ev = None
    text = instance.text.strip()
    if not text:
      return
    self._lookup_barcode_async(text, source='search', input_widget=instance)
  
  def add_to_cart(self, product, sale_mode=None, source='manual'):
    """Adicionar produto ao carrinho."""
    try:
      if product is None:
        self.show_message("Produto indisponivel.")
        return

      info = _unpack_sale_product(product)
      product_id = info['id']
      product_name = info['name']
      product_stock = info['stock']
      is_sold_by_weight = info['is_weight']
      units_per_package = info['units_per_package']
      allow_pack_sale = bool(
        info['allow_pack_sale'] and units_per_package and units_per_package >= 2 and not is_sold_by_weight
      )
      base_price, _promo_price, promo_active, discount_pct, _days = _calculate_promo(product)
      unit_price = base_price

      if is_sold_by_weight:
        self.show_weight_popup(product)
        return

      if sale_mode is None:
        sale_mode = 'unit'

      if sale_mode == 'pack':
        if not allow_pack_sale:
          sale_mode = 'unit'
        else:
          pack_units = int(units_per_package)
          pack_price = unit_price * pack_units
          for item in self.cart_items:
            if item['id'] == product_id and item.get('sale_mode') == 'pack':
              next_units = item.get('qty_units', item['qty'] * pack_units) + pack_units
              if next_units <= product_stock:
                item['qty'] += 1
                item['qty_units'] = next_units
                item['total'] = item['qty'] * item['price']
                self.update_cart_display()
                return
              self.show_message("Estoque insuficiente!")
              return

          self.cart_items.append({
            'id': product_id,
            'name': product_name,
            'qty': 1,
            'qty_units': pack_units,
            'pack_units': pack_units,
            'price': pack_price,
            'unit_price': unit_price,
            'total': pack_price,
            'max_stock': product_stock,
            'base_price': base_price,
            'promo_active': promo_active,
            'discount_pct': discount_pct,
            'is_weight': False,
            'weight_kg': 0,
            'sale_mode': 'pack',
          })
          self.update_cart_display()
          self._update_action_states()
          return

      for item in self.cart_items:
        if item['id'] == product_id and item.get('sale_mode', 'unit') == 'unit':
          next_units = item.get('qty_units', item['qty']) + 1
          if next_units <= product_stock:
            item['qty'] += 1
            item['qty_units'] = next_units
            item['total'] = item['qty'] * item['price']
            self.update_cart_display()
            return
          self.show_message("Estoque insuficiente!")
          return

      self.cart_items.append({
        'id': product_id,
        'name': product_name,
        'qty': 1,
        'qty_units': 1,
        'pack_units': None,
        'price': unit_price,
        'unit_price': unit_price,
        'total': unit_price,
        'max_stock': product_stock,
        'base_price': base_price,
        'promo_active': promo_active,
        'discount_pct': discount_pct,
        'is_weight': False,
        'weight_kg': 0,
        'sale_mode': 'unit',
      })

      self.update_cart_display()
      self._update_action_states()

    except Exception as e:
      print(f"Erro ao adicionar ao carrinho: {e}")
      traceback.print_exc()
      self.show_message("Falha ao adicionar produto.")

  def _resolve_product_from_barcode(self, barcode_value):
    lookup_fn = getattr(self.db, "find_product_by_barcode_fast", None)
    if callable(lookup_fn):
      product = lookup_fn(barcode_value)
    else:
      product = self.db.get_product_by_barcode(barcode_value)
    if not product:
      return None

    product_id = product[0]
    enriched = self.products_dict.get(product_id)
    if enriched:
      return enriched

    live_rows = self.db.get_products_for_sale_ids([product_id]) or []
    if live_rows:
      return live_rows[0]
    return product

  def _lookup_barcode_async(self, barcode_value, source='search', input_widget=None):
    barcode_value = (barcode_value or "").strip()
    if not barcode_value:
      return False
    if self._barcode_lookup_active:
      if source != 'scanner':
        self.show_message("Aguarde a busca atual terminar.")
      return False

    self._barcode_lookup_active = True

    def worker():
      product = None
      error = None
      try:
        product = self._resolve_product_from_barcode(barcode_value)
      except Exception as exc:
        error = str(exc)
      Clock.schedule_once(
        lambda dt, data=product, err=error, code=barcode_value, src=source, widget=input_widget:
        self._apply_barcode_lookup(data, err, code, src, widget),
        0,
      )

    Thread(target=worker, daemon=True).start()
    return True

  def _apply_barcode_lookup(self, product, error, barcode_value, source, input_widget=None):
    self._barcode_lookup_active = False

    if error:
      if should_log_debug():
        print(f"Erro na busca por codigo: {error}")
      if source == 'scanner':
        self.play_scanner_sound(success=False)
        self.ids.scanner_status.text = 'Erro ao buscar'
        self.ids.scanner_status.text_color = _theme_color('danger', [0.9, 0.2, 0.2, 1])
      else:
        self.show_message("âŒ Erro ao buscar produto!")
      return

    if not product:
      if source == 'scanner':
        self.play_scanner_sound(success=False)
        self.ids.scanner_status.text = 'âœ— NÃ£o encontrado'
        self.ids.scanner_status.text_color = _theme_color('warning', [0.88, 0.32, 0.22, 1])
      else:
        self.show_message("âš  Codigo nao encontrado!")
      return

    self.add_to_cart(product, source='barcode')
    if source == 'scanner':
      self.play_scanner_sound(success=True)
      self.ids.scanner_status.text = f'âœ“ {product[1][:15]}'
      self.ids.scanner_status.text_color = _theme_color('success', [0.16, 0.72, 0.22, 1])
    else:
      self.show_message(f'âœ“ {product[1]} adicionado!')
      if input_widget is not None:
        try:
          input_widget.text = ''
        except Exception:
          pass

  def show_weight_popup(self, product):
    """Popup de balanÃ§a para produtos vendidos por KG"""
    info = _unpack_sale_product(product)
    product_id = info['id']
    product_name = info['name']
    product_stock = info['stock']
    base_price, _promo_price, promo_active, _discount_pct, _days = _calculate_promo(product)
    product_price_per_kg = base_price
    
    content = MDBoxLayout(
      orientation='vertical',
      padding=dp(20),
      spacing=dp(12),
      size_hint_y=None,
      height=dp(560)
    )
    
    # Header
    header = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(70),
      md_bg_color=_theme_color('success', [0.15, 0.65, 0.25, 1]),
      padding=dp(12),
      radius=[dp(10)]
    )
    
    title = MDLabel(
      text='BALANÃ‡A DIGITAL',
      font_style="H5",
      bold=True,
      theme_text_color="Custom",
      text_color=_theme_color('on_primary', [1, 1, 1, 1]),
      halign='center'
    )
    
    product_label = MDLabel(
      text=product_name,
      font_style="Body1",
      theme_text_color="Custom",
      text_color=_theme_color('on_primary', [1, 1, 1, 0.9]),
      halign='center'
    )
    
    header.add_widget(title)
    header.add_widget(product_label)
    
    # Info
    info_card = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(100),
      padding=dp(12),
      spacing=dp(6)
    )
    
    price_label_base = MDLabel(
      text=f'PreÃ§o base/KG: {base_price:.2f} MZN',
      font_size=dp(13),
      theme_text_color="Secondary"
    )

    price_label_promo = MDLabel(
      text=f'PreÃ§o promo/KG: {product_price_per_kg:.2f} MZN',
      bold=True,
      font_size=dp(15),
      theme_text_color="Custom",
      text_color=_theme_color('success', [0.15, 0.7, 0.3, 1])
    )
    
    stock_label = MDLabel(
      text=f'Estoque disponÃ­vel: {product_stock:.2f} kg',
      font_size=dp(14)
    )
    
    if False:
      info_card.add_widget(price_label_base)
      info_card.add_widget(price_label_promo)
    else:
      price_label_promo.text = f'PreÃ§o por KG: {product_price_per_kg:.2f} MZN'
      info_card.add_widget(price_label_promo)
    info_card.add_widget(stock_label)
    
    # Input de peso
    weight_input = MDTextField(
      hint_text='Digite o peso em KG',
      input_filter='float',
      mode='rectangle',
      size_hint_y=None,
      height=dp(56),
      font_size=dp(18)
    )

    # Input de preco total
    price_input = MDTextField(
      hint_text='Ou digite o valor total (MZN)',
      input_filter='float',
      mode='rectangle',
      size_hint_y=None,
      height=dp(56),
      font_size=dp(18)
    )
    
    # Preview do cÃ¡lculo
    calc_card = MDCard(
      orientation='vertical',
      size_hint_y=None,
      height=dp(90),
      padding=dp(12),
      spacing=dp(4),
      md_bg_color=_theme_color('card', [0.95, 0.95, 0.95, 1])
    )
    
    calc_title = MDLabel(
      text='CÃLCULO:',
      font_size=dp(12),
      bold=True,
      theme_text_color="Secondary"
    )
    
    calc_formula = MDLabel(
      text='',
      font_size=dp(14),
      id='calc_formula'
    )
    
    calc_result = MDLabel(
      text='',
      font_size=dp(17),
      bold=True,
      theme_text_color="Custom",
      text_color=_theme_color('success', [0.12, 0.65, 0.25, 1]),
      id='calc_result'
    )
    
    calc_card.add_widget(calc_title)
    calc_card.add_widget(calc_formula)
    calc_card.add_widget(calc_result)
    
    # FunÃ§Ãµes de atualizaÃ§Ã£o do cÃ¡lculo (peso <-> preÃ§o)
    updating = {'active': False}

    def _set_calc(weight):
      if weight <= 0:
        calc_formula.text = 'Peso deve ser maior que 0'
        calc_result.text = ''
        calc_formula.text_color = _theme_color('danger', [0.9, 0.3, 0.3, 1])
        return False

      if weight > product_stock:
        calc_formula.text = f'Maximo: {product_stock:.2f} kg'
        calc_result.text = ''
        calc_formula.text_color = _theme_color('danger', [0.9, 0.3, 0.3, 1])
        return False

      total_price = weight * product_price_per_kg
      calc_formula.text = f'{weight:.2f} KG x {product_price_per_kg:.2f} MZN/KG ='
      calc_formula.text_color = _theme_color('text_primary', [0.2, 0.2, 0.2, 1])
      calc_result.text = f'TOTAL: {total_price:.2f} MZN'
      return True

    def update_from_weight(instance, value):
      if updating['active']:
        return
      updating['active'] = True
      try:
        if not value or value.strip() == '':
          price_input.text = ''
          calc_formula.text = ''
          calc_result.text = ''
          return
        weight = float(value)
        total_price = weight * product_price_per_kg
        price_input.text = f'{total_price:.2f}'
        _set_calc(weight)
      except ValueError:
        calc_formula.text = 'Digite um numero valido'
        calc_formula.text_color = _theme_color('danger', [0.9, 0.3, 0.3, 1])
        calc_result.text = ''
      finally:
        updating['active'] = False

    def update_from_price(instance, value):
      if updating['active']:
        return
      updating['active'] = True
      try:
        if not value or value.strip() == '':
          weight_input.text = ''
          calc_formula.text = ''
          calc_result.text = ''
          return
        total_price = float(value)
        if product_price_per_kg <= 0:
          return
        weight = total_price / product_price_per_kg
        weight_input.text = f'{weight:.3f}'
        _set_calc(weight)
      except ValueError:
        calc_formula.text = 'Digite um numero valido'
        calc_formula.text_color = _theme_color('danger', [0.9, 0.3, 0.3, 1])
        calc_result.text = ''
      finally:
        updating['active'] = False

    weight_input.bind(text=update_from_weight)
    price_input.bind(text=update_from_price)
    
    # BotÃµes
    buttons_box = MDBoxLayout(
      size_hint_y=None,
      height=dp(50),
      spacing=dp(10)
    )
    
    cancel_btn = MDRaisedButton(
      text='âœ— CANCELAR',
      md_bg_color=_theme_color('danger', [0.7, 0.3, 0.3, 1])
    )
    
    add_btn = MDRaisedButton(
      text='âœ“ ADICIONAR',
      md_bg_color=_theme_color('success', [0.12, 0.62, 0.22, 1])
    )
    
    buttons_box.add_widget(cancel_btn)
    buttons_box.add_widget(add_btn)
    
    # Montagem
    content.add_widget(header)
    content.add_widget(info_card)
    content.add_widget(weight_input)
    content.add_widget(price_input)
    content.add_widget(calc_card)
    content.add_widget(Widget())
    content.add_widget(buttons_box)
    
    # Dialog
    dialog = MDDialog(
      title='',
      type='custom',
      content_cls=content,
      size_hint=(0.8, None),
      height=dp(620)
    )
    
    # AÃ§Ãµes dos botÃµes
    cancel_btn.bind(on_release=lambda x: dialog.dismiss())
    
    def add_weighted_product(instance):
      try:
        weight_text = weight_input.text.strip()
        price_text = price_input.text.strip()

        if not weight_text and price_text:
          if product_price_per_kg > 0:
            weight = float(price_text) / product_price_per_kg
            weight_text = f"{weight:.3f}"
            weight_input.text = weight_text
          else:
            weight_text = ''

        if not weight_text:
          self.show_message('Digite o peso ou o valor!')
          return

        weight = float(weight_text)

        if weight <= 0:
          self.show_message('Peso deve ser maior que 0!')
          return

        if weight > product_stock:
          self.show_message(f'Estoque insuficiente!\nMaximo: {product_stock:.2f} kg')
          return
        
        total_price = weight * product_price_per_kg
        
        # Verificar se produto jÃ¡ estÃ¡ no carrinho
        for item in self.cart_items:
          if item['id'] == product_id and item['is_weight']:
            new_weight = item['weight_kg'] + weight
            
            if new_weight > product_stock:
              self.show_message(f'Estoque insuficiente!\nMaximo: {product_stock:.2f} kg')
              return
            
            item['weight_kg'] = new_weight
            item['qty'] = new_weight
            item['qty_units'] = new_weight
            item['total'] = new_weight * product_price_per_kg
            
            dialog.dismiss()
            self.update_cart_display()
            self.show_message(f'{weight:.2f} kg adicionado!\nTotal: {item["weight_kg"]:.2f} kg')
            return
        
        # Adicionar novo item por peso
        self.cart_items.append({
          'id': product_id,
          'name': product_name,
          'qty': weight,
          'qty_units': weight,
          'pack_units': None,
          'price': product_price_per_kg,
          'unit_price': product_price_per_kg,
          'total': total_price,
          'max_stock': product_stock,
          'base_price': base_price,
          'promo_active': promo_active,
          'discount_pct': _discount_pct,
          'is_weight': True,
          'weight_kg': weight,
          'sale_mode': 'weight',
        })
        
        dialog.dismiss()
        self.update_cart_display()
        self.show_message(f'{weight:.2f} kg adicionado!\nTotal: {total_price:.2f} MZN')
        
      except ValueError:
        self.show_message('Peso invalido!')
      except Exception as e:
        print(f"Erro: {e}")
        import traceback
        traceback.print_exc()
        self.show_message('Erro ao adicionar!')
    
    add_btn.bind(on_release=add_weighted_product)
    
    dialog.open()
  
  def update_cart_display(self):
    """Atualizar exibiÃ§Ã£o do carrinho"""
    cart_list = self.ids.cart_list
    cart_list.clear_widgets()
    self.total_amount = 0
    compact_ui = Window.width < dp(1100)
    ultra_compact_ui = Window.width < dp(980)
    row_h = dp(36) if compact_ui else dp(40)
    qty_h = dp(28) if compact_ui else dp(30)
    qty_w_pack = dp(44) if ultra_compact_ui else (dp(38) if compact_ui else dp(44))
    qty_w_unit = dp(40) if compact_ui else dp(46)
    qty_font = dp(10) if compact_ui else dp(11)
    qty_suffix_font = dp(8) if compact_ui else dp(9)

    if not self.cart_items:
      self.ids.cart_count_label.text = '0 itens'
    else:
      self.ids.cart_count_label.text = f'{len(self.cart_items)} itens'

    for i, item in enumerate(self.cart_items):
      bg_color = _theme_color('surface_alt', [0.95, 0.97, 0.98, 1]) if i % 2 == 0 else _theme_color('card', [1, 1, 1, 1])

      row = MDCard(
        orientation='horizontal',
        size_hint_y=None,
        height=row_h,
        padding=[dp(4), dp(2), dp(4), dp(2)],
        spacing=dp(4),
        elevation=0,
        radius=[dp(6)],
        md_bg_color=bg_color
      )

      id_label = MDLabel(
        text=str(item['id']),
        halign='center',
        size_hint_x=0.10,
        font_size=dp(11),
        theme_text_color="Primary"
      )

      sale_mode = item.get('sale_mode', 'weight' if item.get('is_weight', False) else 'unit')
      display_name = item['name']
      if sale_mode == 'pack':
        display_name = f"{display_name} (EMB)"
      name = display_name[:20] + '...' if len(display_name) > 20 else display_name
      name_label = MDLabel(
        text=name,
        halign='left',
        size_hint_x=0.40,
        font_size=dp(11),
        theme_text_color="Primary",
        shorten=True,
        shorten_from="right"
      )

      if item.get('is_weight', False):
        qty_widget = MDLabel(
          text=f"{item['weight_kg']:.2f} kg",
          halign='center',
          size_hint_x=0.18,
          font_size=dp(11),
          theme_text_color="Custom",
          text_color=_theme_color('warning', [0.55, 0.35, 0.0, 1]),
          bold=True
        )
      elif sale_mode == 'pack':
        qty_widget = MDBoxLayout(
          orientation='horizontal',
          spacing=dp(2),
          padding=[dp(2), 0, dp(2), 0],
          size_hint_x=0.18,
        )
        qty_field = MDTextField(
          text=str(int(item['qty'])),
          multiline=False,
          input_filter='int',
          mode='rectangle',
          size_hint=(None, None),
          width=qty_w_pack,
          height=qty_h,
          font_size=qty_font,
          halign='center',
          line_color_normal=_theme_color('text_secondary', [0.75, 0.75, 0.75, 1]),
          line_color_focus=_theme_color('primary', [0.2, 0.5, 0.8, 1]),
          text_color_normal=_theme_color('text_primary', [0.15, 0.15, 0.15, 1]),
          text_color_focus=_theme_color('text_primary', [0.15, 0.15, 0.15, 1]),
          hint_text_color=_theme_color('text_secondary', [0.5, 0.5, 0.5, 1])
        )
        qty_field.bind(text=lambda inst, val, idx=i: self.schedule_qty_update(idx, val))
        qty_widget.add_widget(qty_field)
        if not ultra_compact_ui:
          qty_widget.add_widget(MDLabel(
            text='emb',
            halign='left',
            size_hint_x=1,
            font_size=qty_suffix_font,
            theme_text_color='Secondary',
          ))
      else:
        qty_widget = MDBoxLayout(
          orientation='horizontal',
          size_hint_x=0.18,
          padding=[dp(2), 0, dp(2), 0],
        )
        qty_widget.add_widget(Widget())
        qty_field = MDTextField(
          text=str(int(item['qty'])),
          multiline=False,
          input_filter='int',
          mode='rectangle',
          size_hint=(None, None),
          width=qty_w_unit,
          height=qty_h,
          font_size=qty_font,
          halign='center',
          line_color_normal=_theme_color('text_secondary', [0.75, 0.75, 0.75, 1]),
          line_color_focus=_theme_color('primary', [0.2, 0.5, 0.8, 1]),
          text_color_normal=_theme_color('text_primary', [0.15, 0.15, 0.15, 1]),
          text_color_focus=_theme_color('text_primary', [0.15, 0.15, 0.15, 1]),
          hint_text_color=_theme_color('text_secondary', [0.5, 0.5, 0.5, 1])
        )
        qty_field.bind(text=lambda inst, val, idx=i: self.schedule_qty_update(idx, val))
        qty_widget.add_widget(qty_field)
        qty_widget.add_widget(Widget())

      total_label = MDLabel(
        text=f'{item["total"]:.2f}',
        halign='right',
        size_hint_x=0.22,
        font_size=dp(11),
        theme_text_color="Custom",
        text_color=_theme_color('success', [0.12, 0.65, 0.25, 1]),
        bold=True
      )

      remove_btn = MDIconButton(
        icon='delete',
        theme_text_color="Custom",
        text_color=_theme_color('danger', [0.85, 0.2, 0.2, 1]),
        size_hint_x=0.10,
        pos_hint={'center_y': 0.5},
        on_release=lambda btn, idx=i: self.remove_from_cart(idx)
      )

      row.add_widget(id_label)
      row.add_widget(name_label)
      row.add_widget(qty_widget)
      row.add_widget(total_label)
      row.add_widget(remove_btn)

      cart_list.add_widget(row)
      self.total_amount += item['total']

    self.ids.total_label.text = f'{self.total_amount:.2f} MZN'
    self.calculate_change()
    self._update_action_states()
  
  def increase_qty(self, index):
    """Aumentar quantidade de um item"""
    try:
      if index >= len(self.cart_items):
        return
      
      item = self.cart_items[index]
      
      if item.get('is_weight', False):
        return

      if item.get('sale_mode') == 'pack':
        pack_units = int(item.get('pack_units') or 1)
        next_qty = item['qty'] + 1
        next_units = next_qty * pack_units
        if next_units <= item['max_stock']:
          item['qty'] = next_qty
          item['qty_units'] = next_units
          item['total'] = next_qty * item['price']
          self.update_cart_display()
        else:
          self.show_message("âš  Estoque insuficiente!")
        return

      if item['qty'] + 1 <= item['max_stock']:
        item['qty'] += 1
        item['qty_units'] = item['qty']
        item['total'] = item['qty'] * item['price']
        self.update_cart_display()
      else:
        self.show_message("âš  Estoque insuficiente!")
        
    except Exception as e:
      print(f"âŒ Erro: {e}")
  
  def decrease_qty(self, index):
    """Diminuir quantidade de um item"""
    try:
      if index >= len(self.cart_items):
        return
      
      item = self.cart_items[index]
      
      if item.get('is_weight', False):
        return

      if item['qty'] > 1:
        item['qty'] -= 1
        if item.get('sale_mode') == 'pack':
          pack_units = int(item.get('pack_units') or 1)
          item['qty_units'] = item['qty'] * pack_units
        else:
          item['qty_units'] = item['qty']
        item['total'] = item['qty'] * item['price']
        self.update_cart_display()
      else:
        self.remove_from_cart(index)
        
    except Exception as e:
      print(f"âŒ Erro: {e}")
  
  def update_qty(self, index, value):
    """Atualizar quantidade"""
    try:
      if not value or value.strip() == '':
        return
      qty = int(value)
      if qty <= 0:
        return
      if index >= len(self.cart_items):
        return
      
      if self.cart_items[index].get('is_weight', False):
        return

      item = self.cart_items[index]
      if item.get('sale_mode') == 'pack':
        pack_units = int(item.get('pack_units') or 1)
        qty_units = qty * pack_units
      else:
        qty_units = qty

      if qty_units > item['max_stock']:
        self.show_message("âš  Quantidade excede estoque!")
        return

      item['qty'] = qty
      item['qty_units'] = qty_units
      item['total'] = qty * item['price']
      self.update_cart_display()
      
    except ValueError:
      pass
    except Exception as e:
      print(f"âŒ Erro: {e}")

  def schedule_qty_update(self, index, value):
    pending = self._qty_update_events.pop(index, None)
    if pending:
      pending.cancel()
    self._qty_update_events[index] = Clock.schedule_once(
      lambda dt, idx=index, raw=value: self._apply_scheduled_qty_update(idx, raw),
      0.12,
    )

  def _apply_scheduled_qty_update(self, index, value):
    self._qty_update_events.pop(index, None)
    self.update_qty(index, value)
  
  def remove_from_cart(self, index):
    """Remover item do carrinho"""
    try:
      if 0 <= index < len(self.cart_items):
        self.cart_items.pop(index)
        self.update_cart_display()
    except Exception as e:
      print(f"âŒ Erro: {e}")
  
  def clear_cart(self, *args):
    """Limpar carrinho"""
    self.cart_items.clear()
    self.update_cart_display()

  def open_products_panel(self, *args):
    stale = (time.perf_counter() - self._last_products_refresh_at) >= self.PRODUCTS_CACHE_SECONDS
    if stale and not self._products_loading:
      self.manual_refresh_stock(silent=True)
    self.focus_product_search()

  def refresh_products_panel(self, *args):
    self.manual_refresh_stock(silent=False)

  def _stop_scanner_if_active(self):
    if not self.scanning:
      return
    self.scanning = False
    Clock.unschedule(self.update_camera)
    self.release_camera()
    scan_btn = self.ids.get("scan_btn") if hasattr(self, "ids") else None
    if scan_btn is not None:
      scan_btn.icon = 'barcode-scan'
      scan_btn.md_bg_color = _theme_color('success', [0.16, 0.66, 0.26, 1])
    scanner_status = self.ids.get("scanner_status") if hasattr(self, "ids") else None
    if scanner_status is not None:
      scanner_status.text = 'Inativo'
      scanner_status.text_color = _theme_color('text_secondary', [0.5, 0.5, 0.5, 1])

  def open_sales_history(self, *args):
    """Abrir histÃ³rico de vendas"""
    if not self.manager:
      return
    self._stop_scanner_if_active()

    app = App.get_running_app()
    ensure_screen = getattr(app, "ensure_screen", None) if app else None
    if 'sales_history' not in self.manager.screen_names and callable(ensure_screen):
      ensure_screen('sales_history')
    if 'sales_history' not in self.manager.screen_names:
      return
    screen = self.manager.get_screen('sales_history')
    if hasattr(screen, 'back_target'):
      screen.back_target = self.name or 'manager'
    if hasattr(screen, 'request_enter_refresh'):
      Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)
    self.manager.current = 'sales_history'

  def open_losses_screen(self, *args):
    """Abrir tela de perdas"""
    if not self.manager:
      return
    self._stop_scanner_if_active()

    app = App.get_running_app()
    ensure_screen = getattr(app, "ensure_screen", None) if app else None
    if 'losses' not in self.manager.screen_names and callable(ensure_screen):
      ensure_screen('losses')
    if 'losses' not in self.manager.screen_names:
      return
    screen = self.manager.get_screen('losses')
    if hasattr(screen, 'back_target'):
      screen.back_target = self.name or 'manager'
    self.manager.current = 'losses'
    if 'losses' in self.manager.screen_names:
      if hasattr(screen, "prepare_open_from_admin"):
        Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0.02)
      elif hasattr(screen, "request_enter_refresh"):
        Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)

  
  def calculate_change(self, *args):
    """Calcular troco"""
    try:
      paid_text = self.ids.paid_input.text
      paid = float(paid_text) if paid_text else 0
      change = paid - self.total_amount
      
      if change >= 0:
        self.ids.change_label.text = f'{change:.2f} MZN'
        self.ids.change_label.text_color = _theme_color('success', [0.16, 0.66, 0.16, 1])
      else:
        self.ids.change_label.text = 'INSUFICIENTE'
        self.ids.change_label.text_color = _theme_color('danger', [0.88, 0.22, 0.22, 1])
        
    except ValueError:
      self.ids.change_label.text = '0.00 MZN'
    except Exception as e:
      self.ids.change_label.text = '0.00 MZN'
  
  # ==========================================
  # SCANNER DE CÃ“DIGO DE BARRAS
  # ==========================================
  
  def toggle_scanner(self, *args):
    """Ligar/desligar scanner"""
    if not self.scanning:
      if not self._ensure_scanner_dependencies():
        return
      self.scanning = True
      self.ids.scan_btn.icon = 'barcode-off'
      self.ids.scan_btn.md_bg_color = _theme_color('danger', [0.88, 0.26, 0.26, 1])
      self.ids.scanner_status.text = 'Iniciando...'
      self.ids.scanner_status.text_color = _theme_color('warning', [0.9, 0.7, 0.1, 1])
      Clock.schedule_once(self.init_camera, 0.1)
    else:
      self.scanning = False
      self.ids.scan_btn.icon = 'barcode-scan'
      
      self.ids.scan_btn.md_bg_color = _theme_color('success', [0.16, 0.66, 0.26, 1])
      self.ids.scanner_status.text = 'Inativo'
      self.ids.scanner_status.text_color = _theme_color('text_secondary', [0.5, 0.5, 0.5, 1])
      Clock.unschedule(self.update_camera)
      self.release_camera()
  
  def release_camera(self):
    """Liberar recursos da cÃ¢mera"""
    if self.camera_capture is not None:
      try:
        self.camera_capture.release()
      except:
        pass
      self.camera_capture = None
    
    if hasattr(self.ids, 'camera_image'):
      self.ids.camera_image.texture = None

  def _ensure_scanner_dependencies(self):
    try:
      self._load_vision_modules()
      return True
    except RuntimeError as exc:
      self.scanning = False
      self.ids.scan_btn.icon = 'barcode-scan'
      self.ids.scan_btn.md_bg_color = _theme_color('success', [0.16, 0.66, 0.26, 1])
      self.ids.scanner_status.text = 'Scanner indisponivel'
      self.ids.scanner_status.text_color = _theme_color('danger', [0.9, 0.2, 0.2, 1])
      self.show_snackbar(str(exc))
      return False

  def _load_vision_modules(self):
    if self._vision_modules is None:
      self._vision_modules = get_vision_dependencies()
    return self._vision_modules
  
  def init_camera(self, dt):
    """Inicializar cÃ¢mera"""
    try:
      cv2, _np, _decode = self._load_vision_modules()
      self.release_camera()
      
      self.camera_capture = cv2.VideoCapture(self.current_camera)
      
      if self.camera_capture.isOpened():
        self.camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.ids.scanner_status.text = f'Ativo (Cam {self.current_camera})'
        self.ids.scanner_status.text_color = _theme_color('success', [0.16, 0.72, 0.22, 1])
        
        self.last_barcode = None
        self.last_barcode_time = 0
        
        Clock.schedule_interval(self.update_camera, 1.0 / 20.0)
      else:
        self.ids.scanner_status.text = 'CÃ¢mera nÃ£o encontrada'
        self.ids.scanner_status.text_color = _theme_color('danger', [0.9, 0.2, 0.2, 1])
        self.scanning = False
        self.ids.scan_btn.icon = 'barcode-scan'
        self.ids.scan_btn.md_bg_color = _theme_color('success', [0.16, 0.66, 0.26, 1])
        
    except Exception as e:
      print(f"âŒ Erro ao inicializar cÃ¢mera: {e}")
      self.ids.scanner_status.text = 'Erro na cÃ¢mera'
      self.ids.scanner_status.text_color = _theme_color('danger', [0.9, 0.2, 0.2, 1])
      self.scanning = False
  
  def update_camera(self, dt):
    """Atualizar frame da cÃ¢mera e detectar cÃ³digos"""
    if not self.scanning or self.camera_capture is None:
      return
    
    try:
      cv2, np, decode = self._load_vision_modules()
      ret, frame = self.camera_capture.read()
      
      if not ret or frame is None:
        return
      
      frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
      
      import time
      current_time = time.time()
      
      codes = decode(frame)
      
      if codes:
        for code in codes:
          try:
            barcode_raw = code.data.decode('utf-8')
            barcode_value = ''.join(c for c in barcode_raw if c.isprintable()).strip()
            
            if (barcode_value == self.last_barcode and 
                (current_time - self.last_barcode_time) < 2):
              continue
            
            self.last_barcode = barcode_value
            self.last_barcode_time = current_time
            
            self.ids.scanner_status.text = 'Buscando...'
            self.ids.scanner_status.text_color = _theme_color('primary', [0.2, 0.5, 0.8, 1])
            self._lookup_barcode_async(barcode_value, source='scanner')
            
            pts = code.polygon
            if len(pts) == 4:
              pts = [(p.x, p.y) for p in pts]
              cv2.polylines(frame, [np.array(pts, dtype=np.int32)], 
                           True, (0, 255, 0), 3)
            
            x, y, w, h = code.rect
            cv2.putText(frame, barcode_value, (x, y - 10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
          except Exception as e:
            print(f"âŒ Erro ao processar cÃ³digo: {e}")
            continue
      else:
        if (current_time - self.last_barcode_time) > 2.5:
          self.ids.scanner_status.text = 'Ativo'
          self.ids.scanner_status.text_color = _theme_color('success', [0.16, 0.72, 0.22, 1])
      
      buf = cv2.flip(frame, 0).tobytes()
      texture = Texture.create(
        size=(frame.shape[1], frame.shape[0]), 
        colorfmt='bgr'
      )
      texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
      self.ids.camera_image.texture = texture
      
    except Exception as e:
      print(f"âŒ Erro no update_camera: {e}")
  
  def switch_camera(self, *args):
    """Trocar para prÃ³xima cÃ¢mera disponÃ­vel"""
    was_scanning = self.scanning
    
    if self.scanning:
      self.scanning = False
      Clock.unschedule(self.update_camera)
      self.release_camera()
    
    self.current_camera = (self.current_camera + 1) % 4
    
    if was_scanning:
      self.scanning = True
      self.ids.scan_btn.icon = 'barcode-off'
      self.ids.scan_btn.md_bg_color = _theme_color('danger', [0.88, 0.26, 0.26, 1])
      self.ids.scanner_status.text = f'Trocando para cam {self.current_camera}...'
      self.ids.scanner_status.text_color = _theme_color('warning', [0.9, 0.7, 0.1, 1])
      Clock.schedule_once(self.init_camera, 0.1)
  
  # ==========================================
  # FINALIZAÃ‡ÃƒO E OUTROS
  # ==========================================
  
  def finalize_sale(self, *args):
    """Finalizar venda"""
    if self._sale_submitting:
      return
    if not self.cart_items:
      self.show_message("âš  Carrinho vazio!")
      return
    
    try:
      paid_text = self.ids.paid_input.text
      paid = float(paid_text) if paid_text else 0
      
      if paid < self.total_amount:
        self.show_message("âš  Pagamento insuficiente!")
        return
    except ValueError:
      self.show_message("âš  Valor de pagamento invÃ¡lido!")
      return
    
    change = paid - self.total_amount
    self._set_sale_busy(True)
    cart_snapshot = [dict(item) for item in self.cart_items]
    total_amount = float(self.total_amount)

    app = App.get_running_app()
    username = getattr(app, "current_user", None)
    role = getattr(app, "current_role", None) or "manager"

    def worker():
      try:
        cart_ids = [item.get('id') for item in cart_snapshot if item.get('id') is not None]
        live_rows = self.db.get_products_for_sale_ids(cart_ids) or []
        live_map = {row[0]: row for row in live_rows}

        conflicts = []
        for item in cart_snapshot:
          live_product = live_map.get(item['id']) or self.products_dict.get(item['id'])
          live_stock = _unpack_sale_product(live_product)['stock'] if live_product else 0.0
          needed_units = float(item.get('qty_units', item.get('qty', 0)))
          item['max_stock'] = live_stock
          if needed_units > live_stock:
            conflicts.append((item['name'], needed_units, live_stock))

        if conflicts:
          return {"status": "conflict", "conflicts": conflicts, "live_map": live_map}

        for item in cart_snapshot:
          quantity_for_stock = item.get('qty_units', item['qty'])
          sale_unit_price = item.get('unit_price', item['price'])
          sale_result = self.db.add_sale(
            item['id'],
            quantity_for_stock,
            sale_unit_price,
            username,
            role,
            is_promotional=bool(item.get('promo_active', False)),
          )
          if not sale_result:
            raise RuntimeError(f"Falha ao gravar venda do item {item['name']}")

        items_count = len(cart_snapshot)
        modes = ",".join(sorted({str(i.get('sale_mode', 'unit')).upper() for i in cart_snapshot}))
        details = (
          f"Itens: {items_count} | Total: {total_amount:.2f} MZN | "
          f"Pago: {paid:.2f} | Troco: {change:.2f} | Modos: {modes}"
        )
        return {"status": "ok", "details": details}
      except Exception as exc:
        return {"status": "error", "error": str(exc)}

    def apply_result(dt, result):
      self._set_sale_busy(False)
      status = (result or {}).get("status")
      if status == "conflict":
        conflicts = result.get("conflicts") or []
        live_map = result.get("live_map") or {}
        for item in self.cart_items:
          live_product = live_map.get(item['id']) or self.products_dict.get(item['id'])
          item['max_stock'] = _unpack_sale_product(live_product)['stock'] if live_product else 0.0
        self.update_cart_display()
        if conflicts:
          first_name, needed, available = conflicts[0]
          self.show_message(
            f"⚠ Stock alterado: {first_name} ({needed:.2f} > {available:.2f})."
          )
        return
      if status == "ok":
        self.show_message("âœ“ Venda finalizada com sucesso!")
        self._log_action("SALE", result.get("details", "Venda realizada"))
        Clock.schedule_once(lambda _next: self.reset_sale(), 0.8)
        return
      error = (result or {}).get("error")
      print(f"âŒ Erro ao finalizar venda: {error}")
      self.show_message("âŒ Erro ao finalizar venda!")

    def commit_worker():
      result = worker()
      Clock.schedule_once(lambda dt, payload=result: apply_result(dt, payload), 0)

    Thread(target=commit_worker, daemon=True).start()

  def _set_sale_busy(self, busy):
    self._sale_submitting = bool(busy)
    for widget_id in ("finalize_btn", "receipt_btn", "cancel_btn"):
      widget = self.ids.get(widget_id) if hasattr(self, "ids") else None
      if widget is not None:
        widget.disabled = self._sale_submitting
    self._update_action_states()
  
  def reset_sale(self):
    """Resetar venda"""
    self.cart_items.clear()
    self.ids.paid_input.text = ''
    self.update_cart_display()
    self.load_products()
  
  def print_receipt(self, *args):
    """Imprimir recibo"""
    if not self.cart_items:
      self.show_message("âš  Nada para imprimir!")
      return
    
    receipt_text = "=" * 40 + "\n"
    receipt_text += "   RECIBO DE VENDA\n"
    receipt_text += "=" * 40 + "\n"
    receipt_text += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    receipt_text += "-" * 40 + "\n"
    
    for item in self.cart_items:
      receipt_text += f"{item['name']}\n"
      
      if item.get('is_weight', False):
        receipt_text += f" {item['weight_kg']:.2f} kg x {item['price']:.2f} = {item['total']:.2f} MZN\n"
      elif item.get('sale_mode') == 'pack':
        pack_units = int(item.get('pack_units') or 1)
        receipt_text += (
          f" {int(item['qty'])} emb ({pack_units} un cada) x "
          f"{item['price']:.2f} = {item['total']:.2f} MZN\n"
        )
      else:
        receipt_text += f" {int(item['qty'])} un x {item['price']:.2f} = {item['total']:.2f} MZN\n"
    
    receipt_text += "-" * 40 + "\n"
    receipt_text += f"TOTAL: {self.total_amount:.2f} MZN\n"
    
    try:
      paid = float(self.ids.paid_input.text) if self.ids.paid_input.text else 0
      change = paid - self.total_amount
      receipt_text += f"Pago: {paid:.2f} MZN\n"
      receipt_text += f"Troco: {change:.2f} MZN\n"
    except:
      pass
    
    receipt_text += "=" * 40 + "\n"
    receipt_text += "    Obrigado!\n"
    receipt_text += "=" * 40
    
    self.show_receipt_popup(receipt_text)
  
  def show_receipt_popup(self, receipt_text):
    """Mostrar popup do recibo"""
    content = MDBoxLayout(
      orientation='vertical',
      padding=dp(20),
      spacing=dp(15),
      size_hint_y=None,
      height=dp(500)
    )
    
    scroll = ScrollView()
    receipt_label = MDLabel(
      text=receipt_text,
      size_hint_y=None,
      font_size=dp(14),
      halign='left'
    )
    receipt_label.bind(texture_size=receipt_label.setter('size'))
    scroll.add_widget(receipt_label)
    
    btn_layout = MDBoxLayout(
      size_hint_y=None,
      height=dp(50),
      spacing=dp(10)
    )
    
    save_btn = MDRaisedButton(
      text='ðŸ’¾ SALVAR',
      md_bg_color=_theme_color('primary', [0.2, 0.5, 0.8, 1])
    )
    
    close_btn = MDRaisedButton(
      text='âœ— FECHAR',
      md_bg_color=_theme_color('card_alt', [0.5, 0.5, 0.5, 1])
    )
    
    btn_layout.add_widget(save_btn)
    btn_layout.add_widget(close_btn)
    
    content.add_widget(scroll)
    content.add_widget(btn_layout)
    
    dialog = MDDialog(
      title='ðŸ“„ Recibo de Venda',
      type='custom',
      content_cls=content,
      size_hint=(0.7, 0.8)
    )
    
    close_btn.bind(on_release=lambda x: dialog.dismiss())
    save_btn.bind(on_release=lambda x: self.save_receipt(receipt_text, dialog))
    
    dialog.open()
  
  def save_receipt(self, receipt_text, dialog):
    """Salvar recibo em arquivo"""
    try:
      filename = f"recibo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
      with open(filename, 'w', encoding='utf-8') as f:
        f.write(receipt_text)
      
      self.show_message(f"âœ“ Recibo salvo: {filename}")
      self._log_action("SAVE_RECEIPT", f"Recibo salvo: {filename}")
      dialog.dismiss()
      
    except Exception as e:
      print(f"âŒ Erro ao salvar recibo: {e}")
      self.show_message("âŒ Erro ao salvar recibo!")
  
  def cancel_sale(self, *args):
    """Cancelar venda"""
    if not self.cart_items:
      self.show_message("âš  Carrinho vazio!")
      return
    
    items_count = len(self.cart_items)
    total = self.total_amount
    
    self.cart_items.clear()
    self.ids.paid_input.text = ''
    self.update_cart_display()
    
    self.show_message("âœ“ Venda cancelada!")
    self._log_action("CANCEL_SALE", f"Itens: {items_count} | Total: {total:.2f} MZN")
    self._update_action_states()
  
  def show_message(self, message):
    """Mostrar feedback leve e nao-bloqueante."""
    self.show_snackbar(str(message))

  def focus_product_search(self, *args):
    search_input = self.ids.get("search_input") if hasattr(self, "ids") else None
    if search_input is None:
      return
    try:
      search_input.focus = True
    except Exception:
      pass
    products_list = self.ids.get("products_list") if hasattr(self, "ids") else None
    if products_list is not None:
      try:
        products_list.scroll_y = 1
      except Exception:
        pass
  
  def go_back(self, *args):
    """Voltar para a tela anterior ou login."""
    self._stop_scanner_if_active()
    if not self.manager:
      return
    if getattr(self, "back_target", None) in self.manager.screen_names:
      self.manager.current = self.back_target
      return
    if 'manager' in self.manager.screen_names:
      self.manager.current = 'manager'
      return
    self.manager.current = 'login'

  def return_to_login(self, *args):
    self._stop_scanner_if_active()
    app = App.get_running_app()
    if app:
      app.current_user = None
      app.current_role = None
    if not self.manager:
      return
    for screen_name in ("login_manager", "login"):
      if screen_name in self.manager.screen_names:
        screen = self.manager.get_screen(screen_name)
        if hasattr(screen, "reset_fields"):
          try:
            screen.reset_fields()
          except Exception:
            pass
        self.manager.current = screen_name
        return

  def on_enter(self):
    """Ao entrar na tela"""
    self._sync_theme_action()
    self._update_action_states()
    stale = (time.perf_counter() - self._last_products_refresh_at) >= self.PRODUCTS_CACHE_SECONDS
    if (not self._loaded_products) or stale:
      self.manual_refresh_stock(silent=True)
    app = App.get_running_app()
    warmup = getattr(app, "warmup_screens", None) if app else None
    if callable(warmup):
      Clock.schedule_once(
        lambda dt: warmup(("sales_history", "losses", "losses_history"), delay=0.12),
        0.24,
      )
    self._start_stock_polling()
    Clock.schedule_once(self._init_badge, 0.1)
    Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)

  def on_leave(self):
    """Ao sair da tela"""
    self._stop_stock_polling()
    if self._search_ev:
      self._search_ev.cancel()
      self._search_ev = None
    if self.scanning:
      self.scanning = False
      Clock.unschedule(self.update_camera)
      self.release_camera()
    self._stop_ai_polling()


# ------------------------------------------------------------------
    # Snackbar for notifications
    # ------------------------------------------------------------------
  def show_snackbar(self, message):
        MDSnackbar(
            MDLabel(
                text=message,
                theme_text_color="Custom",
                text_color=_theme_color('on_primary', [1, 1, 1, 1]),
            ),
            pos=(dp(10), dp(10)),
            size_hint_x=0.5,
        ).open()

  def show_ai_insights(self, *args):
        self.open_ai_menu()

  def open_ai_menu(self, caller=None):
        """Abre o historico da monitorizacao inteligente."""
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


 # ------------------------------------------------------------------
    # Sistema de NotificaÃ§Ãµes e AnimaÃ§Ã£o de Abanar
    # ------------------------------------------------------------------
  def _init_badge(self, dt):
        """Inicializa o badge de notificaÃ§Ãµes"""
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

  def add_notification(self):
        """Adiciona uma nova notificaÃ§Ã£o"""
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

  def clear_notifications(self):
        """Limpa todas as notificaÃ§Ãµes"""
        self.notification_count = 0
        self.update_notification_badge(0)

  def update_notification_badge(self, count):
        """
        Atualiza o badge e controla a animaÃ§Ã£o de abanar
        
        Args:
            count (int): NÃºmero de notificaÃ§Ãµes
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
        """Mostra o badge com animaÃ§Ã£o pop"""
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
        """Esconde o badge com animaÃ§Ã£o"""
        if not hasattr(self.ids, 'ai_badge'):
            return
        
        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

  def _start_swing_animation(self):
        """Inicia animaÃ§Ã£o de abanar/balanÃ§ar a lÃ¢mpada"""
        if not hasattr(self.ids, 'ai_button'):
            return
        
        self._stop_swing_animation()
        
        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False
            
            # Usar pos_hint para criar efeito de balanÃ§o (movimento lateral e vertical)
            original_pos = {"right": 0.965, "y": 0.04}
            
            # SequÃªncia de balanÃ§o simulando oscilaÃ§Ã£o
            swing = (
                # BalanÃ§o para direita-cima
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                # BalanÃ§o para esquerda-baixo
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.3, transition='in_out_sine') +
                # BalanÃ§o direita-meio
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                # BalanÃ§o esquerda-meio
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                # BalanÃ§o direita-pequeno
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.2, transition='in_out_sine') +
                # BalanÃ§o esquerda-pequeno
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.2, transition='in_out_sine') +
                # Volta ao centro
                Animation(pos_hint=original_pos, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True
        
        # Executar balanÃ§o a cada 2.5 segundos
        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)  # Executar imediatamente
    
  def _stop_swing_animation(self):
        """Para a animaÃ§Ã£o de abanar"""
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None
        
        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            
            # Retornar Ã  posiÃ§Ã£o original
            anim = Animation(
                pos_hint={"right": 0.965, "y": 0.04},
                duration=0.2,
                transition='out_sine'
            )
            anim.start(self.ids.ai_button)

if __name__ == "__main__":
  from manager_app import ManagerApp

  ManagerApp().run()


