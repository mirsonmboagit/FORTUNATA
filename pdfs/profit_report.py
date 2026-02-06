from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from num2words import num2words
from .base_report import BasePDFReport


class ProfitReport(BasePDFReport):
    """
    Gera relatório de lucro em PDF com análise aprofundada.
    Apresenta análise de rentabilidade e margem de lucro.
    """
    
    def generate(self, data, filters):
        """
        Gera o relatório de lucro.
        
        Args:
            data: DataFrame com colunas: description, sold_stock, lucro_unitario,
                  lucro_total, percentual_lucro
            filters: Dict com start_date, end_date, product, category
        
        Returns:
            String com o caminho do arquivo PDF gerado
        """
        pdf_path = self._get_timestamp_filename("relatorio_lucro")
        doc = SimpleDocTemplate(
            pdf_path, 
            pagesize=landscape(A4), 
            topMargin=0.5*inch, 
            bottomMargin=0.5*inch,
            leftMargin=0.4*inch,
            rightMargin=0.4*inch
        )
        
        elements = []
        
        self._create_header(
            elements,
            "RELATÓRIO DE LUCRO",
            "Análise Detalhada de Rentabilidade e Margem de Lucro",
            filters
        )
        
        elements.append(Spacer(1, 14))
        self._add_financial_summary(elements, data)
        elements.append(Spacer(1, 20))
        self._add_top_profitable_products(elements, data)
        elements.append(Spacer(1, 18))
        self._add_margin_analysis(elements, data)
        self._create_footer(elements)
        
        doc.build(elements)
        return pdf_path
    
    def _add_financial_summary(self, elements, data):
        """Adiciona seção de resumo financeiro expandido."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'FinancialTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#f39c12'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Resumo Financeiro e de Rentabilidade", title_style))
        
        # Cálculos expandidos
        total_lucro = data['lucro_total'].sum()
        media_lucro = data['lucro_total'].mean()
        media_margem = data['percentual_lucro'].mean()
        lucro_unitario_medio = data['lucro_unitario'].mean()
        
        # Produtos lucrativos vs não lucrativos
        produtos_lucrativos = len(data[data['lucro_total'] > 0])
        produtos_prejuizo = len(data[data['lucro_total'] <= 0])
        
        # Melhor margem
        melhor_margem = data['percentual_lucro'].max()
        
        summary_data = [
            ['MÉTRICA', 'VALOR', 'POR EXTENSO'],
            ['Total de Produtos Analisados', f"{len(data)}", num2words(len(data), lang='pt')],
            ['Produtos Lucrativos', f"{produtos_lucrativos}", num2words(produtos_lucrativos, lang='pt')],
            ['Produtos em Prejuízo', f"{produtos_prejuizo}", num2words(produtos_prejuizo, lang='pt')],
            ['Lucro Total Consolidado', f"MZN {total_lucro:,.2f}", f"{num2words(int(total_lucro), lang='pt')} meticais"],
            ['Lucro Médio por Produto', f"MZN {media_lucro:,.2f}", f"{num2words(int(media_lucro), lang='pt')} meticais"],
            ['Lucro Médio Unitário', f"MZN {lucro_unitario_medio:.2f}", f"{num2words(int(lucro_unitario_medio), lang='pt')} meticais"],
            ['Margem de Lucro Média', f"{media_margem:.2f}%", f"{num2words(int(media_margem), lang='pt')} por cento"],
            ['Melhor Margem Registrada', f"{melhor_margem:.2f}%", f"{num2words(int(melhor_margem), lang='pt')} por cento"],
        ]
        
        summary_table = Table(summary_data, colWidths=[3.5*inch, 2.5*inch, 4.2*inch])
        
        summary_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f39c12')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Corpo
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fef9f3')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#f39c12')),
            
            # Alinhamento
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),
            
            # Destaques
            ('TEXTCOLOR', (1, 4), (1, 6), colors.HexColor('#27ae60')),
            ('FONTNAME', (1, 4), (1, 8), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        elements.append(summary_table)
    
    def _add_top_profitable_products(self, elements, data):
        """Adiciona seção de top 15 produtos mais lucrativos com dados expandidos."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'TopProfitTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#e67e22'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Top 15 Produtos Mais Lucrativos", title_style))
        
        top_profit = data.nlargest(15, 'lucro_total')
        
        detail_data = [[
            '#', 'Produto', 'Qtd.\nVendida', 
            'Lucro\nUnitário', 'Lucro\nTotal', 'Margem\n%', 'Classif.'
        ]]
        
        for idx, (_, row) in enumerate(top_profit.iterrows(), 1):
            # Classificação da margem
            if row['percentual_lucro'] >= 50:
                classif = "Excelente"
            elif row['percentual_lucro'] >= 30:
                classif = "Ótima"
            elif row['percentual_lucro'] >= 15:
                classif = "Boa"
            elif row['percentual_lucro'] > 0:
                classif = "Regular"
            else:
                classif = "Prejuízo"
            
            detail_data.append([
                str(idx),
                str(row['description'])[:30],
                f"{int(row['sold_stock']):,}",
                f"{row['lucro_unitario']:.2f}",
                f"{row['lucro_total']:,.2f}",
                f"{row['percentual_lucro']:.1f}%",
                classif
            ])
        
        detail_table = Table(detail_data, colWidths=[
            0.4*inch, 3.0*inch, 1.1*inch, 1.2*inch, 1.6*inch, 1.0*inch, 1.1*inch
        ])
        
        detail_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e67e22')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Corpo
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fef5ed')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Bordas
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#e67e22')),
            
            # Destaques
            ('TEXTCOLOR', (4, 1), (4, -1), colors.HexColor('#27ae60')),
            ('FONTNAME', (4, 1), (5, -1), 'Helvetica-Bold'),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 9),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        elements.append(detail_table)
    
    def _add_margin_analysis(self, elements, data):
        """Adiciona análise de distribuição de margens."""
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'MarginTitle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#8e44ad'),
            spaceAfter=10,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("Análise de Distribuição de Margens", title_style))
        
        # Distribuição por faixas de margem
        excelente = len(data[data['percentual_lucro'] >= 50])
        otima = len(data[(data['percentual_lucro'] >= 30) & (data['percentual_lucro'] < 50)])
        boa = len(data[(data['percentual_lucro'] >= 15) & (data['percentual_lucro'] < 30)])
        regular = len(data[(data['percentual_lucro'] > 0) & (data['percentual_lucro'] < 15)])
        prejuizo = len(data[data['percentual_lucro'] <= 0])
        
        margin_data = [
            ['Faixa de Margem', 'Quantidade de Produtos', '% do Total', 'Classificação'],
            ['≥ 50%', str(excelente), f"{(excelente/len(data)*100):.1f}%", 'Excelente'],
            ['30% - 49%', str(otima), f"{(otima/len(data)*100):.1f}%", 'Ótima'],
            ['15% - 29%', str(boa), f"{(boa/len(data)*100):.1f}%", 'Boa'],
            ['1% - 14%', str(regular), f"{(regular/len(data)*100):.1f}%", 'Regular'],
            ['≤ 0%', str(prejuizo), f"{(prejuizo/len(data)*100):.1f}%", 'Prejuízo'],
        ]
        
        margin_table = Table(margin_data, colWidths=[2.5*inch, 2.5*inch, 2.0*inch, 2.0*inch])
        
        margin_table.setStyle(TableStyle([
            # Cabeçalho
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            
            # Corpo
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4ecf7')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#95a5a6')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#8e44ad')),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            
            # Destaques condicionais
            ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#27ae60')),  # Excelente
            ('TEXTCOLOR', (1, 2), (1, 2), colors.HexColor('#2ecc71')),  # Ótima
            ('TEXTCOLOR', (1, 3), (1, 3), colors.HexColor('#f39c12')),  # Boa
            ('TEXTCOLOR', (1, 4), (1, 4), colors.HexColor('#e67e22')),  # Regular
            ('TEXTCOLOR', (1, 5), (1, 5), colors.HexColor('#e74c3c')),  # Prejuízo
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        
        elements.append(margin_table)