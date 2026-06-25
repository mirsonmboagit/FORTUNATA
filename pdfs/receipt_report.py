import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Preformatted

from .base_report import BasePDFReport
from utils.paths import RECEIPTS_DIR
from utils.thermal_printer import format_receipt_text


class ReceiptReport(BasePDFReport):
    def __init__(self, output_dir=None):
        output_dir = output_dir or RECEIPTS_DIR
        super().__init__(output_dir=output_dir)

    def _get_operator_timestamp_filename(self, receipt_data):
        operator = str((receipt_data or {}).get("operator") or "Operador").strip()
        safe_operator = self._sanitize_name(operator) or "Operador"
        safe_report_type = self._sanitize_name("recibo_venda")
        now = datetime.now()
        date_folder = now.strftime("%Y-%m-%d")
        time_part = now.strftime("%H-%M-%S")
        final_dir = os.path.join(
            self.base_output_dir,
            safe_operator,
            safe_report_type,
            date_folder,
        )
        self._ensure_directory(final_dir)
        base_filename = self._sanitize_name(f"{safe_report_type}_{time_part}.pdf")
        final_filename = self._resolve_duplicate_filename(final_dir, base_filename)
        return os.path.join(final_dir, final_filename)

    def generate(self, receipt_data, paper_width_mm=80):
        receipt_data = receipt_data or {}
        pdf_path = self._get_operator_timestamp_filename(receipt_data)
        try:
            paper_width_mm = int(paper_width_mm or 80)
        except Exception:
            paper_width_mm = 80
        paper_width_mm = 58 if paper_width_mm <= 58 else 80

        receipt_text = format_receipt_text(receipt_data, paper_width_mm=paper_width_mm).rstrip()
        line_count = max(1, len(receipt_text.splitlines()))
        font_size = 6.6 if paper_width_mm <= 58 else 7.4
        leading = font_size + 2.0
        margin = 4 * mm
        page_width = paper_width_mm * mm
        page_height = max(120 * mm, (line_count * leading) + (margin * 2) + (8 * mm))

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=(page_width, page_height),
            topMargin=margin,
            bottomMargin=margin,
            leftMargin=margin,
            rightMargin=margin,
        )

        style = ParagraphStyle(
            "ThermalReceiptText",
            fontName="Courier",
            fontSize=font_size,
            leading=leading,
            textColor=colors.black,
            splitLongWords=1,
        )

        doc.build([Preformatted(receipt_text, style)])
        return pdf_path
