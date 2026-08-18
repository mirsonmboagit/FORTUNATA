"""Core analitico para deteccao proativa de eventos de negocio."""

from __future__ import annotations

from datetime import datetime
from typing import Any


Alert = dict[str, Any]


def _format_number(value: float) -> str:
    value = float(value or 0.0)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _format_money(value: float) -> str:
    return f"{float(value or 0.0):.2f} meticais"


def _format_quantity(value: float, singular: str = "unidade", plural: str = "unidades") -> str:
    amount = float(value or 0.0)
    label = singular if abs(amount - 1) < 0.001 else plural
    return f"{_format_number(amount)} {label}"


def _format_sales_count(value: float) -> str:
    return _format_quantity(value, "venda", "vendas")


def _format_sales_registration(value: float) -> str:
    amount = float(value or 0.0)
    verb = "foi registada" if abs(amount - 1) < 0.001 else "foram registadas"
    return f"Hoje {verb} {_format_sales_count(amount)}."


def _alerta(
    tipo: str,
    categoria: str,
    mensagem: str,
    detalhes: str | None = None,
    timestamp: datetime | None = None,
) -> Alert:
    payload: Alert = {
        "tipo": tipo,
        "categoria": categoria,
        "mensagem": mensagem,
        "timestamp": timestamp or datetime.now(),
    }
    if detalhes:
        payload["detalhes"] = detalhes
    return payload


def analisar_vendas(snapshot: dict[str, Any]) -> list[Alert]:
    """Compara a venda do dia com a media semanal recente."""
    vendas_hoje = snapshot.get("vendas_hoje", {})
    media = snapshot.get("media_semanal", {})
    total_hoje = float(vendas_hoje.get("total") or 0.0)
    media_total = float(media.get("media_total") or 0.0)
    if media_total <= 0:
        return []

    ratio = total_hoje / media_total
    detalhes = (
        f"Hoje foram vendidos {_format_money(total_hoje)}. "
        f"A média semanal é de {_format_money(media_total)}."
    )
    if ratio < 0.70:
        return [
            _alerta(
                "critico",
                "vendas",
                "As vendas de hoje estão muito abaixo da média semanal.",
                detalhes,
            )
        ]
    if ratio < 0.85:
        return [
            _alerta(
                "atencao",
                "vendas",
                "As vendas de hoje estão abaixo da média semanal.",
                detalhes,
            )
        ]
    if ratio > 1.20:
        return [
            _alerta(
                "info",
                "vendas",
                "As vendas de hoje estão acima da média semanal.",
                detalhes,
            )
        ]
    return []


def analisar_stock(snapshot: dict[str, Any]) -> list[Alert]:
    """Detecta stock critico e saida acelerada."""
    alerts: list[Alert] = []
    for item in snapshot.get("stock_produtos", []):
        stock_atual = float(item.get("stock_atual") or 0.0)
        stock_minimo = float(item.get("stock_minimo") or 0.0)
        media_diaria = float(item.get("media_diaria_qty") or 0.0)
        qty_hoje = float(item.get("qty_hoje") or 0.0)
        descricao = str(item.get("descricao") or "Produto")
        unit_singular = "quilograma" if item.get("is_weight") else "unidade"
        unit_plural = "quilogramas" if item.get("is_weight") else "unidades"

        if stock_atual <= stock_minimo:
            alerts.append(
                _alerta(
                    "critico",
                    "stock",
                    f"Stock critico: o estoque de {descricao} está baixo. "
                    f"Restam {_format_quantity(stock_atual, unit_singular, unit_plural)}.",
                    f"O mínimo definido é de {_format_quantity(stock_minimo, unit_singular, unit_plural)}. "
                    f"A média de saída é de {_format_quantity(media_diaria, unit_singular, unit_plural)} por dia.",
                )
            )

        if media_diaria > 0 and qty_hoje > media_diaria * 1.30:
            alerts.append(
                _alerta(
                    "info",
                    "stock",
                    f"A saída de {descricao} está acima do normal hoje.",
                    f"O total vendido hoje é de {_format_quantity(qty_hoje, unit_singular, unit_plural)}. "
                    f"A média diária é de {_format_quantity(media_diaria, unit_singular, unit_plural)}.",
                )
            )

    return alerts


def analisar_produtos_parados(snapshot: dict[str, Any], dias_sem_venda: int = 14) -> list[Alert]:
    """Marca produtos com stock parado por periodo relevante."""
    alerts: list[Alert] = []
    for item in snapshot.get("stock_produtos", []):
        last_sale_days = item.get("last_sale_days_ago")
        if last_sale_days is None:
            continue
        stock_atual = float(item.get("stock_atual") or 0.0)
        stock_minimo = float(item.get("stock_minimo") or 0.0)
        if last_sale_days < dias_sem_venda or stock_atual <= stock_minimo:
            continue
        descricao = str(item.get("descricao") or "Produto")
        alerts.append(
            _alerta(
                "atencao",
                "stock",
                f"{descricao} está sem vendas há {int(last_sale_days)} dias.",
                f"Restam {_format_quantity(stock_atual)}. "
                f"O estoque mínimo definido é de {_format_quantity(stock_minimo)}.",
            )
        )
    return alerts


