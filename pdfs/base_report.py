from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from datetime import datetime
import os
import re


class BasePDFReport:
    """
    Classe base para geração de relatórios em PDF.
    Organiza por tipo de relatório / ano / mês,
    valida nomes no Windows e evita sobrescrita de arquivos.
    """

    INVALID_CHARS_PATTERN = r'[<>:"/\\|?*]'  # Windows invalid chars

    def __init__(self, output_dir="Relatórios"):
        self.base_output_dir = os.path.abspath(output_dir)
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
    def generate(self, data, filters):
        raise NotImplementedError("Subclasses devem implementar generate()")
