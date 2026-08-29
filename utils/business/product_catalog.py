"""Shared, UI-independent product catalogue grouping helpers."""

from datetime import datetime


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_product_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_catalog_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def admin_catalog_key(product):
    barcode = str(product[12] if len(product) > 12 and product[12] is not None else "").strip().lower()
    if barcode:
        return f"bc:{barcode}"

    description = " ".join(str(product[1] if len(product) > 1 and product[1] is not None else "").split()).lower()
    category = " ".join(str(product[11] if len(product) > 11 and product[11] is not None else "").split()).lower()
    sale_price = round(safe_float(product[4] if len(product) > 4 else 0.0), 4)
    is_weight = 1 if (len(product) > 15 and bool(product[15])) else 0
    units_per_package = (
        int(safe_float(product[23], 0))
        if len(product) > 23 and product[23] not in (None, "")
        else 0
    )
    allow_pack_sale = 1 if (len(product) > 24 and bool(product[24])) else 0
    vat_rule = str(product[25] if len(product) > 25 and product[25] not in (None, "") else "STANDARD").strip().upper()
    return (
        f"desc:{description}|cat:{category}|w:{is_weight}|p:{sale_price:.4f}|"
        f"u:{units_per_package}|a:{allow_pack_sale}|v:{vat_rule}"
    )


def aggregate_admin_product_rows(rows, selected_lot_ids_by_catalog_key=None):
    """Aggregate sibling product lots into the tuple shape used by AdminScreen."""
    selected_lot_ids_by_catalog_key = dict(selected_lot_ids_by_catalog_key or {})

    def lot_sort_key(product):
        expiry_dt = parse_catalog_date(product[13] if len(product) > 13 else "")
        product_id = normalize_product_id(product[0] if product else None) or 0
        return (1 if expiry_dt is None else 0, expiry_dt or datetime.max, product_id)

    def representative_group_row(bucket_rows):
        def priority(row):
            status = str(row[16] if len(row) > 16 and row[16] is not None else "").strip().upper()
            if "EXPIR" in status:
                status_rank = 0
            elif "PERTO" in status:
                status_rank = 1
            elif "ATIVO" in status:
                status_rank = 2
            else:
                status_rank = 3
            expiry_dt = parse_catalog_date(row[13] if len(row) > 13 else "")
            missing_expiry = 1 if expiry_dt is None else 0
            row_id = normalize_product_id(row[0] if row else None) or 0
            return (status_rank, missing_expiry, expiry_dt or datetime.max, -row_id)

        return min(bucket_rows, key=priority)

    grouped = {}
    ordered_keys = []
    for row in list(rows or []):
        if not row:
            continue
        catalog_key = admin_catalog_key(row)
        if catalog_key not in grouped:
            grouped[catalog_key] = []
            ordered_keys.append(catalog_key)
        grouped[catalog_key].append(row)

    aggregated = []
    for catalog_key in ordered_keys:
        bucket_rows = grouped[catalog_key]
        representative = representative_group_row(bucket_rows)
        ordered_bucket_rows = sorted(bucket_rows, key=lot_sort_key)
        source_ids = tuple(
            product_id
            for product_id in (normalize_product_id(row[0] if row else None) for row in bucket_rows)
            if product_id is not None
        )
        lot_count = len(source_ids) or 1
        selected_lot_id = normalize_product_id(selected_lot_ids_by_catalog_key.get(catalog_key))
        selected_row = next(
            (row for row in bucket_rows if normalize_product_id(row[0] if row else None) == selected_lot_id),
            None,
        )
        selected_lot_position = None
        if selected_row is not None:
            selected_lot_position = next(
                (
                    idx
                    for idx, row in enumerate(ordered_bucket_rows, start=1)
                    if normalize_product_id(row[0] if row else None) == selected_lot_id
                ),
                None,
            )
        else:
            selected_lot_id = None

        display_row = selected_row or representative
        if selected_row is not None:
            existing_stock = safe_float(display_row[2])
            sold_stock = safe_float(display_row[3])
            total_purchase_price = safe_float(display_row[5])
            unit_purchase_price = safe_float(display_row[6])
            sale_price = safe_float(display_row[4])
            profit_per_unit = safe_float(display_row[7])
            total_profit = safe_float(display_row[8])
            profit_percentage = safe_float(display_row[9])
            price_percentage = safe_float(display_row[10])
            expiry_value = display_row[13] if len(display_row) > 13 else ""
            date_added = display_row[14] if len(display_row) > 14 else ""
            barcode_value = display_row[12] if len(display_row) > 12 else ""
            sku_value = display_row[22] if len(display_row) > 22 else ""
        else:
            existing_stock = sum(safe_float(row[2]) for row in bucket_rows)
            sold_stock = sum(safe_float(row[3]) for row in bucket_rows)
            total_purchase_price = sum(safe_float(row[5]) for row in bucket_rows)
            total_profit = sum(safe_float(row[8]) for row in bucket_rows)
            sold_cost_total = sum(safe_float(row[6]) * safe_float(row[3]) for row in bucket_rows)
            if existing_stock > 1e-9:
                unit_purchase_price = total_purchase_price / existing_stock
            elif sold_stock > 1e-9:
                unit_purchase_price = sold_cost_total / sold_stock
            else:
                unit_purchase_price = safe_float(representative[6])
            sale_price = safe_float(representative[4])
            profit_per_unit = sale_price - unit_purchase_price
            profit_percentage = (total_profit * 100.0 / sold_cost_total) if sold_cost_total > 1e-9 else 0.0
            price_percentage = ((sale_price - unit_purchase_price) / unit_purchase_price * 100.0) if unit_purchase_price > 1e-9 else 0.0

            expiry_candidates = [row[13] for row in bucket_rows if len(row) > 13 and str(row[13] or "").strip()]
            expiry_value = min(expiry_candidates, key=lambda value: parse_catalog_date(value) or datetime.max) if expiry_candidates else representative[13]
            date_added_candidates = [row[14] for row in bucket_rows if len(row) > 14 and str(row[14] or "").strip()]
            date_added = min(date_added_candidates, key=lambda value: parse_catalog_date(value) or datetime.max) if date_added_candidates else representative[14]
            barcode_value = next((row[12] for row in bucket_rows if len(row) > 12 and str(row[12] or "").strip()), representative[12] if len(representative) > 12 else "")
            sku_value = next((row[22] for row in bucket_rows if len(row) > 22 and str(row[22] or "").strip()), representative[22] if len(representative) > 22 else "")

        aggregated.append((
            display_row[0], display_row[1], existing_stock, sold_stock, sale_price,
            total_purchase_price, unit_purchase_price, profit_per_unit, total_profit,
            profit_percentage, price_percentage, display_row[11], barcode_value,
            expiry_value, date_added, display_row[15], display_row[16], display_row[17],
            display_row[18], display_row[19], display_row[20], display_row[21], sku_value,
            display_row[23], display_row[24], display_row[25], catalog_key, lot_count,
            source_ids, selected_lot_id, selected_lot_position,
        ))
    return aggregated


def rebuild_admin_display_ids(aggregated_rows, start=1):
    display_ids = {}
    for index, row in enumerate(list(aggregated_rows or []), start=max(1, int(start or 1))):
        source_ids = row[28] if len(row) > 28 and row[28] else (row[0],)
        for value in source_ids:
            product_id = normalize_product_id(value)
            if product_id is not None:
                display_ids[product_id] = index
    return display_ids
