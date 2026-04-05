from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .base_report import BasePDFReport


class ReceiptReport(BasePDFReport):
    def __init__(self, output_dir="Recibos"):
        super().__init__(output_dir=output_dir)

    @staticmethod
    def _money(value):
        try:
            return f"{float(value or 0.0):,.2f} MZN".replace(",", " ")
        except Exception:
            return "0.00 MZN"

    def generate(self, receipt_data):
        pdf_path = self._get_timestamp_filename("recibo_venda")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A5,
            topMargin=0.4 * inch,
            bottomMargin=0.45 * inch,
            leftMargin=0.45 * inch,
            rightMargin=0.45 * inch,
        )

        styles = getSampleStyleSheet()
        brand_style = ParagraphStyle(
            "ReceiptBrand",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#d9e7f2"),
            alignment=TA_CENTER,
        )
        title_style = ParagraphStyle(
            "ReceiptTitle",
            parent=styles["Heading1"],
            fontSize=18,
            leading=20,
            textColor=colors.white,
            alignment=TA_CENTER,
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReceiptSubtitle",
            parent=styles["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#d9e7f2"),
            alignment=TA_CENTER,
        )
        section_style = ParagraphStyle(
            "ReceiptSection",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#16324f"),
            alignment=TA_LEFT,
        )
        label_style = ParagraphStyle(
            "ReceiptLabel",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#62707e"),
            alignment=TA_LEFT,
        )
        value_style = ParagraphStyle(
            "ReceiptValue",
            parent=styles["BodyText"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#1a1f24"),
            alignment=TA_RIGHT,
        )
        total_label_style = ParagraphStyle(
            "ReceiptTotalLabel",
            parent=styles["BodyText"],
            fontSize=11,
            leading=13,
            textColor=colors.white,
            alignment=TA_LEFT,
        )
        total_value_style = ParagraphStyle(
            "ReceiptTotalValue",
            parent=styles["BodyText"],
            fontSize=12,
            leading=14,
            textColor=colors.white,
            alignment=TA_RIGHT,
        )
        note_style = ParagraphStyle(
            "ReceiptNote",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#6a7683"),
            alignment=TA_CENTER,
        )
        vat_note_style = ParagraphStyle(
            "ReceiptVatNote",
            parent=styles["BodyText"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#31506b"),
            alignment=TA_LEFT,
        )

        elements = []
        receipt_code = str(receipt_data.get("receipt_code") or "").strip()
        header_rows = [
            [Paragraph(receipt_data.get("store_name") or "Loja", brand_style)],
            [Paragraph("RECIBO DE VENDA", title_style)],
        ]
        if receipt_code:
            header_rows.append([Paragraph(f"Ref. {receipt_code}", subtitle_style)])

        header_table = Table(header_rows, colWidths=[4.54 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#16324f")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#16324f")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 10))

        meta_rows = [
            [
                Paragraph("Data", label_style),
                Paragraph(receipt_data.get("issued_at") or datetime.now().strftime("%d/%m/%Y %H:%M"), value_style),
            ],
            [
                Paragraph("Operador", label_style),
                Paragraph(receipt_data.get("operator") or "Sistema", value_style),
            ],
            [
                Paragraph("Itens", label_style),
                Paragraph(str(receipt_data.get("items_count") or 0), value_style),
            ],
        ]
        meta_table = Table(meta_rows, colWidths=[1.45 * inch, 1.95 * inch])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f8fb")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e0e8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8e0e8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(meta_table)
        elements.append(Spacer(1, 10))

        item_rows = [[
            Paragraph("Produto", section_style),
            Paragraph("Qtd", section_style),
            Paragraph("Preco", section_style),
            Paragraph("Total", section_style),
        ]]
        for item in receipt_data.get("items") or []:
            name = str(item.get("name") or "").strip()
            vat_tag = str(item.get("vat_tag") or "").strip()
            sale_mode = str(item.get("sale_mode_label") or "").strip()
            description = name
            details = " | ".join([part for part in (vat_tag, sale_mode) if part])
            if details:
                description = f"{description}<br/><font size=7 color='#6a7683'>{details}</font>"
            item_rows.append(
                [
                    Paragraph(description, section_style),
                    Paragraph(str(item.get("qty_text") or "-"), value_style),
                    Paragraph(self._money(item.get("unit_price")), value_style),
                    Paragraph(self._money(item.get("line_total")), value_style),
                ]
            )

        item_table = Table(item_rows, colWidths=[2.0 * inch, 0.62 * inch, 0.92 * inch, 1.0 * inch], repeatRows=1)
        item_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16324f")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e0e8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e1e7ee")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ]
            )
        )
        elements.append(item_table)
        elements.append(Spacer(1, 10))

        vat_note = str(receipt_data.get("vat_note") or "").strip()
        if vat_note:
            vat_table = Table([[Paragraph(vat_note, vat_note_style)]], colWidths=[4.54 * inch])
            vat_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf5fb")),
                        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8e0e8")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            elements.append(vat_table)
            elements.append(Spacer(1, 8))

        totals_rows = [
            [
                Paragraph("Subtotal", label_style),
                Paragraph(self._money(receipt_data.get("subtotal")), value_style),
            ],
            [
                Paragraph("IVA", label_style),
                Paragraph(self._money(receipt_data.get("vat_total")), value_style),
            ],
        ]
        paid_amount = receipt_data.get("paid_amount")
        if paid_amount is not None:
            totals_rows.append(
                [
                    Paragraph("Pago", label_style),
                    Paragraph(self._money(paid_amount), value_style),
                ]
            )
        change_amount = receipt_data.get("change_amount")
        if change_amount is not None:
            totals_rows.append(
                [
                    Paragraph("Troco", label_style),
                    Paragraph(self._money(change_amount), value_style),
                ]
            )

        totals_table = Table(totals_rows, colWidths=[1.45 * inch, 1.95 * inch], hAlign="RIGHT")
        totals_table.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(totals_table)
        elements.append(Spacer(1, 6))

        total_table = Table(
            [[
                Paragraph("TOTAL FINAL", total_label_style),
                Paragraph(self._money(receipt_data.get("total")), total_value_style),
            ]],
            colWidths=[1.75 * inch, 1.65 * inch],
            hAlign="RIGHT",
        )
        total_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1f7a45")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#1f7a45")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        elements.append(total_table)
        elements.append(Spacer(1, 12))

        footer_lines = []
        footer_lines.append("Documento gerado automaticamente pela aplicacao.")
        footer_lines.append("Obrigado pela preferencia.")
        elements.append(Paragraph("<br/>".join(footer_lines), note_style))

        doc.build(elements)
        return pdf_path
