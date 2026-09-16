"""Gera uma base SQLite isolada para stress do SIGE MPE.

Exemplo:
    python scripts/generate_stress_dataset.py --target J:\\loja_stress\\inventory_stress_15m.db

O gerador nunca altera a base de origem. Pode ser retomado: cada conjunto usa
prefixos exclusivos e o número já criado é conferido antes de inserir lotes.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter


PRODUCT_PREFIX = "STRESS15M-"
SALE_PREFIX = "STRESS15M-SALE-"
OWNER = "joe"
CATEGORIES = ("Mercearia", "Bebidas", "Higiene", "Casa", "Frescos", "Tecnologia")
PAYMENTS = ("cash", "card", "mobile", "emola")
ALERT_TYPES = ("PRICE_ANOMALY", "STOCK_RISK", "REPEATED_VOID", "UNUSUAL_SALE")


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)


def _batches(start: int, stop: int, size: int):
    for first in range(start, stop, size):
        yield first, min(stop, first + size)


def _month_for(index: int) -> datetime:
    month_index = index % 60
    return datetime(2021 + month_index // 12, month_index % 12 + 1, (index % 27) + 1, 8 + (index % 11), index % 60)


def _insert_products(conn: sqlite3.Connection, count: int, batch_size: int) -> int:
    existing = conn.execute("SELECT COUNT(*) FROM products WHERE barcode LIKE ?", (f"{PRODUCT_PREFIX}%",)).fetchone()[0]
    now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    for first, stop in _batches(existing + 1, count + 1, batch_size):
        rows = []
        for index in range(first, stop):
            category = CATEGORIES[index % len(CATEGORIES)]
            cost = round(2.5 + (index % 900) * 0.17, 2)
            price = round(cost * (1.12 + (index % 23) / 100), 2)
            rows.append((
                f"Produto stress {category} {index:08d}", category, float(20 + index % 480),
                float(index % 19), price, round(cost * (20 + index % 480), 2), cost,
                round(price - cost, 2), f"{PRODUCT_PREFIX}{index:08d}",
                f"{2030 + index % 6}-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}",
                now, 1 if index % 41 == 0 else 0, "1 un", "PERTO_DO_PRAZO" if index % 97 == 0 else "ATIVO",
                "TESTE_STRESS", "Carga sintetica de desempenho", now, OWNER,
                f"STRESS15M-SKU-{index:08d}", None, 0, "STANDARD", OWNER,
            ))
        conn.executemany(
            """INSERT INTO products (description, category, existing_stock, sold_stock, sale_price,
               total_purchase_price, unit_purchase_price, profit_per_unit, barcode, expiry_date,
               date_added, is_sold_by_weight, package_quantity, status, status_source, status_reason,
               status_updated_at, status_updated_by, sku, units_per_package, allow_pack_sale,
               vat_rule_code, owner_username) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        conn.commit()
        print(f"products {stop - 1:,}/{count:,}", flush=True)
    return count


