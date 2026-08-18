from datetime import datetime, timedelta

from utils.business.sales_transactions import group_sale_records, refund_window_status


def test_groups_multiple_products_into_one_transaction_and_keeps_legacy_separate():
    now = datetime(2026, 8, 6, 10, 5, 0)
    records = [
        {
            "sale_id": 1, "transaction_code": "TX-100", "sale_date": "2026-08-06 10:00:00",
            "product": "Arroz", "qty": 1, "price": 40, "total": 40,
            "returned_qty": 0, "available_qty": 1, "created_by": "mirson",
        },
        {
            "sale_id": 2, "transaction_code": "TX-100", "sale_date": "2026-08-06 10:00:00",
            "product": "Oleo", "qty": 2, "price": 50, "total": 100,
            "returned_qty": 0, "available_qty": 2, "created_by": "mirson",
        },
        {
            "sale_id": 3, "transaction_code": "", "sale_date": "2026-08-06 09:50:00",
            "product": "Sal", "qty": 1, "price": 20, "total": 20,
            "returned_qty": 0, "available_qty": 1, "created_by": "mirson",
        },
    ]

    grouped = group_sale_records(records, now=now)

    assert len(grouped) == 2
    assert grouped[0]["item_count"] == 2
    assert grouped[0]["quantity"] == 3
    assert grouped[0]["net_total"] == 140
    assert grouped[0]["can_refund"] is True
    assert grouped[1]["transaction_key"] == "sale:3"
    assert grouped[1]["can_refund"] is False


def test_refund_window_closes_after_ten_minutes():
    now = datetime(2026, 8, 6, 10, 11, 0)
    allowed, seconds_left = refund_window_status("2026-08-06 10:00:00", now=now)

    assert allowed is False
    assert seconds_left == 0
