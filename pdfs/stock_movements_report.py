from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class StockMovementsReport(BasePDFReport):
    """Relatorio PDF para movimentos recentes e historico de stock."""

    LOSS_CODES = {"DAMAGE", "EXPIRED", "THEFT", "ADJUSTMENT"}

    def generate(self, rows, filters):
        rows = rows or []
        filters = filters or {}

        pdf_path = self._get_timestamp_filename("movimentos_stock")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.45 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.35 * inch,
            rightMargin=0.35 * inch,
        )

        elements = []
        self._add_header(elements, filters, len(rows))
        elements.append(Spacer(1, 12))
        self._add_summary(elements, rows)
        elements.append(Spacer(1, 14))
        self._add_table(elements, rows)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _build_cell(self, value, style, fallback="-"):
        text = str(value or fallback).strip() or fallback
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    def _add_header(self, elements, filters, record_count):
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "StockMovementsTitle",
            parent=styles["Heading1"],
            fontSize=22,
            textColor=colors.HexColor("#1f4e79"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        subtitle_style = ParagraphStyle(
            "StockMovementsSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#5f6b7a"),
            spaceAfter=12,
        )

        title = filters.get("title") or "MOVIMENTOS DE STOCK"
        filter_label = filters.get("filter_label") or "TODOS"
        source_label = filters.get("source_label") or "Tela de reposicao de stock"
        generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        elements.append(Paragraph(str(title).upper(), title_style))
        elements.append(
            Paragraph(
                "Exportacao da lista exibida na janela de movimentos de stock",
                subtitle_style,
            )
        )

        info_rows = [
            ["Filtro aplicado", filter_label],
            ["Registos exportados", str(filters.get("record_count") or record_count)],
            ["Origem", source_label],
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

    def _add_summary(self, elements, rows):
        styles = getSampleStyleSheet()
        section_style = ParagraphStyle(
            "StockMovementsSection",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#2d6a4f"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        elements.append(Paragraph("Resumo dos Movimentos", section_style))

        total_in = sum(1 for row in rows if str(row.get("direction") or "").upper() == "IN")
        total_out = sum(1 for row in rows if str(row.get("direction") or "").upper() == "OUT")
        total_restock = sum(1 for row in rows if str(row.get("movement_code") or "").upper() == "RESTOCK")
        total_losses = sum(1 for row in rows if str(row.get("movement_code") or "").upper() in self.LOSS_CODES)

        summary_rows = [
            ["METRICA", "VALOR"],
            ["Total de movimentos", str(len(rows))],
            ["Entradas", str(total_in)],
            ["Saidas", str(total_out)],
            ["Reposicoes", str(total_restock)],
            ["Perdas/Ajustes", str(total_losses)],
        ]

        summary_table = Table(summary_rows, colWidths=[3.1 * inch, 2.1 * inch])
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

    def _add_table(self, elements, rows):
        styles = getSampleStyleSheet()
        section_style = ParagraphStyle(
            "StockMovementsTableTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#1f4e79"),
            spaceAfter=8,
            fontName="Helvetica-Bold",
        )
        cell_style = ParagraphStyle(
            "StockMovementsCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=9.2,
            textColor=colors.HexColor("#1f1f1f"),
            wordWrap="LTR",
            splitLongWords=True,
        )

        elements.append(Paragraph("Detalhamento dos Registos", section_style))

        table_rows = [[
            "Entrada",
            "Saida",
            "Atual",
            "Tipo",
            "Produto",
            "Qtd",
            "Dir",
            "Usuario",
        ]]

        for row in rows:
            direction = str(row.get("direction") or "-").upper()
            direction_style = ParagraphStyle(
                f"Direction{direction}",
                parent=cell_style,
                alignment=1,
                textColor=colors.HexColor("#2d8b57") if direction == "IN" else colors.HexColor("#d64545"),
                fontName="Helvetica-Bold",
            )
            type_style = ParagraphStyle(
                f"Type{direction}",
                parent=cell_style,
                alignment=1,
                textColor=direction_style.textColor,
                fontName="Helvetica-Bold",
            )

            table_rows.append([
                self._build_cell(row.get("entry_date"), cell_style),
                self._build_cell(row.get("exit_date"), cell_style),
                self._build_cell(row.get("update_day"), cell_style),
                self._build_cell(row.get("movement_label"), type_style),
                self._build_cell(row.get("product_name"), cell_style),
                self._build_cell(row.get("qty_text"), cell_style),
                self._build_cell(direction, direction_style),
                self._build_cell(row.get("created_by"), cell_style),
            ])

        table = Table(
            table_rows,
            colWidths=[
                1.22 * inch,
                1.22 * inch,
                0.95 * inch,
                0.95 * inch,
                3.15 * inch,
                0.80 * inch,
                0.68 * inch,
                0.95 * inch,
            ],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f5ea8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d6df")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("ALIGN", (0, 1), (3, -1), "CENTER"),
            ("ALIGN", (5, 1), (7, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
