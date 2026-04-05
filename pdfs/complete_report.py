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
            "Visão Geral Consolidada de Produtos e Desempenho Financeiro",
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
            "TABELA-MÃE: Visão Consolidada de Produtos",
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
            "Movimentação, precificação, rentabilidade, performance e status de estoque",
            ParagraphStyle(
                'Subtitle',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor("#7f8c8d"),
                spaceAfter=12,
            )
        ))

        header = [
            "Produto", "Categoria", "Entrada", "Saída", "Vendido",
            "Estoque", "Rot.%", "P.Compra", "P.Venda",
            "Markup%", "Receita", "Lucro", "Margem%", "Status"
        ]

        rows = [header]

        for _, r in data.iterrows():
            receita = r["sold_stock"] * r["sale_price"]
            rot = (r["sold_stock"] / r["entrada"] * 100) if r["entrada"] else 0
            markup = (
                (r["sale_price"] - r["unit_purchase_price"])
                / r["unit_purchase_price"] * 100
            ) if r["unit_purchase_price"] else 0

            if r["remanescente"] == 0:
                status = "Esgotado"
            elif r["remanescente"] < r["entrada"] * 0.15:
                status = "Crítico"
            elif r["remanescente"] < r["entrada"] * 0.3:
                status = "Baixo"
            elif r["remanescente"] < r["entrada"] * 0.6:
                status = "Médio"
            else:
                status = "Alto"

            rows.append([
                self._build_table_cell(r["description"], text_cell_style, max_len=42),
                self._build_table_cell(r["category"], text_cell_style, max_len=24),
                int(r["entrada"]),
                int(r["saida"]),
                int(r["sold_stock"]),
                int(r["remanescente"]),
                f"{rot:.1f}",
                f"{r['unit_purchase_price']:.2f}",
                f"{r['sale_price']:.2f}",
                f"{markup:.1f}",
                f"{receita:,.2f}",
                f"{r['lucro_total']:,.2f}",
                f"{r['percentual_lucro']:.1f}",
                self._build_table_cell(status, status_cell_style, max_len=12),
            ])

        # 🔒 SAFE WIDTH (nunca encosta no A4)
        SAFE_TABLE_WIDTH = 10.35 * inch

        colWidths = [
            2.35, 1.30, 0.62, 0.62, 0.62, 0.70,
            0.62, 0.74, 0.74, 0.66,
            0.98, 0.98, 0.70, 0.80
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
        title = Paragraph("RESUMO ANALÍTICO DO PERÍODO", title_style)
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
            "Consolidação de indicadores-chave de performance e resultados financeiros",
            subtitle_style
        )
        elements.append(subtitle)

        # Cálculos expandidos
        total_produtos = len(data)
        total_entrada = int(data["entrada"].sum())
        total_saida = int(data["saida"].sum())
        total_vendido = int(data["sold_stock"].sum())
        total_estoque_atual = int(data["remanescente"].sum())
        
        receita_total = data["valor_total_vendas"].sum()
        lucro_total = data["lucro_total"].sum()
        margem_media = data["percentual_lucro"].mean()
        
        # Métricas de performance
        taxa_rotatividade_geral = (total_vendido / total_entrada * 100) if total_entrada > 0 else 0
        ticket_medio = receita_total / total_vendido if total_vendido > 0 else 0
        lucro_por_produto = lucro_total / total_produtos if total_produtos > 0 else 0

        # Produtos com estoque crítico
        produtos_esgotados = len(data[data["remanescente"] == 0])
        produtos_criticos = len(data[data["remanescente"] < data["entrada"] * 0.15])

        resumo = [
            ["INDICADOR", "VALOR", "OBSERVAÇÃO"],
            
            # Seção: Inventário
            ["Total de Produtos Analisados", f"{total_produtos}", "Produtos únicos no período"],
            ["Entrada Total de Estoque", f"{total_entrada:,}", "Unidades adicionadas"],
            ["Saída Total de Estoque", f"{total_saida:,}", "Unidades removidas"],
            ["Unidades Vendidas", f"{total_vendido:,}", "Vendas confirmadas"],
            ["Estoque Atual Disponível", f"{total_estoque_atual:,}", "Saldo em inventário"],
            
            # Separador visual
            ["", "", ""],
            
            # Seção: Performance Financeira
            ["Receita Total (MZN)", f"{receita_total:,.2f}", "Faturamento bruto"],
            ["Lucro Total (MZN)", f"{lucro_total:,.2f}", "Resultado líquido"],
            ["Margem Média de Lucro (%)", f"{margem_media:.2f}%", "Rentabilidade média"],
            ["Ticket Médio (MZN)", f"{ticket_medio:.2f}", "Valor médio por unidade vendida"],
            ["Lucro Médio por Produto (MZN)", f"{lucro_por_produto:,.2f}", "Rentabilidade por SKU"],
            
            # Separador visual
            ["", "", ""],
            
            # Seção: Indicadores Operacionais
            ["Taxa de Rotatividade Geral (%)", f"{taxa_rotatividade_geral:.2f}%", "Eficiência de vendas"],
            ["Produtos Esgotados", f"{produtos_esgotados}", "Sem estoque disponível"],
            ["Produtos em Estoque Crítico", f"{produtos_criticos}", "Reposição urgente necessária"],
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
            
            # Separadores (linhas vazias)
            ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#ecf0f1")),
            ("BACKGROUND", (0, 12), (-1, 12), colors.HexColor("#ecf0f1")),
            ("LINEABOVE", (0, 6), (-1, 6), 1.5, colors.HexColor("#95a5a6")),
            ("LINEABOVE", (0, 12), (-1, 12), 1.5, colors.HexColor("#95a5a6")),
            
            # Corpo
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, 5), [colors.white, colors.HexColor("#f8f9fa")]),
            ("ROWBACKGROUNDS", (0, 7), (-1, 11), [colors.white, colors.HexColor("#f8f9fa")]),
            ("ROWBACKGROUNDS", (0, 13), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#2c3e50")),

            # Estilo de texto
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("ALIGN", (2, 1), (2, -1), "LEFT"),
            
            # Destaques
            ("TEXTCOLOR", (1, 7), (1, 7), colors.HexColor("#27ae60")),  # Receita
            ("TEXTCOLOR", (1, 8), (1, 8), colors.HexColor("#16a085")),  # Lucro
            ("TEXTCOLOR", (1, 9), (1, 9), colors.HexColor("#2980b9")),  # Margem
            
            ("FONTNAME", (1, 7), (1, 9), "Helvetica-Bold"),

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
                "Grafico de Barras: Produtos com Maior Receita",
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
        title = Paragraph("Top 5 Produtos Mais Lucrativos", title_style)
        elements.append(title)
        
        top_lucro = data.nlargest(5, 'lucro_total')
        top_data = [["#", "Produto", "Receita (MZN)", "Lucro (MZN)", "Margem %"]]
        
        for idx, (_, row) in enumerate(top_lucro.iterrows(), 1):
            receita = row["sold_stock"] * row["sale_price"]
            top_data.append([
                str(idx),
                self._build_table_cell(row["description"], table_text_style, max_len=54),
                f"{receita:,.2f}",
                f"{row['lucro_total']:,.2f}",
                f"{row['percentual_lucro']:.1f}%"
            ])
        
        top_table = Table(top_data, colWidths=[0.4*inch, 5*inch, 1.8*inch, 1.8*inch, 1.2*inch])
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
        title2 = Paragraph("Produtos que Requerem Atenção (Estoque Crítico/Esgotado)", title_style)
        elements.append(title2)
        
        critical = data[
            (data["remanescente"] == 0) | 
            (data["remanescente"] < data["entrada"] * 0.15)
        ].head(5)
        
        if len(critical) > 0:
            critical_data = [["Produto", "Categoria", "Estoque Atual", "Status", "Ação Sugerida"]]
            
            for _, row in critical.iterrows():
                if row["remanescente"] == 0:
                    status = "Esgotado"
                    acao = "Reposição imediata"
                else:
                    status = "Crítico"
                    acao = "Reposição urgente"
                
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
                "<i>Nenhum produto em situação crítica no momento.</i>",
                styles['Normal']
            )
            elements.append(no_critical)
