from datetime import datetime
import time

import cv2
import numpy as np
from pyzbar.pyzbar import decode

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.animation import Animation
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton

from database.database import Database


Builder.load_file("utils/restock_screen.kv")


class RestockScreen(MDScreen):
    def __init__(self, db=None, **kwargs):
        super().__init__(**kwargs)
        self.db = db or Database()
        self.products = []
        self.selected_product = None
        self.current_step = 1
        # Scanner
        self.scanning = False
        self.camera = None
        self.current_camera_index = 0
        self.last_scan_code = None
        self.last_scan_time = 0
        Clock.schedule_once(self.init_screen, 0.1)

    def init_screen(self, dt):
        self.load_products()
        self.set_scanner_status("Pronto para escanear")
        self.update_ui_state()

    def on_enter(self):
        app = App.get_running_app()
        role = getattr(app, "current_role", None)
        if role != "admin":
            self.show_dialog("Acesso Negado", "Apenas admin pode repor stock.")
            if self.manager:
                self.manager.current = "manager"
            return
        self.load_products()
        self.clear_form()
        self.set_scanner_status("Pronto para escanear")
        self.current_step = 1
        self.update_ui_state()

    def on_leave(self):
        self.stop_scanner()

    def go_back(self):
        if self.manager:
            self.manager.current = "admin"

    def open_restock_history(self, *args):
        if not self.manager:
            return
        self.manager.current = "restock_history"
        if "restock_history" in self.manager.screen_names:
            screen = self.manager.get_screen("restock_history")
            Clock.schedule_once(lambda dt: screen.load_restock_table(), 0.1)

    # ---------- UI State ----------
    def update_ui_state(self):
        if "search_card" not in self.ids:
            return
        search_h, form_h, selected_h = self._calc_card_heights()
        if self.current_step == 1:
            self._show_card(self.ids.search_card, search_h)
            self._hide_card(self.ids.restock_form_card)
            self._hide_card(self.ids.selected_product_card)
            self.ids.step1_icon.icon = "numeric-1-circle"
            self.ids.step1_label.bold = True
            self.ids.step1_label.theme_text_color = "Primary"
            self.ids.step2_icon.icon = "numeric-2-circle-outline"
            self.ids.step2_label.bold = False
            self.ids.step2_label.theme_text_color = "Hint"
        else:
            self._hide_card(self.ids.search_card)
            self._show_card(self.ids.restock_form_card, form_h)
            self._show_card(self.ids.selected_product_card, selected_h)
            self.ids.step1_icon.icon = "check-circle"
            self.ids.step1_label.bold = False
            self.ids.step1_label.theme_text_color = "Secondary"
            self.ids.step2_icon.icon = "numeric-2-circle"
            self.ids.step2_label.bold = True
            self.ids.step2_label.theme_text_color = "Primary"

    def _show_card(self, card, height):
        anim = Animation(height=height, opacity=1, duration=0.25, t="out_cubic")
        anim.start(card)

    def _hide_card(self, card):
        anim = Animation(height=0, opacity=0, duration=0.2, t="out_cubic")
        anim.start(card)

    def _calc_card_heights(self):
        base = max(self.height, dp(600))
        search_h = max(dp(360), base * 0.55)
        form_h = max(dp(240), base * 0.32)
        selected_h = dp(90)
        return search_h, form_h, selected_h

    def on_size(self, *args):
        Clock.unschedule(self._deferred_layout)
        Clock.schedule_once(self._deferred_layout, 0.05)

    def _deferred_layout(self, dt):
        self.update_ui_state()

    # ---------- Scanner ----------
    def set_scanner_status(self, text, color=None):
        if "scanner_status" in self.ids:
            self.ids.scanner_status.text = text
            if color is not None:
                self.ids.scanner_status.text_color = color

    def toggle_scanner(self):
        if self.scanning:
            self.stop_scanner()
        else:
            self.start_scanner()

    def start_scanner(self):
        self.scanning = True
        if "scan_btn" in self.ids:
            self.ids.scan_btn.icon = "barcode-off"
        self.set_scanner_status("Iniciando...")
        Clock.schedule_once(self.open_camera, 0.1)

    def stop_scanner(self):
        self.scanning = False
        if "scan_btn" in self.ids:
            self.ids.scan_btn.icon = "barcode-scan"
        self.set_scanner_status("Scanner parado")
        Clock.unschedule(self.scan_frame)
        self.close_camera()

    def open_camera(self, dt):
        try:
            self.close_camera()
            self.camera = cv2.VideoCapture(self.current_camera_index)
            if self.camera.isOpened():
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.last_scan_code = None
                self.last_scan_time = 0
                self.set_scanner_status("Escaneando...")
                Clock.schedule_interval(self.scan_frame, 1 / 20)
            else:
                self.set_scanner_status("Camera nao encontrada")
                self.stop_scanner()
        except Exception:
            self.set_scanner_status("Erro na camera")
            self.stop_scanner()

    def close_camera(self):
        if self.camera:
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None
        if "camera_image" in self.ids:
            self.ids.camera_image.texture = None

    def scan_frame(self, dt):
        if not self.scanning or not self.camera:
            return
        try:
            ret, frame = self.camera.read()
            if not ret:
                return
            frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
            codes = decode(frame)
            if codes:
                self.process_barcode(codes[0])
            self.show_frame(frame)
        except Exception:
            pass

    def process_barcode(self, code):
        try:
            barcode = code.data.decode("utf-8").strip()
            now = time.time()
            if barcode == self.last_scan_code and (now - self.last_scan_time) < 2:
                return
            self.last_scan_code = barcode
            self.last_scan_time = now
            product = self.find_product_by_barcode(barcode)
            if product:
                self.ids.search_input.text = barcode
                self.select_product(product)
                self.set_scanner_status("Produto encontrado")
                self.stop_scanner()
            else:
                self.set_scanner_status("Produto nao encontrado")
        except Exception:
            pass

    def show_frame(self, frame):
        try:
            buf = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(
                size=(frame.shape[1], frame.shape[0]),
                colorfmt="bgr",
            )
            texture.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
            self.ids.camera_image.texture = texture
        except Exception:
            pass

    def switch_camera(self):
        was_scanning = self.scanning
        if was_scanning:
            self.stop_scanner()
        self.current_camera_index = (self.current_camera_index + 1) % 4
        if was_scanning:
            Clock.schedule_once(lambda dt: self.start_scanner(), 0.1)

    # ---------- Produtos ----------
    def load_products(self):
        try:
            self.db.cursor.execute(
                """
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status
                FROM products
                """
            )
            self.products = self.db.cursor.fetchall() or []
            self.show_products(self.products)
        except Exception as e:
            print(f"Erro ao carregar produtos: {e}")
            self.products = []

    def show_products(self, products):
        if "products_list" not in self.ids:
            return
        self.ids.products_list.clear_widgets()

        if not products:
            empty = TwoLineListItem(
                text="Nenhum produto disponível",
                secondary_text="Sem resultados para este filtro",
            )
            self.ids.products_list.add_widget(empty)
            return

        for p in products:
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            unit = "KG" if is_weight else "UN"

            def on_item_click(instance, product=p):
                self.select_product(product)

            item = TwoLineListItem(
                text=name,
                secondary_text=f"Stock: {stock:.1f} {unit} • Custo: {float(cost or 0):.2f} MZN",
            )
            item.bind(on_release=on_item_click)
            self.ids.products_list.add_widget(item)

    def on_search(self, text):
        query = (text or "").strip().lower()
        if not query:
            self.show_products(self.products)
            return

        filtered = []
        for p in self.products:
            if len(p) < 9:
                continue
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            if query in search_in_id or query in search_in_name or query in search_in_barcode:
                filtered.append(p)
        self.show_products(filtered)

    def on_search_enter(self):
        query = self.ids.search_input.text.strip().lower()
        if not query:
            return
        filtered = []
        for p in self.products:
            if len(p) < 9:
                continue
            pid, name, stock, price, cost, barcode, is_weight, exp, status = p
            search_in_id = str(pid).lower()
            search_in_name = (name or "").lower()
            search_in_barcode = str(barcode).lower() if barcode else ""
            if query in search_in_id or query in search_in_name or query in search_in_barcode:
                filtered.append(p)
        if len(filtered) == 1:
            self.select_product(filtered[0])
        elif len(filtered) > 1:
            self.show_dialog("Busca", f"Encontrados {len(filtered)} produtos. Clique em um ou refine a busca.")
        else:
            self.show_dialog("Busca", "Nenhum produto encontrado.")

    def find_product_by_barcode(self, barcode):
        for p in self.products:
            if len(p) > 5 and p[5] and str(p[5]).strip() == str(barcode).strip():
                return p
        return None

    def select_product(self, product):
        self.selected_product = product
        pid, name, stock, price, cost, barcode, is_weight, exp, status = product
        unit = "KG" if is_weight else "UN"
        self.ids.selected_name.text = name
        self.ids.selected_stock.text = f"Stock: {stock:.1f} {unit}"
        self.ids.selected_cost.text = f"Custo atual: {float(cost or 0):.2f} MZN"
        self.ids.selected_price.text = f"Preço venda: {float(price or 0):.2f} MZN"
        self.ids.qty_input.text = "1"
        self.ids.qty_input.input_filter = "float" if is_weight else "int"
        self.ids.cost_input.text = f"{float(cost or 0):.2f}"
        self.current_step = 2
        self.update_ui_state()

    def clear_selection(self):
        self.selected_product = None
        self.ids.selected_name.text = "Produto Selecionado"
        self.ids.selected_stock.text = "Stock: --"
        self.ids.selected_cost.text = "Custo atual: --"
        self.ids.selected_price.text = "Preco venda: --"
        self.ids.qty_input.text = ""
        self.ids.cost_input.text = ""
        self.current_step = 1
        self.update_ui_state()

    # ---------- Reposição ----------
    def register_restock(self):
        if not self.selected_product:
            self.show_dialog("Erro", "Nenhum produto selecionado")
            return

        pid, name, stock, price, cost, barcode, is_weight, exp, status = self.selected_product

        try:
            qty = float(self.ids.qty_input.text.strip())
        except Exception:
            self.show_dialog("Erro", "Quantidade inválida")
            return

        if not is_weight and not float(qty).is_integer():
            self.show_dialog("Erro", "Quantidade deve ser inteira para produtos por unidade")
            return
        if qty <= 0:
            self.show_dialog("Erro", "Quantidade deve ser maior que zero")
            return

        try:
            unit_cost = float(self.ids.cost_input.text.strip())
        except Exception:
            self.show_dialog("Erro", "Custo unitário inválido")
            return
        if unit_cost <= 0:
            self.show_dialog("Erro", "Custo unitário deve ser maior que zero")
            return

        note = self.ids.note_input.text.strip()

        app = App.get_running_app()
        user = getattr(app, "current_user", None)
        role = getattr(app, "current_role", "admin")

        movement_id = self.db.restock_product(
            pid,
            qty,
            unit_cost,
            reason="Reposição de stock",
            note=note,
            created_by=user,
            created_role=role,
        )
        if movement_id:
            if user:
                self.db.log_action(user, role, "RESTOCK", f"{name} | {qty}")
            self.show_dialog("Sucesso", "Reposição registrada com sucesso!")
            self.clear_form()
            self.load_products()
        else:
            self.show_dialog("Erro", "Falha ao registrar reposição")

    def clear_form(self):
        self.selected_product = None
        self.ids.selected_name.text = "Produto Selecionado"
        self.ids.selected_stock.text = "Stock: --"
        self.ids.selected_cost.text = "Custo atual: --"
        self.ids.selected_price.text = "Preço venda: --"
        self.ids.qty_input.text = ""
        self.ids.cost_input.text = ""
        self.ids.note_input.text = ""
        self.ids.search_input.text = ""
        self.current_step = 1
        self.update_ui_state()

    def show_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda x: dialog.dismiss())],
        )
        dialog.open()
