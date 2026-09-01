from api.api_manager import APIManager
from admin.product_form import ProductForm


def test_not_found_payload_is_not_a_product():
    payload = {"barcode": "6000000000000", "name": "Nenhum produto encontrado."}

    assert APIManager._is_placeholder_result(payload) is True
    assert ProductForm._has_usable_product_payload(payload) is False


def test_real_product_payload_remains_usable():
    payload = {"barcode": "6000000000000", "name": "Produto de teste", "price": "25"}

    assert ProductForm._has_usable_product_payload(payload) is True
