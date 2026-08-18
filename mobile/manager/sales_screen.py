"""POS tactil e historico agrupado para o Manager Mobile.

Esta tela nao importa o POS desktop: assim o APK fica livre de bibliotecas
Windows, OpenCV/ZBar e impressao termica. Toda escrita e feita pela API.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from threading import Thread
from uuid import uuid4

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    DictProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from mobile.manager.runtime import get_mobile_terminal_id
from utils.business.sales_transactions import (
    REFUND_WINDOW_MINUTES,
    group_sale_records,
    refund_window_status,
)


KV_PATH = Path(__file__).with_name("sales_screen.kv")
try:
    Builder.unload_file(str(KV_PATH))
except Exception:
    pass
Builder.load_file(str(KV_PATH))


def _number(value, fallback=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(fallback)


def _integer(value, fallback=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(fallback)


def _truth(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim"}


def _money(value) -> str:
    return f"{_number(value):,.2f}".replace(",", " ") + " MT"


def _quantity(value, weight=False) -> str:
    number = _number(value)
    if weight or not number.is_integer():
        return f"{number:.3f}".rstrip("0").rstrip(".") + (" kg" if weight else "")
    return str(int(number))


def _parse_amount(value) -> float:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    return max(0.0, _number(text))


def _catalog_key(product: dict) -> str:
    barcode = str(product.get("barcode") or "").strip().lower()
    if barcode:
        return f"bc:{barcode}"
    description = " ".join(str(product.get("name") or "").split()).lower()
    price = _number(product.get("price"))
    is_weight = 1 if product.get("is_weight") else 0
    units = _integer(product.get("units_per_package"))
    pack = 1 if product.get("allow_pack_sale") else 0
    vat = str(product.get("vat_rule_code") or "STANDARD").strip().upper()
    return f"desc:{description}|w:{is_weight}|p:{price:.4f}|u:{units}|a:{pack}|v:{vat}"


def _product_from_row(row) -> dict | None:
    """Normaliza listas JSON da API e tuplos SQLite sem expor a interface."""
    if isinstance(row, dict):
        product = {
            "id": _integer(row.get("id")),
            "name": str(row.get("description") or row.get("name") or "Produto").strip(),
            "stock": _number(row.get("stock", row.get("existing_stock"))),
            "price": _number(row.get("sale_price", row.get("price"))),
            "barcode": row.get("barcode"),
            "is_weight": _truth(row.get("is_sold_by_weight", row.get("is_weight"))),
            "expiry_date": row.get("expiry_date"),
            "status": row.get("status"),
            "units_per_package": _integer(row.get("units_per_package")),
            "allow_pack_sale": _truth(row.get("allow_pack_sale")),
            "vat_rule_code": str(row.get("vat_rule_code") or "STANDARD").strip().upper(),
            "catalog_key": str(row.get("catalog_key") or "").strip().lower(),
            "lot_count": max(1, _integer(row.get("lot_count"), 1)),
        }
    elif isinstance(row, (list, tuple)) and len(row) >= 4:
        product = {
            "id": _integer(row[0]),
            "name": str(row[1] or "Produto").strip(),
            "stock": _number(row[2]),
            "price": _number(row[3]),
            "barcode": row[4] if len(row) > 4 else None,
            "is_weight": _truth(row[5]) if len(row) > 5 else False,
            "expiry_date": row[6] if len(row) > 6 else None,
            "status": row[7] if len(row) > 7 else None,
            "units_per_package": _integer(row[8]) if len(row) > 8 else 0,
            "allow_pack_sale": _truth(row[9]) if len(row) > 9 else False,
            "vat_rule_code": str(row[10] or "STANDARD").strip().upper() if len(row) > 10 else "STANDARD",
            "catalog_key": str(row[11] or "").strip().lower() if len(row) > 11 else "",
            "lot_count": max(1, _integer(row[12], 1)) if len(row) > 12 else 1,
        }
    else:
        return None

    if product["id"] <= 0 or not product["name"]:
        return None
    product["catalog_key"] = product["catalog_key"] or _catalog_key(product)
    return product


def _aggregate_lots(rows) -> list[dict]:
    grouped: OrderedDict[str, dict] = OrderedDict()
    for row in rows or []:
        product = _product_from_row(row)
        if product is None:
            continue
        key = product["catalog_key"]
        if key not in grouped:
            grouped[key] = dict(product)
            continue
        grouped[key]["stock"] += product["stock"]
        grouped[key]["lot_count"] += 1
    return list(grouped.values())


class MobileManagerSalesScreen(MDScreen):
    """Venda, pagamento, caixa e estorno de dez minutos num unico ecran."""

    db = ObjectProperty(None, allownone=True)
    active_tab = StringProperty("catalog")
    products = ListProperty([])
    cart_items = ListProperty([])
    transactions = ListProperty([])
    search_text = StringProperty("")
    payment_method = StringProperty("cash")
    discount_text = StringProperty("")
    paid_amount_text = StringProperty("")
    subtotal_amount = NumericProperty(0.0)
    discount_amount = NumericProperty(0.0)
    total_amount = NumericProperty(0.0)
    change_amount = NumericProperty(0.0)
    cart_count = NumericProperty(0)
    cash_session = DictProperty({})
    products_loading = BooleanProperty(False)
    history_loading = BooleanProperty(False)
    sale_in_progress = BooleanProperty(False)
    cash_operation_in_progress = BooleanProperty(False)
    status_message = StringProperty("")

    PAYMENT_OPTIONS = (
        ("cash", "Dinheiro"),
        ("card", "Cartao"),
        ("mobile", "M-Pesa"),
        ("emola", "E-MOLA"),
    )

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        # O Kivy pode disparar on_kv_post durante super().__init__(). Estes
        # campos precisam existir antes da primeira renderizacao da tela.
        self._products_token = 0
        self._history_token = 0
        self._render_event = None
        self._terminal_id = None
        self._payment_subtotal_label = None
        self._payment_discount_label = None
        self._payment_total_label = None
        self._payment_change_label = None
        self._pending_sale = None
        super().__init__(**kwargs)
        self.db = db

    def on_kv_post(self, *args):
        self._schedule_render()

    def on_pre_enter(self, *args):
        self._activate_api_user()
        self._refresh_totals()
        if not self.products and not self.products_loading:
            self.load_products()
        if self.active_tab == "payment":
            self.refresh_cash_session()
        self._schedule_render()

    def on_size(self, *args):
        if self.active_tab in {"payment", "history"}:
            self._schedule_render()

    def set_database(self, db):
        self.db = db
        self.products = []
        self.transactions = []
        self.cash_session = {}
        self._activate_api_user()

    def _app(self):
        return App.get_running_app()

    def _current_user(self) -> str:
        app = self._app()
        return str(getattr(app, "current_user", "") or "").strip()

    def _current_role(self) -> str:
        app = self._app()
        return str(getattr(app, "current_role", "") or "manager").strip() or "manager"

    def _activate_api_user(self):
        setter = getattr(self.db, "set_active_user", None)
        if callable(setter):
            try:
                setter(self._current_user(), self._current_role())
            except Exception:
                pass

    def _get_terminal_id(self) -> str:
        if not self._terminal_id:
            self._terminal_id = get_mobile_terminal_id()
        return self._terminal_id

    def _schedule_render(self):
        if self._render_event is not None:
            return
        self._render_event = Clock.schedule_once(self._render_current_tab, 0)

    def _render_current_tab(self, *_args):
        self._render_event = None
        container = self.ids.get("page_container") if getattr(self, "ids", None) else None
        if container is None:
            return
        container.clear_widgets()
        if self.active_tab == "catalog":
            container.add_widget(self._build_catalog_page())
        elif self.active_tab == "cart":
            container.add_widget(self._build_cart_page())
        elif self.active_tab == "payment":
            container.add_widget(self._build_payment_page())
        else:
            container.add_widget(self._build_history_page())

    def _scroll_body(self):
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        body = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(2), dp(2), dp(2), dp(14)],
            size_hint_y=None,
        )
        body.bind(minimum_height=body.setter("height"))
        scroll.add_widget(body)
        return scroll, body

    def _label(self, text, *, height=28, bold=False, color=None, font_style=None, halign="left"):
        label = MDLabel(
            text=str(text),
            size_hint_y=None,
            height=dp(height),
            bold=bold,
            halign=halign,
            theme_text_color="Custom" if color else "Primary",
        )
        if font_style:
            label.font_style = font_style
        if color:
            label.text_color = color
        return label

    def _paragraph(self, text, color=None):
        label = self._label(text, height=40, color=color)
        label.text_size = (0, None)
        label.bind(texture_size=lambda widget, size: setattr(widget, "height", max(dp(34), size[1] + dp(5))))
        return label

    def _button(self, text, callback, *, color=None, width=None, disabled=False):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        button = MDRaisedButton(
            text=text,
            size_hint_y=None,
            height=dp(48),
            disabled=disabled,
            md_bg_color=color or tokens.get("primary", [0.06, 0.25, 0.43, 1]),
        )
        if width is not None:
            button.size_hint_x = None
            button.width = dp(width)
        button.bind(on_release=callback)
        return button

    def _card(self, *, height=None, padding=(12, 12, 12, 12), spacing=8):
        card = MDCard(
            orientation="vertical",
            padding=[dp(value) for value in padding],
            spacing=dp(spacing),
            radius=[dp(16)],
            elevation=1,
            size_hint_y=None if height is not None else 1,
        )
        if height is not None:
            card.height = dp(height)
        return card

    # ---------- Catalogo / leitor HID ----------
    def show_tab(self, tab_name):
        if tab_name not in {"catalog", "cart", "payment", "history"}:
            return
        self.active_tab = tab_name
        if tab_name == "payment":
            self.refresh_cash_session()
        elif tab_name == "history":
            self.load_history()
        self._schedule_render()

    def _build_catalog_page(self):
        scroll, body = self._scroll_body()
        body.add_widget(self._label("Produtos", height=34, bold=True, font_style="H6"))

        search_row = MDBoxLayout(size_hint_y=None, height=dp(58), spacing=dp(8))
        field = MDTextField(
            text=self.search_text,
            hint_text="Produto ou codigo do leitor",
            mode="rectangle",
            size_hint_x=1,
        )
        field.bind(text=lambda _field, value: setattr(self, "search_text", value))
        field.bind(on_text_validate=lambda *_: self.submit_search())
        search_row.add_widget(field)
        search_row.add_widget(self._button("BUSCAR", lambda *_: self.submit_search(), width=96))
        body.add_widget(search_row)
        body.add_widget(self._paragraph("Leitor USB/Bluetooth: toque no campo, leia o codigo e envie Enter.", color=[0.2, 0.3, 0.4, 1]))

        if self.products_loading:
            body.add_widget(self._label("A carregar catalogo…", height=42, halign="center"))
            return scroll
        if not self.products:
            body.add_widget(self._paragraph("Nenhum produto disponivel. Atualize a pesquisa ou confirme a ligacao a API."))
            body.add_widget(self._button("ATUALIZAR", lambda *_: self.load_products()))
            return scroll

        for product in self.products:
            body.add_widget(self._build_product_card(product))
        return scroll

    def _build_product_card(self, product):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=170)
        title_row = MDBoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
        name = self._label(product["name"], height=30, bold=True)
        name.size_hint_x = 0.70
        name.shorten = True
        price = self._label(_money(product["price"]), height=30, bold=True, color=tokens.get("success"))
        price.size_hint_x = 0.30
        title_row.add_widget(name)
        title_row.add_widget(price)
        card.add_widget(title_row)

        stock_label = f"Stock: {_quantity(product['stock'], product['is_weight'])}"
        if product.get("is_weight"):
            stock_label += "  ·  por peso"
        elif product.get("allow_pack_sale") and product.get("units_per_package"):
            stock_label += f"  ·  emb. {product['units_per_package']} un"
        if product.get("lot_count", 1) > 1:
            stock_label += f"  ·  {product['lot_count']} lotes"
        if product.get("barcode"):
            stock_label += f"\nCod.: {product['barcode']}"
        card.add_widget(self._paragraph(stock_label, color=tokens.get("text_secondary")))
        card.add_widget(self._button("ADICIONAR AO CARRINHO", lambda *_button, item=product: self.add_product(item)))
        return card

    def submit_search(self):
        query = str(self.search_text or "").strip()
        if not query:
            self.load_products()
            return
        self._products_token += 1
        token = self._products_token
        self.products_loading = True
        self._schedule_render()

        def task():
            lots = self.db.get_products_by_barcode(query) or []
            direct = _aggregate_lots(lots)
            if direct:
                return {"direct": direct[0], "products": []}
            rows = self.db.get_products_for_sale_catalog_page(
                search_text=query, limit=80, offset=0, refresh_statuses=False
            ) or []
            return {"direct": None, "products": [item for item in (_product_from_row(row) for row in rows) if item]}

        def done(result=None, error=None):
            if token != self._products_token:
                return
            self.products_loading = False
            if error:
                self.status_message = "Nao foi possivel pesquisar o catalogo."
                self._schedule_render()
                return
            direct = (result or {}).get("direct")
            if direct:
                self.add_product(direct)
                self.search_text = ""
                self.status_message = f"{direct['name']} adicionado ao carrinho."
                self._schedule_render()
                return
            self.products = (result or {}).get("products") or []
            self.status_message = ""
            self._schedule_render()

        self._background(task, done)

    def load_products(self):
        self._products_token += 1
        token = self._products_token
        query = str(self.search_text or "").strip()
        self.products_loading = True
        self._schedule_render()

        def task():
            rows = self.db.get_products_for_sale_catalog_page(
                search_text=query, limit=80, offset=0, refresh_statuses=False
            ) or []
            return [item for item in (_product_from_row(row) for row in rows) if item]

        def done(result=None, error=None):
            if token != self._products_token:
                return
            self.products_loading = False
            self.products = result or []
            self.status_message = "" if not error else "Nao foi possivel carregar o catalogo."
            self._schedule_render()

        self._background(task, done)

    # ---------- Carrinho ----------
    def add_product(self, product):
        if self.sale_in_progress:
            return
        product = dict(product or {})
        if not product:
            return
        if product.get("is_weight"):
            self._open_weight_dialog(product)
            return

        key = product.get("catalog_key") or _catalog_key(product)
        items = [dict(item) for item in self.cart_items]
        for item in items:
            if item.get("catalog_key") == key:
                if _number(item.get("qty")) + 1 > _number(product.get("stock")) + 1e-9:
                    self._show_message("Stock insuficiente", "Nao ha mais unidades disponiveis para esta venda.")
                    return
                item["qty"] = _number(item.get("qty")) + 1
                self.cart_items = items
                self._invalidate_pending_sale()
                self._refresh_totals()
                return

        if _number(product.get("stock")) < 1:
            self._show_message("Stock insuficiente", "Este produto deixou de estar disponivel.")
            return
        items.append({
            "id": product["id"],
            "catalog_key": key,
            "name": product["name"],
            "barcode": product.get("barcode"),
            "qty": 1.0,
            "price": _number(product.get("price")),
            "max_stock": _number(product.get("stock")),
            "is_weight": False,
            "vat_rule_code": product.get("vat_rule_code") or "STANDARD",
        })
        self.cart_items = items
        self._invalidate_pending_sale()
        self._refresh_totals()

    def _open_weight_dialog(self, product, current_item=None):
        if self.sale_in_progress:
            return
        available_stock = _number(product.get("stock", product.get("max_stock")))
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(14), dp(4), dp(14), dp(2)], adaptive_height=True)
        content.add_widget(self._paragraph(f"{product['name']}\nDisponivel: {_quantity(available_stock, True)}", color=[0.2, 0.3, 0.4, 1]))
        field = MDTextField(
            text=_quantity(current_item.get("qty"), True).replace(" kg", "") if current_item else "",
            hint_text="Peso em kg",
            mode="rectangle",
            input_filter="float",
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(field)
        cancel = MDFlatButton(text="CANCELAR")
        confirm = MDRaisedButton(text="ADICIONAR" if current_item is None else "GUARDAR")
        dialog = MDDialog(title="Venda por peso", type="custom", content_cls=content, buttons=[cancel, confirm])
        cancel.bind(on_release=lambda *_: dialog.dismiss())

        def save_weight(*_args):
            qty = _parse_amount(field.text)
            if qty <= 0 or qty > available_stock + 1e-9:
                field.error = True
                field.helper_text = "Indique um peso disponivel maior que zero"
                field.helper_text_mode = "on_error"
                return
            self._store_weight_product(product, qty, current_item=current_item)
            dialog.dismiss()

        confirm.bind(on_release=save_weight)
        dialog.open()

    def _store_weight_product(self, product, qty, current_item=None):
        key = product.get("catalog_key") or _catalog_key(product)
        available_stock = _number(product.get("stock", product.get("max_stock")))
        items = [dict(item) for item in self.cart_items]
        if current_item is not None:
            index = next((idx for idx, item in enumerate(items) if item.get("cart_id") == current_item.get("cart_id")), -1)
            if index >= 0:
                items[index]["qty"] = qty
                items[index]["max_stock"] = available_stock
                self.cart_items = items
                self._invalidate_pending_sale()
                self._refresh_totals()
                return
        for item in items:
            if item.get("catalog_key") == key and item.get("is_weight"):
                next_qty = _number(item.get("qty")) + qty
                if next_qty > available_stock + 1e-9:
                    self._show_message("Stock insuficiente", "O peso total ultrapassa o stock disponivel.")
                    return
                item["qty"] = next_qty
                self.cart_items = items
                self._invalidate_pending_sale()
                self._refresh_totals()
                return
        items.append({
            "cart_id": uuid4().hex,
            "id": product["id"],
            "catalog_key": key,
            "name": product["name"],
            "barcode": product.get("barcode"),
            "qty": qty,
            "price": _number(product.get("price")),
            "max_stock": available_stock,
            "is_weight": True,
            "vat_rule_code": product.get("vat_rule_code") or "STANDARD",
        })
        self.cart_items = items
        self._invalidate_pending_sale()
        self._refresh_totals()

    def _build_cart_page(self):
        scroll, body = self._scroll_body()
        heading = MDBoxLayout(size_hint_y=None, height=dp(42))
        heading.add_widget(self._label(f"Carrinho ({int(self.cart_count)})", height=38, bold=True, font_style="H6"))
        if self.cart_items:
            app = self._app()
            heading.add_widget(self._button("LIMPAR", lambda *_: self.clear_cart(), color=getattr(app, "theme_tokens", {}).get("danger"), width=94))
        body.add_widget(heading)
        if not self.cart_items:
            body.add_widget(self._paragraph("O carrinho esta vazio. Adicione produtos no catalogo."))
            body.add_widget(self._button("VER PRODUTOS", lambda *_: self.show_tab("catalog")))
            return scroll
        for index, item in enumerate(self.cart_items):
            body.add_widget(self._build_cart_item_card(index, item))
        body.add_widget(self._summary_card())
        body.add_widget(self._button("IR PARA PAGAMENTO", lambda *_: self.show_tab("payment")))
        return scroll

    def _build_cart_item_card(self, index, item):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=180 if item.get("is_weight") else 168)
        title = self._label(item.get("name") or "Produto", height=30, bold=True)
        title.shorten = True
        card.add_widget(title)
        details = f"{_quantity(item.get('qty'), item.get('is_weight'))} × {_money(item.get('price'))}\nTotal: {_money(_number(item.get('qty')) * _number(item.get('price')))}"
        card.add_widget(self._paragraph(details, color=tokens.get("text_secondary")))
        controls = MDBoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        if item.get("is_weight"):
            controls.add_widget(self._button("EDITAR PESO", lambda *_button, product=item, current=item: self._open_weight_dialog(product, current), width=158))
        else:
            controls.add_widget(self._button("−", lambda *_button, position=index: self.change_quantity(position, -1), width=54))
            controls.add_widget(self._button("+", lambda *_button, position=index: self.change_quantity(position, 1), width=54))
        controls.add_widget(self._button("REMOVER", lambda *_button, position=index: self.remove_cart_item(position), color=tokens.get("danger")))
        card.add_widget(controls)
        return card

    def change_quantity(self, index, delta):
        if self.sale_in_progress:
            return
        items = [dict(item) for item in self.cart_items]
        if index < 0 or index >= len(items):
            return
        item = items[index]
        qty = _number(item.get("qty")) + _number(delta)
        if qty <= 0:
            items.pop(index)
        elif qty <= _number(item.get("max_stock")) + 1e-9:
            item["qty"] = qty
        else:
            self._show_message("Stock insuficiente", "Nao existem mais unidades deste produto.")
            return
        self.cart_items = items
        self._invalidate_pending_sale()
        self._refresh_totals()

    def remove_cart_item(self, index):
        if self.sale_in_progress:
            return
        items = [dict(item) for item in self.cart_items]
        if 0 <= index < len(items):
            items.pop(index)
            self.cart_items = items
            self._invalidate_pending_sale()
            self._refresh_totals()

    def clear_cart(self):
        if self.sale_in_progress:
            self._show_message("Venda em curso", "Aguarde a confirmacao antes de alterar o carrinho.")
            return
        self.cart_items = []
        self.discount_text = ""
        self.paid_amount_text = ""
        self._invalidate_pending_sale()
        self._refresh_totals()

    def _refresh_totals(self):
        subtotal = round(sum(_number(item.get("qty")) * _number(item.get("price")) for item in self.cart_items), 2)
        discount = min(_parse_amount(self.discount_text), subtotal)
        total = max(0.0, round(subtotal - discount, 2))
        paid = total if self.payment_method != "cash" else _parse_amount(self.paid_amount_text)
        self.subtotal_amount = subtotal
        self.discount_amount = discount
        self.total_amount = total
        self.change_amount = max(0.0, round(paid - total, 2))
        # O indicador inferior representa linhas no carrinho. Isso evita
        # truncar, por exemplo, 0.750 kg para "0" no telemovel.
        self.cart_count = len(self.cart_items)
        self._update_live_payment_labels()

    def _invalidate_pending_sale(self):
        """Uma venda pendente so pode ser repetida se o carrinho for identico."""
        self._pending_sale = None

    @staticmethod
    def _sale_fingerprint(cart_snapshot, discount, payment_method, cash_session_id):
        items = tuple(
            sorted(
                (
                    int(item.get("id") or 0),
                    str(item.get("catalog_key") or ""),
                    round(_number(item.get("qty")), 6),
                    round(_number(item.get("price")), 6),
                    str(item.get("vat_rule_code") or "STANDARD"),
                )
                for item in (cart_snapshot or [])
            )
        )
        return (
            items,
            round(_number(discount), 2),
            str(payment_method or "cash"),
            int(cash_session_id or 0),
        )

    def _update_live_payment_labels(self):
        if self._payment_subtotal_label is not None:
            self._payment_subtotal_label.text = f"Subtotal: {_money(self.subtotal_amount)}"
        if self._payment_discount_label is not None:
            self._payment_discount_label.text = f"Desconto: −{_money(self.discount_amount)}"
            self._payment_discount_label.opacity = 1 if self.discount_amount else 0
        if self._payment_total_label is not None:
            self._payment_total_label.text = f"Total: {_money(self.total_amount)}"
        if self._payment_change_label is not None:
            self._payment_change_label.text = f"Troco: {_money(self.change_amount)}"

    def _summary_card(self):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=132)
        card.add_widget(self._label(f"Subtotal: {_money(self.subtotal_amount)}", height=25, color=tokens.get("text_secondary")))
        if self.discount_amount:
            card.add_widget(self._label(f"Desconto: −{_money(self.discount_amount)}", height=25, color=tokens.get("success")))
        card.add_widget(self._label(f"Total: {_money(self.total_amount)}", height=34, bold=True, color=tokens.get("success"), font_style="H6"))
        return card

    def _payment_summary_card(self):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=132)
        self._payment_subtotal_label = self._label(
            f"Subtotal: {_money(self.subtotal_amount)}", height=25, color=tokens.get("text_secondary")
        )
        self._payment_discount_label = self._label(
            f"Desconto: −{_money(self.discount_amount)}", height=25, color=tokens.get("success")
        )
        self._payment_discount_label.opacity = 1 if self.discount_amount else 0
        self._payment_total_label = self._label(
            f"Total: {_money(self.total_amount)}", height=34, bold=True, color=tokens.get("success"), font_style="H6"
        )
        card.add_widget(self._payment_subtotal_label)
        card.add_widget(self._payment_discount_label)
        card.add_widget(self._payment_total_label)
        return card

    # ---------- Pagamento e caixa ----------
    def set_payment_method(self, method):
        if self.sale_in_progress:
            return
        if method not in {option[0] for option in self.PAYMENT_OPTIONS}:
            return
        self.payment_method = method
        self._invalidate_pending_sale()
        self._refresh_totals()
        self._schedule_render()

    def set_discount_text(self, value):
        if self.sale_in_progress:
            return
        previous_discount = self.discount_amount
        self.discount_text = str(value or "")
        self._refresh_totals()
        if abs(previous_discount - self.discount_amount) > 0.0001:
            self._invalidate_pending_sale()

    def set_paid_amount_text(self, value):
        self.paid_amount_text = str(value or "")
        self._refresh_totals()

    def _build_payment_page(self):
        scroll, body = self._scroll_body()
        body.add_widget(self._label("Pagamento", height=34, bold=True, font_style="H6"))
        body.add_widget(self._payment_summary_card())

        body.add_widget(self._label("Forma de pagamento", height=24, bold=True))
        columns = 4 if self.width >= dp(560) else 2
        grid = GridLayout(cols=columns, spacing=dp(8), size_hint_y=None)
        grid.height = dp(48) * ((len(self.PAYMENT_OPTIONS) + columns - 1) // columns) + dp(8)
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        for method, label in self.PAYMENT_OPTIONS:
            grid.add_widget(self._button(
                label,
                lambda *_button, selected=method: self.set_payment_method(selected),
                color=tokens.get("success") if method == self.payment_method else tokens.get("primary"),
            ))
        body.add_widget(grid)

        discount = MDTextField(text=self.discount_text, hint_text="Desconto (MT)", mode="rectangle", size_hint_y=None, height=dp(56))
        discount.bind(text=lambda _field, value: self.set_discount_text(value))
        body.add_widget(discount)

        if self.payment_method == "cash":
            paid = MDTextField(text=self.paid_amount_text, hint_text="Valor recebido (MT)", mode="rectangle", size_hint_y=None, height=dp(56))
            paid.bind(text=lambda _field, value: self.set_paid_amount_text(value))
            body.add_widget(paid)
            self._payment_change_label = self._label(
                f"Troco: {_money(self.change_amount)}", height=28, bold=True, color=tokens.get("success")
            )
            body.add_widget(self._payment_change_label)
        else:
            self._payment_change_label = None
            label = dict(self.PAYMENT_OPTIONS).get(self.payment_method, "Pagamento")
            body.add_widget(self._paragraph(f"{label}: confirme o pagamento antes de finalizar. O valor da venda sera registado integralmente."))

        body.add_widget(self._cash_session_card())
        body.add_widget(self._button(
            "A FINALIZAR…" if self.sale_in_progress else "FINALIZAR VENDA",
            lambda *_: self.finalize_sale(),
            color=tokens.get("success"),
            disabled=self.sale_in_progress or not self.cart_items,
        ))
        body.add_widget(self._paragraph("O recibo e o historico ficam centralizados no servidor. Esta versao nao tenta imprimir por bibliotecas Windows."))
        return scroll

    def _cash_session_card(self):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        session = dict(self.cash_session or {})
        if session.get("id"):
            text = f"Caixa #{session.get('id')} aberto\nTerminal: {self._get_terminal_id()}"
            action = self._button("ATUALIZAR CAIXA", lambda *_: self.refresh_cash_session(), width=170)
            color = tokens.get("success")
        else:
            text = f"Nenhum caixa aberto neste telefone\nTerminal: {self._get_terminal_id()}"
            action = self._button("ABRIR CAIXA", lambda *_: self.open_cash_dialog(), width=150)
            color = tokens.get("warning")
        card = self._card(height=116)
        card.add_widget(self._label("Caixa", height=24, bold=True))
        row = MDBoxLayout(size_hint_y=None, height=dp(58), spacing=dp(8))
        row.add_widget(self._paragraph(text, color=color))
        row.add_widget(action)
        card.add_widget(row)
        return card

    def refresh_cash_session(self):
        user = self._current_user()
        if not self.db or not user:
            return
        terminal_id = self._get_terminal_id()

        def task():
            return self.db.get_open_cash_session(user, terminal_id)

        def done(result=None, error=None):
            self.cash_session = dict(result or {}) if not error else {}
            if self.active_tab == "payment":
                self._schedule_render()

        self._background(task, done)

    def open_cash_dialog(self):
        if self.cash_operation_in_progress:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(14), dp(4), dp(14), dp(2)], adaptive_height=True)
        content.add_widget(self._paragraph("Defina o fundo inicial deste terminal. O caixa sera registado na API central."))
        field = MDTextField(hint_text="Fundo inicial (MT)", text="0", mode="rectangle", input_filter="float", size_hint_y=None, height=dp(56))
        content.add_widget(field)
        cancel = MDFlatButton(text="CANCELAR")
        confirm = MDRaisedButton(text="ABRIR CAIXA")
        dialog = MDDialog(title="Abrir caixa", type="custom", content_cls=content, buttons=[cancel, confirm])
        cancel.bind(on_release=lambda *_: dialog.dismiss())

        def create_cash(*_args):
            amount = _parse_amount(field.text)
            if amount < 0:
                return
            self.cash_operation_in_progress = True
            confirm.disabled = True

            def task():
                return self.db.open_cash_session(
                    self._current_user(), self._get_terminal_id(), amount,
                    role=self._current_role(),
                )

            def done(result=None, error=None):
                self.cash_operation_in_progress = False
                confirm.disabled = False
                if error or not (result or {}).get("ok"):
                    self._show_message("Caixa", str((result or {}).get("message") or "Nao foi possivel abrir o caixa."))
                    return
                self.cash_session = dict((result or {}).get("session") or {})
                dialog.dismiss()
                self._schedule_render()

            self._background(task, done)

        confirm.bind(on_release=create_cash)
        dialog.open()

    # ---------- Confirmacao da venda agrupada ----------
    def _allocate_discount(self, cart_snapshot, discount):
        subtotal = sum(_number(item.get("qty")) * _number(item.get("price")) for item in cart_snapshot)
        remaining = min(max(_number(discount), 0.0), subtotal)
        prepared = []
        for index, item in enumerate(cart_snapshot):
            line_total = round(_number(item.get("qty")) * _number(item.get("price")), 2)
            if index == len(cart_snapshot) - 1:
                line_discount = round(remaining, 2)
            elif subtotal > 0:
                line_discount = round(min(remaining, discount * (line_total / subtotal)), 2)
                remaining = round(remaining - line_discount, 2)
            else:
                line_discount = 0.0
            qty = max(_number(item.get("qty")), 0.000001)
            prepared.append({
                **item,
                "line_discount": line_discount,
                "effective_unit_price": round(max(0.0, line_total - line_discount) / qty, 6),
            })
        return prepared

    def _live_lots_for_item(self, item):
        barcode = str(item.get("barcode") or "").strip()
        if barcode:
            rows = self.db.get_products_by_barcode(barcode, include_expired=False, include_zero_stock=False) or []
        else:
            rows = self.db.get_products_for_sale_page(
                search_text=item.get("name") or "", limit=250, offset=0, refresh_statuses=False
            ) or []
        key = str(item.get("catalog_key") or "").strip().lower()
        return [product for product in (_product_from_row(row) for row in rows) if product and product["catalog_key"] == key]

    def _build_commit_allocations(self, cart_snapshot, discount):
        allocations = []
        conflicts = []
        for item in self._allocate_discount(cart_snapshot, discount):
            lots = self._live_lots_for_item(item)
            requested = _number(item.get("qty"))
            available = sum(_number(lot.get("stock")) for lot in lots)
            if requested <= 0 or requested > available + 1e-9:
                conflicts.append((item.get("name") or "Produto", requested, available))
                continue
            remaining_qty = requested
            remaining_discount = _number(item.get("line_discount"))
            for index, lot in enumerate(lots):
                if remaining_qty <= 1e-9:
                    break
                qty = min(remaining_qty, _number(lot.get("stock")))
                if qty <= 1e-9:
                    continue
                is_last = qty >= remaining_qty - 1e-9
                lot_discount = remaining_discount if is_last else round(_number(item.get("line_discount")) * qty / requested, 2)
                remaining_discount = round(remaining_discount - lot_discount, 2)
                allocations.append({
                    **item,
                    "id": lot["id"],
                    "qty": qty,
                    "is_promotional": str(lot.get("status") or "").strip().upper() == "PERTO_DO_PRAZO",
                    "vat_rule_code": item.get("vat_rule_code") or lot.get("vat_rule_code") or "STANDARD",
                    "discount_amount": lot_discount,
                })
                remaining_qty -= qty
            if remaining_qty > 1e-6:
                conflicts.append((item.get("name") or "Produto", requested, available))
        return allocations, conflicts

    def finalize_sale(self):
        if self.sale_in_progress:
            return
        if not self.cart_items:
            self.show_tab("catalog")
            return
        if not self.cash_session.get("id"):
            self._show_message("Caixa fechado", "Abra o caixa deste telefone antes de finalizar uma venda.")
            self.open_cash_dialog()
            return
        self._refresh_totals()
        if self.total_amount <= 0:
            self._show_message("Valor invalido", "O total da venda precisa ser superior a zero.")
            return
        if self.payment_method == "cash" and _parse_amount(self.paid_amount_text) + 1e-9 < self.total_amount:
            self._show_message("Valor recebido", "O valor recebido e menor que o total da venda.")
            return

        cart_snapshot = [dict(item) for item in self.cart_items]
        discount = self.discount_amount
        user = self._current_user()
        role = self._current_role()
        session_id = self.cash_session.get("id")
        fingerprint = self._sale_fingerprint(
            cart_snapshot,
            discount,
            self.payment_method,
            session_id,
        )
        pending = self._pending_sale or {}
        if pending.get("fingerprint") == fingerprint:
            transaction_code = pending["transaction_code"]
        else:
            transaction_code = (
                f"MOB-{self._get_terminal_id().split('-')[-1]}-"
                f"{datetime.now():%Y%m%d%H%M%S%f}-{uuid4().hex[:4].upper()}"
            )
            pending = {
                "fingerprint": fingerprint,
                "transaction_code": transaction_code,
            }
            self._pending_sale = pending
        self.sale_in_progress = True
        self._schedule_render()

        def task():
            # Se a resposta anterior se perdeu, reutilizamos exactamente as
            # mesmas alocacoes/lotes. Assim a API pode reconhecer o mesmo
            # codigo antes de qualquer nova verificacao de stock.
            allocations = [dict(item) for item in (pending.get("allocations") or [])]
            if not allocations:
                allocations, conflicts = self._build_commit_allocations(cart_snapshot, discount)
                if conflicts:
                    return {"status": "conflict", "conflicts": conflicts}
                # Campo Python simples, sem atualizacao visual fora da thread
                # principal; protege a repeticao idempotente apos timeout.
                self._pending_sale = {**pending, "allocations": [dict(item) for item in allocations]}
            result = self.db.add_sales_transaction(
                transaction_code,
                allocations,
                username=user,
                role=role,
                terminal_id=self._get_terminal_id(),
                payment_method=self.payment_method,
                cash_session_id=session_id,
            )
            if (result or {}).get("ok"):
                return {"status": "ok", "transaction_code": transaction_code, "idempotent": bool(result.get("idempotent"))}
            last_error = str(getattr(self.db, "last_error", lambda: "")() or "").strip()
            return {
                "status": "retry" if last_error else "error",
                "message": last_error or str((result or {}).get("message") or "A API nao confirmou a venda."),
            }

        def done(result=None, error=None):
            self.sale_in_progress = False
            result = result or {}
            if error:
                self._show_message(
                    "Ligacao interrompida",
                    "O estado da venda pode estar a ser confirmado pelo servidor. Toque em FINALIZAR novamente para verificar sem duplicar.",
                )
            elif result.get("status") == "conflict":
                self._invalidate_pending_sale()
                name, requested, available = (result.get("conflicts") or [("Produto", 0, 0)])[0]
                self._show_message("Stock atualizado", f"{name}: solicitado {_quantity(requested)}, disponivel {_quantity(available)}.")
            elif result.get("status") == "ok":
                self._invalidate_pending_sale()
                self.clear_cart()
                self.status_message = f"Venda {result.get('transaction_code')} concluida."
                completion = "A venda foi confirmada pelo servidor sem duplicar a transacao." if result.get("idempotent") else "A venda foi guardada como uma unica transacao no servidor."
                self._show_message("Venda concluida", completion)
                self.show_tab("catalog")
                self.load_products()
                self.load_history(force=True)
            elif result.get("status") == "retry":
                self._show_message(
                    "Confirmacao pendente",
                    "A resposta da API nao chegou. Toque em FINALIZAR novamente; a mesma transacao sera verificada sem duplicar stock.",
                )
            else:
                self._invalidate_pending_sale()
                self._show_message("Venda nao concluida", str(result.get("message") or "A API nao confirmou a venda."))
            self._schedule_render()

        self._background(task, done)

    # ---------- Historico agrupado e estorno ----------
    @staticmethod
    def _sale_record_from_row(row):
        if isinstance(row, dict):
            return dict(row)
        if not isinstance(row, (list, tuple)):
            return {}
        qty = _number(row[2]) if len(row) > 2 else 0.0
        returned = _number(row[6]) if len(row) > 6 else 0.0
        return {
            "sale_id": row[0] if len(row) > 0 else None,
            "product": (row[1] if len(row) > 1 else "") or "Produto",
            "qty": qty,
            "price": _number(row[3]) if len(row) > 3 else 0.0,
            "total": _number(row[4]) if len(row) > 4 else 0.0,
            "sale_date": row[5] if len(row) > 5 else "",
            "returned_qty": returned,
            "available_qty": max(0.0, _number(row[7]) if len(row) > 7 else qty - returned),
            "created_by": row[8] if len(row) > 8 else "",
            "created_role": row[9] if len(row) > 9 else "",
            "is_promotional": _truth(row[10]) if len(row) > 10 else False,
            "transaction_code": str(row[12] if len(row) > 12 else "").strip(),
        }

    def load_history(self, force=False):
        if self.history_loading and not force:
            return
        self._history_token += 1
        token = self._history_token
        self.history_loading = True
        if self.active_tab == "history":
            self._schedule_render()

        def task():
            rows = self.db.get_recent_sales(limit=120) or []
            records = [self._sale_record_from_row(row) for row in rows]
            return group_sale_records(records)

        def done(result=None, error=None):
            if token != self._history_token:
                return
            self.history_loading = False
            self.transactions = result or []
            if error:
                self.status_message = "Nao foi possivel carregar o historico."
            if self.active_tab == "history":
                self._schedule_render()

        self._background(task, done)

    def _build_history_page(self):
        scroll, body = self._scroll_body()
        header = MDBoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        header.add_widget(self._label("Historico", height=38, bold=True, font_style="H6"))
        header.add_widget(self._button("ATUALIZAR", lambda *_: self.load_history(force=True), width=118, disabled=self.history_loading))
        body.add_widget(header)
        body.add_widget(self._paragraph(f"Cada cartinho aparece como uma venda unica. O estorno e permitido por {REFUND_WINDOW_MINUTES} minutos."))
        if self.history_loading:
            body.add_widget(self._label("A carregar vendas…", height=42, halign="center"))
            return scroll
        if not self.transactions:
            body.add_widget(self._paragraph("Ainda nao existem vendas recentes para este utilizador."))
            return scroll
        for transaction in self.transactions:
            body.add_widget(self._build_transaction_card(transaction))
        return scroll

    def _build_transaction_card(self, transaction):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=190)
        date_value = str(transaction.get("sale_date") or "")[:16]
        card.add_widget(self._label(f"{date_value}  ·  {_money(transaction.get('net_total'))}", height=28, bold=True, color=tokens.get("success")))
        names = []
        for item in transaction.get("items") or []:
            name = str(item.get("product") or "Produto")
            if name not in names:
                names.append(name)
        card.add_widget(self._paragraph(" · ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else ""), color=tokens.get("text_secondary")))
        seconds = _integer(transaction.get("refund_seconds_left"))
        if transaction.get("can_refund"):
            minutes, secs = divmod(max(0, seconds), 60)
            status = f"Estorno disponivel: {minutes:02d}:{secs:02d}"
            color = tokens.get("warning")
        else:
            status = "Estorno indisponivel"
            color = tokens.get("text_muted")
        card.add_widget(self._label(f"{len(transaction.get('items') or [])} produto(s)  ·  {status}", height=26, color=color))
        card.add_widget(self._button("VER PRODUTOS", lambda *_button, sale=transaction: self.open_transaction_dialog(sale)))
        return card

    def open_transaction_dialog(self, transaction):
        items = list((transaction or {}).get("items") or [])
        if not items:
            return
        content_scroll = ScrollView(do_scroll_x=False)
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(8), dp(4), dp(8), dp(4)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content_scroll.add_widget(content)
        content.add_widget(self._paragraph(f"{len(items)} produto(s) · Total: {_money(transaction.get('net_total'))}"))
        for item in items:
            content.add_widget(self._build_transaction_item(item))
        close = MDFlatButton(text="FECHAR")
        dialog = MDDialog(title="Produtos da venda", type="custom", content_cls=content_scroll, buttons=[close])
        close.bind(on_release=lambda *_: dialog.dismiss())
        dialog.open()

    def _build_transaction_item(self, item):
        app = self._app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        card = self._card(height=132, padding=(10, 8, 10, 8), spacing=4)
        card.add_widget(self._label(item.get("product") or "Produto", height=25, bold=True))
        available = _number(item.get("available_qty"))
        card.add_widget(self._label(f"{_quantity(item.get('qty'))} × {_money(item.get('price'))}  ·  disponivel: {_quantity(available)}", height=24, color=tokens.get("text_secondary")))
        allowed, seconds = refund_window_status(item.get("sale_date"))
        can_refund = allowed and available > 0.0001
        if can_refund:
            card.add_widget(self._button("ESTORNAR ITEM", lambda *_button, record=item: self.open_refund_dialog(record), color=tokens.get("warning")))
        else:
            card.add_widget(self._label("Prazo de estorno expirado ou item ja devolvido.", height=26, color=tokens.get("text_muted")))
        return card

    def open_refund_dialog(self, item):
        allowed, _seconds = refund_window_status(item.get("sale_date"))
        available = _number(item.get("available_qty"))
        if not allowed or available <= 0:
            self._show_message("Estorno", "Este item ja nao pode ser estornado.")
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(14), dp(4), dp(14), dp(2)], adaptive_height=True)
        content.add_widget(self._paragraph(f"{item.get('product')}\nMaximo: {_quantity(available)}"))
        quantity = MDTextField(hint_text="Quantidade a estornar", text=_quantity(available), mode="rectangle", input_filter="float", size_hint_y=None, height=dp(56))
        reason = MDTextField(hint_text="Motivo (opcional)", mode="rectangle", size_hint_y=None, height=dp(56))
        content.add_widget(quantity)
        content.add_widget(reason)
        cancel = MDFlatButton(text="CANCELAR")
        confirm = MDRaisedButton(text="CONFIRMAR ESTORNO")
        dialog = MDDialog(title="Estornar item", type="custom", content_cls=content, buttons=[cancel, confirm])
        cancel.bind(on_release=lambda *_: dialog.dismiss())

        def submit(*_args):
            qty = _parse_amount(quantity.text)
            if qty <= 0 or qty > available + 1e-9:
                quantity.error = True
                quantity.helper_text = "Quantidade fora do limite disponivel"
                quantity.helper_text_mode = "on_error"
                return
            confirm.disabled = True

            def task():
                return self.db.refund_sale_item(
                    item.get("sale_id"), qty, reason=reason.text,
                    username=self._current_user(), role=self._current_role(), terminal_id=self._get_terminal_id(),
                )

            def done(result=None, error=None):
                confirm.disabled = False
                if error or not (result or {}).get("ok"):
                    self._show_message("Estorno", str((result or {}).get("message") or "O estorno nao foi concluido."))
                    return
                dialog.dismiss()
                self._show_message("Estorno concluido", str((result or {}).get("message") or "O stock foi devolvido e o historico atualizado."))
                self.load_history(force=True)
                self.load_products()

            self._background(task, done)

        confirm.bind(on_release=submit)
        dialog.open()

    # ---------- Navegacao e tarefas ----------
    def request_logout(self):
        if self.sale_in_progress or self.cash_operation_in_progress:
            self._show_message("Operacao em curso", "Aguarde a confirmacao da operacao actual antes de sair.")
            return
        cancel = MDFlatButton(text="CANCELAR")
        confirm = MDRaisedButton(text="SAIR")
        dialog = MDDialog(title="Terminar sessao", text="Pretende sair da conta do gerente neste telefone?", buttons=[cancel, confirm])
        cancel.bind(on_release=lambda *_: dialog.dismiss())

        def logout(*_args):
            dialog.dismiss()
            setter = getattr(self.db, "set_active_user", None)
            if callable(setter):
                setter(None, None)
            app = self._app()
            if app:
                app.current_user = None
                app.current_role = None
            if self.manager and "login" in self.manager.screen_names:
                self.manager.current = "login"

        confirm.bind(on_release=logout)
        dialog.open()

    def change_connection(self):
        if self.sale_in_progress or self.cash_operation_in_progress:
            self._show_message("Operacao em curso", "Aguarde a confirmacao da operacao actual antes de alterar o servidor.")
            return
        cancel = MDFlatButton(text="CANCELAR")
        confirm = MDRaisedButton(text="ALTERAR")
        dialog = MDDialog(
            title="Alterar servidor",
            text="A sessao sera terminada e o carrinho actual sera limpo. Continuar?",
            buttons=[cancel, confirm],
        )
        cancel.bind(on_release=lambda *_: dialog.dismiss())

        def open_connection(*_args):
            dialog.dismiss()
            app = self._app()
            opener = getattr(app, "open_mobile_connection", None) if app else None
            if callable(opener):
                opener()

        confirm.bind(on_release=open_connection)
        dialog.open()

    def _background(self, task, callback):
        def worker():
            try:
                result = task()
                Clock.schedule_once(lambda _dt: callback(result=result), 0)
            except Exception as exc:
                Clock.schedule_once(lambda _dt, error=exc: callback(error=error), 0)

        Thread(target=worker, daemon=True).start()

    @staticmethod
    def _show_message(title, message):
        close = MDFlatButton(text="OK")
        dialog = MDDialog(title=str(title), text=str(message), buttons=[close])
        close.bind(on_release=lambda *_: dialog.dismiss())
        dialog.open()
