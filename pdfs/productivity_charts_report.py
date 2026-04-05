from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class ProductivityChartsReport(BasePDFReport):
    MAX_DAILY_ITEMS = 10
    MAX_TERMINAL_ITEMS = 8

    def generate(self, payload, filters):
        payload = payload or {}
        summary = payload.get("summary") or {}
        daily_series = list(payload.get("daily_series") or [])
        terminal_series = list(payload.get("terminal_series") or [])

        if not daily_series and not terminal_series:
            raise ValueError("Sem dados de produtividade para imprimir.")

        pdf_path = self._get_timestamp_filename("graficos_produtividade")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.45 * inch,
            rightMargin=0.45 * inch,
        )

        elements = []
        self._create_header(
            elements,
            "GRAFICOS DE PRODUTIVIDADE",
            "Impressao exclusiva dos graficos principais do painel inteligente",
            filters,
        )

        elements.append(self._build_intro(summary))
        elements.append(Spacer(1, 12))

        daily_items, daily_subtitle = self._build_daily_items(daily_series)
        terminal_items, terminal_subtitle = self._build_terminal_items(terminal_series)

        charts_table = Table(
            [[
                self._build_chart_cell(
                    "Grafico Diario de Vendas",
                    daily_subtitle,
                    self._build_bar_chart(
                        "Vendas por Dia",
                        daily_items,
                        width=4.95 * inch,
                        max_items=0,
                        value_formatter=lambda value: f"{int(round(value))} vendas",
                        accent_color="#0F6CBD",
                        sort_items=False,
                        empty_message="Sem movimento diario no periodo.",
                    ),
                ),
                self._build_chart_cell(
                    "Grafico de Ranking por Caixa",
                    terminal_subtitle,
                    self._build_bar_chart(
                        "Caixas Mais Ativos",
                        terminal_items,
                        width=4.95 * inch,
                        max_items=0,
                        value_formatter=lambda value: f"{int(round(value))} vendas",
                        accent_color="#2D8B57",
                        sort_items=False,
                        empty_message="Sem caixas ativos no periodo.",
                    ),
                ),
            ]],
            colWidths=[5.15 * inch, 5.15 * inch],
            hAlign="CENTER",
        )
        charts_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(charts_table)

        self._create_footer(elements)
        doc.build(elements)
        return pdf_path

    def _build_intro(self, summary):
        styles = getSampleStyleSheet()
        intro_style = ParagraphStyle(
            "ChartsIntro",
            parent=styles["Normal"],
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor("#4b5563"),
        )

        total_sales = int(summary.get("total_sales") or 0)
        active_terminals = int(summary.get("active_terminals") or 0)
        total_revenue = self._to_float(summary.get("total_revenue"))

        intro_text = (
            "Este documento imprime apenas os graficos principais de produtividade. "
            f"Resumo rapido: {total_sales} venda(s), receita total de {total_revenue:,.2f} MZN "
            f"e {active_terminals} caixa(s) ativo(s) no periodo selecionado."
        )
        return Paragraph(intro_text, intro_style)

    def _build_chart_cell(self, title, subtitle, chart):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ChartCellTitle",
            parent=styles["Heading2"],
            fontSize=12,
            leading=14,
            textColor=colors.HexColor("#1f2d3d"),
            spaceAfter=4,
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "ChartCellSubtitle",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=8,
        )

        return [
            Paragraph(title, title_style),
            Paragraph(subtitle, subtitle_style),
            chart,
        ]

    def _build_daily_items(self, daily_series):
        daily_series = list(daily_series or [])
        if not daily_series:
            return [], "Sem dias disponiveis para impressao."

        non_zero_indexes = [
            index
            for index, item in enumerate(daily_series)
            if int(item.get("sales_count") or 0) > 0
        ]
        end_index = (non_zero_indexes[-1] + 1) if non_zero_indexes else len(daily_series)
        start_index = max(0, end_index - self.MAX_DAILY_ITEMS)
        selected_days = daily_series[start_index:end_index]

        items = [
            (
                self._format_day_label(item.get("date")),
                int(item.get("sales_count") or 0),
            )
            for item in selected_days
        ]

        if len(daily_series) > len(selected_days):
            subtitle = f"Ultimos {len(selected_days)} dias ate a venda mais recente do periodo"
        else:
            subtitle = "Periodo completo selecionado"
        return items, subtitle

    def _build_terminal_items(self, terminal_series):
        terminal_series = list(terminal_series or [])
        selected_terminals = terminal_series[: self.MAX_TERMINAL_ITEMS]
        items = [
            (
                str(item.get("terminal_id") or "CAIXA-PRINCIPAL"),
                int(item.get("sales_count") or 0),
            )
            for item in selected_terminals
        ]
        if not items:
            return [], "Sem caixas ativos para impressao."
        subtitle = f"Top {len(items)} caixas por numero de vendas"
        return items, subtitle

    def _format_day_label(self, value):
        text = str(value or "").strip()
        if len(text) >= 10:
            return f"{text[8:10]}/{text[5:7]}"
        return text or "--/--"
