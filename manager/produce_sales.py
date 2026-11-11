"""Simple selling choices for produce received in sacks of unknown weight.

Versao LITE — dialogo leve, legivel e rapido no PDV.
"""
from __future__ import annotations

import math

from kivy.app import App
from kivy.metrics import dp, sp

from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout,
    NativeButton as MDRaisedButton,
    NativeDialog as MDDialog,
    NativeFlatButton as MDFlatButton,
    NativeLabel as MDLabel,
    NativeTextField as MDTextField,
)


MODE_LABELS = {
    "unit": "Unidade",
    "heap": "Montinho",
    "weight": "Kg",
    "sack": "Saco",
    "amount": "Valor",
}

MODE_HINTS = {
    "unit": ("Quantidade de unidades", "Preco por unidade (MT)"),
    "heap": ("Quantidade de montinhos", "Preco por montinho (MT)"),
    "weight": ("Peso vendido em kg", "Preco por kg (MT)"),
    "sack": ("Quantidade de sacos", "Preco por saco (MT)"),
    "amount": ("1", "Valor total (MT)"),
}


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
        "id": info["id"],
        "catalog_key": f"sacks:{info['id']}",
        "name": info["name"],
        "barcode": info["barcode"],
        "qty": quantity,
        "qty_units": quantity,
        "pack_units": None,
        "price": price,
        "unit_price": price,
        "total": round(quantity * price, 2),
        "max_stock": info["stock"] if mode == "sack" else float("inf"),
        "is_weight": mode == "weight",
        "weight_kg": quantity if mode == "weight" else 0,
        "sale_mode": mode,
        "produce_sale_mode": mode,
        "promo_active": False,
        "vat_rule_code": info["vat_rule_code"],
        "lot_count": 1,
    }


class ProduceSalesMixin:
    """Mixin LITE para venda de produtos recebidos em sacos."""

    def show_produce_dialog(self, info, settings=None):
        if settings is None:
            settings = self.db.get_produce_settings(info["id"])
        if not settings or settings["stock_mode"] != "SACKS":
            self.show_message("Atualize a lista de produtos e tente novamente.")
            return

        info = dict(info, stock=float(settings["sacks_available"]))
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}

        primary = tokens.get("primary", [0.15, 0.52, 0.76, 1])
        card_bg = tokens.get("card", [0.16, 0.18, 0.22, 1])
        card_alt = tokens.get("card_alt", [0.20, 0.22, 0.28, 1])
        text_c = tokens.get("text_primary", [0.95, 0.96, 0.98, 1])
        muted = tokens.get("manager_ink", tokens.get("text_secondary", [0.69, 0.73, 0.81, 1]))
        success = tokens.get("success", [0.14, 0.55, 0.32, 1])
        danger = tokens.get("danger", [0.78, 0.20, 0.24, 1])
        on_primary = tokens.get("on_primary", [1, 1, 1, 1])

        # ---- conteudo ----
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(320),
            padding=[dp(4), dp(2), dp(4), dp(2)],
        )

        # Stock banner
        stock_card = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=[dp(8), dp(4), dp(8), dp(4)],
        )
        stock_card.add_widget(MDLabel(
            text=f"{info['stock']:g} sacos disponiveis",
            bold=True,
            font_size=dp(14),
            theme_text_color="Custom",
            text_color=text_c,
        ))
        stock_card.add_widget(MDLabel(
            text="Saldo avulso nao medido",
            halign="right",
            font_size=dp(12),
            theme_text_color="Custom",
            text_color=muted,
        ))
        content.add_widget(stock_card)

        # Mode buttons (compact chips)
        choices = MDBoxLayout(spacing=dp(5), size_hint_y=None, height=dp(38))
        mode_buttons = {}
        state = {"mode": "unit"}

        quantity = MDTextField(
            text="1",
            hint_text="Quantidade de unidades",
            input_filter="int",
            mode="rectangle",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(48),
        )
        price = MDTextField(
            text=str(info["unit_price"]),
            hint_text="Preco por unidade (MT)",
            input_filter="float",
            mode="rectangle",
            font_size=dp(16),
            size_hint_y=None,
            height=dp(48),
        )
        preview = MDLabel(
            text="",
            size_hint_y=None,
            height=dp(36),
            bold=True,
            font_size=dp(16),
            halign="center",
            theme_text_color="Custom",
            text_color=success,
        )

        def _style_modes():
            for mode, btn in mode_buttons.items():
                active = mode == state["mode"]
                btn.md_bg_color = primary if active else card_alt
                try:
                    btn.text_color = on_primary if active else text_c
                except Exception:
                    pass

        def refresh(*_):
            try:
                qty = float(str(quantity.text or "0").replace(",", "."))
                pr = float(str(price.text or "0").replace(",", "."))
                total = qty * pr
                preview.text = f"Total  {total:.2f} MT"
            except ValueError:
                preview.text = "Total  —"

        def choose(mode):
            state["mode"] = mode
            quantity.disabled = mode == "amount"
            quantity.input_filter = "float" if mode == "weight" else "int"
            quantity.text = "1"
            q_hint, p_hint = MODE_HINTS[mode]
            quantity.hint_text = q_hint
            price.hint_text = p_hint
            price.text = str(info["unit_price"]) if mode == "unit" else ""
            _style_modes()
            refresh()

        for mode, label in MODE_LABELS.items():
            btn = MDRaisedButton(
                text=label,
                font_size=sp(12),
                size_hint_x=1,
                md_bg_color=card_alt,
                on_release=lambda _b, m=mode: choose(m),
            )
            mode_buttons[mode] = btn
            choices.add_widget(btn)

        content.add_widget(choices)
        content.add_widget(quantity)
        content.add_widget(price)

        content.add_widget(preview)

        quantity.bind(text=refresh)
        price.bind(text=refresh)
        _style_modes()
        refresh()

        dialog = MDDialog(
            title=str(info.get("name") or "Produto"),
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="Cancelar"),
                MDFlatButton(text="Saco terminado"),
                MDRaisedButton(text="Adicionar", md_bg_color=success),
            ],
        )
        dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())

        def add(*_):
            try:
                item = make_produce_cart_item(info, state["mode"], quantity.text, price.text)
                reserved = sum(
                    i["qty"]
                    for i in self.cart_items
                    if i["id"] == info["id"] and i.get("produce_sale_mode") == "sack"
                )
                if reserved + (item["qty"] if state["mode"] == "sack" else 0) >= info["stock"]:
                    has_loose = state["mode"] != "sack" or any(
                        i["id"] == info["id"] and i.get("produce_sale_mode") not in (None, "sack")
                        for i in self.cart_items
                    )
                    if has_loose:
                        raise ValueError(
                            "Reserve um saco para as vendas avulsas ou retire a venda do saco inteiro."
                        )
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
                self.show_message(
                    "Conclua ou retire as vendas deste produto do carrinho antes de terminar o saco."
                )
                return
            confirmation = MDDialog(
                title="Terminar um saco?",
                text="Confirme que o conteudo de um saco acabou. O stock sera reduzido em 1 saco.",
                buttons=[
                    MDFlatButton(text="Cancelar"),
                    MDRaisedButton(text="Terminar", md_bg_color=danger),
                ],
            )
            confirmation.buttons[0].bind(on_release=lambda *_: confirmation.dismiss())

            def commit(*_):
                app_ = App.get_running_app()
                result = self.db.finish_produce_sack(
                    info["id"],
                    getattr(app_, "current_user", None),
                    getattr(app_, "current_role", None),
                )
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
