from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import pandas as pd
from xml.sax.saxutils import escape

from .base_report import BasePDFReport


class CompleteReport(BasePDFReport):
    """
    Relatório completo em PDF
    Tabela-mãe robusta + resumo analítico (sempre depois da tabela)
    """

    def generate(self, data, filters):
        pdf_path = self._get_timestamp_filename("relatorio_completo")

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=landscape(A4),
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.6 * inch,     # ⬅ margem externa maior
            rightMargin=0.6 * inch,    # ⬅ margem externa maior
        )

        elements = []

        self._create_header(
            elements,
            "RELATÓRIO COMPLETO",
            "Resumo de vendas, estoque e lucro",
            filters,
        )

        elements.append(Spacer(1, 14))

        # 1️⃣ TABELA-MÃE (NUNCA TOCA NAS LATERAIS)
        self._add_master_table(elements, data)

        elements.append(PageBreak())

        # 2️⃣ RESUMO ANALÍTICO
        self._add_general_summary(elements, data)
        elements.append(Spacer(1, 16))
        self._add_overview_chart(elements, data)

        # 3️⃣ ANÁLISES COMPLEMENTARES
        self._add_performance_analysis(elements, data)

        self._create_footer(elements)

        doc.build(elements)
        return pdf_path

    def _build_table_cell(self, value, style, fallback="-", max_len=None):
        if pd.isna(value):
            text = fallback
        else:
            text = str(value).strip() or fallback

        if max_len:
            text = self._truncate_text(text, max_len)

        safe_text = escape(text).replace("\n", "<br/>")
        return Paragraph(safe_text, style)

    # ─────────────────────────────────────────────
    # 🔹 TABELA-MÃE SEGURA (SAFE AREA)
    # ─────────────────────────────────────────────
    def _add_master_table(self, elements, data):
        styles = getSampleStyleSheet()
        text_cell_style = ParagraphStyle(
            "MasterTableText",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=8.4,
            textColor=colors.HexColor("#1f1f1f"),
            wordWrap="LTR",
            splitLongWords=True,
        )
        status_cell_style = ParagraphStyle(
            "MasterTableStatus",
            parent=text_cell_style,
            alignment=1,
        )

        elements.append(Paragraph(
            "Produtos do período",
            ParagraphStyle(
                'Title',
                parent=styles['Heading1'],
                fontSize=16,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor("#1f2d3d"),
                spaceAfter=6,
            )
        ))

        elements.append(Paragraph(
            "Entradas, vendas, estoque e lucro de cada produto",
            ParagraphStyle(
                'Subtitle',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor("#7f8c8d"),
                spaceAfter=12,
            )
        ))

        header = [
            "Produto", "Categoria", "Entrada", "Vendido", "Em\nestoque",
            "Preço de\ncompra", "Preço de\nvenda", "Total de\nvendas", "Lucro", "Situação"
        ]

        rows = [header]

        for _, r in data.iterrows():
            receita = r["sold_stock"] * r["sale_price"]

            if r["remanescente"] == 0:
                status = "Esgotado"
            elif r["remanescente"] < r["entrada"] * 0.30:
                status = "Muito baixo"
            elif r["remanescente"] < r["entrada"] * 0.60:
                status = "Baixo"
            else:
                status = "Disponível"

            rows.append([
                self._build_table_cell(r["description"], text_cell_style, max_len=42),
                self._build_table_cell(r["category"], text_cell_style, max_len=24),
                int(r["entrada"]),
                int(r["sold_stock"]),
                int(r["remanescente"]),
                f"{r['unit_purchase_price']:.2f}",
                f"{r['sale_price']:.2f}",
                f"{receita:,.2f}",
                f"{r['lucro_total']:,.2f}",
                self._build_table_cell(status, status_cell_style, max_len=12),
            ])

        # 🔒 SAFE WIDTH (nunca encosta no A4)
        SAFE_TABLE_WIDTH = 10.35 * inch

        colWidths = [
            2.40, 1.30, 0.72, 0.75, 0.85,
            0.90, 0.90, 1.15, 1.15, 0.90,
        ]

        scale = SAFE_TABLE_WIDTH / sum(colWidths)
        colWidths = [w * scale for w in colWidths]

        table = Table(
            rows,
            colWidths=colWidths,
            repeatRows=1,
            hAlign='CENTER',   # ⬅ centralizada
        )

        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2d3d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 1), (1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f8f9fa")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))

        elements.append(table)


    # ─────────────────────────────────────────────
    # 🔹 RESUMO ANALÍTICO (DEPOIS DA TABELA-MÃE)
    # ─────────────────────────────────────────────
    def _add_general_summary(self, elements, data):
        """
        Resumo analítico consolidado do período com métricas-chave.
        """
        styles = getSampleStyleSheet()

        # Título da seção
        title_style = ParagraphStyle(
            'SummaryTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=8,
            fontName='Helvetica-Bold'
        )
        title = Paragraph("RESUMO DO PERÍODO", title_style)
        elements.append(title)
        
        subtitle_style = ParagraphStyle(
            'SummarySubtitle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#7f8c8d'),
            spaceAfter=14,
            fontName='Helvetica-Oblique'
        )
        subtitle = Paragraph(
            "Veja rapidamente as vendas, o estoque e o lucro deste período.",
            subtitle_style
        )
        elements.append(subtitle)

        # Cálculos expandidos
        total_produtos = len(data)
        total_entrada = int(data["entrada"].sum())
        total_vendido = int(data["sold_stock"].sum())
        total_estoque_atual = int(data["remanescente"].sum())
        
        receita_total = data["valor_total_vendas"].sum()
        lucro_total = data["lucro_total"].sum()
        lucro_por_produto = lucro_total / total_produtos if total_produtos > 0 else 0

        produtos_esgotados = len(data[data["remanescente"] == 0])
        produtos_com_estoque_baixo = len(
            data[(data["remanescente"] > 0) & (data["remanescente"] < data["entrada"] * 0.60)]
        )

        resumo = [
            ["RESUMO", "VALOR", "O QUE SIGNIFICA"],
            ["Produtos no relatório", f"{total_produtos}", "Produtos incluídos no período"],
            ["Unidades adicionadas", f"{total_entrada:,}", "Entradas no estoque"],
            ["Unidades vendidas", f"{total_vendido:,}", "Vendas realizadas"],
            ["Unidades em estoque", f"{total_estoque_atual:,}", "Disponíveis neste momento"],
            ["Total de vendas", f"MZN {receita_total:,.2f}", "Valor vendido"],
            ["Lucro total", f"MZN {lucro_total:,.2f}", "Valor ganho nas vendas"],
            ["Lucro médio por produto", f"MZN {lucro_por_produto:,.2f}", "Média dos produtos do relatório"],
            ["Produtos sem estoque", f"{produtos_esgotados}", "Já precisam de reposição"],
            ["Produtos com estoque baixo", f"{produtos_com_estoque_baixo}", "Convém preparar a reposição"],
        ]

        table = Table(
            resumo,
            colWidths=[3.8 * inch, 2.2 * inch, 3.5 * inch]
        )

        table.setStyle(TableStyle([
            # Cabeçalho
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 11),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            
            # Corpo
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#2c3e50")),

            # Estilo de texto
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("ALIGN", (2, 1), (2, -1), "LEFT"),
            
            # Destaques
            ("TEXTCOLOR", (1, 5), (1, 5), colors.HexColor("#27ae60")),
            ("TEXTCOLOR", (1, 6), (1, 6), colors.HexColor("#16a085")),
            
            ("FONTNAME", (1, 5), (1, 6), "Helvetica-Bold"),

            # Padding
            ("TOPPADDING", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("TOPPADDING", (0, 1), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))

        elements.append(table)
    
    # ─────────────────────────────────────────────
    # 🔹 ANÁLISES COMPLEMENTARES
    # ─────────────────────────────────────────────
    def _add_overview_chart(self, elements, data):
        top_revenue = data.nlargest(7, "valor_total_vendas")
        chart_items = [
            (row["description"], row["valor_total_vendas"])
            for _, row in top_revenue.iterrows()
        ]
        elements.append(
            self._build_bar_chart(
                "Produtos com mais vendas em valor",
                chart_items,
                value_formatter=lambda value: f"MZN {value:,.2f}",
                accent_color="#34495e",
            )
        )

    def _add_performance_analysis(self, elements, data):
        """
        Análises adicionais: Top performers e produtos que requerem atenção.
        """
        elements.append(Spacer(1, 20))
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'AnalysisTitle',
            parent=styles['Heading2'],
            fontSize=13,
            textColor=colors.HexColor('#34495e'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        table_text_style = ParagraphStyle(
            "AnalysisTableText",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=9.2,
            textColor=colors.HexColor("#1f1f1f"),
            wordWrap="LTR",
            splitLongWords=True,
        )
        
        # Top 5 produtos por lucro
        title = Paragraph("Produtos com mais lucro", title_style)
        elements.append(title)
        
        top_lucro = data.nlargest(5, 'lucro_total')
        top_data = [["#", "Produto", "Total de vendas (MZN)", "Lucro (MZN)"]]
        
        for idx, (_, row) in enumerate(top_lucro.iterrows(), 1):
            receita = row["sold_stock"] * row["sale_price"]
            top_data.append([
                str(idx),
                self._build_table_cell(row["description"], table_text_style, max_len=54),
                f"{receita:,.2f}",
                f"{row['lucro_total']:,.2f}",
            ])
        
        top_table = Table(top_data, colWidths=[0.4*inch, 5.1*inch, 2.2*inch, 2.2*inch])
        top_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        
        elements.append(top_table)
        elements.append(Spacer(1, 15))
        
        # Produtos que requerem atenção
        title2 = Paragraph("Produtos para repor", title_style)
        elements.append(title2)
        
        critical = data[
            (data["remanescente"] == 0) | 
            (data["remanescente"] < data["entrada"] * 0.30)
        ].head(5)
        
        if len(critical) > 0:
            critical_data = [["Produto", "Categoria", "Estoque Atual", "Status", "Ação Sugerida"]]
            
            for _, row in critical.iterrows():
                if row["remanescente"] == 0:
                    status = "Sem estoque"
                    acao = "Repor assim que possível"
                else:
                    status = "Estoque baixo"
                    acao = "Preparar a reposição"
                
                critical_data.append([
                    self._build_table_cell(row["description"], table_text_style, max_len=46),
                    self._build_table_cell(row["category"], table_text_style, max_len=24),
                    str(int(row["remanescente"])),
                    self._build_table_cell(status, table_text_style, max_len=12),
                    self._build_table_cell(acao, table_text_style, max_len=32),
                ])
            
            critical_table = Table(critical_data, colWidths=[3.5*inch, 1.5*inch, 1.3*inch, 1.2*inch, 2.7*inch])
            critical_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e74c3c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ALIGN", (4, 1), (4, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            
            elements.append(critical_table)
        else:
            no_critical = Paragraph(
                "<i>Não há produtos a repor neste momento.</i>",
                styles['Normal']
            )
            elements.append(no_critical)
