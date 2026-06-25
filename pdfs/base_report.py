from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from datetime import datetime
import math
import os
import re

from utils.paths import REPORTS_DIR, resolve_path


class BasePDFReport:
    """
    Classe base para geração de relatórios em PDF.
    Organiza por tipo de relatório / ano / mês,
    valida nomes no Windows e evita sobrescrita de arquivos.
    """

    INVALID_CHARS_PATTERN = r'[<>:"/\\|?*]'  # Windows invalid chars
    CHART_PALETTE = (
        colors.HexColor("#0F6CBD"),
        colors.HexColor("#2D8B57"),
        colors.HexColor("#E67E22"),
        colors.HexColor("#8E44AD"),
        colors.HexColor("#D64545"),
        colors.HexColor("#16A085"),
        colors.HexColor("#5C6BC0"),
        colors.HexColor("#F4B400"),
    )

    def __init__(self, output_dir=None):
        resolved_output_dir = output_dir or REPORTS_DIR
        self.base_output_dir = str(resolve_path(resolved_output_dir))
        self.styles = getSampleStyleSheet()
        self._ensure_directory(self.base_output_dir)

    # ─────────────────────────────────────────────
    # 📁 GERENCIAMENTO DE DIRETÓRIOS
    # ─────────────────────────────────────────────
    def _ensure_directory(self, path):
        if not os.path.exists(path):
            os.makedirs(path)

    # ─────────────────────────────────────────────
    # 🧹 LIMPEZA DE NOMES (WINDOWS SAFE)
    # ─────────────────────────────────────────────
    def _sanitize_name(self, name: str) -> str:
        """
        Remove caracteres inválidos no Windows
        """
        name = re.sub(self.INVALID_CHARS_PATTERN, "", name)
        return name.strip()

    # ─────────────────────────────────────────────
    # 🔁 EVITAR SOBRESCRITA DE PDF
    # ─────────────────────────────────────────────
    def _resolve_duplicate_filename(self, directory, filename):
        """
        Se arquivo existir, cria nome com (1), (2), ...
        """
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename

        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f"{base}({counter}){ext}"
            counter += 1

        return new_filename

    # ─────────────────────────────────────────────
    # 📄 CRIA NOME FINAL DO PDF
    # ─────────────────────────────────────────────
    def _get_timestamp_filename(self, report_type: str):
        """
        Cria caminho final do PDF:
        Relatórios/Tipo do Relatório/AAAA-MM-DD/arquivo.pdf
        """

        now = datetime.now()

        safe_report_type = self._sanitize_name(report_type)

        # 📅 Pasta de data completa (ÚLTIMA pasta)
        date_folder = now.strftime("%Y-%m-%d")

        # ⏱️ Hora no nome do ficheiro
        time_part = now.strftime("%H-%M-%S")

        # 📁 Diretório final
        final_dir = os.path.join(
            self.base_output_dir,
            safe_report_type,
            date_folder
        )
        self._ensure_directory(final_dir)

        # 📄 Nome base do PDF
        base_filename = f"{safe_report_type.lower().replace(' ', '_')}_{time_part}.pdf"
        base_filename = self._sanitize_name(base_filename)

        # 🔁 Evita sobrescrever ficheiros
        final_filename = self._resolve_duplicate_filename(
            final_dir,
            base_filename
        )

        return os.path.join(final_dir, final_filename)

    # ─────────────────────────────────────────────
    # 🧾 CABEÇALHO PADRÃO
    # ─────────────────────────────────────────────
    def _create_header(self, elements, title, report_type, filters):
        header_style = ParagraphStyle(
            'HeaderTitle',
            parent=self.styles['Heading1'],
            fontSize=26,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=25,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )

        elements.append(Paragraph(f"<b>{title}</b>", header_style))

        info_data = [
            ['Tipo de Relatório:', report_type],
            [
                'Período:',
                f"{filters['start_date'].strftime('%d/%m/%Y')} até {filters['end_date'].strftime('%d/%m/%Y')}"
            ],
            ['Produto:', filters.get('product', 'Todos os Produtos')],
            ['Categoria:', filters.get('category', 'Todas as Categorias')],
            ['Vendedor/Gerente:', filters.get('seller', 'Todos os Vendedores')],
            ['Gerado em:', datetime.now().strftime('%d/%m/%Y %H:%M:%S')],
        ]

        info_table = Table(info_data, colWidths=[2.8 * inch, 5.2 * inch])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#2c3e50')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))

        elements.append(info_table)
        elements.append(Spacer(1, 20))

    # ─────────────────────────────────────────────
    # 🔻 RODAPÉ PADRÃO
    # ─────────────────────────────────────────────
    def _create_footer(self, elements):
        elements.append(Spacer(1, 30))

        footer_style = ParagraphStyle(
            'Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )

        footer_text = f"Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        elements.append(Paragraph(footer_text, footer_style))

    # ─────────────────────────────────────────────
    # 🚫 MÉTODO ABSTRATO
    # ─────────────────────────────────────────────
    def _to_float(self, value, default=0.0):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(numeric) or math.isinf(numeric):
            return default
        return numeric

    def _truncate_text(self, value, max_len=28):
        text = str(value or "").strip() or "Sem rotulo"
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    def _format_chart_value(self, value, formatter=None):
        if callable(formatter):
            return str(formatter(value))
        numeric = self._to_float(value)
        if abs(numeric) >= 1000:
            return f"{numeric:,.2f}"
        if float(numeric).is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}"

    def _build_bar_chart(
        self,
        title,
        items,
        width=10.0 * inch,
        max_items=7,
        value_formatter=None,
        accent_color="#2c3e50",
        sort_items=True,
        empty_message="Sem dados para gerar o grafico.",
    ):
        normalized = []
        for item in items or []:
            if isinstance(item, dict):
                label = item.get("label")
                value = self._to_float(item.get("value"))
                color = item.get("color")
            else:
                label = item[0] if len(item) > 0 else "Sem rotulo"
                value = self._to_float(item[1] if len(item) > 1 else 0)
                color = item[2] if len(item) > 2 else None
            if color is not None and isinstance(color, str):
                color = colors.HexColor(color)
            normalized.append((self._truncate_text(label, 30), value, color))

        if sort_items:
            normalized.sort(key=lambda row: row[1], reverse=True)
        if max_items:
            normalized = normalized[:max_items]

        title_color = colors.HexColor(accent_color) if isinstance(accent_color, str) else accent_color
        if not normalized:
            drawing = Drawing(width, 82)
            drawing.add(String(16, 58, title, fontName="Helvetica-Bold", fontSize=12, fillColor=title_color))
            drawing.add(
                String(
                    16,
                    34,
                    empty_message,
                    fontName="Helvetica",
                    fontSize=9,
                    fillColor=colors.HexColor("#7f8c8d"),
                )
            )
            return drawing

        max_value = max(max(value for _, value, _ in normalized), 1.0)
        left_padding = 18
        label_width = min(190, width * 0.28)
        value_width = 104
        chart_x = left_padding + label_width
        chart_width = max(120, width - chart_x - value_width - 18)
        row_height = 26
        bar_height = 14
        axis_y = 20
        height = 78 + (len(normalized) * row_height)
        drawing = Drawing(width, height)

        drawing.add(
            String(
                left_padding,
                height - 18,
                title,
                fontName="Helvetica-Bold",
                fontSize=12,
                fillColor=title_color,
            )
        )
        drawing.add(
            String(
                left_padding,
                height - 32,
                "Grafico de barras colorido preparado para impressao em PDF.",
                fontName="Helvetica",
                fontSize=7.8,
                fillColor=colors.HexColor("#7f8c8d"),
            )
        )
        drawing.add(
            Line(
                chart_x,
                axis_y,
                chart_x + chart_width,
                axis_y,
                strokeColor=colors.HexColor("#d8dee6"),
                strokeWidth=0.8,
            )
        )
        drawing.add(
            String(
                chart_x,
                axis_y - 11,
                "0",
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#8a96a3"),
            )
        )
        max_label = self._format_chart_value(max_value, value_formatter)
        drawing.add(
            String(
                chart_x + chart_width - max(18, len(max_label) * 4),
                axis_y - 11,
                max_label,
                fontName="Helvetica",
                fontSize=7,
                fillColor=colors.HexColor("#8a96a3"),
            )
        )

        first_bar_y = height - 58
        for index, (label, value, color) in enumerate(normalized):
            fill_color = color or self.CHART_PALETTE[index % len(self.CHART_PALETTE)]
            bar_y = first_bar_y - (index * row_height)
            bar_width = 0 if value <= 0 else max(6, chart_width * (value / max_value))
            bar_width = min(chart_width, bar_width)

            drawing.add(
                Rect(
                    chart_x,
                    bar_y,
                    chart_width,
                    bar_height,
                    fillColor=colors.HexColor("#eef2f6"),
                    strokeColor=colors.HexColor("#d8dee6"),
                    strokeWidth=0.45,
                )
            )
            if bar_width > 0:
                drawing.add(
                    Rect(
                        chart_x,
                        bar_y,
                        bar_width,
                        bar_height,
                        fillColor=fill_color,
                        strokeColor=fill_color,
                    )
                )

            drawing.add(
                Rect(
                    left_padding,
                    bar_y + 2,
                    10,
                    10,
                    fillColor=fill_color,
                    strokeColor=fill_color,
                )
            )
            drawing.add(
                String(
                    left_padding + 16,
                    bar_y + 2,
                    label,
                    fontName="Helvetica-Bold",
                    fontSize=8.5,
                    fillColor=colors.HexColor("#2c3e50"),
                )
            )
            drawing.add(
                String(
                    chart_x + chart_width + 12,
                    bar_y + 2,
                    self._format_chart_value(value, value_formatter),
                    fontName="Helvetica-Bold",
                    fontSize=8.5,
                    fillColor=fill_color,
                )
            )

        return drawing

    def generate(self, data, filters):
        raise NotImplementedError("Subclasses devem implementar generate()")
