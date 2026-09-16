"""Restaura os índices secundários da tabela products numa base de stress."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from time import perf_counter


INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_products_status ON products (status)",
    "CREATE INDEX IF NOT EXISTS idx_products_owner_status ON products (COALESCE(owner_username, ''), status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products (sku)",
    "CREATE INDEX IF NOT EXISTS idx_products_barcode ON products (barcode)",
    "CREATE INDEX IF NOT EXISTS idx_products_description ON products (description)",
    "CREATE INDEX IF NOT EXISTS idx_products_category ON products (category)",
    "CREATE INDEX IF NOT EXISTS idx_products_date_added ON products (date_added)",
    "CREATE INDEX IF NOT EXISTS idx_products_sale_filter ON products (status, expiry_date, existing_stock)",
    "CREATE INDEX IF NOT EXISTS idx_products_barcode_normalized ON products (LOWER(TRIM(barcode))) WHERE barcode IS NOT NULL AND TRIM(barcode) <> ''",
    "CREATE INDEX IF NOT EXISTS idx_products_owner_barcode_normalized ON products (COALESCE(owner_username, ''), LOWER(TRIM(barcode))) WHERE barcode IS NOT NULL AND TRIM(barcode) <> ''",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    started = perf_counter()
    with sqlite3.connect(args.database, timeout=120) as conn:
        conn.execute("PRAGMA busy_timeout = 120000")
        for statement in INDEXES:
            conn.execute(statement)
            conn.commit()
            print(statement.split(" ON ", 1)[0].replace("CREATE INDEX IF NOT EXISTS ", ""), flush=True)
        conn.execute("ANALYZE")
        conn.commit()
    print(f"elapsed_s={perf_counter() - started:.2f}")


if __name__ == "__main__":
    main()
