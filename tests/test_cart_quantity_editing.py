"""Exercise the cart handlers without starting the graphical application."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

source = Path(__file__).resolve().parents[1] / "manager" / "manager_screen.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
           and node.name in {"update_qty", "schedule_qty_update", "finalize_sale"}]
namespace = {"_safe_float": lambda value, default=0: float(value or default),
             "_format_money": lambda value: str(value)}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)


@pytest.mark.parametrize("mode,units", [("unit", 1), ("pack", 6)])
def test_empty_and_zero_preserve_item_and_allow_retyping(mode, units):
    item = dict(qty=2, qty_units=2 * units, price=10, total=20,
                sale_mode=mode, pack_units=units, max_stock=100)
    label = SimpleNamespace(text="20")
    cart = SimpleNamespace(cart_items=[item], _qty_update_events={},
        _cart_row_widgets=[SimpleNamespace(quantity_total_label=label)],
        recalculate_totals=lambda: None, _update_action_states=lambda: None)
    cart.update_qty = lambda index, value: namespace["update_qty"](cart, index, value)
    for raw, expected in [("", 0), ("0", 0), ("3", 3)]:
        namespace["schedule_qty_update"](cart, 0, raw)
        assert cart.cart_items == [item]
        assert item["qty"] == expected
        assert item["qty_units"] == expected * units
        assert item["qty_text"] == raw
        assert cart.total_amount == expected * 10
        assert label.text == str(expected * 10)


def test_sale_cannot_commit_zero_quantity():
    messages = []
    cart = SimpleNamespace(_sale_submitting=False, cart_items=[{"qty": 0}],
                           show_message=messages.append)
    namespace["finalize_sale"](cart)
    assert messages == ["Informe uma quantidade maior que zero ou remova o artigo."]
