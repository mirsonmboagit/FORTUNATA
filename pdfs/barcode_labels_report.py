from datetime import datetime

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import eanbc
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .base_report import BasePDFReport


class BarcodeLabelsReport(BasePDFReport):
    """Gera folhas A4 com etiquetas de codigos de barras recortaveis."""

    def generate(self, labels):
        pdf_path = self._get_timestamp_filename("etiquetas_codigos_barras")
        c = canvas.Canvas(pdf_path, pagesize=A4)
        page_w, page_h = A4

        margin_x = 9 * mm
        margin_y = 11 * mm
        cols = 3
        rows = 8
        label_w = (page_w - (2 * margin_x)) / cols
        label_h = (page_h - (2 * margin_y)) / rows

        labels = list(labels or [])
        for index, label in enumerate(labels):
            slot = index % (cols * rows)
            if index and slot == 0:
                self._draw_footer(c, page_w)
                c.showPage()

            row = slot // cols
            col = slot % cols
            x = margin_x + (col * label_w)
            y = page_h - margin_y - ((row + 1) * label_h)
            self._draw_cut_box(c, x, y, label_w, label_h)
            self._draw_label(c, x, y, label_w, label_h, label)

        if not labels:
            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(page_w / 2, page_h / 2, "Sem etiquetas para gerar.")

        self._draw_footer(c, page_w)
        c.save()
        return pdf_path

    def _draw_cut_box(self, c, x, y, w, h):
        c.saveState()
        c.setStrokeColor(colors.HexColor("#b8c2cc"))
        c.setLineWidth(0.35)
        c.setDash(2, 2)
        c.rect(x, y, w, h, stroke=1, fill=0)
        c.setDash()
        mark = 3.2 * mm
        c.setStrokeColor(colors.HexColor("#77818c"))
        for mx, my, sx, sy in (
            (x, y, 1, 1),
            (x + w, y, -1, 1),
            (x, y + h, 1, -1),
            (x + w, y + h, -1, -1),
        ):
            c.line(mx, my, mx + (mark * sx), my)
            c.line(mx, my, mx, my + (mark * sy))
        c.restoreState()

    def _draw_label(self, c, x, y, w, h, label):
        name = self._clean_text(label.get("name"), 34)
        barcode_value = str(label.get("barcode") or "").strip()
        copy_no = int(label.get("copy_no") or 1)
        copies = int(label.get("copies") or 1)

        pad_x = 4.5 * mm
        title_y = y + h - 6 * mm
        c.setFillColor(colors.HexColor("#3a67b7"))
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + (w / 2), title_y, "EAN-13")

        barcode = eanbc.Ean13BarcodeWidget(barcode_value)
        barcode.barHeight = 15.5 * mm
        barcode.barWidth = 0.34 * mm
        barcode.fontName = "Helvetica"
        barcode.fontSize = 7.8
        barcode.humanReadable = True
        barcode_width = barcode.getBounds()[2] - barcode.getBounds()[0]
        barcode_height = barcode.getBounds()[3] - barcode.getBounds()[1]
        drawing = Drawing(barcode_width, barcode_height)
        drawing.add(barcode)
        barcode_x = x + (w - barcode_width) / 2
        barcode_y = y + 7.4 * mm
        renderPDF.draw(drawing, c, barcode_x, barcode_y)

        c.setFillColor(colors.HexColor("#5f6b77"))
        c.setFont("Helvetica", 5.8)
        c.drawString(x + pad_x, y + 3 * mm, name)
        c.drawRightString(x + w - pad_x, y + 3 * mm, f"{copy_no}/{copies}")

    def _draw_footer(self, c, page_w):
        c.setFillColor(colors.HexColor("#7b8794"))
        c.setFont("Helvetica", 7)
        c.drawCentredString(
            page_w / 2,
            5 * mm,
            f"Etiquetas geradas em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        )

    @staticmethod
    def _clean_text(value, max_len):
        text = " ".join(str(value or "Produto").split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."
