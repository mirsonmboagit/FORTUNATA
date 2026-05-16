from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class ShoppingListReport(BasePDFReport):
    """PDF simples da lista de compras."""

    def generate(self, payload, filters=None):
        payload = payload or {}
        items = payload.get("items") or []
        summary = payload.get("summary") or {}

        pdf_path = self._get_timestamp_filename("lista_de_compras")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            topMargin=0.55 * inch,
            bottomMargin=0.55 * inch,
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
        )

        elements = []
        self._add_header(elements, len(items), summary)
        elements.append(Spacer(1, 12))
        self._add_items_table(elements, items)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _money(self, value):
        try:
            return f"{float(value or 0):,.2f} MZN"
        except Exception:
            return "0.00 MZN"

    def _qty(self, value, unit):
        try:
            number = float(value or 0)
        except Exception:
            number = 0.0
        if str(unit or "").upper() == "KG":
            return f"{number:.2f} KG"
        return f"{int(round(number))} UN"

    def _cell(self, value, style, fallback="-", max_len=None):
        text = str(value if value is not None else fallback).strip() or fallback
        if max_len and len(text) > max_len:
            text = text[: max_len - 3].rstrip() + "..."
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    def _add_header(self, elements, item_count, summary):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ShoppingListTitle",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=colors.HexColor("#1f4e79"),
            alignment=TA_CENTER,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )
        info_style = ParagraphStyle(
            "ShoppingListInfo",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#34495e"),
            alignment=TA_CENTER,
            leading=13,
        )

        total = self._money(summary.get("total_investment"))
        elements.append(Paragraph("LISTA DE COMPRAS", title_style))
        elements.append(
            Paragraph(
                f"{item_count} produtos | Total estimado: {total} | Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                info_style,
            )
        )

    def _add_items_table(self, elements, items):
        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle(
            "ShoppingListCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=10.5,
            textColor=colors.HexColor("#1f1f1f"),
            wordWrap="LTR",
            splitLongWords=True,
        )
        center_style = ParagraphStyle(
            "ShoppingListCenter",
            parent=cell_style,
            alignment=1,
        )
        money_style = ParagraphStyle(
            "ShoppingListMoney",
            parent=cell_style,
            alignment=2,
        )

        rows = [["Produto", "Quantidade", "Preco unit.", "Total"]]
        for item in items:
            unit = item.get("unit") or "UN"
            rows.append([
                self._cell(item.get("name"), cell_style, max_len=42),
                self._cell(self._qty(item.get("needed_qty"), unit), center_style),
                self._cell(self._money(item.get("unit_cost")), money_style),
                self._cell(self._money(item.get("purchase_cost")), money_style),
            ])

        if len(rows) == 1:
            rows.append([
                self._cell("Nenhum produto precisa de reposicao.", cell_style),
                "-",
                "-",
                "-",
            ])

        table = Table(
            rows,
            colWidths=[3.35 * inch, 1.25 * inch, 1.35 * inch, 1.35 * inch],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d6df")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        elements.append(table)
