from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from datetime import datetime
from .base_report import BasePDFReport


class LogsReport(BasePDFReport):
    """
    Gera relatorio simples de logs do sistema em PDF.
    """

    ACTION_LABELS = {
        "LOGIN": "Login realizado",
        "LOGOUT": "Logout realizado",
        "CREATE_USER": "Usuário criado",
        "DELETE_USER": "Usuário removido",
        "UPDATE_ADMIN": "Dados do admin atualizados",
        "ADD_PRODUCT": "Produto adicionado",
        "UPDATE_PRODUCT": "Produto atualizado",
        "DELETE_PRODUCT": "Produto removido",
        "SALE": "Venda registrada",
        "CANCEL_SALE": "Venda cancelada",
        "SAVE_RECEIPT": "Recibo salvo",
        "REGISTER_LOSS": "Perda registrada",
        "APPROVE_LOSS": "Perda aprovada",
    }

    def _action_to_label(self, action):
        if not action:
            return "Ação desconhecida"
        label = self.ACTION_LABELS.get(action)
        if label:
            return label
        return f"Ação: {action}"

    def generate(self, logs, filters):
        pdf_path = self._get_timestamp_filename("relatorio_logs")
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            topMargin=0.6 * inch,
            bottomMargin=0.6 * inch,
            leftMargin=0.6 * inch,
            rightMargin=0.6 * inch,
        )

        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "LogsTitle",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=colors.HexColor("#2c3e50"),
            alignment=TA_CENTER,
            spaceAfter=16,
        )
        elements.append(Paragraph("RELATORIO DE LOGS DO SISTEMA", title_style))

        info_data = [
            ["Usuario:", filters.get("user") or "Todos"],
            ["Acao:", filters.get("action") or "Todas"],
            ["Role:", filters.get("role") or "Todos"],
            ["Gerado em:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")],
        ]
        info_table = Table(info_data, colWidths=[1.2 * inch, 4.8 * inch])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#2c3e50")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 14))

        table_data = [[
            "Data/Hora",
            "Usuario",
            "Role",
            "Acao",
            "Detalhes",
        ]]

        for log in logs:
            _id, username, role, action, details, timestamp = log
            details_text = details or ""
            if len(details_text) > 80:
                details_text = details_text[:77] + "..."
            table_data.append([
                str(timestamp),
                str(username),
                str(role),
                self._action_to_label(action),
                details_text,
            ])

        table = Table(table_data, colWidths=[
            1.4 * inch, 1.3 * inch, 0.9 * inch, 1.1 * inch, 2.6 * inch
        ])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 1), (3, -1), "CENTER"),
            ("ALIGN", (4, 1), (4, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))

        elements.append(table)
        self._create_footer(elements)

        doc.build(elements)
        return pdf_path
