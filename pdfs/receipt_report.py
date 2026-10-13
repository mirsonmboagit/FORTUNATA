import os
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Preformatted

from .base_report import BasePDFReport
from utils.config.paths import RECEIPTS_DIR
from utils.hardware.thermal_printer import format_receipt_text


class ReceiptReport(BasePDFReport):
    """
    Gera recibos em PDF para papel térmico de 58 mm ou 80 mm.

    Recursos visuais:
    - Usa assets/image/fundo.png como fundo, se o ficheiro existir.
    - Usa assets/image/main2.png centralizada no fim do recibo, se existir.
    - Se algum recurso não existir ou não puder ser lido, o PDF é gerado
      normalmente, sem esse recurso.
    """

    def __init__(self, output_dir=None):
        output_dir = output_dir or RECEIPTS_DIR
        super().__init__(output_dir=output_dir)
        self.project_root = self._find_project_root()

    @staticmethod
    def _find_project_root():
        """
        Procura a raiz do projeto a partir deste ficheiro.
        Funciona mesmo que este módulo esteja dentro de uma pasta reports/.
        """
        current = Path(__file__).resolve().parent
        for candidate in (current, *current.parents):
            if (candidate / "assets").is_dir():
                return candidate

        # Fallback comum: raiz do projeto acima da pasta do módulo.
        return Path(__file__).resolve().parents[1]

    def _find_asset(self, *relative_parts):
        """Devolve o primeiro caminho existente para um recurso."""
        candidates = [
            self.project_root.joinpath(*relative_parts),
            Path.cwd().joinpath(*relative_parts),
        ]

        # Também suporta execução a partir de uma pasta interna do projeto.
        try:
            candidates.append(
                Path(__file__).resolve().parents[1].joinpath(*relative_parts)
            )
        except (IndexError, OSError):
            pass

        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def _get_operator_timestamp_filename(self, receipt_data):
        operator = str((receipt_data or {}).get("operator") or "Atendente").strip()
        safe_operator = self._sanitize_name(operator) or "Atendente"
        safe_report_type = self._sanitize_name("recibo_venda")
        now = datetime.now()
        date_folder = now.strftime("%Y-%m-%d")

        # Mantém a hora no nome e evita colisões de ficheiros.
        time_part = now.strftime("%H-%M-%S")
        final_dir = os.path.join(
            self.base_output_dir,
            safe_operator,
            safe_report_type,
            date_folder,
        )
        self._ensure_directory(final_dir)

        base_filename = self._sanitize_name(
            f"{safe_report_type}_{time_part}.pdf"
        )
        final_filename = self._resolve_duplicate_filename(final_dir, base_filename)
        return os.path.join(final_dir, final_filename)

    @staticmethod
    def _image_reader(path):
        """
        Abre imagens com Pillow e devolve um ImageReader compatível com
        ReportLab. A conversão também permite usar ficheiros .ico.
        """
        if not path:
            return None

        try:
            with PILImage.open(path) as source:
                image = source.convert("RGBA")
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                buffer.seek(0)
                return ImageReader(buffer)
        except Exception:
            return None

    def _draw_page_decoration(
        self,
        pdf_canvas,
        doc,
        background_reader=None,
        footer_reader=None,
    ):
        """Desenha um fundo ampliado e a imagem de marca no fim do recibo."""
        page_width, page_height = doc.pagesize

        if background_reader is not None:
            try:
                pdf_canvas.saveState()
                # A folha fica maior e parcialmente fora da página, para que
                # apenas uma parte dela seja visível. A zona inferior continua
                # reservada para o logótipo main2.png, sem contacto entre ambos.
                # A cobra/folha deve ocupar aproximadamente 85% da área útil
                # do recibo, ficando cortada pelas margens e sem tocar no logótipo.
                footer_reserved_height = 21 * mm
                # Aumenta ainda mais a cobra/folha, deixando-a bem cortada
                # nas laterais e no topo, sem invadir a zona do logótipo.
                bg_width = page_width * 1.62
                bg_height = page_height * 1.12
                bg_x = (page_width - bg_width) / 2
                bg_y = footer_reserved_height

                # Desenha a folha com transparência reduzida para que o texto
                # do recibo permaneça legível por cima dela.
                pdf_canvas.saveState()
                try:
                    pdf_canvas.setFillAlpha(0.30)
                    pdf_canvas.setStrokeAlpha(0.30)
                except (AttributeError, TypeError):
                    # Compatibilidade com versões do ReportLab sem alpha.
                    pass

                pdf_canvas.drawImage(
                    background_reader,
                    bg_x,
                    bg_y,
                    width=bg_width,
                    height=bg_height,
                    preserveAspectRatio=False,
                    mask="auto",
                )
                pdf_canvas.restoreState()
                pdf_canvas.restoreState()
            except Exception:
                try:
                    pdf_canvas.restoreState()
                except Exception:
                    pass

        if footer_reader is not None:
            try:
                pdf_canvas.saveState()
                # Imagem centralizada perto do fim do recibo.
                image_width = min(page_width * 0.36, 21 * mm)
                image_height = 12 * mm
                x = (page_width - image_width) / 2
                y = 3 * mm
                pdf_canvas.drawImage(
                    footer_reader,
                    x,
                    y,
                    width=image_width,
                    height=image_height,
                    preserveAspectRatio=True,
                    anchor="c",
                    mask="auto",
                )
                pdf_canvas.restoreState()
            except Exception:
                try:
                    pdf_canvas.restoreState()
                except Exception:
                    pass

    def generate(self, receipt_data, paper_width_mm=80):
        """
        Gera o recibo e devolve o caminho completo do PDF.

        Args:
            receipt_data (dict): dados usados por format_receipt_text().
            paper_width_mm (int): largura do papel, 58 ou 80 mm.

        Returns:
            str: caminho do PDF criado.
        """
        receipt_data = receipt_data or {}
        pdf_path = self._get_operator_timestamp_filename(receipt_data)

        try:
            paper_width_mm = int(paper_width_mm or 80)
        except (TypeError, ValueError):
            paper_width_mm = 80

        paper_width_mm = 58 if paper_width_mm <= 58 else 80

        receipt_text = format_receipt_text(
            receipt_data,
            paper_width_mm=paper_width_mm,
        ).rstrip()

        line_count = max(1, len(receipt_text.splitlines()))
        font_size = 6.6 if paper_width_mm <= 58 else 7.4
        leading = font_size + 2.0
        margin = 4 * mm

        page_width = paper_width_mm * mm
        # Reserva espaço físico para o logótipo no rodapé. Assim, o texto
        # nunca pode ser composto por cima da imagem main2.png.
        footer_reserved_height = 21 * mm
        page_height = max(
            120 * mm,
            (line_count * leading) + margin + footer_reserved_height + (8 * mm),
        )

        background_path = self._find_asset("assets", "image", "fundo.png")
        main_image_path = self._find_asset("assets", "image", "main2.png")

        background_reader = self._image_reader(background_path)
        footer_reader = self._image_reader(main_image_path)

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=(page_width, page_height),
            topMargin=margin,
            bottomMargin=footer_reserved_height,
            leftMargin=margin,
            rightMargin=margin,
            title="Recibo de venda",
            author="NECTAR",
        )

        style = ParagraphStyle(
            "ThermalReceiptText",
            fontName="Courier",
            fontSize=font_size,
            leading=leading,
            textColor=colors.black,
            splitLongWords=1,
            spaceBefore=0,
            spaceAfter=0,
        )

        def decorate_page(pdf_canvas, document):
            self._draw_page_decoration(
                pdf_canvas,
                document,
                background_reader=background_reader,
                footer_reader=footer_reader,
            )

        story = [Preformatted(receipt_text, style)]
        doc.build(
            story,
            onFirstPage=decorate_page,
            onLaterPages=decorate_page,
        )

        return pdf_path
