"""Core analitico para deteccao proativa de eventos de negocio."""

from __future__ import annotations

from datetime import datetime
from typing import Any


Alert = dict[str, Any]


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
        f"Hoje: {total_hoje:.2f} MZN | "
        f"Media semanal: {media_total:.2f} MZN | "
        f"Razao: {ratio * 100:.1f}%"
    )
    if ratio < 0.70:
        return [
            _alerta(
                "critico",
                "vendas",
                f"Vendas do dia muito abaixo da media semanal ({ratio * 100:.1f}%).",
                detalhes,
            )
        ]
    if ratio < 0.85:
        return [
            _alerta(
                "atencao",
                "vendas",
                f"Vendas do dia abaixo da faixa esperada ({ratio * 100:.1f}% da media).",
                detalhes,
            )
        ]
    if ratio > 1.20:
        return [
            _alerta(
                "info",
                "vendas",
                f"Vendas do dia acima do ritmo semanal (+{(ratio - 1) * 100:.1f}%).",
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

        if stock_atual <= stock_minimo:
            alerts.append(
                _alerta(
                    "critico",
                    "stock",
                    f"Stock critico em {descricao}: {stock_atual:.2f} disponivel para minimo de {stock_minimo:.2f}.",
                    f"Media diaria: {media_diaria:.2f} | Vendido hoje: {qty_hoje:.2f}",
                )
            )

        if media_diaria > 0 and qty_hoje > media_diaria * 1.30:
            aumento = ((qty_hoje / media_diaria) - 1.0) * 100.0
            alerts.append(
                _alerta(
                    "info",
                    "stock",
                    f"Saida acelerada em {descricao}: ritmo {aumento:.1f}% acima da media historica.",
                    f"Hoje: {qty_hoje:.2f} | Media diaria: {media_diaria:.2f}",
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
                f"Produto parado: {descricao} esta ha {int(last_sale_days)} dias sem venda.",
                f"Stock atual: {stock_atual:.2f} | Minimo operacional: {stock_minimo:.2f}",
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
                    f"Caixa {terminal_id} sem vendas hoje, abaixo do padrao operacional.",
                    f"Media diaria historica: {media_vendas:.1f} vendas",
                )
            )
            continue
        if minutos_sem_venda is not None and minutos_sem_venda > limite and vendas_hoje > 0:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    f"Caixa {terminal_id} sem vendas ha {minutos_sem_venda:.0f} min, acima do padrao.",
                    f"Limite calculado: {limite:.0f} min | Vendas hoje: {vendas_hoje}",
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
                    "Margem do dia abaixo do padrao historico.",
                    f"Hoje: {margem_hoje:.2f}% | Historico: {margem_hist:.2f}%",
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
                    "Descontos do dia acima da media historica.",
                    f"Hoje: {desconto_hoje:.2f}% | Historico: {desconto_hist:.2f}%",
                )
            )
        elif desconto_hist == 0 and desconto_hoje >= 5.0:
            alerts.append(
                _alerta(
                    "atencao",
                    "produtividade",
                    "Descontos relevantes detectados em um contexto sem historico previo.",
                    f"Desconto medio do dia: {desconto_hoje:.2f}%",
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
                    "Anomalia estatistica: faturamento de hoje abaixo da curva recente.",
                    f"Z-score: {z_score:.2f} | Hoje: {total_hoje:.2f} | Media: {media_total:.2f}",
                )
            )
        elif z_score >= 2.0:
            alerts.append(
                _alerta(
                    "info",
                    "vendas",
                    "Anomalia positiva: faturamento de hoje acima da curva recente.",
                    f"Z-score: {z_score:.2f} | Hoje: {total_hoje:.2f} | Media: {media_total:.2f}",
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
                        f"Anomalia de procura em {descricao}: volume fora da curva historica.",
                        f"Z-score: {z_score:.2f} | Hoje: {qty_hoje:.2f} | Media: {media_qty:.2f}",
                    )
                )
        elif qty_hoje >= media_qty * 2.0:
            alerts.append(
                _alerta(
                    "info",
                    "stock",
                    f"Anomalia de procura em {descricao}: volume pelo menos 2x acima da media.",
                    f"Hoje: {qty_hoje:.2f} | Media: {media_qty:.2f}",
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
