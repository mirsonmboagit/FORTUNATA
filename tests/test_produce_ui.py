from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def app():
    from kivy.app import App
    from kivymd.app import MDApp
    from utils.config.theme import get_theme_tokens
    previous = App.get_running_app()
    instance = MDApp()
    instance.theme_tokens = get_theme_tokens("Light")
    yield instance
    App._running_app = previous


def test_form_saves_sacks_without_weight(app, monkeypatch):
    from admin.product_form import ProductForm
    from database import provider
    db = Mock()
    db.add_product.return_value = 7
    db.last_error.return_value = None
    monkeypatch.setattr(provider, "get_db", lambda: db)
    form = ProductForm(SimpleNamespace(load_products=Mock()))
    monkeypatch.setattr(form, "_show_snackbar", Mock())
    form._set_produce_mode(True)
    form.description.text = "Cebola"
    form.category_field.text = "Horticolas"
    form.existing_stock.text = "1"
    form.total_purchase_price.text = "800"
    form.sale_price.text = "5"
    assert form.sack_weight_input.text == ""
    assert form._validate_fields()
    form._save_to_database(None, None, False)
    args, kwargs = db.add_product.call_args
    assert args[2] == 1
    assert kwargs["produce_options"] == {"stock_mode": "SACKS", "sack_weight_kg": None}
    assert form.weight_state_btn.disabled
    form._set_produce_mode(False)
    assert not form.weight_state_btn.disabled
    form.on_dismiss()


def test_dialog_adds_three_pieces_without_requesting_weight(app, monkeypatch):
    from kivymd.uix.dialog import MDDialog
    from kivymd.uix.textfield import MDTextField
    from manager.produce_sales import ProduceSalesMixin
    dialogs = []
    monkeypatch.setattr(MDDialog, "open", lambda dialog: dialogs.append(dialog))
    db = SimpleNamespace(get_produce_settings=lambda pid: {"stock_mode": "SACKS", "sacks_available": 1, "sack_weight_kg": None})
    screen = SimpleNamespace(db=db, cart_items=[], show_message=Mock(), _request_cart_display_update=Mock())
    info = {"id": 7, "name": "Cebola", "stock": 1, "unit_price": 5, "barcode": None, "vat_rule_code": "STANDARD"}
    ProduceSalesMixin.show_produce_dialog(screen, info)
    dialog = dialogs[0]
    fields = [widget for widget in dialog.content_cls.walk() if isinstance(widget, MDTextField)]
    quantity = next(widget for widget in fields if widget.hint_text == "Quantidade de unidades")
    quantity.text = "3"
    dialog.buttons[2].dispatch("on_release")
    assert len(screen.cart_items) == 1
    assert screen.cart_items[0]["total"] == 15
    assert screen.cart_items[0]["produce_sale_mode"] == "unit"
    screen.show_message.assert_not_called()
