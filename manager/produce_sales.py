"""Simple selling choices for produce received in sacks of unknown weight."""
import math

from kivy.app import App
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField


MODE_LABELS = {"unit": "Unidade", "heap": "Montinho", "weight": "Kg", "sack": "Saco", "amount": "Valor"}


def make_produce_cart_item(info, mode, quantity, price):
    quantity, price = float(quantity), float(price)
    if mode not in MODE_LABELS or not all(math.isfinite(v) and v > 0 for v in (quantity, price)):
        raise ValueError("Informe quantidade e preco maiores que zero.")
    if mode != "weight" and not quantity.is_integer():
        raise ValueError("A quantidade deve ser inteira.")
    if mode == "amount" and quantity != 1:
        raise ValueError("Informe apenas o valor total.")
    if info["stock"] < 1 or (mode == "sack" and quantity > info["stock"]):
        raise ValueError("Sacos insuficientes.")
    return {
        "id": info["id"], "catalog_key": f"sacks:{info['id']}",
        "name": info["name"], "barcode": info["barcode"],
        "qty": quantity, "qty_units": quantity, "pack_units": None,
        "price": price, "unit_price": price, "total": round(quantity * price, 2),
        "max_stock": info["stock"] if mode == "sack" else float("inf"),
        "is_weight": mode == "weight", "weight_kg": quantity if mode == "weight" else 0,
        "sale_mode": mode, "produce_sale_mode": mode,
        "promo_active": False, "vat_rule_code": info["vat_rule_code"], "lot_count": 1,
    }


class ProduceSalesMixin:
    def show_produce_dialog(self, info):
        settings = self.db.get_produce_settings(info["id"])
        if not settings or settings["stock_mode"] != "SACKS":
            self.show_message("Atualize a lista de produtos e tente novamente.")
            return
        info = dict(info, stock=float(settings["sacks_available"]))
        content = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, height=dp(294))
        content.add_widget(MDLabel(
            text=f"{info['stock']:g} sacos disponiveis. O saldo avulso nao e medido.",
            size_hint_y=None, height=dp(44),
        ))
        choices = MDBoxLayout(spacing=dp(4), size_hint_y=None, height=dp(42))
        quantity = MDTextField(text="1", hint_text="Quantidade de unidades", input_filter="int", mode="rectangle")
        price = MDTextField(text=str(info["unit_price"]), hint_text="Preco por unidade (MT)", input_filter="float", mode="rectangle")
        preview = MDLabel(text="", size_hint_y=None, height=dp(32))
        state = {"mode": "unit"}

        def refresh(*_):
            try:
                total = float(quantity.text or 0) * float(price.text or 0)
                preview.text = f"Total: {total:.2f} MT"
            except ValueError:
                preview.text = ""

        def choose(mode):
            state["mode"] = mode
            quantity.disabled = mode == "amount"
            quantity.input_filter = "float" if mode == "weight" else "int"
            quantity.text = "1"
            quantity.hint_text = "Peso vendido em kg" if mode == "weight" else f"Quantidade: {MODE_LABELS[mode]}"
            price.hint_text = "Valor total (MT)" if mode == "amount" else f"Preco por {MODE_LABELS[mode].lower()} (MT)"
            price.text = str(info["unit_price"]) if mode == "unit" else ""
            refresh()

        for mode, label in MODE_LABELS.items():
            choices.add_widget(MDFlatButton(text=label, on_release=lambda _b, m=mode: choose(m)))
        content.add_widget(choices)
        content.add_widget(quantity)
        content.add_widget(price)
        content.add_widget(preview)
        quantity.bind(text=refresh)
        price.bind(text=refresh)
        refresh()
        dialog = MDDialog(title=info["name"], type="custom", content_cls=content, buttons=[
            MDFlatButton(text="Cancelar"), MDFlatButton(text="Saco terminado"), MDRaisedButton(text="Adicionar"),
        ])
        dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())

        def add(*_):
            try:
                item = make_produce_cart_item(info, state["mode"], quantity.text, price.text)
                reserved = sum(i["qty"] for i in self.cart_items if i["id"] == info["id"] and i.get("produce_sale_mode") == "sack")
                if reserved + (item["qty"] if state["mode"] == "sack" else 0) >= info["stock"]:
                    has_loose = state["mode"] != "sack" or any(i["id"] == info["id"] and i.get("produce_sale_mode") not in (None, "sack") for i in self.cart_items)
                    if has_loose:
                        raise ValueError("Reserve um saco para as vendas avulsas ou retire a venda do saco inteiro.")
                if state["mode"] == "sack" and reserved + item["qty"] > info["stock"]:
                    raise ValueError("Sacos insuficientes.")
            except (ValueError, TypeError) as exc:
                self.show_message(str(exc))
                return
            self.cart_items.append(item)
            dialog.dismiss()
            self._request_cart_display_update()

        def finish(*_):
            if any(i["id"] == info["id"] for i in self.cart_items):
                self.show_message("Conclua ou retire as vendas deste produto do carrinho antes de terminar o saco.")
                return
            confirmation = MDDialog(title="Terminar um saco?", text="Confirme que o conteudo de um saco acabou. O stock sera reduzido em 1 saco.", buttons=[MDFlatButton(text="Cancelar"), MDRaisedButton(text="Terminar")])
            confirmation.buttons[0].bind(on_release=lambda *_: confirmation.dismiss())

            def commit(*_):
                app = App.get_running_app()
                result = self.db.finish_produce_sack(info["id"], getattr(app, "current_user", None), getattr(app, "current_role", None))
                confirmation.dismiss()
                if result.get("ok"):
                    dialog.dismiss()
                    self.load_all_products_to_panel()
                    self.show_message("Saco terminado.")
                else:
                    self.show_message(result.get("message") or "Nao foi possivel terminar o saco.")

            confirmation.buttons[1].bind(on_release=commit)
            confirmation.open()

        dialog.buttons[1].bind(on_release=finish)
        dialog.buttons[2].bind(on_release=add)
        dialog.open()