def _stress_product_bounds(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute("SELECT MIN(id), MAX(id) FROM products WHERE barcode LIKE ?", (f"{PRODUCT_PREFIX}%",)).fetchone()
    if not row or row[0] is None:
        raise RuntimeError("Nenhum produto de stress foi criado")
    return int(row[0]), int(row[1])


def _insert_sales(conn: sqlite3.Connection, total: int, batch_size: int) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM sales WHERE transaction_code LIKE ?", (f"{SALE_PREFIX}%",)).fetchone()[0]
    low, high = _stress_product_bounds(conn)
    span = high - low + 1
    for first, stop in _batches(existing + 1, total + 1, batch_size):
        sales, transactions = [], []
        for index in range(first, stop):
            product_id = low + ((index * 7919) % span)
            quantity = float((index % 7) + 1)
            price = round(3 + (index % 700) * 0.23, 2)
            total_price = round(quantity * price, 2)
            created_at = _month_for(index).strftime("%Y-%m-%d %H:%M:%S")
            code = f"{SALE_PREFIX}{index:09d}"
            payment = PAYMENTS[index % len(PAYMENTS)]
            sales.append((product_id, quantity, price, total_price, created_at, OWNER, "admin", f"POS-{index % 12 + 1:02d}", index % 11 == 0, "STANDARD", "IVA 16%", 16.0, 1.0, round(total_price / 1.16, 2), round(total_price - total_price / 1.16, 2), total_price, OWNER, code, payment, 0.0, None, None, None))
            transactions.append((code, created_at, OWNER, "admin", f"POS-{index % 12 + 1:02d}", payment, None, 1, "COMPLETED", OWNER))
        conn.executemany("""INSERT INTO sales (product_id, quantity, sale_price, total_price, sale_date,
            created_by, created_role, terminal_id, is_promotional, vat_rule_code, vat_label,
            vat_rate_percent, vat_taxable_ratio, net_total, vat_amount, gross_total, owner_username,
            transaction_code, payment_method, discount_amount, discount_reason, discount_authorized_by,
            cash_session_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", sales)
        conn.executemany("INSERT INTO sale_transactions (transaction_code, created_at, created_by, created_role, terminal_id, payment_method, cash_session_id, item_count, status, owner_username) VALUES (?,?,?,?,?,?,?,?,?,?)", transactions)
        conn.commit()
        print(f"sales {stop - 1:,}/{total:,}", flush=True)


def _insert_alerts(conn: sqlite3.Connection, total: int, batch_size: int) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM fraud_alerts WHERE description LIKE 'Stress dataset:%'").fetchone()[0]
    low, high = _stress_product_bounds(conn)
    span = high - low + 1
    for first, stop in _batches(existing + 1, total + 1, batch_size):
        rows = []
        for index in range(first, stop):
            alert_type = ALERT_TYPES[index % len(ALERT_TYPES)]
            created_at = _month_for(index * 13).strftime("%Y-%m-%d %H:%M:%S")
            rows.append((alert_type, (index % 5) + 1, f"Stress {alert_type} {index:07d}", f"Stress dataset: alerta sintetico {index:07d}", OWNER, low + ((index * 3571) % span), None, f'{{"scenario":{index % 12},"monthly":true}}', "REVIEWED" if index % 4 == 0 else "OPEN", created_at, OWNER if index % 4 == 0 else None, created_at if index % 4 == 0 else None, "Validacao automatizada" if index % 4 == 0 else None, OWNER))
        conn.executemany("""INSERT INTO fraud_alerts (alert_type, severity, title, description, related_user,
            related_product_id, related_movement_id, data_json, status, created_at, reviewed_by,
            reviewed_at, resolution_note, owner_username) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        conn.commit()
        print(f"alerts {stop - 1:,}/{total:,}", flush=True)


def _insert_stock_movements(conn: sqlite3.Connection, total: int, batch_size: int) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM stock_movements WHERE note LIKE 'Stress dataset:%'").fetchone()[0]
    low, high = _stress_product_bounds(conn)
    span = high - low + 1
    for first, stop in _batches(existing + 1, total + 1, batch_size):
        rows = []
        for index in range(first, stop):
            qty = float((index % 40) + 1)
            unit_cost = round(2 + (index % 500) * 0.11, 2)
            unit_price = round(unit_cost * 1.25, 2)
            movement_type = "RESTOCK" if index % 3 else "ADJUSTMENT"
            direction = "IN" if movement_type == "RESTOCK" else "OUT"
            created_at = _month_for(index * 7).strftime("%Y-%m-%d %H:%M:%S")
            rows.append((low + ((index * 4253) % span), movement_type, direction, qty, "UN", unit_cost,
                         unit_price, round(qty * unit_cost, 2), round(qty * unit_price, 2), 100.0,
                         100.0 + qty if direction == "IN" else 100.0 - qty, "Stress automatizado",
                         f"Stress dataset: movimento {index:08d}", None, "stress_generator", index,
                         created_at, OWNER, "admin", f"POS-{index % 12 + 1:02d}", "APPROVED", OWNER,
                         created_at, 1, "Fornecedor Stress", f"STRESS-INV-{index:08d}", OWNER))
        conn.executemany("""INSERT INTO stock_movements (product_id, movement_type, direction, qty, unit,
            unit_cost, unit_price, total_cost, total_price, stock_before, stock_after, reason, note,
            evidence_path, reference_table, reference_id, created_at, created_by, created_role, terminal_id,
            approval_status, approved_by, approved_at, applied, supplier_name, invoice_number, owner_username)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        conn.commit()
        print(f"stock_movements {stop - 1:,}/{total:,}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("database/inventory.db"))
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--products", type=int, default=15_000_000)
    parser.add_argument("--sales", type=int, default=600_000)
    parser.add_argument("--alerts", type=int, default=100_000)
    parser.add_argument("--stock-movements", type=int, default=200_000)
    parser.add_argument("--batch-size", type=int, default=50_000)
    args = parser.parse_args()
    if min(args.products, args.sales, args.alerts, args.stock_movements, args.batch_size) < 1:
        parser.error("todos os totais devem ser positivos")
    _copy_database(args.source.resolve(), args.target.resolve())
    started = perf_counter()
    with sqlite3.connect(args.target, timeout=60) as conn:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute("PRAGMA foreign_keys = ON")
        _insert_products(conn, args.products, args.batch_size)
        _insert_sales(conn, args.sales, args.batch_size)
        _insert_alerts(conn, args.alerts, args.batch_size)
        _insert_stock_movements(conn, args.stock_movements, args.batch_size)
        conn.execute("ANALYZE")
        conn.commit()
        summary = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("products", "sales", "sale_transactions", "fraud_alerts", "stock_movements")}
        print({"target": str(args.target.resolve()), "rows": summary, "elapsed_s": round(perf_counter() - started, 2)})


if __name__ == "__main__":
    main()
