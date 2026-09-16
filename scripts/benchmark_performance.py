"""Benchmark isolado: nunca abre a base real da loja.

python scripts/benchmark_performance.py --baseline-source <database.py anterior>
O baseline e opcional; apenas os dois metodos comparados sao extraidos por AST.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import database.database as database_module


def original_method(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Database")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = vars(database_module).copy()
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def measure(db, callback, repeats=3):
    times = []
    for _ in range(repeats):
        started = perf_counter()
        result = callback()
        times.append((perf_counter() - started) * 1000)
    statements = []
    before = db.conn.total_changes
    db.conn.set_trace_callback(statements.append)
    try:
        callback()
    finally:
        db.conn.set_trace_callback(None)
    return {
        "median_ms": round(statistics.median(times), 3),
        "sql_statements": len(statements),
        "changed_rows": db.conn.total_changes - before,
    }, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--products", type=int, default=1000)
    parser.add_argument("--sales", type=int, default=30000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.products < 1 or args.sales < 0:
        parser.error("products deve ser positivo e sales nao negativo")
    output = {"products": args.products, "sales": args.sales, "repeats": 3}
    with tempfile.TemporaryDirectory(prefix="loja_perf_") as folder:
        with contextlib.redirect_stdout(io.StringIO()):
            db = database_module.Database(db_path=str(Path(folder) / "synthetic.sqlite3"))
        try:
            now = datetime.now()
            db.conn.executemany(
                "INSERT INTO products (id, description, existing_stock, sold_stock, sale_price, "
                "total_purchase_price, unit_purchase_price, profit_per_unit, date_added, owner_username, sku) "
                "VALUES (?, ?, 1, 20, 10, 100, 5, 5, ?, 'shop', ?)",
                [(i, f"Produto {i}", now.isoformat(), db._build_sku(i, f"Produto {i}"))
                 for i in range(1, args.products + 1)],
            )
            db.conn.executemany(
                "INSERT INTO sales (product_id, quantity, sale_price, total_price, sale_date, owner_username) VALUES (?, 1, 10, 10, ?, 'shop')",
                [((i % args.products) + 1, (now - timedelta(days=i % 180)).strftime("%Y-%m-%d %H:%M:%S"))
                 for i in range(args.sales)],
            )
            db.conn.commit()
            db.current_data_owner = "shop"
            if args.baseline_source:
                sku_before = original_method(args.baseline_source, "_rebuild_all_skus")
                insights_before = original_method(args.baseline_source, "get_admin_insights")
                db.conn.execute("DROP INDEX idx_sales_owner_day")
                output["sku_before"], _ = measure(db, lambda: sku_before(db))
                output["insights_before"], old = measure(db, lambda: insights_before(db))
                db.conn.execute("CREATE INDEX idx_sales_owner_day ON sales (COALESCE(owner_username, ''), DATE(sale_date))")
                db.conn.commit()
            output["sku_after"], _ = measure(db, db._rebuild_all_skus)
            output["insights_after"], current = measure(db, db.get_admin_insights)
            if args.baseline_source:
                output["identical_insights"] = old == current
                if old != current:
                    raise AssertionError("Os insights mudaram entre baseline e versao otimizada")
            output["history_query_plan"] = db.conn.execute(
                "EXPLAIN QUERY PLAN SELECT SUM(total_price) FROM sales_history "
                "WHERE COALESCE(owner_username, '') = ? AND DATE(sale_date) = ?",
                ("shop", now.date().isoformat()),
            ).fetchall()
        finally:
            db.close()
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
