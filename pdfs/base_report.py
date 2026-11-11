from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import (
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    KeepTogether,
    HRFlowable,
    SimpleDocTemplate,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import inch, mm
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from datetime import datetime
import math
import os
import re

from utils.config.paths import REPORTS_DIR, resolve_path
from .i18n import current_pdf_language, pdf_font, pdf_text


# ── Paleta visual limpa (fácil de ler em ecrã e impressão) ──────────────────
_C = {
    "ink": colors.HexColor("#1B2430"),
    "muted": colors.HexColor("#5B6775"),
    "soft": colors.HexColor("#8A96A3"),
    "line": colors.HexColor("#D8DEE6"),
    "line_strong": colors.HexColor("#B8C2CE"),
    "surface": colors.HexColor("#F5F7FA"),
    "surface_alt": colors.HexColor("#EEF2F6"),
    "header_bg": colors.HexColor("#1F3A5F"),
    "header_fg": colors.white,
    "accent": colors.HexColor("#0F6CBD"),
    "accent_soft": colors.HexColor("#E8F1FB"),
    "success": colors.HexColor("#2D8B57"),
    "warn": colors.HexColor("#E67E22"),
    "danger": colors.HexColor("#D64545"),
}


class BasePDFReport:
    """
    Classe base para geração de relatórios em PDF.
    - Orientação horizontal (landscape) por omissão
    - Layout limpo, legível e organizado
    - Pastas: Relatórios/Tipo/AAAA-MM-DD/arquivo.pdf
    """

    INVALID_CHARS_PATTERN = r'[<>:"/\\|?*]'
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

    # Página em paisagem (horizontal)
    PAGE_SIZE = landscape(A4)
    # Margens equilibradas para não “esmagar” o conteúdo
    MARGIN_LEFT = 16 * mm
    MARGIN_RIGHT = 16 * mm
    MARGIN_TOP = 14 * mm
    MARGIN_BOTTOM = 14 * mm

    def __init__(self, output_dir=None):
        resolved_output_dir = output_dir or REPORTS_DIR
        self.base_output_dir = str(resolve_path(resolved_output_dir))
        self.language = current_pdf_language()
        if self.language == "zh":
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        self.styles = getSampleStyleSheet()
        self._register_styles()
        if self.language == "zh":
            for style_name in (
                "ReportTitle", "ReportSubtitle", "SectionTitle", "BodyClean",
                "MetaLabel", "MetaValue", "TableHeader", "TableHeaderRight",
                "TableCell", "TableCellRight", "FooterNote", "KPIValue", "KPILabel",
            ):
                self.styles[style_name].fontName = pdf_font(self.language)
        self._ensure_directory(self.base_output_dir)

    def _t(self, value):
        """Traduz texto estático no idioma usado no momento da geração."""
        return pdf_text(value, self.language)

    def _translate_table(self, rows):
        """Traduz rótulos conhecidos, mantendo dados livres intactos."""
        return [[self._t(cell) if isinstance(cell, str) else cell for cell in row] for row in rows]

    # ─────────────────────────────────────────────
    # Estilos tipográficos
    # ─────────────────────────────────────────────
    def _register_styles(self):
        self.styles.add(
            ParagraphStyle(
                name="ReportTitle",
                fontName="Helvetica-Bold",
                fontSize=18,
                leading=22,
                textColor=_C["ink"],
                alignment=TA_LEFT,
                spaceAfter=2,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="ReportSubtitle",
                fontName="Helvetica",
                fontSize=9,
                leading=12,
                textColor=_C["muted"],
                alignment=TA_LEFT,
                spaceAfter=0,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="SectionTitle",
                fontName="Helvetica-Bold",
                fontSize=11,
                leading=14,
                textColor=_C["ink"],
                spaceBefore=10,
                spaceAfter=6,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="BodyClean",
                fontName="Helvetica",
                fontSize=9,
                leading=12,
                textColor=_C["ink"],
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="MetaLabel",
                fontName="Helvetica-Bold",
                fontSize=8,
                leading=10,
                textColor=_C["muted"],
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="MetaValue",
                fontName="Helvetica",
                fontSize=8.5,
                leading=11,
                textColor=_C["ink"],
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="TableHeader",
                fontName="Helvetica-Bold",
                fontSize=8,
                leading=10,
                textColor=_C["header_fg"],
                alignment=TA_LEFT,
            )
        )
        # NOVO: cabeçalho alinhado à direita (colunas numéricas)
        self.styles.add(
            ParagraphStyle(
                name="TableHeaderRight",
                fontName="Helvetica-Bold",
                fontSize=8,
                leading=10,
                textColor=_C["header_fg"],
                alignment=TA_RIGHT,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="TableCell",
                fontName="Helvetica",
                fontSize=8,
                leading=10,
                textColor=_C["ink"],
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="TableCellRight",
                fontName="Helvetica",
                fontSize=8,
                leading=10,
                textColor=_C["ink"],
                alignment=TA_RIGHT,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="FooterNote",
                fontName="Helvetica",
                fontSize=7.5,
                leading=9,
                textColor=_C["soft"],
                alignment=TA_CENTER,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="KPIValue",
                fontName="Helvetica-Bold",
                fontSize=14,
                leading=16,
                textColor=_C["ink"],
                alignment=TA_CENTER,
            )
        )
        self.styles.add(
            ParagraphStyle(
                name="KPILabel",
                fontName="Helvetica",
                fontSize=7.5,
                leading=9,
                textColor=_C["muted"],
                alignment=TA_CENTER,
            )
        )

    def _ensure_directory(self, path):
        if not os.path.exists(path):
            os.makedirs(path)

    def _sanitize_name(self, name: str) -> str:
        name = re.sub(self.INVALID_CHARS_PATTERN, "", str(name or ""))
        return name.strip()

    def _resolve_duplicate_filename(self, directory, filename):
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename
        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f"{base}({counter}){ext}"
            counter += 1
        return new_filename

    def _get_timestamp_filename(self, report_type: str):
        now = datetime.now()
        safe_report_type = self._sanitize_name(report_type)
        date_folder = now.strftime("%Y-%m-%d")
        time_part = now.strftime("%H-%M-%S")
        final_dir = os.path.join(self.base_output_dir, safe_report_type, date_folder)
        self._ensure_directory(final_dir)
        base_filename = f"{safe_report_type.lower().replace(' ', '_')}_{time_part}.pdf"
        base_filename = self._sanitize_name(base_filename)
        final_filename = self._resolve_duplicate_filename(final_dir, base_filename)
        return os.path.join(final_dir, final_filename)

    # ─────────────────────────────────────────────
    # Documento landscape pronto a usar
    # ─────────────────────────────────────────────
    def _create_document(self, filepath, title="Relatório NECTAR"):
        """SimpleDocTemplate em orientação horizontal com margens limpas."""
        return SimpleDocTemplate(
            filepath,
            pagesize=self.PAGE_SIZE,
            leftMargin=self.MARGIN_LEFT,
            rightMargin=self.MARGIN_RIGHT,
            topMargin=self.MARGIN_TOP,
            bottomMargin=self.MARGIN_BOTTOM,
            title=title,
            author="NECTAR",
        )

    def _usable_width(self):
        return self.PAGE_SIZE[0] - self.MARGIN_LEFT - self.MARGIN_RIGHT

    # ─────────────────────────────────────────────
    # Cabeçalho limpo
    # ─────────────────────────────────────────────
    def _create_header(self, elements, title, report_type, filters):
        """Cabeçalho compacto: título + faixa de metadados em grelha."""
        filters = filters or {}
        title = self._t(title or "Relatório")
        report_type = self._t(report_type)

        # Título + tipo
        title_block = [
            Paragraph(str(title or "Relatório"), self.styles["ReportTitle"]),
            Paragraph(
                f"NECTAR  ·  {report_type}",
                self.styles["ReportSubtitle"],
            ),
        ]
        for block in title_block:
            elements.append(block)

        elements.append(Spacer(1, 6))
        elements.append(
            HRFlowable(
                width="100%",
                thickness=1.2,
                color=_C["accent"],
                spaceBefore=0,
                spaceAfter=8,
            )
        )

        # Metadados em duas colunas (fácil de ler)
        start = filters.get("start_date")
        end = filters.get("end_date")
        if hasattr(start, "strftime") and hasattr(end, "strftime"):
            period = f"{start.strftime('%d/%m/%Y')} — {end.strftime('%d/%m/%Y')}"
        else:
            period = f"{start or '—'} — {end or '—'}"

        meta_rows = [
            [
                Paragraph("<b>Período</b>", self.styles["MetaLabel"]),
                Paragraph(period, self.styles["MetaValue"]),
                Paragraph("<b>Produto</b>", self.styles["MetaLabel"]),
                Paragraph(
                    str(filters.get("product", "Todos os produtos")),
                    self.styles["MetaValue"],
                ),
            ],
            [
                Paragraph("<b>Categoria</b>", self.styles["MetaLabel"]),
                Paragraph(
                    str(filters.get("category", "Todas as categorias")),
                    self.styles["MetaValue"],
                ),
                Paragraph("<b>Vendedor</b>", self.styles["MetaLabel"]),
                Paragraph(
                    str(filters.get("seller", "Todos os vendedores")),
                    self.styles["MetaValue"],
                ),
            ],
            [
                Paragraph("<b>Criado em</b>", self.styles["MetaLabel"]),
                Paragraph(
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                    self.styles["MetaValue"],
                ),
                Paragraph("<b>Tipo</b>", self.styles["MetaLabel"]),
                Paragraph(str(report_type), self.styles["MetaValue"]),
            ],
        ]

        usable = self._usable_width()
        col_w = [usable * 0.12, usable * 0.38, usable * 0.12, usable * 0.38]
        meta = Table(meta_rows, colWidths=col_w)
        meta.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), _C["surface"]),
                    ("BOX", (0, 0), (-1, -1), 0.6, _C["line"]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, _C["line"]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(meta)
        elements.append(Spacer(1, 12))

    def _create_section_title(self, elements, text):
        elements.append(Paragraph(self._t(text), self.styles["SectionTitle"]))
        elements.append(
            HRFlowable(
                width="100%",
                thickness=0.6,
                color=_C["line_strong"],
                spaceBefore=0,
                spaceAfter=6,
            )
        )

    # ─────────────────────────────────────────────
    # Tabela limpa (cabeçalho escuro, zebra suave)
    # ─────────────────────────────────────────────
    def _build_clean_table(
        self,
        headers,
        rows,
        col_widths=None,
        numeric_cols=None,
    ):
        """
        Tabela legível: header forte, linhas alternadas, padding generoso.

        Colunas numéricas: cabeçalho E valores alinhados à direita
        (o alinhamento de um Paragraph vem do estilo, não do TableStyle).
        """
        numeric_cols = set(numeric_cols or [])

        # Cabeçalho: mesmo alinhamento que os valores da coluna
        header_cells = [
            Paragraph(
                self._t(h),
                self.styles["TableHeaderRight"]
                if idx in numeric_cols
                else self.styles["TableHeader"],
            )
            for idx, h in enumerate(headers)
        ]
        data = [header_cells]

        for row in rows or []:
            cells = []
            for idx, cell in enumerate(row):
                # Já é Flowable (ex.: Paragraph) — usar diretamente
                if hasattr(cell, "wrap") and hasattr(cell, "drawOn"):
                    cells.append(cell)
                    continue
                style = (
                    self.styles["TableCellRight"]
                    if idx in numeric_cols
                    else self.styles["TableCell"]
                )
                text = "—" if cell is None else str(cell)
                cells.append(Paragraph(text, style))
            data.append(cells)

        if col_widths is None:
            usable = self._usable_width()
            n = max(len(headers), 1)
            col_widths = [usable / n] * n

        table = Table(data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), _C["header_bg"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), _C["header_fg"]),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.7, _C["header_bg"]),
            ("LINEBELOW", (0, 0), (-1, 0), 0, _C["header_bg"]),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_C["surface"], colors.white]),
            ("LINEBELOW", (0, 1), (-1, -2), 0.3, _C["line"]),
        ]

        for col in numeric_cols:
            # Mais folga à direita nas colunas numéricas
            style_cmds.append(("RIGHTPADDING", (col, 0), (col, -1), 10))
            # E mais folga à esquerda na coluna de texto logo a seguir
            nxt = col + 1
            if nxt < len(headers) and nxt not in numeric_cols:
                style_cmds.append(("LEFTPADDING", (nxt, 0), (nxt, -1), 12))

        table.setStyle(TableStyle(style_cmds))
        return table

    # ─────────────────────────────────────────────
    # Cartões KPI (resumo no topo)
    # ─────────────────────────────────────────────
    def _build_kpi_row(self, kpis):
        """
        kpis: lista de dicts {label, value} ou tuplos (label, value)
        Mostra até 5 indicadores lado a lado.
        """
        items = []
        for item in (kpis or [])[:5]:
            if isinstance(item, dict):
                label = item.get("label", "")
                value = item.get("value", "—")
            else:
                label = item[0] if len(item) > 0 else ""
                value = item[1] if len(item) > 1 else "—"
            items.append(
                [
                    Paragraph(str(value), self.styles["KPIValue"]),
                    Paragraph(self._t(label), self.styles["KPILabel"]),
                ]
            )

        if not items:
            return Spacer(1, 1)

        usable = self._usable_width()
        n = len(items)
        gap = 6
        cell_w = (usable - gap * (n - 1)) / n

        # Cada KPI é uma mini-tabela de 1 coluna
        cells = []
        for block in items:
            inner = Table([block[0:1], block[1:2]], colWidths=[cell_w - 4])
            inner.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), _C["accent_soft"]),
                        ("BOX", (0, 0), (-1, -1), 0.6, _C["line"]),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            cells.append(inner)

        row = Table([cells], colWidths=[cell_w] * n)
        row.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), gap),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return row

    # ─────────────────────────────────────────────
    # Rodapé
    # ─────────────────────────────────────────────
    def _create_footer(self, elements):
        elements.append(Spacer(1, 16))
        elements.append(
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=_C["line"],
                spaceBefore=0,
                spaceAfter=6,
            )
        )
        elements.append(
            Paragraph(
                f"NECTAR  ·  Relatório gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  ·  Uso interno",
                self.styles["FooterNote"],
            )
        )

    # ─────────────────────────────────────────────
    # Helpers numéricos / texto
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
        text = str(value or "").strip() or "Sem rótulo"
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

    # ─────────────────────────────────────────────
    # Gráfico de barras (paisagem — mais largo)
    # ─────────────────────────────────────────────
    def _build_bar_chart(
        self,
        title,
        items,
        width=None,
        max_items=8,
        value_formatter=None,
        accent_color="#0F6CBD",
        sort_items=True,
        empty_message="Não há dados para mostrar neste gráfico.",
    ):
        if width is None:
            width = self._usable_width()

        normalized = []
        for item in items or []:
            if isinstance(item, dict):
                label = item.get("label")
                value = self._to_float(item.get("value"))
                color = item.get("color")
            else:
                label = item[0] if len(item) > 0 else "Sem rótulo"
                value = self._to_float(item[1] if len(item) > 1 else 0)
                color = item[2] if len(item) > 2 else None
            if color is not None and isinstance(color, str):
                color = colors.HexColor(color)
            normalized.append((self._truncate_text(label, 32), value, color))

        if sort_items:
            normalized.sort(key=lambda row: row[1], reverse=True)
        if max_items:
            normalized = normalized[:max_items]

        title_color = (
            colors.HexColor(accent_color)
            if isinstance(accent_color, str)
            else accent_color
        )
        if not normalized:
            drawing = Drawing(width, 72)
            drawing.add(
                String(
                    12,
                    48,
                    title,
                    fontName="Helvetica-Bold",
                    fontSize=11,
                    fillColor=title_color,
                )
            )
            drawing.add(
                String(
                    12,
                    28,
                    empty_message,
                    fontName="Helvetica",
                    fontSize=9,
                    fillColor=_C["soft"],
                )
            )
            return drawing

        max_value = max(max(value for _, value, _ in normalized), 1.0)
        left_padding = 14
        label_width = min(200, width * 0.26)
        value_width = 96
        chart_x = left_padding + label_width
        chart_width = max(140, width - chart_x - value_width - 14)
        row_height = 24
        bar_height = 13
        axis_y = 18
        height = 70 + (len(normalized) * row_height)
        drawing = Drawing(width, height)

        drawing.add(
            String(
                left_padding,
                height - 16,
                title,
                fontName="Helvetica-Bold",
                fontSize=11,
                fillColor=title_color,
            )
        )
        drawing.add(
            Line(
                chart_x,
                axis_y,
                chart_x + chart_width,
                axis_y,
                strokeColor=_C["line"],
                strokeWidth=0.7,
            )
        )
        drawing.add(
            String(
                chart_x,
                axis_y - 10,
                "0",
                fontName="Helvetica",
                fontSize=7,
                fillColor=_C["soft"],
            )
        )
        max_label = self._format_chart_value(max_value, value_formatter)
        drawing.add(
            String(
                chart_x + chart_width - max(16, len(max_label) * 3.8),
                axis_y - 10,
                max_label,
                fontName="Helvetica",
                fontSize=7,
                fillColor=_C["soft"],
            )
        )

        first_bar_y = height - 52
        for index, (label, value, color) in enumerate(normalized):
            fill_color = color or self.CHART_PALETTE[index % len(self.CHART_PALETTE)]
            bar_y = first_bar_y - (index * row_height)
            bar_width = 0 if value <= 0 else max(5, chart_width * (value / max_value))
            bar_width = min(chart_width, bar_width)

            # Pista de fundo
            drawing.add(
                Rect(
                    chart_x,
                    bar_y,
                    chart_width,
                    bar_height,
                    fillColor=_C["surface_alt"],
                    strokeColor=_C["line"],
                    strokeWidth=0.4,
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

            # Marcador de cor + rótulo
            drawing.add(
                Rect(
                    left_padding,
                    bar_y + 1.5,
                    9,
                    9,
                    fillColor=fill_color,
                    strokeColor=fill_color,
                )
            )
            drawing.add(
                String(
                    left_padding + 14,
                    bar_y + 1.5,
                    label,
                    fontName="Helvetica-Bold",
                    fontSize=8,
                    fillColor=_C["ink"],
                )
            )
            drawing.add(
                String(
                    chart_x + chart_width + 10,
                    bar_y + 1.5,
                    self._format_chart_value(value, value_formatter),
                    fontName="Helvetica-Bold",
                    fontSize=8,
                    fillColor=fill_color,
                )
            )

        return drawing

    def generate(self, data, filters):
        raise NotImplementedError("Subclasses devem implementar generate()")
