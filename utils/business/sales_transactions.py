"""Regras de apresentacao e prazo de estorno das transacoes de venda."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Iterable


REFUND_WINDOW_MINUTES = 10


def parse_sale_datetime(value: Any) -> datetime | None:
    """Converte as datas legadas e atuais de venda sem depender da interface."""
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(microsecond=0)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def transaction_key(transaction_code: Any, sale_id: Any) -> str:
    """Agrupa linhas do mesmo carrinho, sem fundir registos antigos sem codigo."""
    code = str(transaction_code or "").strip()
    return code or f"sale:{sale_id}"


def refund_window_status(sale_date: Any, now: datetime | None = None) -> tuple[bool, int]:
    """Indica se a venda ainda pode ser estornada e os segundos restantes."""
    sale_dt = parse_sale_datetime(sale_date)
    if sale_dt is None:
        return False, 0
    now_dt = (now or datetime.now()).replace(microsecond=0)
    elapsed_seconds = max(0, int((now_dt - sale_dt).total_seconds()))
    remaining_seconds = int(timedelta(minutes=REFUND_WINDOW_MINUTES).total_seconds()) - elapsed_seconds
    return remaining_seconds >= 0, max(0, remaining_seconds)


def group_sale_records(records: Iterable[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """Agrupa as linhas de produtos em uma unica venda por transacao."""
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for index, record in enumerate(records or []):
        sale_id = record.get("sale_id")
        key = transaction_key(record.get("transaction_code"), sale_id if sale_id is not None else index)
        sale_date = record.get("sale_date") or ""
        sale_dt = parse_sale_datetime(sale_date)
        group = grouped.get(key)
        if group is None:
            group = {
                "transaction_key": key,
                "transaction_code": str(record.get("transaction_code") or "").strip(),
                "sale_date": sale_date,
                "sale_dt": sale_dt,
                "created_by": record.get("created_by") or "",
                "items": [],
                "gross_total": 0.0,
                "refunded_total": 0.0,
                "net_total": 0.0,
                "quantity": 0.0,
                "is_promotional": False,
            }
            grouped[key] = group
        group["items"].append(record)
        quantity = float(record.get("qty") or 0.0)
        price = float(record.get("price") or 0.0)
        total = float(record.get("total") or 0.0)
        refunded_qty = float(record.get("returned_qty") or 0.0)
        refunded_total = refunded_qty * price
        group["quantity"] += quantity
        group["gross_total"] += total
        group["refunded_total"] += refunded_total
        group["net_total"] += max(0.0, total - refunded_total)
        group["is_promotional"] = bool(group["is_promotional"] or record.get("is_promotional"))

    transactions = []
    for group in grouped.values():
        can_refund, seconds_left = refund_window_status(group["sale_date"], now=now)
        group["item_count"] = len(group["items"])
        group["can_refund"] = bool(
            can_refund
            and any(float(item.get("available_qty") or 0.0) > 0.0001 for item in group["items"])
        )
        group["refund_seconds_left"] = seconds_left
        transactions.append(group)
    return transactions