def analisar_produtividade(snapshot: dict[str, Any]) -> list[Alert]:
    """Avalia inatividade de caixa, margem e descontos fora do padrao."""
    atividade = snapshot.get("atividade_caixa", {})
    alerts: list[Alert] = []

    for terminal in atividade.get("terminais", []):
        vendas_hoje = int(terminal.get("vendas_hoje") or 0)
        media_vendas = float(terminal.get("media_vendas_dia") or 0.0)
        minutos_sem_venda = terminal.get("minutos_sem_venda")
        limite = float(terminal.get("limite_inatividade_min") or 0.0)
        terminal_id = str(terminal.get("terminal_id") or "CAIXA")
        if media_vendas <= 0:
            continue
        if vendas_hoje == 0 and media_vendas >= 1.0:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    f"O caixa {terminal_id} ainda não registou vendas hoje.",
                    f"A média diária é de {_format_sales_count(media_vendas)}.",
                )
            )
            continue
        if minutos_sem_venda is not None and minutos_sem_venda > limite and vendas_hoje > 0:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    f"O caixa {terminal_id} está há {minutos_sem_venda:.0f} minutos sem registar vendas.",
                    f"O limite definido é de {limite:.0f} minutos. "
                    + _format_sales_registration(vendas_hoje),
                )
            )

    margem_hoje = atividade.get("margem_percentual_hoje")
    margem_hist = atividade.get("margem_percentual_historica")
    if margem_hoje is not None and margem_hist is not None and margem_hist > 0:
        if margem_hoje < margem_hist * 0.80:
            alerts.append(
                _alerta(
                    "critico",
                    "produtividade",
                    "A margem de lucro de hoje está abaixo do habitual.",
                    f"Hoje a margem é de {margem_hoje:.2f}%. "
                    f"A margem habitual é de {margem_hist:.2f}%.",
                )
            )

    desconto_hoje = float(atividade.get("desconto_percentual_hoje") or 0.0)
    desconto_hist = float(atividade.get("desconto_percentual_historico") or 0.0)
    total_vendas_hoje = int(atividade.get("total_vendas_hoje") or 0)
    if total_vendas_hoje >= 3:
        if desconto_hist > 0 and desconto_hoje > desconto_hist * 1.40:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    "Os descontos de hoje estão acima do habitual.",
                    f"Hoje os descontos são de {desconto_hoje:.2f}%. "
                    f"A média habitual é de {desconto_hist:.2f}%.",
                )
            )
        elif desconto_hist == 0 and desconto_hoje >= 5.0:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    "Foram aplicados descontos hoje, mas ainda não existe histórico para comparação.",
                    f"O desconto médio de hoje é de {desconto_hoje:.2f}%.",
                )
            )

    return alerts


def detectar_anomalias(snapshot: dict[str, Any]) -> list[Alert]:
    """Aplica leituras estatisticas simples sobre vendas e produtos."""
    alerts: list[Alert] = []
    vendas_hoje = snapshot.get("vendas_hoje", {})
    media = snapshot.get("media_semanal", {})
    total_hoje = float(vendas_hoje.get("total") or 0.0)
    media_total = float(media.get("media_total") or 0.0)
    desvio = float(media.get("desvio_total") or 0.0)

    if desvio > 0 and media_total > 0:
        z_score = (total_hoje - media_total) / desvio
        if z_score <= -2.0:
            alerts.append(
                _alerta(
                    "critico",
                    "vendas",
                    "O faturamento de hoje está muito abaixo do habitual.",
                    f"Hoje o faturamento é de {_format_money(total_hoje)}. "
                    f"A média é de {_format_money(media_total)}.",
                )
            )
        elif z_score >= 2.0:
            alerts.append(
                _alerta(
                    "info",
                    "vendas",
                    "O faturamento de hoje está acima do habitual.",
                    f"Hoje o faturamento é de {_format_money(total_hoje)}. "
                    f"A média é de {_format_money(media_total)}.",
                )
            )

    for product in snapshot.get("vendas_por_produto", []):
        media_qty = float(product.get("media_diaria_qty") or 0.0)
        qty_hoje = float(product.get("qty_hoje") or 0.0)
        desvio_qty = float(product.get("desvio_qty") or 0.0)
        descricao = str(product.get("descricao") or "Produto")
        if media_qty <= 0 or qty_hoje <= 0:
            continue
        if desvio_qty > 0:
            z_score = (qty_hoje - media_qty) / desvio_qty
            if z_score >= 2.0:
                alerts.append(
                    _alerta(
                        "info",
                        "stock",
                        f"A venda de {descricao} está acima do normal hoje.",
                        f"O total vendido hoje é de {_format_quantity(qty_hoje)}. "
                        f"A média diária é de {_format_quantity(media_qty)}.",
                    )
                )
        elif qty_hoje >= media_qty * 2.0:
            alerts.append(
                    _alerta(
                        "info",
                        "stock",
                        f"A venda de {descricao} está acima do normal hoje.",
                        f"O total vendido hoje é de {_format_quantity(qty_hoje)}. "
                        f"A média diária é de {_format_quantity(media_qty)}.",
                )
            )
    return alerts


def executar_analise(snapshot: dict[str, Any]) -> list[Alert]:
    """Executa todas as rotinas obrigatorias do motor de inteligencia."""
    alerts: list[Alert] = []
    alerts.extend(analisar_vendas(snapshot))
    alerts.extend(analisar_stock(snapshot))
    alerts.extend(analisar_produtos_parados(snapshot))
    alerts.extend(analisar_produtividade(snapshot))
    alerts.extend(detectar_anomalias(snapshot))
    return alerts
