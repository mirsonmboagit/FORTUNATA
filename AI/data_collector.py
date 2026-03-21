"""Camada de coleta de dados para a monitorizacao inteligente."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, pstdev
from threading import Lock
from typing import Any, Callable


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


class IntelligenceDataCollector:
    """Coleta dados operacionais a partir do SQLite sem tocar na UI."""

    def __init__(self, db: Any | None = None, default_ttl: float = 20.0) -> None:
        self.db = db
        self.default_ttl = max(5.0, float(default_ttl))
        self.db_path = self._resolve_db_path(db)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = Lock()

    def collect_snapshot(self) -> dict[str, Any]:
        """Agrupa todas as consultas reutilizando uma unica conexao."""
        return self._cached("snapshot", self.default_ttl, self._build_snapshot)

    def get_vendas_hoje(self) -> dict[str, Any]:
        """Faturamento e volume acumulados do dia atual."""
        return self.collect_snapshot()["vendas_hoje"]

    def get_media_semanal(self) -> dict[str, Any]:
        """Media diaria das ultimas 7 jornadas completas."""
        return self.collect_snapshot()["media_semanal"]

    def get_stock_produtos(self) -> list[dict[str, Any]]:
        """Estado atual de stock com baseline operacional por produto."""
        return self.collect_snapshot()["stock_produtos"]

    def get_vendas_por_produto(self) -> list[dict[str, Any]]:
        """Historico consolidado de vendas por produto."""
        return self.collect_snapshot()["vendas_por_produto"]

    def get_atividade_caixa(self) -> dict[str, Any]:
        """Metricas de produtividade e atividade dos caixas."""
        return self.collect_snapshot()["atividade_caixa"]

    def _build_snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            stock_produtos = self._query_stock_produtos(conn)
            vendas_por_produto = self._query_vendas_por_produto(conn)
            return {
                "coletado_em": datetime.now(),
                "vendas_hoje": self._query_vendas_hoje(conn),
                "media_semanal": self._query_media_semanal(conn),
                "stock_produtos": stock_produtos,
                "vendas_por_produto": vendas_por_produto,
                "atividade_caixa": self._query_atividade_caixa(conn),
                "banner_insights": self._build_banner_insights(stock_produtos),
            }

    def _cached(self, key: str, ttl: float, builder: Callable[[], Any]) -> Any:
        now = datetime.now().timestamp()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= ttl:
                return cached[1]
        payload = builder()
        with self._cache_lock:
            self._cache[key] = (now, payload)
        return payload

    def _resolve_db_path(self, db: Any | None) -> str:
        if getattr(db, "db_path", None):
            return os.path.abspath(str(db.db_path))

        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        server_config = os.path.join(root_dir, "server", "config.json")
        if os.path.exists(server_config):
            try:
                with open(server_config, "r", encoding="utf-8") as handle:
                    cfg = json.load(handle) or {}
                db_path = cfg.get("db_path")
                if db_path:
                    return os.path.abspath(db_path)
            except Exception:
                pass

        return os.path.join(root_dir, "database", "inventory.db")

    def _connect(self) -> sqlite3.Connection:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Banco SQLite nao encontrado: {self.db_path}")
        return sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)

    def _query_vendas_hoje(self, conn: sqlite3.Connection) -> dict[str, Any]:
        today = date.today().isoformat()
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(total_price), 0) AS total,
                COUNT(*) AS vendas,
                COALESCE(SUM(quantity), 0) AS itens,
                COALESCE(AVG(total_price), 0) AS ticket_medio,
                MIN(sale_date) AS primeira_venda,
                MAX(sale_date) AS ultima_venda
            FROM sales
            WHERE DATE(sale_date) = ?
            """,
            (today,),
        ).fetchone()

        hourly_rows = conn.execute(
            """
            SELECT
                strftime('%H', sale_date) AS hora,
                COALESCE(SUM(total_price), 0) AS total,
                COUNT(*) AS vendas
            FROM sales
            WHERE DATE(sale_date) = ?
            GROUP BY strftime('%H', sale_date)
            ORDER BY hora
            """,
            (today,),
        ).fetchall()

        return {
            "data": today,
            "total": _safe_float(row["total"]),
            "vendas": int(row["vendas"] or 0),
            "itens": _safe_float(row["itens"]),
            "ticket_medio": _safe_float(row["ticket_medio"]),
            "primeira_venda": row["primeira_venda"],
            "ultima_venda": row["ultima_venda"],
            "por_hora": [
                {
                    "hora": str(item["hora"]),
                    "total": _safe_float(item["total"]),
                    "vendas": int(item["vendas"] or 0),
                }
                for item in hourly_rows
            ],
        }

    def _query_media_semanal(self, conn: sqlite3.Connection, days: int = 7) -> dict[str, Any]:
        today = date.today()
        start_date = today - timedelta(days=days)
        raw_rows = conn.execute(
            """
            SELECT
                DATE(sale_date) AS dia,
                COALESCE(SUM(total_price), 0) AS total,
                COUNT(*) AS vendas
            FROM sales
            WHERE DATE(sale_date) >= ? AND DATE(sale_date) < ?
            GROUP BY DATE(sale_date)
            ORDER BY dia
            """,
            (start_date.isoformat(), today.isoformat()),
        ).fetchall()

        indexed = {
            str(row["dia"]): {
                "data": str(row["dia"]),
                "total": _safe_float(row["total"]),
                "vendas": int(row["vendas"] or 0),
            }
            for row in raw_rows
        }

        series = []
        totals = []
        counts = []
        for offset in range(days, 0, -1):
            day_value = today - timedelta(days=offset)
            day_key = day_value.isoformat()
            payload = indexed.get(day_key, {"data": day_key, "total": 0.0, "vendas": 0})
            series.append(payload)
            totals.append(_safe_float(payload["total"]))
            counts.append(int(payload["vendas"]))

        return {
            "dias_considerados": days,
            "media_total": mean(totals) if totals else 0.0,
            "media_vendas": mean(counts) if counts else 0.0,
            "desvio_total": pstdev(totals) if len(totals) > 1 else 0.0,
            "serie_diaria": series,
        }

    def _query_stock_produtos(
        self,
        conn: sqlite3.Connection,
        history_days: int = 30,
    ) -> list[dict[str, Any]]:
        start_date = (date.today() - timedelta(days=history_days)).isoformat()
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.description,
                COALESCE(p.existing_stock, 0) AS stock_atual,
                COALESCE(p.is_sold_by_weight, 0) AS is_weight,
                p.expiry_date AS expiry_date,
                COALESCE(p.sale_price, 0) AS preco_tabela,
                COALESCE(p.unit_purchase_price, 0) AS custo_unitario,
                COALESCE(p.status, 'ATIVO') AS status,
                COALESCE(hist.qty_total, 0) AS qty_historica,
                COALESCE(hist.rev_total, 0) AS receita_historica,
                hist.last_sale_at,
                COALESCE(today.qty_today, 0) AS qty_hoje
            FROM products p
            LEFT JOIN (
                SELECT
                    product_id,
                    COALESCE(SUM(quantity), 0) AS qty_total,
                    COALESCE(SUM(total_price), 0) AS rev_total,
                    MAX(sale_date) AS last_sale_at
                FROM sales
                WHERE DATE(sale_date) >= ?
                GROUP BY product_id
            ) hist ON hist.product_id = p.id
            LEFT JOIN (
                SELECT product_id, COALESCE(SUM(quantity), 0) AS qty_today
                FROM sales
                WHERE DATE(sale_date) = DATE('now')
                GROUP BY product_id
            ) today ON today.product_id = p.id
            WHERE COALESCE(p.status, 'ATIVO') != 'INATIVO'
            ORDER BY p.description COLLATE NOCASE
            """,
            (start_date,),
        ).fetchall()

        products = []
        now = datetime.now()
        for row in rows:
            avg_daily_qty = _safe_float(row["qty_historica"]) / max(history_days, 1)
            is_weight = bool(row["is_weight"])
            stock_min = max(0.5 if is_weight else 1.0, round(avg_daily_qty * 3, 2))
            last_sale_at = _parse_datetime(row["last_sale_at"])
            last_sale_days = None
            if last_sale_at:
                last_sale_days = max(0, (now.date() - last_sale_at.date()).days)

            products.append(
                {
                    "id": int(row["id"]),
                    "descricao": str(row["description"]),
                    "stock_atual": _safe_float(row["stock_atual"]),
                    "stock_minimo": stock_min,
                    "is_weight": is_weight,
                    "expiry_date": row["expiry_date"],
                    "preco_tabela": _safe_float(row["preco_tabela"]),
                    "custo_unitario": _safe_float(row["custo_unitario"]),
                    "status": str(row["status"] or "ATIVO"),
                    "qty_historica": _safe_float(row["qty_historica"]),
                    "receita_historica": _safe_float(row["receita_historica"]),
                    "media_diaria_qty": avg_daily_qty,
                    "qty_hoje": _safe_float(row["qty_hoje"]),
                    "last_sale_at": row["last_sale_at"],
                    "last_sale_days_ago": last_sale_days,
                }
            )

        return products

    def _build_banner_insights(
        self,
        stock_produtos: list[dict[str, Any]],
        low_threshold: float = 5.0,
        forecast_days: int = 14,
    ) -> dict[str, Any]:
        """Reconstrói os sinais clássicos dos banners de stock e validade."""
        today = date.today()
        low_stock: list[tuple[Any, ...]] = []
        expiring_7: list[tuple[Any, ...]] = []
        expiring_15: list[tuple[Any, ...]] = []
        expiring_90: list[tuple[Any, ...]] = []
        expiry_levels: dict[str, list[tuple[Any, ...]]] = {
            "vencido": [],
            "critico": [],
            "alto": [],
            "medio": [],
            "leve": [],
        }
        forecasts: list[dict[str, Any]] = []
        expiry_risk: list[dict[str, Any]] = []

        for item in stock_produtos:
            descricao = str(item.get("descricao") or "Produto")
            stock_atual = _safe_float(item.get("stock_atual"))
            media_diaria = _safe_float(item.get("media_diaria_qty"))
            is_weight = bool(item.get("is_weight"))
            expiry_date = _parse_datetime(item.get("expiry_date"))
            unit = "kg" if is_weight else "un"
            days_left = None
            recommended_qty = 0.0

            if media_diaria > 0:
                days_left = stock_atual / media_diaria
                recommended_qty = max(0.0, (media_diaria * forecast_days) - stock_atual)

            forecasts.append(
                {
                    "product_id": item.get("id"),
                    "name": descricao,
                    "stock": stock_atual,
                    "unit": unit,
                    "avg_daily": media_diaria,
                    "days_left": days_left,
                    "recommended_qty": recommended_qty,
                }
            )

            if stock_atual <= low_threshold:
                low_stock.append(
                    (
                        descricao,
                        stock_atual,
                        is_weight,
                        days_left if days_left is not None else 999.0,
                        item.get("id"),
                    )
                )

            if not expiry_date:
                continue

            days_to_expiry = (expiry_date.date() - today).days
            formatted_date = expiry_date.strftime("%d/%m/%Y")
            expiry_tuple = (descricao, days_to_expiry, formatted_date, stock_atual, unit)

            if days_to_expiry <= 0:
                expiry_levels["vencido"].append(expiry_tuple)
                continue
            if days_to_expiry <= 7:
                expiring_7.append(expiry_tuple)
                expiry_levels["critico"].append(expiry_tuple)
            elif days_to_expiry <= 15:
                expiring_15.append(expiry_tuple)
                expiry_levels["alto"].append(expiry_tuple)
            elif days_to_expiry <= 30:
                expiry_levels["alto"].append(expiry_tuple)
            elif days_to_expiry <= 60:
                expiry_levels["medio"].append(expiry_tuple)
            elif days_to_expiry <= 90:
                expiry_levels["leve"].append(expiry_tuple)
            if days_to_expiry <= 90:
                expiring_90.append(expiry_tuple)

            if media_diaria > 0:
                days_to_sell = stock_atual / media_diaria
                if days_to_sell > days_to_expiry:
                    unsold_qty = max(0.0, stock_atual - (media_diaria * days_to_expiry))
                    preco_tabela = _safe_float(item.get("preco_tabela"))
                    custo_unitario = _safe_float(item.get("custo_unitario"))
                    expiry_risk.append(
                        {
                            "name": descricao,
                            "days_to_expiry": days_to_expiry,
                            "days_to_sell": days_to_sell,
                            "stock": stock_atual,
                            "unit": unit,
                            "unsold_qty": unsold_qty,
                            "loss_revenue": unsold_qty * preco_tabela,
                            "loss_profit": unsold_qty * (preco_tabela - custo_unitario),
                        }
                    )

        low_stock.sort(key=lambda item: _safe_float(item[1]))
        expiring_7.sort(key=lambda item: int(item[1]))
        expiring_15.sort(key=lambda item: int(item[1]))
        expiring_90.sort(key=lambda item: int(item[1]))
        for level in ("vencido", "critico", "alto", "medio", "leve"):
            expiry_levels[level].sort(key=lambda item: int(item[1]))
        forecasts.sort(key=lambda item: (item["days_left"] is None, item["days_left"] or 9999))
        expiry_risk.sort(key=lambda item: item["days_to_expiry"])

        recommendations: list[str] = []
        recommendations_stock: list[str] = []
        recommendations_expiry: list[str] = []

        for name, stock, is_weight, _days_left, _prod_id in low_stock[:3]:
            unit = "kg" if is_weight else "un"
            text = f"{name}: stock baixo ({stock:.1f} {unit}) - repor"
            recommendations.append(text)
            recommendations_stock.append(text)

        expiry_priority = (
            expiry_levels["vencido"]
            + expiry_levels["critico"]
            + expiry_levels["alto"]
            + expiry_levels["medio"]
            + expiry_levels["leve"]
        )
        for name, days_left, _date_str, _stock, _unit in expiry_priority[:3]:
            if days_left <= 0:
                text = f"{name} vencido - retirar da venda"
            elif days_left <= 7:
                text = f"{name} vence em {days_left} dias - priorizar venda"
            else:
                text = f"{name} vence em {days_left} dias - acompanhar"
            recommendations.append(text)
            recommendations_expiry.append(text)

        if not recommendations:
            recommendations.append("Tudo estavel no momento. Sem riscos imediatos de stock ou validade.")

        alerts = []
        if low_stock:
            alerts.append(f"{len(low_stock)} produtos com stock baixo.")
        if expiry_levels["vencido"]:
            alerts.append(f"{len(expiry_levels['vencido'])} produtos vencidos.")
        if expiry_levels["critico"]:
            alerts.append(f"{len(expiry_levels['critico'])} produtos em alerta critico (7 dias).")
        if expiry_levels["alto"]:
            alerts.append(f"{len(expiry_levels['alto'])} produtos em alerta alto (30 dias).")
        if expiry_levels["medio"]:
            alerts.append(f"{len(expiry_levels['medio'])} produtos em alerta medio (60 dias).")
        if expiry_levels["leve"]:
            alerts.append(f"{len(expiry_levels['leve'])} produtos em alerta leve (90 dias).")

        expiry_total = (
            len(expiry_levels["vencido"])
            + len(expiry_levels["critico"])
            + len(expiry_levels["alto"])
            + len(expiry_levels["medio"])
            + len(expiry_levels["leve"])
        )

        return {
            "alerts": alerts,
            "recommendations": recommendations,
            "recommendations_stock": recommendations_stock,
            "recommendations_expiry": recommendations_expiry,
            "low_stock": low_stock,
            "expiring_15": expiring_15,
            "expiring_7": expiring_7,
            "expiring_90": expiring_90,
            "expiry_levels": expiry_levels,
            "stock_forecast": forecasts[:20],
            "expiry_risk": expiry_risk[:20],
            "alert_count": len(low_stock) + expiry_total,
            "badge_counts": {
                "stock": len(low_stock),
                "expiry_vencido": len(expiry_levels["vencido"]),
                "expiry_critico": len(expiry_levels["critico"]),
                "expiry_alto": len(expiry_levels["alto"]),
                "expiry_medio": len(expiry_levels["medio"]),
                "expiry_leve": len(expiry_levels["leve"]),
                "expiry_total": expiry_total,
                "expiry_7": len(expiring_7),
                "expiry_15": len(expiring_15),
                "total": len(low_stock) + expiry_total,
            },
        }

    def _query_vendas_por_produto(
        self,
        conn: sqlite3.Connection,
        history_days: int = 30,
    ) -> list[dict[str, Any]]:
        start_date = (date.today() - timedelta(days=history_days)).isoformat()
        rows = conn.execute(
            """
            SELECT
                s.product_id,
                COALESCE(p.description, pa.description) AS descricao,
                DATE(s.sale_date) AS dia,
                COALESCE(SUM(s.quantity), 0) AS qty,
                COALESCE(SUM(s.total_price), 0) AS receita,
                COALESCE(AVG(s.sale_price), 0) AS preco_medio,
                COALESCE(MAX(COALESCE(p.sale_price, pa.sale_price, s.sale_price)), 0) AS preco_tabela,
                COALESCE(MAX(COALESCE(p.unit_purchase_price, pa.unit_purchase_price, 0)), 0) AS custo_unitario,
                MAX(s.sale_date) AS ultima_venda
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN products_archive pa ON s.product_id = pa.id
            WHERE DATE(s.sale_date) >= ?
            GROUP BY s.product_id, DATE(s.sale_date)
            ORDER BY descricao COLLATE NOCASE, dia
            """,
            (start_date,),
        ).fetchall()

        today = date.today().isoformat()
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            product_id = int(row["product_id"])
            item = grouped.setdefault(
                product_id,
                {
                    "id": product_id,
                    "descricao": str(row["descricao"]),
                    "preco_tabela": _safe_float(row["preco_tabela"]),
                    "custo_unitario": _safe_float(row["custo_unitario"]),
                    "ultima_venda": row["ultima_venda"],
                    "serie_diaria": [],
                    "qty_hoje": 0.0,
                    "receita_hoje": 0.0,
                },
            )
            qty = _safe_float(row["qty"])
            receita = _safe_float(row["receita"])
            item["serie_diaria"].append(
                {
                    "data": str(row["dia"]),
                    "qty": qty,
                    "receita": receita,
                    "preco_medio": _safe_float(row["preco_medio"]),
                }
            )
            if str(row["dia"]) == today:
                item["qty_hoje"] += qty
                item["receita_hoje"] += receita

        for item in grouped.values():
            historical = [entry for entry in item["serie_diaria"] if entry["data"] != today]
            qty_series = [entry["qty"] for entry in historical]
            item["media_diaria_qty"] = mean(qty_series) if qty_series else 0.0
            item["desvio_qty"] = pstdev(qty_series) if len(qty_series) > 1 else 0.0

        return sorted(grouped.values(), key=lambda item: item["descricao"].lower())

    def _query_atividade_caixa(
        self,
        conn: sqlite3.Connection,
        baseline_days: int = 30,
    ) -> dict[str, Any]:
        start_date = (date.today() - timedelta(days=baseline_days)).isoformat()
        rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(s.terminal_id, ''), 'CAIXA-PRINCIPAL') AS terminal_id,
                s.sale_date,
                COALESCE(s.quantity, 0) AS quantity,
                COALESCE(s.total_price, 0) AS total_price,
                COALESCE(s.sale_price, 0) AS sale_price,
                COALESCE(COALESCE(p.sale_price, pa.sale_price), s.sale_price) AS reference_price,
                COALESCE(COALESCE(p.unit_purchase_price, pa.unit_purchase_price), 0) AS unit_cost,
                COALESCE(s.is_promotional, 0) AS is_promotional
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN products_archive pa ON s.product_id = pa.id
            WHERE DATE(s.sale_date) >= ?
            ORDER BY terminal_id, s.sale_date
            """,
            (start_date,),
        ).fetchall()

        now = datetime.now()
        today = now.date()
        by_terminal: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            sale_dt = _parse_datetime(row["sale_date"])
            if not sale_dt:
                continue
            reference_price = _safe_float(row["reference_price"], _safe_float(row["sale_price"], 0.0))
            sale_price = _safe_float(row["sale_price"])
            discount_ratio = 0.0
            if reference_price > 0:
                discount_ratio = max(0.0, (reference_price - sale_price) / reference_price)
            by_terminal[str(row["terminal_id"])].append(
                {
                    "sale_dt": sale_dt,
                    "quantity": _safe_float(row["quantity"]),
                    "total_price": _safe_float(row["total_price"]),
                    "unit_cost": _safe_float(row["unit_cost"]),
                    "discount_ratio": discount_ratio,
                    "is_promotional": bool(row["is_promotional"]),
                }
            )

        terminais = []
        all_today = []
        all_history = []
        for terminal_id, items in by_terminal.items():
            today_items = [item for item in items if item["sale_dt"].date() == today]
            historical_items = [item for item in items if item["sale_dt"].date() < today]
            all_today.extend(today_items)
            all_history.extend(historical_items)

            historical_counts: dict[str, int] = defaultdict(int)
            grouped_days: dict[str, list[datetime]] = defaultdict(list)
            for item in historical_items:
                day_key = item["sale_dt"].date().isoformat()
                historical_counts[day_key] += 1
                grouped_days[day_key].append(item["sale_dt"])

            daily_counts = list(historical_counts.values())
            gaps_minutes = []
            for timestamps in grouped_days.values():
                timestamps.sort()
                for current, nxt in zip(timestamps, timestamps[1:]):
                    gaps_minutes.append((nxt - current).total_seconds() / 60.0)

            revenue_today = sum(item["total_price"] for item in today_items)
            revenue_history = sum(item["total_price"] for item in historical_items)
            cost_today = sum(item["quantity"] * item["unit_cost"] for item in today_items)
            cost_history = sum(item["quantity"] * item["unit_cost"] for item in historical_items)
            margin_today = ((revenue_today - cost_today) / revenue_today * 100.0) if revenue_today > 0 else None
            margin_history = ((revenue_history - cost_history) / revenue_history * 100.0) if revenue_history > 0 else None

            last_sale_at = max((item["sale_dt"] for item in today_items), default=None)
            idle_minutes = None
            if last_sale_at:
                idle_minutes = max(0.0, (now - last_sale_at).total_seconds() / 60.0)

            avg_gap = mean(gaps_minutes) if gaps_minutes else None
            inactivity_threshold = 120.0 if avg_gap is None else max(60.0, min(180.0, avg_gap * 1.8))

            terminais.append(
                {
                    "terminal_id": terminal_id,
                    "vendas_hoje": len(today_items),
                    "media_vendas_dia": mean(daily_counts) if daily_counts else 0.0,
                    "ultima_venda": last_sale_at.isoformat(sep=" ") if last_sale_at else None,
                    "minutos_sem_venda": idle_minutes,
                    "limite_inatividade_min": inactivity_threshold,
                    "margem_percentual_hoje": margin_today,
                    "margem_percentual_historica": margin_history,
                    "desconto_percentual_hoje": (mean([item["discount_ratio"] for item in today_items]) * 100.0) if today_items else 0.0,
                    "desconto_percentual_historico": (mean([item["discount_ratio"] for item in historical_items]) * 100.0) if historical_items else 0.0,
                }
            )

        overall_revenue_today = sum(item["total_price"] for item in all_today)
        overall_revenue_history = sum(item["total_price"] for item in all_history)
        overall_cost_today = sum(item["quantity"] * item["unit_cost"] for item in all_today)
        overall_cost_history = sum(item["quantity"] * item["unit_cost"] for item in all_history)

        overall_margin_today = None
        if overall_revenue_today > 0:
            overall_margin_today = ((overall_revenue_today - overall_cost_today) / overall_revenue_today) * 100.0

        overall_margin_history = None
        if overall_revenue_history > 0:
            overall_margin_history = ((overall_revenue_history - overall_cost_history) / overall_revenue_history) * 100.0

        return {
            "coletado_em": now,
            "terminais": sorted(terminais, key=lambda item: item["terminal_id"]),
            "margem_percentual_hoje": overall_margin_today,
            "margem_percentual_historica": overall_margin_history,
            "desconto_percentual_hoje": (mean([item["discount_ratio"] for item in all_today]) * 100.0) if all_today else 0.0,
            "desconto_percentual_historico": (mean([item["discount_ratio"] for item in all_history]) * 100.0) if all_history else 0.0,
            "total_vendas_hoje": len(all_today),
            "ultima_venda": max((item["sale_dt"] for item in all_today), default=None),
        }
