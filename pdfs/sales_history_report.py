from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class SalesHistoryReport(BasePDFReport):
    """Relatorio PDF para a tela de historico de vendas."""

    def generate(self, records, filters):
        records = records or []
        filters = filters or {}

        pdf_path = self._get_timestamp_filename("historico_vendas")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.35 * inch,
            rightMargin=0.35 * inch,
        )

        elements = []
        self._add_header(elements, filters, len(records))
        elements.append(Spacer(1, 12))
        self._add_summary(elements, records)
        elements.append(Spacer(1, 14))
        self._add_top_products_chart(elements, records)
        elements.append(Spacer(1, 14))
        self._add_sales_table(elements, records)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _parse_sale_datetime(self, value):
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _format_date(self, value):
        parsed = self._parse_sale_datetime(value)
        if parsed is None:
            return str(value or "")[:16]
        return parsed.strftime("%d/%m/%Y %H:%M")

    def _format_money(self, value):
        return f"MZN {self._to_float(value):,.2f}"

    def _format_qty(self, value):
        numeric = self._to_float(value)
        if float(numeric).is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}"

    def _safe_text(self, value, limit=36):
        return self._truncate_text(value, limit)

    def _row_financials(self, row):
        total = self._to_float(row.get("total"))
        price = self._to_float(row.get("price"))
        returned_qty = self._to_float(row.get("returned_qty"))
        refunded_total = returned_qty * price
        net_total = max(0.0, total - refunded_total)
        return total, refunded_total, net_total

    def _build_summary_metrics(self, records):
        gross_total = 0.0
        refunded_total = 0.0
        net_total = 0.0
        promotional_count = 0
        refunded_count = 0

        for row in records:
            total, refunded, net = self._row_financials(row)
            gross_total += total
            refunded_total += refunded
            net_total += net
            if row.get("is_promotional"):
                promotional_count += 1
            if self._to_float(row.get("returned_qty")) > 0:
                refunded_count += 1

        total_sales = len(records)
        avg_ticket = net_total / total_sales if total_sales else 0.0
        return {
            "total_sales": total_sales,
            "gross_total": gross_total,
            "refunded_total": refunded_total,
            "net_total": net_total,
            "avg_ticket": avg_ticket,
            "promotional_count": promotional_count,
            "refunded_count": refunded_count,
        }

    def _add_header(self, elements, filters, record_count):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "SalesHistoryTitle",
            parent=styles["Heading1"],
            fontSize=22,
            textColor=colors.HexColor("#1f4e79"),
            spaceAfter=10,
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "SalesHistorySubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#5f6b7a"),
            spaceAfter=12,
        )

        start_dt = filters.get("start_date") or datetime.now()
        end_dt = filters.get("end_date") or start_dt
        filter_label = filters.get("filter_label") or "Todos os registos"
        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        elements.append(Paragraph("HISTORICO DE VENDAS", title_style))
        elements.append(
            Paragraph(
                "Exportacao detalhada da tela de historico de vendas",
                subtitle_style,
            )
        )

        info_rows = [
            ["Filtro aplicado", filter_label],
            [
                "Periodo",
                f"{start_dt.strftime('%d/%m/%Y')} ate {end_dt.strftime('%d/%m/%Y')}",
            ],
            ["Registos exportados", str(filters.get("record_count") or record_count)],
            ["Gerado em", generated_at],
        ]
        info_table = Table(info_rows, colWidths=[2.0 * inch, 6.2 * inch])
        info_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf2f8")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#22313f")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d6df")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)

    def _add_summary(self, elements, records):
        styles = getSampleStyleSheet()
        section_style = ParagraphStyle(
            "SalesHistorySection",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#2d6a4f"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Resumo Executivo", section_style))

        metrics = self._build_summary_metrics(records)
        summary_rows = [
            ["METRICA", "VALOR"],
            ["Total de vendas", str(metrics["total_sales"])],
            ["Receita bruta", self._format_money(metrics["gross_total"])],
            ["Valor estornado", self._format_money(metrics["refunded_total"])],
            ["Receita liquida", self._format_money(metrics["net_total"])],
            ["Ticket medio liquido", self._format_money(metrics["avg_ticket"])],
            ["Vendas promocionais", str(metrics["promotional_count"])],
            ["Vendas com estorno", str(metrics["refunded_count"])],
        ]

        summary_table = Table(summary_rows, colWidths=[3.2 * inch, 2.4 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d6a4f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4fbf7")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d6df")),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        elements.append(summary_table)

    def _add_top_products_chart(self, elements, records):
        by_product = {}
        for row in records:
            label = self._safe_text(row.get("product"), 28)
            total, refunded_total, net_total = self._row_financials(row)
            info = by_product.setdefault(
                label,
                {"qty": 0.0, "gross_total": 0.0, "refunded_total": 0.0, "net_total": 0.0},
            )
            info["qty"] += self._to_float(row.get("qty"))
            info["gross_total"] += total
            info["refunded_total"] += refunded_total
            info["net_total"] += net_total

        chart_items = [
            {
                "label": name,
                "value": info["net_total"],
            }
            for name, info in by_product.items()
        ]

        elements.append(
            self._build_bar_chart(
                "Top produtos por receita liquida",
                chart_items,
                value_formatter=lambda value: f"MZN {value:,.2f}",
                accent_color="#1f4e79",
                empty_message="Sem vendas suficientes para gerar o grafico.",
            )
        )

    def _add_sales_table(self, elements, records):
        styles = getSampleStyleSheet()
        section_style = ParagraphStyle(
            "SalesHistoryTableTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#8b4513"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Lista detalhada de vendas", section_style))

        data = [[
            "Data",
            "Produto",
            "Qtd",
            "Preco Unit.",
            "Bruto",
            "Estorno",
            "Liquido",
            "Promo",
            "Utilizador",
        ]]

        for row in records:
            total, refunded_total, net_total = self._row_financials(row)
            data.append([
                self._format_date(row.get("sale_date")),
                self._safe_text(row.get("product"), 32),
                self._format_qty(row.get("qty")),
                self._format_money(row.get("price")),
                self._format_money(total),
                self._format_money(refunded_total),
                self._format_money(net_total),
                "Sim" if row.get("is_promotional") else "Nao",
                self._safe_text(row.get("created_by") or row.get("created_role") or "N/A", 16),
            ])

        if len(data) == 1:
            data.append(["Sem vendas para exportar", "-", "-", "-", "-", "-", "-", "-", "-"])

        table = Table(
            data,
            repeatRows=1,
            colWidths=[
                1.30 * inch,
                2.95 * inch,
                0.62 * inch,
                1.00 * inch,
                1.05 * inch,
                1.05 * inch,
                1.10 * inch,
                0.60 * inch,
                0.95 * inch,
            ],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b4513")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.2),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff8f2")]),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0d7de")),
            ("FONTSIZE", (0, 1), (-1, -1), 7.7),
            ("ALIGN", (2, 1), (-1, -1), "CENTER"),
            ("ALIGN", (3, 1), (6, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(table)
