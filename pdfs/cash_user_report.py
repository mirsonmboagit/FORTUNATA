from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class CashUserReport(BasePDFReport):
    """Gera relatorio de vendas por utilizador e caixa."""

    def generate(self, payload, filters):
        payload = payload or {}
        summary = payload.get("summary") or {}
        user_series = list(payload.get("user_series") or [])
        session_rows = list(payload.get("session_rows") or [])

        if not user_series and not session_rows:
            raise ValueError("Sem movimentos de caixa no periodo selecionado.")

        pdf_path = self._get_timestamp_filename("relatorio_caixa_usuarios")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
        )

        elements = []
        self._create_header(
            elements,
            "RELATORIO DE CAIXA POR UTILIZADOR",
            "Abertura e fechamento operacional calculados pela primeira e ultima venda",
            filters,
        )
        self._add_summary(elements, summary)
        elements.append(Spacer(1, 14))
        self._add_user_ranking(elements, user_series)
        elements.append(Spacer(1, 14))
        self._add_session_rows(elements, session_rows)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _add_summary(self, elements, summary):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CashSummaryTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#0F6CBD"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Resumo do Periodo", title_style))

        leader = summary.get("leader_user") or {}
        leader_text = "N/A"
        if leader:
            leader_text = (
                f"{leader.get('username') or 'N/A'} - "
                f"{int(leader.get('sales_count') or 0)} venda(s), "
                f"{self._to_float(leader.get('revenue')):,.2f} MZN"
            )

        data = [
            ["METRICA", "VALOR"],
            ["Utilizadores ativos", str(int(summary.get("total_users") or 0))],
            ["Caixas/terminais ativos", str(int(summary.get("total_terminals") or 0))],
            ["Dias com movimento", str(int(summary.get("total_days") or 0))],
            ["Total de vendas", str(int(summary.get("total_sales") or 0))],
            ["Receita total", f"{self._to_float(summary.get('total_revenue')):,.2f} MZN"],
            ["Ticket medio", f"{self._to_float(summary.get('avg_ticket')):,.2f} MZN"],
            ["Primeira abertura", self._format_datetime(summary.get("first_opening_at"))],
            ["Ultimo fechamento", self._format_datetime(summary.get("last_closing_at"))],
            ["Utilizador lider", leader_text],
        ]

        table = Table(data, colWidths=[2.8 * inch, 7.3 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6CBD")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#c9d3df")),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        elements.append(table)

    def _add_user_ranking(self, elements, user_series):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CashUserTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#2D8B57"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Resumo por Utilizador", title_style))

        data = [["#", "Utilizador", "Perfil", "Vendas", "Receita", "Ticket", "Dias", "Caixas"]]
        for index, item in enumerate(user_series[:18], 1):
            data.append([
                str(index),
                self._truncate_text(item.get("username"), 24),
                self._truncate_text(item.get("role"), 12),
                str(int(item.get("sales_count") or 0)),
                f"{self._to_float(item.get('revenue')):,.2f}",
                f"{self._to_float(item.get('avg_ticket')):,.2f}",
                str(int(item.get("active_days") or 0)),
                str(int(item.get("active_terminals") or 0)),
            ])

        table = Table(
            data,
            colWidths=[0.35 * inch, 2.15 * inch, 0.9 * inch, 0.75 * inch, 1.2 * inch, 1.05 * inch, 0.55 * inch, 0.6 * inch],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D8B57")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f8f3")]),
            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#b8c8bd")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

    def _add_session_rows(self, elements, session_rows):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CashSessionTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#E67E22"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Abertura e Fechamento por Caixa", title_style))

        data = [["Data", "Utilizador", "Caixa", "Abertura", "Fechamento", "Vendas", "Receita", "Ticket"]]
        for item in session_rows[:28]:
            data.append([
                self._format_date(item.get("date")),
                self._truncate_text(item.get("username"), 18),
                self._truncate_text(item.get("terminal_id"), 18),
                self._format_time(item.get("opening_at")),
                self._format_time(item.get("closing_at")),
                str(int(item.get("sales_count") or 0)),
                f"{self._to_float(item.get('revenue')):,.2f}",
                f"{self._to_float(item.get('avg_ticket')):,.2f}",
            ])

        table = Table(
            data,
            colWidths=[0.8 * inch, 1.6 * inch, 1.55 * inch, 0.9 * inch, 0.95 * inch, 0.65 * inch, 1.15 * inch, 1.0 * inch],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E67E22")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff6ec")]),
            ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#d9c4ac")),
            ("FONTSIZE", (0, 0), (-1, -1), 7.8),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

    def _format_datetime(self, value):
        text = str(value or "").strip()
        if len(text) >= 16:
            return f"{text[8:10]}/{text[5:7]}/{text[0:4]} {text[11:16]}"
        return text or "N/A"

    def _format_date(self, value):
        text = str(value or "").strip()
        if len(text) >= 10:
            return f"{text[8:10]}/{text[5:7]}/{text[0:4]}"
        return text or "N/A"

    def _format_time(self, value):
        text = str(value or "").strip()
        if len(text) >= 16:
            return text[11:16]
        return text or "N/A"
