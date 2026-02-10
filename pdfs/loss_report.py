from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from .base_report import BasePDFReport
from datetime import datetime


LOSS_LABELS = {
    "DAMAGE": "Danificado",
    "EXPIRED": "Expirado",
    "THEFT": "Roubo",
    "ADJUSTMENT": "Ajuste",
}


class LossReport(BasePDFReport):
    """
    Relatório profissional de perdas em PDF.
    Inclui resumo executivo, perdas por tipo/utilizador/produto e lista detalhada.
    """

    def generate(self, data, filters):
        metrics = data.get("metrics") or {}
        records = data.get("records") or []

        pdf_path = self._get_timestamp_filename("relatorio_perdas")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
        )

        elements = []
        self._create_header(
            elements,
            "RELATÓRIO DE PERDAS",
            "Análise de perdas e desperdícios",
            filters,
        )

        elements.append(Spacer(1, 14))
        self._add_summary(elements, metrics)
        elements.append(Spacer(1, 16))
        self._add_by_type(elements, metrics.get("by_type", {}))
        elements.append(Spacer(1, 14))
        self._add_by_user(elements, metrics.get("by_user", []))
        elements.append(Spacer(1, 14))
        self._add_by_product(elements, metrics.get("by_product", []))
        elements.append(Spacer(1, 16))
        self._add_records_table(elements, records)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _add_section_title(self, elements, text, color_hex):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor(color_hex),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph(text, title_style))

    def _add_summary(self, elements, metrics):
        self._add_section_title(elements, "Resumo Executivo", "#2980b9")

        total_cost = metrics.get("total_cost", 0) or 0
        total_revenue = metrics.get("total_revenue_lost", 0) or 0
        total_profit = metrics.get("total_profit_lost", total_revenue - total_cost) or 0
        loss_pct = metrics.get("loss_percentage", 0) or 0
        total_sales = metrics.get("total_sales", 0) or 0
        loss_count = metrics.get("loss_count", 0) or 0
        avg_loss = metrics.get("avg_loss_value", 0) or 0

        summary_data = [
            ["MÉTRICA", "VALOR"],
            ["Registos de Perda", f"{loss_count}"],
            ["Custo Total das Perdas", f"MZN {total_cost:,.2f}"],
            ["Receita Perdida", f"MZN {total_revenue:,.2f}"],
            ["Lucro Perdido Estimado", f"MZN {total_profit:,.2f}"],
            ["Perdas vs Vendas", f"{loss_pct:.2f}%"],
            ["Total de Vendas (Período)", f"MZN {total_sales:,.2f}"],
            ["Perda Média por Evento", f"MZN {avg_loss:,.2f}"],
        ]

        table = Table(summary_data, colWidths=[3.6 * inch, 3.2 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2980b9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)

    def _add_by_type(self, elements, by_type):
        self._add_section_title(elements, "Perdas por Tipo", "#27ae60")

        rows = [["Tipo", "Registos", "Custo", "Receita Perdida", "Lucro Perdido"]]
        for key, info in (by_type or {}).items():
            label = LOSS_LABELS.get(key, key)
            rows.append([
                label,
                f"{info.get('count', 0)}",
                f"MZN {info.get('total_cost', 0):,.2f}",
                f"MZN {info.get('total_revenue_lost', 0):,.2f}",
                f"MZN {info.get('total_profit_lost', 0):,.2f}",
            ])

        if len(rows) == 1:
            rows.append(["Sem perdas no período", "-", "-", "-", "-"])

        table = Table(rows, colWidths=[2.2 * inch, 1.2 * inch, 1.8 * inch, 2.1 * inch, 2.0 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f8f0")]),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

    def _add_by_user(self, elements, rows):
        self._add_section_title(elements, "Perdas por Utilizador", "#8e44ad")

        data = [["Utilizador", "Eventos", "Custo", "Receita Perdida"]]
        for user, cost, revenue, events in rows or []:
            data.append([
                user or "N/A",
                f"{events}",
                f"MZN {float(cost):,.2f}",
                f"MZN {float(revenue):,.2f}",
            ])

        if len(data) == 1:
            data.append(["Sem dados", "-", "-", "-"])

        table = Table(data, colWidths=[3.0 * inch, 1.0 * inch, 2.2 * inch, 2.2 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8e44ad")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f2ff")]),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

    def _add_by_product(self, elements, rows):
        self._add_section_title(elements, "Top 10 Produtos com Perdas", "#c0392b")

        data = [["Produto", "Eventos", "Custo Total"]]
        for _, name, count, total_cost in rows or []:
            data.append([
                str(name)[:40],
                f"{count}",
                f"MZN {float(total_cost):,.2f}",
            ])

        if len(data) == 1:
            data.append(["Sem dados", "-", "-"])

        table = Table(data, colWidths=[5.5 * inch, 1.2 * inch, 2.0 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fdecea")]),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

    def _add_records_table(self, elements, records):
        self._add_section_title(elements, "Lista Detalhada de Perdas (últimos registos)", "#2c3e50")

        data = [["Data", "Produto", "Tipo", "Qtd", "Custo", "Receita Perdida", "Utilizador"]]

        for row in records[:60]:
            created_at, product, movement_type, qty, unit, total_cost, total_price, reason, created_by = row
            try:
                dt = datetime.fromisoformat(str(created_at))
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                date_str = str(created_at)[:16]

            label = LOSS_LABELS.get(movement_type, movement_type)
            data.append([
                date_str,
                str(product)[:28],
                label,
                f"{float(qty):.2f} {unit}",
                f"MZN {float(total_cost):,.2f}",
                f"MZN {float(total_price):,.2f}",
                created_by or "N/A",
            ])

        if len(data) == 1:
            data.append(["Sem perdas no período", "-", "-", "-", "-", "-", "-"])

        table = Table(data, colWidths=[
            1.6 * inch, 3.2 * inch, 1.1 * inch, 1.1 * inch, 1.2 * inch, 1.4 * inch, 1.2 * inch
        ])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("ALIGN", (3, 1), (-1, -1), "CENTER"),
            ("ALIGN", (4, 1), (5, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(table)
