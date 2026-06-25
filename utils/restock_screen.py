from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.textfield import MDTextField

from database.provider import get_db
from ui.components.loading_overlay import ScreenLoadingController
from utils.expiry_alerts import evaluate_expiry_alert
from utils.perf_utils import perf_start, perf_log


Builder.load_file(str(Path(__file__).with_name("restock_screen.kv")))


class StockProductRow(ButtonBehavior, MDBoxLayout):
    def __init__(self, product=None, **kwargs):
        super().__init__(**kwargs)
        self.product = product


class RestockScreen(MDScreen):
    REFRESH_SECONDS = 5
    ENTER_REFRESH_DELAY_SECONDS = 0.14
    PRODUCTS_RENDER_BATCH_SIZE = 28
    MOVEMENTS_RENDER_BATCH_SIZE = 60
    LOW_STOCK_THRESHOLD = 5
    PRODUCT_COL_HINTS = [0.08, 0.24, 0.11, 0.09, 0.09, 0.13, 0.14, 0.12]
    MOVEMENT_COL_HINTS = [0.12, 0.12, 0.09, 0.10, 0.18, 0.09, 0.09, 0.11, 0.10]  # last=DEL
    OUT_TYPES = [
        ("AJUSTE", "ADJUSTMENT"),
        ("DANIFICADO", "DAMAGE"),
        ("EXPIRADO", "EXPIRED"),
        ("ROUBO", "THEFT"),
    ]
    # Filter options for movement modal — rendered as buttons
    MOVEMENT_FILTERS = [
        ("TODOS", "ALL"),
        ("ENTRADAS", "IN"),
        ("SAIDAS", "OUT"),
        ("REPOSICAO", "RESTOCK"),
        ("PERDAS", "LOSS"),
    ]

    def __init__(self, db=None, **kwargs):
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.back_target = "admin_home"
        self.products = []
        self.movements = []
        self.selected_product = None
        self.current_mode = "IN"
        self._search_ev = None
        self._pending_search = ""
        self._products_load_token = 0
        self._products_loading = False
        self._pending_products_load = False
        self._product_load_callbacks = []
        self._last_products_loaded_at = 0.0
        self._products_render_ev = None
        self._products_render_rows = []
        self._products_render_index = 0
        self._enter_refresh_ev = None
        self._last_refresh_at = 0.0
        self._refresh_running = False
        self._pending_refresh = False
        self._movements_load_token = 0
        self._movements_loading = False
        self._pending_movements_limit = None
        self._movement_load_callbacks = []
        self._last_movements_loaded_at = 0.0
        self._last_movements_limit = 0
        self._movements_dialog = None
        self._movements_filter_btns = {}        # key -> MDRaisedButton/MDFlatButton
        self._movements_delete_btn = None       # "ELIMINAR VISÍVEIS" global button
        self._movements_print_btn = None
        self._movements_total_label = None
        self._movements_table_container = None
        self._movements_modal_rows = []
        self._movements_modal_title = ""
        self._movements_modal_limit = 200
        self._movements_filter_key = ""
        self._movements_render_ev = None
        self._movements_render_rows = []
        self._movements_render_index = 0
        self._movements_row_cache = []
        self._movements_empty_label = None
        self._movement_pdf_busy = False
        self._stock_form_dialog = None
        self._modal_title_label = None
        self._modal_selected_product_label = None
        self._modal_selected_stock_label = None
        self._modal_qty_input = None
        self._modal_note_input = None
        self._modal_expiry_input = None
        self._modal_unit_cost_input = None
        self._modal_supplier_input = None
        self._modal_invoice_input = None
        self._modal_movement_type_field = None
        self._modal_movement_type_btn = None
        self._modal_entry_date_field = None
        self._modal_exit_date_field = None
        self._modal_update_day_field = None
        self._modal_entry_expiry_row = None
        self._modal_entry_cost_row = None
        self._modal_entry_supplier_row = None
        self._modal_out_type_row = None
        self._modal_submit_btn = None
        self._out_label_to_code = {label: code for label, code in self.OUT_TYPES}
        self._out_code_to_label = {code: label for label, code in self.OUT_TYPES}
        self.stock_movements_report = None
        self.pdf_viewer = None
        self._expiry_alerts_by_id = {}
        self._movement_submitting = False
        self._loading_controller = getattr(self, "_loading_controller", None)
        # Out-type dropdown replaced with inline buttons
        self._out_type_btns = {}
        Clock.schedule_once(self.init_screen, 0.1)

    def init_screen(self, _dt):
        self._apply_mode_ui()
        self._set_now_markers()

    def on_kv_post(self, base_widget):
        self._ensure_loading_overlay()

    def on_enter(self):
        app = App.get_running_app()
        role = getattr(app, "current_role", None)
        if role != "admin":
            actor = getattr(app, "current_user", None) or "desconhecido"
            self._log_action(
                actor,
                role or "guest",
                "ACCESS_DENIED",
                "Tentativa de abrir a tela de reposicao sem privilegio admin",
            )
            self._show_dialog("Acesso Negado", "Apenas admin pode gerir stock nesta tela.")
            self._redirect_after_denied()
            return
        if not self.products:
            self.load_products()
        elif (perf_counter() - self._last_products_loaded_at) >= self.REFRESH_SECONDS:
            self.load_products()
        self._apply_mode_ui()
        Clock.schedule_once(lambda dt: self._focus_field("search_input"), 0.05)

    def _log_action(self, actor, role, action, details):
        try:
            self.db.log_action(actor, role, action, details)
        except Exception:
            pass

    def on_leave(self):
        if self._enter_refresh_ev:
            self._enter_refresh_ev.cancel()
            self._enter_refresh_ev = None
        self._stop_products_render()
        self._dismiss_stock_form_dialog()
        self._dismiss_movements_dialog()
        self._clear_loading_overlay()

    def _ensure_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is None:
            self._loading_controller = ScreenLoadingController(self)
        self._loading_controller.attach()
        return self._loading_controller

    def _set_loading_overlay(self, key, active, message="", detail=""):
        controller = self._ensure_loading_overlay()
        if active:
            controller.show(key, message, detail)
        else:
            controller.hide(key)

    def _clear_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is not None:
            self._loading_controller.clear()

    def go_back(self):
        if not self.manager:
            return
        if getattr(self, "back_target", None) in self.manager.screen_names:
            self.manager.current = self.back_target
            return
        self.manager.current = "admin"

    def _redirect_after_denied(self):
        if not self.manager:
            return
        try:
            names = list(getattr(self.manager, "screen_names", []) or [])
            for candidate in ("manager", "admin", "login"):
                if candidate in names:
                    self.manager.current = candidate
                    return
            if names:
                self.manager.current = names[0]
        except Exception:
            pass

    def open_restock_history(self, *args):
        self._open_movements_modal_async("Historico de Movimentos", limit=600)

    def open_recent_movements_modal(self, *args):
        self._open_movements_modal_async("Movimentos Recentes", limit=200)

    def _open_movements_modal_async(self, title, limit=200):
        self._movements_modal_limit = int(limit or 200)
        self._open_movements_modal(title, [])

    def prepare_open_from_admin(self, mode):
        self.set_mode(mode)
        if not self.products:
            self.load_products()

    def request_enter_refresh(self, force=False, delay=None):
        delay = self.ENTER_REFRESH_DELAY_SECONDS if delay is None else max(0, float(delay))
        if self._enter_refresh_ev:
            self._enter_refresh_ev.cancel()
            self._enter_refresh_ev = None

        data_ready = bool(self.products) and bool(self.movements)
        stale = (perf_counter() - self._last_refresh_at) >= self.REFRESH_SECONDS
        if not force and data_ready and not stale:
            return

        self._enter_refresh_ev = Clock.schedule_once(
            lambda dt, hard=bool(force): self._run_scheduled_refresh(hard),
            delay,
        )

    def _run_scheduled_refresh(self, force=False):
        self._enter_refresh_ev = None
        self.force_refresh(silent=True, force=force)

    def force_refresh(self, *args, silent=False, force=False):
        if self._refresh_running:
            self._pending_refresh = True
            return False
        if not force and (perf_counter() - self._last_refresh_at) < 0.8:
            return False

        started_at = perf_start()
        self._refresh_running = True
        try:
            self.load_products()
            self.load_movements(limit=200)
            self._refresh_selected_product()
            self._update_sync_label()
            self._last_refresh_at = perf_counter()
            perf_log(
                "restock.force_refresh",
                started_at,
                f"products={len(self.products)} movements={len(self.movements)} mode={self.current_mode}",
            )
            return True
        except Exception as exc:
            if not silent:
                self._show_dialog("Erro", f"Falha ao atualizar dados de stock: {exc}")
            return False
        finally:
            self._refresh_running = False
            if self._pending_refresh:
                self._pending_refresh = False
                Clock.schedule_once(lambda dt: self.force_refresh(silent=True, force=True), 0.05)

    def _update_sync_label(self):
        if "sync_label" in self.ids:
            self.ids.sync_label.text = f"Ult. sync: {datetime.now().strftime('%H:%M:%S')}"

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=lambda message: self._show_dialog("Erro", message))
        return self.pdf_viewer

    def _ensure_stock_movements_report(self):
        if self.stock_movements_report is None:
            from pdfs.stock_movements_report import StockMovementsReport
            self.stock_movements_report = StockMovementsReport()
        return self.stock_movements_report

    def _set_movements_print_busy(self, busy):
        self._movement_pdf_busy = bool(busy)
        if self._movement_pdf_busy:
            self._set_loading_overlay(
                "movements_print",
                True,
                "A preparar PDF dos movimentos...",
                "Estamos a organizar o historico filtrado para impressao.",
            )
        else:
            self._set_loading_overlay("movements_print", False)
        if self._movements_print_btn:
            self._movements_print_btn.disabled = self._movement_pdf_busy
            self._movements_print_btn.text = "A IMPRIMIR..." if self._movement_pdf_busy else "IMPRIMIR PDF"

    # ---------- Mode ----------
    def set_mode(self, mode):
        mode = str(mode or "IN").upper()
        self.current_mode = "OUT" if mode == "OUT" else "IN"
        self._apply_mode_ui()

    def _apply_mode_ui(self):
        if not self.ids:
            return
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.15, 0.35, 0.65, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])
        danger = tokens.get("danger", [0.85, 0.2, 0.2, 1])
        card = tokens.get("card", [1, 1, 1, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])

        is_in = self.current_mode == "IN"
        self.ids.mode_in_btn.md_bg_color = success if is_in else card
        self.ids.mode_in_btn.text_color = on_primary if is_in else text_primary
        self.ids.mode_out_btn.md_bg_color = danger if not is_in else card
        self.ids.mode_out_btn.text_color = on_primary if not is_in else text_primary
        self.ids.form_title.text = "Registo de Entrada" if is_in else "Registo de Saida"
        self.ids.submit_btn.text = "REGISTAR ENTRADA" if is_in else "REGISTAR SAIDA"
        self.ids.submit_btn.md_bg_color = success if is_in else primary

        self._set_row_visibility(
            row_id="entry_cost_row",
            visible=is_in,
            target_height=dp(52),
            field_ids=("unit_cost_input",),
        )
        self._set_row_visibility(
            row_id="entry_expiry_row",
            visible=is_in,
            target_height=dp(52),
            field_ids=("expiry_input",),
        )
        self._set_row_visibility(
            row_id="entry_supplier_row",
            visible=is_in,
            target_height=dp(52),
            field_ids=("supplier_input", "invoice_input"),
        )
        self._set_row_visibility(
            row_id="out_type_row",
            visible=not is_in,
            target_height=dp(52),
            field_ids=("movement_type_field",),
        )
        self._sync_stock_form_modal_from_hidden()

    def _set_movement_busy(self, busy):
        self._movement_submitting = bool(busy)
        if self._movement_submitting:
            action_label = "entrada" if self.current_mode == "IN" else "saida"
            self._set_loading_overlay(
                "movement_submit",
                True,
                f"A registar {action_label} de stock...",
                "Estamos a validar os dados e a guardar o movimento no sistema.",
            )
        else:
            self._set_loading_overlay("movement_submit", False)
        busy_text = "A PROCESSAR..."
        if self.ids and "submit_btn" in self.ids:
            self.ids.submit_btn.disabled = self._movement_submitting
            if self._movement_submitting:
                self.ids.submit_btn.text = busy_text
        if self._modal_submit_btn:
            self._modal_submit_btn.disabled = self._movement_submitting
            if self._movement_submitting:
                self._modal_submit_btn.text = busy_text
        if not self._movement_submitting:
            self._apply_mode_ui()

    def _set_row_visibility(self, row_id, visible, target_height, field_ids):
        if row_id not in self.ids:
            return
        row = self.ids[row_id]
        row.height = target_height if visible else 0
        row.opacity = 1 if visible else 0
        row.disabled = not visible
        for field_id in field_ids:
            if field_id in self.ids:
                self.ids[field_id].disabled = not visible

    def open_movement_type_menu(self):
        """No-op: out-type is now selected via inline buttons in the KV layout."""
        pass

    def _select_out_type(self, label):
        """Called by inline out-type buttons."""
        if "movement_type_field" in self.ids:
            self.ids.movement_type_field.text = label
        if self._modal_movement_type_field:
            self._modal_movement_type_field.text = label
        # Highlight active button
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.15, 0.35, 0.65, 1])
        card = tokens.get("card", [1, 1, 1, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        for btn_label, btn in self._out_type_btns.items():
            active = (btn_label == label)
            btn.md_bg_color = primary if active else card
            btn.text_color = on_primary if active else text_primary

    def _build_out_type_buttons(self, container):
        """Build inline out-type selector buttons and store refs."""
        self._out_type_btns = {}
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.15, 0.35, 0.65, 1])
        card = tokens.get("card", [1, 1, 1, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        current = "AJUSTE"
        for label, _code in self.OUT_TYPES:
            active = (label == current)
            btn = MDRaisedButton(
                text=label,
                md_bg_color=primary if active else card,
                text_color=on_primary if active else text_primary,
                size_hint=(None, None),
                height=dp(36),
                width=dp(110),
                on_release=lambda _b, lbl=label: self._select_out_type(lbl),
            )
            self._out_type_btns[label] = btn
            container.add_widget(btn)

    # ---------- Stock register modal ----------
    def open_stock_register_modal(self, *args):
        self._dismiss_stock_form_dialog()

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(500),
        )

        form_scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
        form_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            padding=[dp(2), dp(2), dp(2), dp(8)],
        )
        form_box.bind(minimum_height=form_box.setter("height"))
        form_scroll.add_widget(form_box)

        self._modal_title_label = MDLabel(
            text="Registo de Entrada",
            font_style="Subtitle1",
            bold=True,
            size_hint_y=None,
            height=dp(28),
        )
        form_box.add_widget(self._modal_title_label)

        form_box.add_widget(
            MDLabel(
                text="Produto selecionado",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(20),
            )
        )
        self._modal_selected_product_label = MDLabel(
            text="Produto: --",
            size_hint_y=None,
            height=dp(22),
            theme_text_color="Primary",
        )
        form_box.add_widget(self._modal_selected_product_label)
        self._modal_selected_stock_label = MDLabel(
            text="Stock atual: --",
            size_hint_y=None,
            height=dp(22),
            theme_text_color="Secondary",
        )
        form_box.add_widget(self._modal_selected_stock_label)

        form_box.add_widget(
            MDLabel(
                text="Dados do movimento",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(20),
            )
        )
        qty_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        self._modal_qty_input = MDTextField(
            hint_text="Quantidade *",
            mode="rectangle",
            input_filter="float",
        )
        self._modal_note_input = MDTextField(
            hint_text="Observacao",
            mode="rectangle",
        )
        qty_row.add_widget(self._modal_qty_input)
        qty_row.add_widget(self._modal_note_input)
        form_box.add_widget(qty_row)

        self._modal_entry_expiry_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8),
        )
        self._modal_expiry_input = MDTextField(
            hint_text="Validade do lote DD/MM/AAAA",
            mode="rectangle",
        )
        self._modal_entry_expiry_row.add_widget(self._modal_expiry_input)
        form_box.add_widget(self._modal_entry_expiry_row)

        self._modal_entry_cost_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8),
        )
        self._modal_unit_cost_input = MDTextField(
            hint_text="Custo unitario *",
            mode="rectangle",
            input_filter="float",
        )
        self._modal_entry_cost_row.add_widget(self._modal_unit_cost_input)
        form_box.add_widget(self._modal_entry_cost_row)

        self._modal_entry_supplier_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8),
        )
        self._modal_supplier_input = MDTextField(
            hint_text="Fornecedor (opcional)",
            mode="rectangle",
        )
        self._modal_invoice_input = MDTextField(
            hint_text="N. Fatura (opcional)",
            mode="rectangle",
        )
        self._modal_entry_supplier_row.add_widget(self._modal_supplier_input)
        self._modal_entry_supplier_row.add_widget(self._modal_invoice_input)
        form_box.add_widget(self._modal_entry_supplier_row)

        # Out-type: inline buttons instead of dropdown
        self._modal_out_type_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8),
        )
        self._modal_movement_type_field = MDTextField(
            hint_text="Tipo de saida",
            mode="rectangle",
            readonly=True,
            text="AJUSTE",
        )
        self._modal_out_type_row.add_widget(self._modal_movement_type_field)
        form_box.add_widget(self._modal_out_type_row)

        form_box.add_widget(
            MDLabel(
                text="Datas",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(20),
            )
        )
        dates_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        self._modal_entry_date_field = MDTextField(
            hint_text="Data de Entrada",
            mode="rectangle",
            readonly=True,
            text="--",
        )
        self._modal_exit_date_field = MDTextField(
            hint_text="Data de Saida",
            mode="rectangle",
            readonly=True,
            text="--",
        )
        self._modal_update_day_field = MDTextField(
            hint_text="Dia de Atualizacao",
            mode="rectangle",
            readonly=True,
            text="--",
        )
        dates_row.add_widget(self._modal_entry_date_field)
        dates_row.add_widget(self._modal_exit_date_field)
        dates_row.add_widget(self._modal_update_day_field)
        form_box.add_widget(dates_row)

        content.add_widget(form_scroll)

        actions_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        actions_row.add_widget(MDFlatButton(text="LIMPAR", on_release=lambda _btn: self.clear_form()))
        self._modal_submit_btn = MDRaisedButton(
            text="REGISTAR ENTRADA",
            on_release=lambda _btn: self.register_movement_from_modal(),
        )
        actions_row.add_widget(self._modal_submit_btn)
        content.add_widget(actions_row)

        dialog = MDDialog(
            title="Registo de Stock",
            type="custom",
            content_cls=content,
            size_hint=(0.86, 0.82),
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda _btn: self._dismiss_stock_form_dialog())],
        )
        self._stock_form_dialog = dialog
        self._sync_stock_form_modal_from_hidden()
        dialog.open()

    def _dismiss_stock_form_dialog(self):
        if self._stock_form_dialog:
            self._stock_form_dialog.dismiss()
            self._stock_form_dialog = None
        self._modal_title_label = None
        self._modal_selected_product_label = None
        self._modal_selected_stock_label = None
        self._modal_qty_input = None
        self._modal_note_input = None
        self._modal_expiry_input = None
        self._modal_unit_cost_input = None
        self._modal_supplier_input = None
        self._modal_invoice_input = None
        self._modal_movement_type_field = None
        self._modal_movement_type_btn = None
        self._modal_entry_date_field = None
        self._modal_exit_date_field = None
        self._modal_update_day_field = None
        self._modal_entry_expiry_row = None
        self._modal_entry_cost_row = None
        self._modal_entry_supplier_row = None
        self._modal_out_type_row = None
        self._modal_submit_btn = None

    def _sync_stock_form_modal_from_hidden(self):
        if not self._stock_form_dialog:
            return
        if "selected_product_label" in self.ids and self._modal_selected_product_label:
            self._modal_selected_product_label.text = self.ids.selected_product_label.text
        if "selected_stock_label" in self.ids and self._modal_selected_stock_label:
            self._modal_selected_stock_label.text = self.ids.selected_stock_label.text
        if "qty_input" in self.ids and self._modal_qty_input:
            self._modal_qty_input.text = self.ids.qty_input.text
        if "note_input" in self.ids and self._modal_note_input:
            self._modal_note_input.text = self.ids.note_input.text
        if "expiry_input" in self.ids and self._modal_expiry_input:
            self._modal_expiry_input.text = self.ids.expiry_input.text
        if "unit_cost_input" in self.ids and self._modal_unit_cost_input:
            self._modal_unit_cost_input.text = self.ids.unit_cost_input.text
        if "supplier_input" in self.ids and self._modal_supplier_input:
            self._modal_supplier_input.text = self.ids.supplier_input.text
        if "invoice_input" in self.ids and self._modal_invoice_input:
            self._modal_invoice_input.text = self.ids.invoice_input.text
        if "movement_type_field" in self.ids and self._modal_movement_type_field:
            self._modal_movement_type_field.text = self.ids.movement_type_field.text
        if "entry_date_field" in self.ids and self._modal_entry_date_field:
            self._modal_entry_date_field.text = self.ids.entry_date_field.text
        if "exit_date_field" in self.ids and self._modal_exit_date_field:
            self._modal_exit_date_field.text = self.ids.exit_date_field.text
        if "update_day_field" in self.ids and self._modal_update_day_field:
            self._modal_update_day_field.text = self.ids.update_day_field.text

        is_in = self.current_mode == "IN"
        if self._modal_title_label:
            self._modal_title_label.text = "Registo de Entrada" if is_in else "Registo de Saida"
        if self._modal_submit_btn:
            tokens = self._theme_tokens()
            self._modal_submit_btn.text = "REGISTAR ENTRADA" if is_in else "REGISTAR SAIDA"
            self._modal_submit_btn.md_bg_color = (
                tokens.get("success", [0.2, 0.7, 0.3, 1]) if is_in else tokens.get("primary", [0.15, 0.35, 0.65, 1])
            )
            self._modal_submit_btn.disabled = self._movement_submitting
            if self._movement_submitting:
                self._modal_submit_btn.text = "A PROCESSAR..."
        self._set_modal_row_visibility(
            self._modal_entry_expiry_row,
            is_in,
            dp(52),
            (self._modal_expiry_input,),
        )
        self._set_modal_row_visibility(
            self._modal_entry_cost_row,
            is_in,
            dp(52),
            (self._modal_unit_cost_input,),
        )
        self._set_modal_row_visibility(
            self._modal_entry_supplier_row,
            is_in,
            dp(52),
            (self._modal_supplier_input, self._modal_invoice_input),
        )
        self._set_modal_row_visibility(
            self._modal_out_type_row,
            not is_in,
            dp(52),
            (self._modal_movement_type_field,),
        )
        if self.ids and "submit_btn" in self.ids:
            self.ids.submit_btn.disabled = self._movement_submitting
            if self._movement_submitting:
                self.ids.submit_btn.text = "A PROCESSAR..."

    @staticmethod
    def _set_modal_row_visibility(row, visible, target_height, fields):
        if not row:
            return
        row.height = target_height if visible else 0
        row.opacity = 1 if visible else 0
        row.disabled = not visible
        for field in fields:
            if field is not None:
                field.disabled = not visible

    def _sync_hidden_form_from_modal(self):
        if not self._stock_form_dialog:
            return
        if self._modal_qty_input and "qty_input" in self.ids:
            self.ids.qty_input.text = self._modal_qty_input.text
        if self._modal_note_input and "note_input" in self.ids:
            self.ids.note_input.text = self._modal_note_input.text
        if self._modal_expiry_input and "expiry_input" in self.ids:
            self.ids.expiry_input.text = self._modal_expiry_input.text
        if self._modal_unit_cost_input and "unit_cost_input" in self.ids:
            self.ids.unit_cost_input.text = self._modal_unit_cost_input.text
        if self._modal_supplier_input and "supplier_input" in self.ids:
            self.ids.supplier_input.text = self._modal_supplier_input.text
        if self._modal_invoice_input and "invoice_input" in self.ids:
            self.ids.invoice_input.text = self._modal_invoice_input.text
        if self._modal_movement_type_field and "movement_type_field" in self.ids:
            self.ids.movement_type_field.text = self._modal_movement_type_field.text

    def register_movement_from_modal(self):
        self._sync_hidden_form_from_modal()
        self.register_movement()
        self._sync_stock_form_modal_from_hidden()

    # ---------- Data load (SYNCHRONOUS — no threading) ----------
    def _fetch_products_for_restock(self):
        rows = []
        try:
            rows = self.db.get_products_for_stock_control(include_velocity=True, velocity_days=14) or []
        except Exception:
            rows = []

        if not rows:
            try:
                fallback = self.db.get_products_for_restock(include_velocity=True, velocity_days=14) or []
                rows = [self._normalize_product_row(r) for r in fallback]
            except Exception:
                rows = []
        else:
            rows = [self._normalize_product_row(r) for r in rows]
        return rows

    def _fetch_movements_for_restock(self, limit=200):
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        rows = []
        try:
            rows = self.db.get_stock_movements(
                start_dt,
                end_dt,
                direction=None,
                product_id=None,
                include_sales=True,
                limit=int(limit or 200),
            ) or []
        except Exception:
            rows = []

        if not rows:
            rows = self._fallback_movements(start_dt, end_dt)
        return rows

    def load_products(self):
        rows = self._fetch_products_for_restock()
        self.products = rows
        self._expiry_alerts_by_id = self._build_expiry_alerts(self.products)
        self._last_products_loaded_at = perf_counter()
        self._apply_search_now()
        # Drain any queued callbacks
        callbacks = list(self._product_load_callbacks)
        self._product_load_callbacks.clear()
        for cb in callbacks:
            try:
                cb(list(rows))
            except Exception:
                pass
        return rows

    def load_movements(self, limit=200, update_table=True):
        rows = self._fetch_movements_for_restock(limit=limit)
        self.movements = rows
        self._last_movements_loaded_at = perf_counter()
        self._last_movements_limit = int(limit or 200)
        if update_table:
            self._show_movements(rows)
        # Drain callbacks
        callbacks = list(self._movement_load_callbacks)
        self._movement_load_callbacks.clear()
        for cb in callbacks:
            try:
                cb(list(rows))
            except Exception:
                pass
        return rows

    # Keep async signatures as thin wrappers for compatibility with callers
    def load_products_async(self, force=False, on_loaded=None):
        stale = (perf_counter() - self._last_products_loaded_at) >= self.REFRESH_SECONDS
        if callable(on_loaded):
            self._product_load_callbacks.append(on_loaded)
        if not force and self.products and not stale:
            callbacks = list(self._product_load_callbacks)
            self._product_load_callbacks.clear()
            for cb in callbacks:
                try:
                    cb(list(self.products))
                except Exception:
                    pass
            return
        self.load_products()

    def load_movements_async(self, limit=200, force=False, on_loaded=None):
        stale = (perf_counter() - self._last_movements_loaded_at) >= self.REFRESH_SECONDS
        if callable(on_loaded):
            self._movement_load_callbacks.append(on_loaded)
        if not force and self.movements and not stale:
            callbacks = list(self._movement_load_callbacks)
            self._movement_load_callbacks.clear()
            for cb in callbacks:
                try:
                    cb(list(self.movements))
                except Exception:
                    pass
            return
        self.load_movements(limit=limit)

    def _fallback_movements(self, start_dt, end_dt):
        try:
            restocks = self.db.get_restock_records(start_dt, end_dt, limit=120) or []
        except Exception:
            return []

        normalized = []
        for idx, row in enumerate(restocks, 1):
            created_at, product_name, qty, unit, unit_cost, total_cost, created_by, note = row
            update_day = str(created_at or "")[:10] if created_at else None
            normalized.append(
                (
                    idx, created_at, created_at, None, update_day, "IN", "RESTOCK",
                    None, product_name, qty, unit, unit_cost, total_cost, None, None,
                    "Reposicao de stock", note, created_by, None, None,
                )
            )
        return normalized

    # ---------- Search ----------
    def on_search(self, text):
        self._pending_search = text or ""
        if self._search_ev:
            self._search_ev.cancel()
        self._search_ev = Clock.schedule_once(lambda dt: self._apply_search_now(), 0.2)

    def on_search_enter(self):
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None
        query = (self._pending_search or self.ids.search_input.text if "search_input" in self.ids else "").strip().lower()
        filtered = self._filter_products(query)
        self._show_products(filtered)
        if not query:
            return
        if len(filtered) == 1:
            self.select_product(filtered[0])
        elif len(filtered) > 1:
            self.show_feedback(f"{len(filtered)} produtos encontrados. Escolha um da lista.", "info")
        else:
            self.show_feedback("Nenhum produto encontrado para esta pesquisa.", "warning")

    def _apply_search_now(self):
        self._search_ev = None
        query = (self._pending_search or self.ids.search_input.text if "search_input" in self.ids else "").strip().lower()
        if not query:
            self._show_products(self.products)
            return
        self._show_products(self._filter_products(query))

    def _filter_products(self, query):
        normalized_query = str(query or "").strip().lower()
        if not normalized_query:
            return list(self.products or [])
        filtered = []
        for p in self.products:
            pid, name, _stock, _price, _cost, barcode, _is_weight, _exp, _status, _avg, _days, _last = (
                self._unpack_product(p)
            )
            terms = [
                str(pid or "").lower(),
                str(name or "").lower(),
                str(barcode or "").lower(),
            ]
            if any(normalized_query in term for term in terms):
                filtered.append(p)
        return filtered

    # ---------- Product table ----------
    def _show_products(self, rows):
        if "products_table" not in self.ids:
            return
        table = self.ids.products_table
        self._stop_products_render()
        table.clear_widgets()

        if not rows:
            table.add_widget(
                MDLabel(
                    text="Nenhum produto encontrado",
                    theme_text_color="Secondary",
                    halign="center",
                    size_hint_y=None,
                    height=dp(36),
                )
            )
            return

        self._products_render_rows = list(rows or [])
        self._products_render_index = 0
        self._render_next_products_batch(0)
        if self._products_render_index < len(self._products_render_rows):
            self._products_render_ev = Clock.schedule_interval(self._render_next_products_batch, 0)

    def _stop_products_render(self):
        if self._products_render_ev:
            self._products_render_ev.cancel()
            self._products_render_ev = None

    def _render_next_products_batch(self, _dt):
        table = self.ids.get("products_table") if hasattr(self, "ids") else None
        if table is None:
            self._stop_products_render()
            return False
        if self._products_render_index >= len(self._products_render_rows):
            self._stop_products_render()
            return False

        start = self._products_render_index
        end = min(start + self.PRODUCTS_RENDER_BATCH_SIZE, len(self._products_render_rows))
        for idx in range(start, end):
            table.add_widget(self._build_stock_product_row(self._products_render_rows[idx], idx))
        self._products_render_index = end

        if self._products_render_index >= len(self._products_render_rows):
            self._stop_products_render()
            return False
        return True

    def _build_stock_product_row(self, raw, idx):
        tokens = self._theme_tokens()
        row_even = tokens.get("surface_alt", [0.97, 0.98, 0.99, 1])
        row_odd = tokens.get("card", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        text_secondary = tokens.get("text_secondary", [0.5, 0.5, 0.5, 1])
        warning = tokens.get("warning", [0.9, 0.65, 0.1, 1])
        danger = tokens.get("danger", [0.85, 0.2, 0.2, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])

        (
            pid, name, stock, _price, _cost, _barcode, is_weight,
            exp_date, _status, avg_daily, days_left, last_update,
        ) = self._unpack_product(raw)
        expiry_alert = self._get_expiry_alert(raw)

        unit = "KG" if is_weight else "UN"
        stock_val = self._to_float(stock)
        avg_val = self._to_float(avg_daily)
        days_val = None if days_left is None else self._to_float(days_left)
        bg_color = row_even if idx % 2 == 0 else row_odd
        stock_color = text_primary
        if stock_val <= self.LOW_STOCK_THRESHOLD:
            stock_color = warning
        if days_val is not None and days_val <= 3:
            stock_color = danger

        row = StockProductRow(
            product=raw,
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            padding=[dp(6), 0],
            spacing=dp(6),
            md_bg_color=bg_color,
        )
        row.bind(on_release=lambda _x, p=raw: self.select_product(p))

        self._add_cell(row, str(pid), self.PRODUCT_COL_HINTS[0], halign="center", color=text_primary, bold=True)
        self._add_cell(row, name or "", self.PRODUCT_COL_HINTS[1], halign="left", color=text_primary, shorten=True)
        stock_text = f"{stock_val:.2f} {unit}" if is_weight else f"{int(stock_val)} {unit}"
        self._add_cell(row, stock_text, self.PRODUCT_COL_HINTS[2], halign="center", color=stock_color, bold=True)
        avg_text = f"{avg_val:.2f}/{unit}" if avg_val > 0 else "--"
        self._add_cell(row, avg_text, self.PRODUCT_COL_HINTS[3], halign="center", color=text_secondary)
        days_text = "--" if days_val is None else f"{days_val:.1f}d"
        self._add_cell(row, days_text, self.PRODUCT_COL_HINTS[4], halign="center", color=text_secondary)
        expiry_color = expiry_alert["color_rgba"] if expiry_alert.get("is_alert") else text_secondary
        expiry_day = self._format_dt(exp_date, with_time=False) if exp_date else "--"
        expiry_text = f"{expiry_day} | {expiry_alert.get('short_label', '--')}" if exp_date else "Sem validade"
        self._add_cell(
            row, expiry_text, self.PRODUCT_COL_HINTS[5], halign="center",
            color=expiry_color, bold=bool(expiry_alert.get("is_alert")), shorten=True,
        )
        self._add_cell(
            row, self._format_dt(last_update, with_time=True),
            self.PRODUCT_COL_HINTS[6], halign="center", color=text_secondary,
        )

        action = MDBoxLayout(size_hint_x=self.PRODUCT_COL_HINTS[7], size_hint_y=None, height=dp(30))
        action_btn = MDRaisedButton(
            text="REGISTAR",
            md_bg_color=success,
            text_color=on_primary,
            size_hint=(1, None),
            height=dp(28),
            on_release=lambda _btn, p=raw: self.open_register_for_product(p),
        )
        action.add_widget(action_btn)
        row.add_widget(action)
        return row

    def _add_cell(self, row, text, hint, halign="left", color=None, bold=False, shorten=False):
        row.add_widget(
            MDLabel(
                text=str(text),
                size_hint_x=hint,
                halign=halign,
                theme_text_color="Custom",
                text_color=color or [0.2, 0.2, 0.2, 1],
                font_style="Caption",
                bold=bold,
                shorten=shorten,
                shorten_from="right",
            )
        )

    def select_product(self, product):
        self.selected_product = self._normalize_product_row(product)
        pid, name, stock, _price, _cost, _barcode, is_weight, _exp, _status, _avg, _days, last_update = (
            self._unpack_product(self.selected_product)
        )
        unit = "KG" if is_weight else "UN"
        stock_text = f"{self._to_float(stock):.2f}" if is_weight else str(int(self._to_float(stock)))
        expiry_text = self._format_expiry_input(_exp) or "sem validade"
        self.ids.selected_product_label.text = f"Produto: {name or '--'} (ID {pid}) | Validade base: {expiry_text}"
        self.ids.selected_stock_label.text = f"Stock atual: {stock_text} {unit}"
        current_price = self._to_float(_price)
        if current_price <= 0:
            current_price = self._to_float(_cost)
        self.ids.unit_cost_input.text = f"{current_price:.2f}" if current_price > 0 else ""
        if "expiry_input" in self.ids:
            self.ids.expiry_input.text = self._format_expiry_input(_exp)
        if last_update:
            self.ids.update_day_field.text = self._format_update_day(last_update)
        else:
            self.ids.update_day_field.text = "--"
        self._sync_stock_form_modal_from_hidden()
        self.show_feedback(f"{name} pronto para {('entrada' if self.current_mode == 'IN' else 'saida')}.", "info")
        Clock.schedule_once(lambda dt: self._focus_field("qty_input", select_all=True), 0)

    def _advance_restock_form(self):
        if not self.selected_product:
            return self._focus_field("search_input", select_all=True)
        if self.current_mode == "IN":
            expiry_text = str(self.ids.expiry_input.text or "").strip() if "expiry_input" in self.ids else ""
            if expiry_text:
                try:
                    self._parse_expiry_input(expiry_text)
                except ValueError as exc:
                    self.show_feedback(str(exc), "warning")
                    return self._focus_field("expiry_input", select_all=True)
            if not str(self.ids.unit_cost_input.text or "").strip():
                self.show_feedback("Informe o custo unitario para concluir a entrada.", "info")
                return self._focus_field("unit_cost_input", select_all=True)
            return self._focus_field("note_input", select_all=True)
        return self._focus_field("note_input", select_all=True)

    def open_register_for_product(self, product):
        self.select_product(product)
        self.open_stock_register_modal()

    def _refresh_selected_product(self):
        if not self.selected_product:
            return
        selected_id = self._unpack_product(self.selected_product)[0]
        for p in self.products:
            if self._unpack_product(p)[0] == selected_id:
                self.select_product(p)
                return

    # ---------- Movement table ----------
    def _show_movements(self, rows):
        if "movements_table" not in self.ids:
            return
        table = self.ids.movements_table
        table.clear_widgets()

        if not rows:
            table.add_widget(
                MDLabel(
                    text="Sem movimentos no periodo",
                    theme_text_color="Secondary",
                    halign="center",
                    size_hint_y=None,
                    height=dp(36),
                )
            )
            return

        tokens = self._theme_tokens()
        row_even = tokens.get("surface_alt", [0.97, 0.98, 0.99, 1])
        row_odd = tokens.get("card", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        text_secondary = tokens.get("text_secondary", [0.5, 0.5, 0.5, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])
        danger = tokens.get("danger", [0.85, 0.2, 0.2, 1])

        for idx, raw in enumerate(rows):
            (
                _mid, _created_at, entry_date, exit_date, update_day, direction, movement_type,
                _product_id, product_name, qty, unit, _unit_cost, _total_cost, _stock_before,
                _stock_after, _reason, _note, created_by, _supplier, _invoice,
            ) = self._normalize_movement_row(raw)

            bg = row_even if idx % 2 == 0 else row_odd
            row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(34),
                padding=[dp(6), 0],
                spacing=dp(6),
                md_bg_color=bg,
            )

            qty_val = self._to_float(qty)
            if str(unit or "UN").upper() == "UN" and float(qty_val).is_integer():
                qty_text = f"{int(qty_val)} UN"
            else:
                qty_text = f"{qty_val:.2f} {unit or 'UN'}"

            direction_color = success if direction == "IN" else danger
            movement_label = self._out_code_to_label.get(movement_type, movement_type or "-")

            self._add_cell(row, self._format_dt(entry_date, with_time=True), self.MOVEMENT_COL_HINTS[0], "center", text_secondary)
            self._add_cell(row, self._format_dt(exit_date, with_time=True), self.MOVEMENT_COL_HINTS[1], "center", text_secondary)
            self._add_cell(row, self._format_update_day(update_day), self.MOVEMENT_COL_HINTS[2], "center", text_secondary)
            self._add_cell(row, movement_label, self.MOVEMENT_COL_HINTS[3], "center", direction_color, bold=True)
            self._add_cell(row, product_name or "-", self.MOVEMENT_COL_HINTS[4], "left", text_primary, shorten=True)
            self._add_cell(row, qty_text, self.MOVEMENT_COL_HINTS[5], "center", text_secondary)
            self._add_cell(row, direction or "-", self.MOVEMENT_COL_HINTS[6], "center", direction_color, bold=True)
            self._add_cell(row, created_by or "-", self.MOVEMENT_COL_HINTS[7], "right", text_secondary, shorten=True)

            table.add_widget(row)

    def _dismiss_movements_dialog(self):
        self._stop_movements_render()
        if self._movements_dialog:
            self._movements_dialog.dismiss()
            self._movements_dialog = None
        self._movements_filter_btns = {}
        self._movements_delete_btn = None
        self._movements_print_btn = None
        self._movements_total_label = None
        self._movements_table_container = None
        self._movements_modal_rows = []
        self._movements_modal_title = ""
        self._movements_filter_key = ""
        self._movements_row_cache = []
        self._movements_empty_label = None
        self._movement_pdf_busy = False

    def _open_movements_modal(self, title, rows):
        self._dismiss_movements_dialog()
        self._movements_modal_rows = list(rows or [])
        self._movements_modal_title = title
        self._movements_filter_key = ""
        tokens = self._theme_tokens()

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(490),
        )

        # ── Filter buttons row ──────────────────────────────────────────
        filter_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(6),
        )
        self._movements_filter_btns = {}
        for label, key in self.MOVEMENT_FILTERS:
            btn = MDRaisedButton(
                text=label,
                size_hint=(None, None),
                height=dp(34),
                width=dp(96),
                on_release=lambda _b, k=key, lbl=label: self._set_movements_filter(k, lbl),
            )
            self._movements_filter_btns[key] = btn
            filter_row.add_widget(btn)
        self._update_filter_btn_styles()

        self._movements_total_label = MDLabel(
            text=f"Total: {len(self._movements_modal_rows)} — selecione um filtro",
            theme_text_color="Secondary",
            valign="middle",
        )
        filter_row.add_widget(self._movements_total_label)
        content.add_widget(filter_row)

        action_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38),
            spacing=dp(8),
            padding=[0, 0, 0, dp(2)],
        )
        action_row.add_widget(
            MDLabel(
                text="As acoes aplicam-se apenas aos movimentos visiveis no filtro actual.",
                theme_text_color="Secondary",
                font_style="Caption",
                valign="middle",
            )
        )

        self._movements_delete_btn = MDRaisedButton(
            text="ELIMINAR VISIVEIS",
            size_hint=(None, None),
            size=(dp(166), dp(34)),
            disabled=True,
            md_bg_color=tokens.get("error", [0.78, 0.12, 0.12, 1]),
            text_color=tokens.get("on_error", [1, 1, 1, 1]),
            on_release=lambda _btn: self.confirm_delete_visible_movements(),
        )

        self._movements_print_btn = MDRaisedButton(
            text="IMPRIMIR PDF",
            size_hint=(None, None),
            size=(dp(132), dp(34)),
            disabled=not bool(self._movements_modal_rows),
            on_release=lambda _btn: self.print_movements_pdf(),
        )
        action_row.add_widget(self._movements_print_btn)
        action_row.add_widget(self._movements_delete_btn)
        content.add_widget(action_row)

        # ── Column header ───────────────────────────────────────────────
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(28),
            md_bg_color=tokens.get("primary", [0.15, 0.35, 0.65, 1]),
            padding=[dp(6), 0],
            spacing=dp(4),
        )
        header_titles = [
            ("ENTRADA", self.MOVEMENT_COL_HINTS[0], "center"),
            ("SAIDA", self.MOVEMENT_COL_HINTS[1], "center"),
            ("ATUAL", self.MOVEMENT_COL_HINTS[2], "center"),
            ("TIPO", self.MOVEMENT_COL_HINTS[3], "center"),
            ("PRODUTO", self.MOVEMENT_COL_HINTS[4], "left"),
            ("QTD", self.MOVEMENT_COL_HINTS[5], "center"),
            ("DIR", self.MOVEMENT_COL_HINTS[6], "center"),
            ("USUARIO", self.MOVEMENT_COL_HINTS[7], "right"),
            ("DEL", self.MOVEMENT_COL_HINTS[8], "center"),
        ]
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])
        for lbl, hint, align in header_titles:
            header.add_widget(
                MDLabel(
                    text=lbl,
                    size_hint_x=hint,
                    halign=align,
                    bold=True,
                    font_style="Caption",
                    theme_text_color="Custom",
                    text_color=on_primary,
                )
            )
        content.add_widget(header)

        body_scroll = ScrollView(do_scroll_x=False)
        body = MDGridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        body.bind(minimum_height=body.setter("height"))
        body_scroll.add_widget(body)
        self._movements_table_container = body
        content.add_widget(body_scroll)

        self._refresh_movements_modal_table()

        dialog = MDDialog(
            title=title,
            type="custom",
            content_cls=content,
            size_hint=(0.88, 0.84),
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda _btn: self._dismiss_movements_dialog())],
        )
        self._movements_dialog = dialog
        dialog.open()

    def _update_filter_btn_styles(self):
        """Highlight the active filter button, dim the rest."""
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.15, 0.35, 0.65, 1])
        surface = tokens.get("surface_alt", [0.93, 0.94, 0.96, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        for key, btn in self._movements_filter_btns.items():
            active = (key == self._movements_filter_key)
            btn.md_bg_color = primary if active else surface
            btn.text_color = on_primary if active else text_primary

    def _set_movements_filter(self, filter_key, filter_label):
        # ── Step 1: visual feedback is INSTANT (same frame) ──────────────
        self._movements_filter_key = filter_key
        self._update_filter_btn_styles()

        # ── Step 2: if rows already built → just toggle visibility ───────
        if self._movements_row_cache:
            self._apply_movements_filter_visibility()
            return

        # ── Step 3: rows not yet built → defer heavy work one frame ──────
        # The button is already highlighted; schedule the rest so the UI
        # can redraw before we block on the DB query or row construction.
        Clock.schedule_once(self._load_and_render_movements_deferred, 0)

    def _load_and_render_movements_deferred(self, _dt=None):
        """Called one frame after the filter button press so the UI redraws first."""
        rows = self._get_movements_for_modal(getattr(self, "_movements_modal_limit", 200))
        self._movements_modal_rows = list(rows or [])
        self._movements_row_cache = []
        self._movements_empty_label = None
        if self._movements_table_container:
            self._movements_table_container.clear_widgets()
        if self._movements_print_btn:
            self._movements_print_btn.disabled = not bool(self._movements_modal_rows)
        self._refresh_movements_modal_table()

    def _get_movements_for_modal(self, limit=200):
        limit = int(limit or 200)
        fresh = (perf_counter() - self._last_movements_loaded_at) < self.REFRESH_SECONDS
        if self.movements and fresh and int(self._last_movements_limit or 0) >= limit:
            return list(self.movements[:limit])
        return self.load_movements(limit=limit, update_table=False)

    def _refresh_movements_modal_table(self):
        if not self._movements_table_container:
            return
        table = self._movements_table_container

        # Cache already built — just toggle visibility, no reconstruction
        if self._movements_row_cache:
            if self._movements_filter_key:
                self._apply_movements_filter_visibility()
            else:
                if self._movements_total_label:
                    self._movements_total_label.text = f"Total: {len(self._movements_modal_rows)}"
            return

        self._stop_movements_render()
        self._movements_row_cache = []
        self._movements_empty_label = None
        table.clear_widgets()

        if not self._movements_modal_rows:
            hint_text = (
                "Selecione um filtro para ver os movimentos."
                if not self._movements_filter_key
                else "Sem movimentos para este filtro"
            )
            self._movements_empty_label = MDLabel(
                text=hint_text,
                theme_text_color="Secondary",
                halign="center",
                size_hint_y=None,
                height=dp(36),
            )
            table.add_widget(self._movements_empty_label)
            if self._movements_total_label:
                self._movements_total_label.text = "Total: 0"
            return

        # Render first batch immediately so rows appear fast,
        # then continue in subsequent frames for the rest
        self._movements_render_rows = list(self._movements_modal_rows)
        self._movements_render_index = 0
        self._render_next_movements_batch(0)   # first batch now
        if self._movements_render_index < len(self._movements_render_rows):
            self._movements_render_ev = Clock.schedule_interval(
                self._render_next_movements_batch, 0
            )

    def _stop_movements_render(self):
        if self._movements_render_ev:
            self._movements_render_ev.cancel()
            self._movements_render_ev = None

    def _render_next_movements_batch(self, _dt):
        if not self._movements_table_container:
            self._stop_movements_render()
            return False
        if self._movements_render_index >= len(self._movements_render_rows):
            self._stop_movements_render()
            # Final update of totals after all rows are rendered
            if self._movements_filter_key:
                self._apply_movements_filter_visibility()
            elif self._movements_total_label:
                self._movements_total_label.text = f"Total: {len(self._movements_modal_rows)}"
            return False

        start = self._movements_render_index
        end = min(start + self.MOVEMENTS_RENDER_BATCH_SIZE, len(self._movements_render_rows))
        self._populate_movements_container(
            self._movements_table_container,
            self._movements_render_rows[start:end],
            start_index=start,
        )
        self._movements_render_index = end

        # Apply filter visibility on each batch so filtered rows hide as they appear
        if self._movements_filter_key:
            self._apply_movements_filter_visibility()

        if self._movements_render_index >= len(self._movements_render_rows):
            self._stop_movements_render()
            if not self._movements_filter_key and self._movements_total_label:
                self._movements_total_label.text = f"Total: {len(self._movements_modal_rows)}"
            return False
        return True

    def _movement_matches_filter(self, direction, movement_type):
        key = (self._movements_filter_key or "ALL").upper()
        direction = str(direction or "").upper()
        movement_type = str(movement_type or "").upper()
        if key == "ALL":
            return True
        if key == "IN":
            return direction == "IN"
        if key == "OUT":
            return direction == "OUT"
        if key == "RESTOCK":
            return movement_type == "RESTOCK"
        if key == "LOSS":
            return movement_type in {"DAMAGE", "EXPIRED", "THEFT", "ADJUSTMENT"}
        return True

    def _apply_movements_filter_visibility(self):
        if not self._movements_table_container:
            return
        visible_count = 0
        for row in self._movements_row_cache:
            direction = getattr(row, "_movement_direction", "")
            movement_type = getattr(row, "_movement_type", "")
            show = self._movement_matches_filter(direction, movement_type)
            row.height = dp(34) if show else 0
            row.opacity = 1 if show else 0
            row.disabled = not show
            if show:
                visible_count += 1

        if self._movements_total_label:
            self._movements_total_label.text = (
                f"Total: {len(self._movements_modal_rows)} | Exibindo: {visible_count}"
            )

        # Enable/disable global delete button based on visible rows
        if self._movements_delete_btn:
            self._movements_delete_btn.disabled = (visible_count == 0)

        if visible_count == 0:
            if not self._movements_empty_label:
                self._movements_empty_label = MDLabel(
                    text="Sem movimentos para este filtro",
                    theme_text_color="Secondary",
                    halign="center",
                    size_hint_y=None,
                    height=dp(36),
                )
            if self._movements_empty_label.parent is None:
                self._movements_table_container.add_widget(self._movements_empty_label)
        else:
            if self._movements_empty_label and self._movements_empty_label.parent is self._movements_table_container:
                self._movements_table_container.remove_widget(self._movements_empty_label)

    def _get_movements_filter_label(self):
        for label, key in self.MOVEMENT_FILTERS:
            if key == self._movements_filter_key:
                return label
        return "TODOS"

    def _get_filtered_movement_rows(self):
        filtered_rows = []
        for raw in self._movements_modal_rows:
            normalized = self._normalize_movement_row(raw)
            direction = str(normalized[5] or "").upper()
            movement_type = str(normalized[6] or "").upper()
            if self._movement_matches_filter(direction, movement_type):
                filtered_rows.append(normalized)
        return filtered_rows

    def _prepare_movement_rows_for_pdf(self, rows):
        prepared = []
        for raw in rows or []:
            (
                _mid, _created_at, entry_date, exit_date, update_day, direction, movement_type,
                _product_id, product_name, qty, unit, _unit_cost, _total_cost, _stock_before,
                _stock_after, _reason, _note, created_by, _supplier, _invoice,
            ) = self._normalize_movement_row(raw)

            qty_val = self._to_float(qty)
            unit_label = unit or "UN"
            if str(unit_label).upper() == "UN" and float(qty_val).is_integer():
                qty_text = f"{int(qty_val)} UN"
            else:
                qty_text = f"{qty_val:.2f} {unit_label}"

            prepared.append(
                {
                    "entry_date": self._format_dt(entry_date, with_time=True),
                    "exit_date": self._format_dt(exit_date, with_time=True),
                    "update_day": self._format_update_day(update_day),
                    "movement_label": self._out_code_to_label.get(movement_type, movement_type or "-"),
                    "movement_code": str(movement_type or "").upper(),
                    "product_name": product_name or "-",
                    "qty_text": qty_text,
                    "direction": str(direction or "-").upper(),
                    "created_by": created_by or "-",
                }
            )
        return prepared

    def print_movements_pdf(self):
        """Gera e abre PDF de movimentos (sincrono — sem thread)."""
        if self._movement_pdf_busy:
            return

        filtered_rows = self._get_filtered_movement_rows()
        if not filtered_rows:
            self._show_dialog("Atencao", "Nao ha movimentos para imprimir com o filtro atual.")
            return

        title = self._movements_modal_title or getattr(self._movements_dialog, "title", "") or "Movimentos de Stock"
        filter_label = self._get_movements_filter_label()
        prepared_rows = self._prepare_movement_rows_for_pdf(filtered_rows)

        self._set_movements_print_busy(True)
        try:
            report = self._ensure_stock_movements_report()
            pdf_path = report.generate(
                prepared_rows,
                {
                    "title": title,
                    "filter_label": filter_label,
                    "record_count": len(prepared_rows),
                    "source_label": "Tela de reposicao de stock",
                },
            )
            self._set_movements_print_busy(False)
            try:
                printed = self._ensure_pdf_viewer().print_pdf(pdf_path)
                self._show_movements_pdf_success(pdf_path, printed=bool(printed))
            except Exception as exc:
                self._show_dialog("Erro", str(exc) or "Erro ao enviar PDF para impressao.")
        except Exception as exc:
            self._set_movements_print_busy(False)
            self._show_dialog("Erro", str(exc) or "Erro ao gerar PDF dos movimentos.")

    def _show_movements_pdf_success(self, pdf_path, printed=True):
        filename = str(pdf_path or "").split("\\")[-1].split("/")[-1]
        message = (
            f"PDF enviado para impressao:\n{filename}"
            if printed
            else f"PDF gerado com sucesso:\n{filename}"
        )
        dialog = MDDialog(
            title="Movimentos em PDF",
            text=message,
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda btn: dialog.dismiss()),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    on_release=lambda btn, path=pdf_path: [dialog.dismiss(), self._ensure_pdf_viewer().view_pdf(path)],
                ),
            ],
        )
        dialog.open()

    def _populate_movements_container(self, table, rows, start_index=0):
        tokens = self._theme_tokens()
        row_even = tokens.get("surface_alt", [0.97, 0.98, 0.99, 1])
        row_odd = tokens.get("card", [1, 1, 1, 1])
        text_primary = tokens.get("text_primary", [0.2, 0.2, 0.2, 1])
        text_secondary = tokens.get("text_secondary", [0.5, 0.5, 0.5, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])
        danger = tokens.get("danger", [0.85, 0.2, 0.2, 1])

        for idx, raw in enumerate(rows):
            (
                mid, _created_at, entry_date, exit_date, update_day, direction, movement_type,
                _product_id, product_name, qty, unit, _unit_cost, _total_cost, _stock_before,
                _stock_after, _reason, _note, created_by, _supplier, _invoice,
            ) = self._normalize_movement_row(raw)

            absolute_idx = start_index + idx
            bg = row_even if absolute_idx % 2 == 0 else row_odd
            row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(34),
                padding=[dp(6), 0],
                spacing=dp(4),
                md_bg_color=bg,
            )

            qty_val = self._to_float(qty)
            if str(unit or "UN").upper() == "UN" and float(qty_val).is_integer():
                qty_text = f"{int(qty_val)} UN"
            else:
                qty_text = f"{qty_val:.2f} {unit or 'UN'}"

            direction_color = success if direction == "IN" else danger
            movement_label = self._out_code_to_label.get(movement_type, movement_type or "-")

            self._add_cell(row, self._format_dt(entry_date, with_time=True), self.MOVEMENT_COL_HINTS[0], "center", text_secondary)
            self._add_cell(row, self._format_dt(exit_date, with_time=True), self.MOVEMENT_COL_HINTS[1], "center", text_secondary)
            self._add_cell(row, self._format_update_day(update_day), self.MOVEMENT_COL_HINTS[2], "center", text_secondary)
            self._add_cell(row, movement_label, self.MOVEMENT_COL_HINTS[3], "center", direction_color, bold=True)
            self._add_cell(row, product_name or "-", self.MOVEMENT_COL_HINTS[4], "left", text_primary, shorten=True)
            self._add_cell(row, qty_text, self.MOVEMENT_COL_HINTS[5], "center", text_secondary)
            self._add_cell(row, direction or "-", self.MOVEMENT_COL_HINTS[6], "center", direction_color, bold=True)
            self._add_cell(row, created_by or "-", self.MOVEMENT_COL_HINTS[7], "right", text_secondary, shorten=True)

            # ── Delete button ───────────────────────────────────────────
            del_cell = MDBoxLayout(
                size_hint_x=self.MOVEMENT_COL_HINTS[8],
                size_hint_y=None,
                height=dp(34),
                padding=[dp(2), dp(3)],
            )
            del_btn = MDRaisedButton(
                text="X",
                md_bg_color=[0.75, 0.1, 0.1, 1],
                text_color=[1, 1, 1, 1],
                size_hint=(1, None),
                height=dp(26),
                on_release=lambda _b, r=row, m=mid, pn=product_name: self.confirm_delete_movement(m, pn, r),
            )
            del_cell.add_widget(del_btn)
            row.add_widget(del_cell)

            row._movement_direction = direction
            row._movement_type = movement_type
            row._movement_id = mid
            row._movement_raw = raw

            table.add_widget(row)
            self._movements_row_cache.append(row)

    # ---------- Delete movements ----------

    def confirm_delete_movement(self, movement_id, product_name, row_widget):
        """Diálogo de confirmação para eliminar um único movimento."""
        if movement_id is None:
            self._show_dialog("Erro", "Este movimento não tem ID e não pode ser eliminado.")
            return
        product_label = str(product_name or "-")
        dialog_ref = {}

        def dismiss_dialog(_button):
            dialog_ref["dialog"].dismiss()

        def delete_movement(_button, mid=movement_id, row=row_widget):
            dialog_ref["dialog"].dismiss()
            self._do_delete_movement(mid, row)

        dialog = MDDialog(
            title="Eliminar Movimento",
            text=f"Tem a certeza que quer eliminar permanentemente o movimento de\n[b]{product_label}[/b]?\n\nEsta acção não pode ser desfeita.",
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=dismiss_dialog),
                MDRaisedButton(
                    text="ELIMINAR",
                    md_bg_color=[0.75, 0.1, 0.1, 1],
                    text_color=[1, 1, 1, 1],
                    on_release=delete_movement,
                ),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open()

    def _do_delete_movement(self, movement_id, row_widget=None):
        """Elimina um movimento da BD e remove a sua linha do modal."""
        try:
            app = App.get_running_app()
            deleted_by = getattr(app, "current_user", None) or "admin"
            if not self.db.delete_stock_movement(movement_id, deleted_by=deleted_by):
                raise RuntimeError("Movimento nao encontrado ou ja eliminado.")
        except Exception as exc:
            self._show_dialog("Erro", f"Falha ao eliminar movimento: {exc}")
            return

        # Remove from in-memory lists
        self._movements_modal_rows = [
            r for r in self._movements_modal_rows
            if self._normalize_movement_row(r)[0] != movement_id
        ]
        self.movements = [
            r for r in self.movements
            if self._normalize_movement_row(r)[0] != movement_id
        ]

        # Hide and remove the row widget immediately — no full rebuild
        if row_widget is not None and row_widget in self._movements_row_cache:
            self._movements_row_cache.remove(row_widget)
            if row_widget.parent is self._movements_table_container:
                self._movements_table_container.remove_widget(row_widget)

        self._apply_movements_filter_visibility()
        self.show_feedback("Movimento eliminado com sucesso.", "success")

    def confirm_delete_visible_movements(self):
        """Diálogo de confirmação para eliminar todos os movimentos visíveis."""
        visible_rows = [
            r for r in self._movements_row_cache
            if self._movement_matches_filter(
                getattr(r, "_movement_direction", ""),
                getattr(r, "_movement_type", ""),
            ) and getattr(r, "_movement_id", None) is not None
        ]
        count = len(visible_rows)
        if count == 0:
            self._show_dialog("Aviso", "Não há movimentos visíveis para eliminar.")
            return

        filter_label = self._get_movements_filter_label()
        dialog_ref = {}

        def dismiss_dialog(_button):
            dialog_ref["dialog"].dismiss()

        def delete_visible_rows(_button, rows=list(visible_rows)):
            dialog_ref["dialog"].dismiss()
            self._do_delete_visible_movements(rows)

        dialog = MDDialog(
            title="Eliminar Movimentos Visíveis",
            text=(
                f"Vai eliminar permanentemente [b]{count} movimento(s)[/b] "
                f"com o filtro '[b]{filter_label}[/b]'.\n\nEsta acção não pode ser desfeita."
            ),
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=dismiss_dialog),
                MDRaisedButton(
                    text=f"ELIMINAR {count}",
                    md_bg_color=[0.75, 0.1, 0.1, 1],
                    text_color=[1, 1, 1, 1],
                    on_release=delete_visible_rows,
                ),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open()

    def _do_delete_visible_movements(self, visible_rows):
        """Elimina em lote os movimentos visíveis da BD e actualiza o modal."""
        errors = []
        deleted_ids = set()
        for row_widget in visible_rows:
            mid = getattr(row_widget, "_movement_id", None)
            if mid is None:
                continue
            try:
                app = App.get_running_app()
                deleted_by = getattr(app, "current_user", None) or "admin"
                if not self.db.delete_stock_movement(mid, deleted_by=deleted_by):
                    raise RuntimeError("Movimento nao encontrado ou ja eliminado.")
                deleted_ids.add(mid)
            except Exception as exc:
                errors.append(str(exc))

        # Remove from in-memory lists
        self._movements_modal_rows = [
            r for r in self._movements_modal_rows
            if self._normalize_movement_row(r)[0] not in deleted_ids
        ]
        self.movements = [
            r for r in self.movements
            if self._normalize_movement_row(r)[0] not in deleted_ids
        ]

        # Remove row widgets immediately
        for row_widget in visible_rows:
            if getattr(row_widget, "_movement_id", None) in deleted_ids:
                if row_widget in self._movements_row_cache:
                    self._movements_row_cache.remove(row_widget)
                if row_widget.parent is self._movements_table_container:
                    self._movements_table_container.remove_widget(row_widget)

        self._apply_movements_filter_visibility()

        if errors:
            self._show_dialog(
                "Concluído com erros",
                f"{len(deleted_ids)} eliminado(s). {len(errors)} erro(s): {'; '.join(errors[:3])}",
            )
        else:
            self.show_feedback(f"{len(deleted_ids)} movimento(s) eliminado(s) com sucesso.", "success")

    # ---------- Submit ----------
    def register_movement(self):
        if self._movement_submitting:
            return

        if not self.selected_product:
            self._show_dialog("Validacao", "Selecione um produto antes de registar movimento.")
            return

        (
            pid, name, stock, _sale_price, _cost, _barcode, is_weight,
            _exp, _status, _avg, _days, _last_update,
        ) = self._unpack_product(self.selected_product)

        qty_text = self.ids.qty_input.text.strip()
        try:
            qty = float(qty_text)
        except Exception:
            self._show_dialog("Erro", "Quantidade invalida.")
            return

        if qty <= 0:
            self._show_dialog("Erro", "Quantidade deve ser maior que zero.")
            return
        if not is_weight and not float(qty).is_integer():
            self._show_dialog("Erro", "Para produtos por unidade, a quantidade deve ser inteira.")
            return

        app = App.get_running_app()
        user = getattr(app, "current_user", None)
        role = getattr(app, "current_role", "admin")
        note = self.ids.note_input.text.strip()
        now = datetime.now()
        is_in = self.current_mode == "IN"

        if is_in:
            try:
                unit_cost = float(self.ids.unit_cost_input.text.strip())
            except Exception:
                self._show_dialog("Erro", "Custo unitario invalido.")
                return
            if unit_cost <= 0:
                self._show_dialog("Erro", "Custo unitario deve ser maior que zero.")
                return
            try:
                expiry_iso = self._parse_expiry_input(self.ids.expiry_input.text)
            except ValueError as exc:
                self._show_dialog("Erro", str(exc))
                return
            supplier = self.ids.supplier_input.text.strip() or None
            invoice = self.ids.invoice_input.text.strip() or None
        else:
            unit_cost = None
            expiry_iso = None
            supplier = None
            invoice = None

        stock_val = self._to_float(stock)
        movement_label = self.ids.movement_type_field.text.strip() or "AJUSTE"
        movement_code = self._out_label_to_code.get(movement_label, movement_label.upper())

        if (not is_in) and qty > stock_val:
            self._show_dialog("Erro", f"Quantidade maior que stock disponivel ({stock_val:.2f}).")
            return

        self._set_movement_busy(True)
        try:
            if is_in:
                movement_id = self.db.restock_product(
                    pid, qty, unit_cost,
                    expiry_date=expiry_iso,
                    reason="Reposicao de stock",
                    note=note,
                    created_by=user,
                    created_role=role,
                    supplier_name=supplier,
                    invoice_number=invoice,
                )
                result = {"ok": bool(movement_id), "direction": "IN",
                          "message": "Falha ao registar entrada de stock." if not movement_id else ""}
            else:
                movement_id = self.db.record_stock_movement(
                    pid, movement_code, qty, "OUT",
                    reason="Saida manual de stock",
                    note=note,
                    created_by=user,
                    created_role=role,
                )
                result = {"ok": bool(movement_id), "direction": "OUT",
                          "message": "Falha ao registar saida de stock." if not movement_id else ""}
        except Exception as exc:
            result = {"ok": False, "message": str(exc)}

        self._set_movement_busy(False)

        if not result.get("ok"):
            self._show_dialog("Erro", result.get("message") or "Falha ao registar movimento.")
            return

        if result.get("direction") == "IN":
            self.ids.entry_date_field.text = now.strftime("%d/%m/%Y %H:%M")
            self.ids.exit_date_field.text = "--"
            self.show_feedback(f"Entrada registada para {name}.", "success")
        else:
            self.ids.entry_date_field.text = "--"
            self.ids.exit_date_field.text = now.strftime("%d/%m/%Y %H:%M")
            self.show_feedback(f"Saida registada para {name}.", "success")

        self.ids.update_day_field.text = now.strftime("%d/%m/%Y")
        self.ids.qty_input.text = "1"
        self.ids.note_input.text = ""
        self.force_refresh()
        Clock.schedule_once(lambda dt: self._focus_field("qty_input", select_all=True), 0)

    def clear_form(self):
        self.selected_product = None
        self.ids.selected_product_label.text = "Produto: --"
        self.ids.selected_stock_label.text = "Stock atual: --"
        self.ids.search_input.text = ""
        self.ids.qty_input.text = "1"
        self.ids.note_input.text = ""
        self.ids.expiry_input.text = ""
        self.ids.unit_cost_input.text = ""
        self.ids.supplier_input.text = ""
        self.ids.invoice_input.text = ""
        self.ids.movement_type_field.text = "AJUSTE"
        self._set_now_markers()
        self._apply_search_now()
        self._sync_stock_form_modal_from_hidden()
        Clock.schedule_once(lambda dt: self._focus_field("search_input"), 0)

    def _set_now_markers(self):
        if not self.ids:
            return
        self.ids.entry_date_field.text = "--"
        self.ids.exit_date_field.text = "--"
        self.ids.update_day_field.text = datetime.now().strftime("%d/%m/%Y")
        self._sync_stock_form_modal_from_hidden()

    def _focus_field(self, field_id, select_all=False):
        if not hasattr(self, "ids"):
            return False
        field = self.ids.get(field_id)
        if field is None or getattr(field, "disabled", False):
            return False
        field.focus = True
        if select_all and hasattr(field, "select_all"):
            Clock.schedule_once(lambda dt, widget=field: widget.select_all(), 0)
        return True

    def show_feedback(self, message, tone="info"):
        tokens = self._theme_tokens()
        tones = {
            "success": tokens.get("success", [0.2, 0.7, 0.3, 1]),
            "warning": tokens.get("warning", [0.9, 0.7, 0.1, 1]),
            "danger": tokens.get("danger", [0.9, 0.2, 0.2, 1]),
            "info": tokens.get("info", [0.2, 0.5, 0.9, 1]),
        }
        MDSnackbar(
            MDLabel(
                text=str(message),
                theme_text_color="Custom",
                text_color=[1, 1, 1, 1],
            ),
            md_bg_color=tones.get(tone, tones["info"]),
            pos=(dp(12), dp(12)),
            size_hint_x=0.58,
        ).open()

    # ---------- Helpers ----------
    def _show_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: dialog.dismiss())],
        )
        dialog.open()

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except Exception:
            return 0.0

    def _normalize_product_row(self, row):
        if not row:
            return (None, "", 0.0, 0.0, 0.0, "", 0, None, "ATIVO", 0.0, None, None)
        row = tuple(row)
        if len(row) >= 12:
            return row[:12]
        if len(row) == 11:
            return tuple(row) + (None,)
        if len(row) == 9:
            return tuple(row) + (0.0, None, None)
        if len(row) < 9:
            pad = (None,) * (9 - len(row))
            base = tuple(row) + pad
            return base + (0.0, None, None)
        return tuple(row) + (None, None)

    def _unpack_product(self, row):
        return self._normalize_product_row(row)

    def _build_expiry_alerts(self, rows):
        alerts = {}
        for raw in rows or []:
            pid, _name, _stock, _price, _cost, _barcode, _is_weight, exp, _status, _avg, _days, _last = (
                self._unpack_product(raw)
            )
            if pid is None:
                continue
            alerts[pid] = evaluate_expiry_alert(exp)
        return alerts

    def _get_expiry_alert(self, row):
        pid, _name, _stock, _price, _cost, _barcode, _is_weight, exp, _status, _avg, _days, _last = (
            self._unpack_product(row)
        )
        if pid is None:
            return evaluate_expiry_alert(exp)
        alert = self._expiry_alerts_by_id.get(pid)
        if alert is None:
            alert = evaluate_expiry_alert(exp)
            self._expiry_alerts_by_id[pid] = alert
        return alert

    def _normalize_movement_row(self, row):
        if not row:
            return (
                None, None, None, None, None, None, None, None, None,
                0.0, "UN", 0.0, 0.0, None, None, "", "", "", None, None,
            )
        row = tuple(row)
        if len(row) >= 20:
            return row[:20]
        return row + (None,) * (20 - len(row))

    @staticmethod
    def _format_dt(value, with_time=True):
        if not value:
            return "--"
        raw = str(value)
        fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
        parsed = None
        for fmt in fmts:
            try:
                parsed = datetime.strptime(raw[:19], fmt)
                break
            except Exception:
                continue
        if parsed is None:
            return raw[:16] if with_time else raw[:10]
        return parsed.strftime("%d/%m/%Y %H:%M") if with_time else parsed.strftime("%d/%m/%Y")

    @staticmethod
    def _format_update_day(value):
        if not value:
            return "--"
        raw = str(value)
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(raw[:19], fmt)
                return dt.strftime("%d/%m/%Y")
            except Exception:
                continue
        return raw[:10]

    @staticmethod
    def _format_expiry_input(value):
        if not value:
            return ""
        raw = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(raw[:19], fmt).strftime("%d/%m/%Y")
            except Exception:
                continue
        return raw

    @staticmethod
    def _parse_expiry_input(value):
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        raise ValueError("Data de validade invalida. Use DD/MM/AAAA.")
